"""
测试运行时边界：占位密钥、显示 mock、执行动作分支。
"""
import time
import actuators
import display
import main
import sensors


class TestHardwareMocks:
    def test_default_dht11_initializes_in_pc_mock(self):
        assert sensors.init() is True

    def test_display_overlay_has_mock_fill_rect(self):
        assert display.init() is True
        display.show_text("OK", 0, 0)
        display.show_overlay("R1", 0, 56)

    def test_display_static_text_is_clipped_to_oled_width(self, monkeypatch):
        class Recorder:
            def __init__(self):
                self.text_calls = []

            def fill(self, c):
                pass

            def show(self):
                pass

            def text(self, t, x, y, *a):
                self.text_calls.append((str(t), x, y))

            def pixel(self, *a):
                pass

            def fill_rect(self, *a):
                pass

            def rect(self, *a):
                pass

            def line(self, *a):
                pass

        recorder = Recorder()
        display._oled = recorder
        monkeypatch.setattr(display.time, "sleep", lambda *args: None)

        display.show_boot()
        display.show_text("1234567890abcdefOVER", 8, 0)
        display.show_overlay("1234567890abcdefOVER", 16, 56)
        display.show_wifi_status(True, "192.168.123.123")
        display.show_action("water", 12345678901234567890, "long")

        for text, x, y in recorder.text_calls:
            assert 0 <= x <= 127
            assert 0 <= y <= 56
            assert x + len(text) * 8 <= 128


class TestExecuteDecision:
    def setup_method(self):
        actuators.init()
        main.state.last_action = "idle"
        main.state.action_count = 0

    def test_unknown_action_falls_back_to_idle(self, monkeypatch):
        monkeypatch.setattr(main, "_refresh_display", lambda *args, **kwargs: None)
        monkeypatch.setattr(display, "show_action", lambda *args, **kwargs: None)

        main.execute_decision({
            "action": "ventilate",
            "duration_sec": 7,
            "reason": "fan hardware removed",
        })

        assert main.state.last_action == "idle"
        assert main.state.last_action_duration == 0
        assert main.state.action_count == 0

    def test_nutrient_action_is_remapped_to_idle(self, monkeypatch):
        """单泵架构：AI 万一返回 nutrient 也应被静默映射为 idle，不调用泵"""
        monkeypatch.setattr(main, "_refresh_display", lambda *args, **kwargs: None)
        monkeypatch.setattr(display, "show_action", lambda *args, **kwargs: None)
        called = {"water": 0}
        monkeypatch.setattr(actuators, "run_water_pump", lambda duration: called.__setitem__("water", called["water"] + 1) or True)

        main.execute_decision({
            "action": "nutrient",
            "duration_sec": 5,
            "reason": "ai legacy",
        })

        assert main.state.last_action == "idle"
        assert main.state.action_count == 0
        assert called["water"] == 0

    def test_light_action_calls_run_light(self, monkeypatch):
        """light 动作正确调用 actuators.run_light"""
        monkeypatch.setattr(main, "_refresh_display", lambda *args, **kwargs: None)
        monkeypatch.setattr(display, "show_action", lambda *args, **kwargs: None)
        called = {"duration": None}
        monkeypatch.setattr(actuators, "run_light", lambda d: called.__setitem__("duration", d) or True)

        main.execute_decision({
            "action": "light",
            "duration_sec": 60,
            "reason": "light LOW 20%<30%",
        })

        assert main.state.last_action == "light"
        assert main.state.last_action_duration == 60
        assert main.state.action_count == 1
        assert called["duration"] == 60

    def test_light_duration_uses_light_max_not_pump_max(self, monkeypatch):
        monkeypatch.setattr(main.config, "PUMP_MAX_RUN_SEC", 60, raising=False)
        monkeypatch.setattr(main.config, "LIGHT_MAX_RUN_SEC", 120, raising=False)
        monkeypatch.setattr(main, "_refresh_display", lambda *args, **kwargs: None)
        monkeypatch.setattr(display, "show_action", lambda *args, **kwargs: None)
        called = {"duration": None}
        monkeypatch.setattr(actuators, "run_light", lambda d: called.__setitem__("duration", d) or True)

        main.execute_decision({
            "action": "light",
            "duration_sec": 100,
            "reason": "pi advice",
        })

        assert called["duration"] == 100


class TestPiAdvice:
    def teardown_method(self):
        main._uart_link = None
        main.state.pending_pi_decision = None
        main.state.last_decision_source = "local"

    def test_pi_advice_takes_priority_when_online(self, monkeypatch):
        class OnlineLink:
            def is_online(self):
                return True

        monkeypatch.setattr(main.config, "DEMO_MODE", False, raising=False)
        main._uart_link = OnlineLink()
        main.state.pending_pi_decision = {
            "action": "water",
            "duration_sec": 8,
            "reason": "pi says dry",
        }

        decision = main.make_decision()

        assert decision["action"] == "water"
        assert main.state.pending_pi_decision is None
        assert main.state.last_decision_source == "pi"

    def test_stale_pi_advice_is_dropped(self, monkeypatch):
        class OfflineLink:
            def is_online(self):
                return False

        monkeypatch.setattr(main.config, "DEMO_MODE", False, raising=False)
        monkeypatch.setattr(main.state, "wifi_connected", False)
        main._uart_link = OfflineLink()
        main.state.pending_pi_decision = {
            "action": "water",
            "duration_sec": 8,
            "reason": "old",
        }
        main.state.plant_info = main.config.get_plant_info(main.state.plant_type)
        main.state.soil_moisture = 80
        main.state.light_level = 80
        main.state.temperature = 24
        main.state.humidity = 60
        main.state.sun_minutes_today = 360
        main.state.start_time = time.time()

        decision = main.make_decision()

        assert decision["action"] == "idle"
        assert main.state.pending_pi_decision is None
        assert main.state.last_decision_source == "local"


def _enable_status_strip():
    import status_strip
    status_strip.config.WS2812_ENABLED = True


class TestStatusStrip:
    """WS2812 育种舱状态灯条"""

    def test_strip_init_returns_true_with_mock(self):
        _enable_status_strip()
        import status_strip
        assert status_strip.init() is True

    def test_show_moisture_lights_correct_count(self):
        _enable_status_strip()
        import status_strip
        status_strip.init()
        status_strip.show_moisture(50)
        # 11 颗灯，50% 应点亮约 6 颗
        lit = sum(1 for px in status_strip._np._buf if px != (0, 0, 0))
        assert 5 <= lit <= 7

    def test_show_moisture_offline_lights_warn_endpoints(self):
        _enable_status_strip()
        import status_strip
        status_strip.init()
        status_strip.show_moisture(None)
        buf = status_strip._np._buf
        # 离线状态：首尾两颗有颜色，中间全灭
        assert buf[0] != (0, 0, 0)
        assert buf[-1] != (0, 0, 0)
        for px in buf[1:-1]:
            assert px == (0, 0, 0)

    def test_set_status_yellow_writes_all_leds(self):
        _enable_status_strip()
        import status_strip
        status_strip.init()
        status_strip.set_status("yellow")
        for px in status_strip._np._buf:
            # 黄色：R 高, G 中, B 低
            r, g, b = px
            assert r > g > b


class TestDemoMode:
    def setup_method(self):
        main.state.demo_soil_moisture = None
        main.state.read_count = 0
        main.state.last_action = "idle"
        main.state.last_action_duration = 0
        main.state.action_count = 0

    def test_demo_sensor_data_drops_soil_without_hardware(self, monkeypatch):
        monkeypatch.setattr(main.config, "DEMO_MODE", True, raising=False)
        monkeypatch.setattr(main.config, "DEMO_PLANT_TYPE", "生菜", raising=False)
        monkeypatch.setattr(main.config, "DEMO_START_SOIL", 42, raising=False)
        monkeypatch.setattr(main.config, "DEMO_SOIL_DROP", 7, raising=False)

        assert main.read_all_sensors() is True
        first = main.state.soil_moisture
        assert main.read_all_sensors() is True

        assert first == 42
        assert main.state.soil_moisture == 35
        assert main.state.light_level > 0
        assert main.state.growth_stage is not None

    def test_demo_decision_and_recovery_cycle(self, monkeypatch):
        monkeypatch.setattr(main.config, "DEMO_MODE", True, raising=False)
        monkeypatch.setattr(main.config, "DEMO_RECOVER_SOIL", 55, raising=False)
        monkeypatch.setattr(main.config, "PUMP_MAX_RUN_SEC", 60, raising=False)
        monkeypatch.setattr(main, "_refresh_display", lambda *args, **kwargs: None)
        monkeypatch.setattr(display, "show_action", lambda *args, **kwargs: None)
        monkeypatch.setattr(actuators, "run_water_pump", lambda duration: True)

        main.state.plant_type = "生菜"
        main.state.plant_info = main.config.get_plant_info(main.state.plant_type)
        main.state.soil_moisture = main.state.plant_info["soil_threshold"] - 1
        main.state.light_level = 72
        main.state.sun_minutes_today = 30

        decision = main.make_decision()
        assert decision["action"] == "water"

        main.execute_decision(decision)
        assert main.state.soil_moisture == 55
        assert main.state.last_action == "water"


class TestDecisionCadence:
    def test_local_decision_runs_each_minute_by_default(self):
        assert main.config.READ_INTERVAL == 60
        assert main.config.DECISION_INTERVAL == 60
