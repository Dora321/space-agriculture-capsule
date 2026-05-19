"""
测试运行时边界：占位密钥、显示 mock、执行动作分支。
"""
import ai_client
import actuators
import display
import telemetry
import main
import sensors


class TestApiKeyPlaceholders:
    def test_template_placeholder_key_is_not_configured(self):
        assert ai_client._is_placeholder_key("YOUR_API_KEY_HERE")

    def test_chinese_placeholder_key_is_not_configured(self):
        assert ai_client._is_placeholder_key("你的DeepSeek API密钥")

    def test_realistic_key_is_configured(self):
        assert not ai_client._is_placeholder_key("sk-realistic-test-key")


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

        recorder = Recorder()
        display._oled = recorder
        monkeypatch.setattr(display.time, "sleep", lambda *args: None)

        display.show_boot()
        display.show_text("1234567890abcdefOVER", 8, 0)
        display.show_overlay("1234567890abcdefOVER", 16, 56)
        display.show_wifi_status(True, "192.168.123.123")
        display.show_action("nutrient", 12345678901234567890, "long")

        for text, x, y in recorder.text_calls:
            assert 0 <= x <= 127
            assert 0 <= y <= 56
            assert x + len(text) * 8 <= 128


class TestExecuteDecision:
    def setup_method(self):
        actuators.init()
        main.state.last_action = "idle"
        main.state.action_count = 0
        main.state.last_nutrient_time = 0

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


class TestTelemetry:
    def test_telemetry_posts_compact_state(self, monkeypatch):
        calls = []

        class Response:
            status_code = 200

            def close(self):
                pass

        def fake_post(url, data=None, headers=None, timeout=None):
            calls.append({
                "url": url,
                "data": data,
                "headers": headers,
                "timeout": timeout,
            })
            return Response()

        import urequests

        monkeypatch.setattr(main.config, "DASHBOARD_URL", "http://127.0.0.1:8790/api/state", raising=False)
        monkeypatch.setattr(main.config, "DASHBOARD_TOKEN", "token", raising=False)
        monkeypatch.setattr(main.config, "DASHBOARD_TIMEOUT", 2, raising=False)
        monkeypatch.setattr(urequests, "post", fake_post, raising=False)

        main.state.soil_moisture = 41
        main.state.light_level = 70
        main.state.temperature = 24.5
        main.state.humidity = 62
        main.state.plant_type = "生菜"
        main.state.growth_stage = {"stage": "seedling"}
        main.state.days_since_planting = 7
        main.state.last_action = "idle"
        main.state.last_decision_reason = "status normal"

        assert telemetry.send_state(main.state, ai_enabled=True) is True
        assert calls[0]["url"].endswith("/api/state")
        assert calls[0]["headers"]["X-Dashboard-Token"] == "token"
        assert b'"soil": 41' in calls[0]["data"]
