"""
测试运行时边界：占位密钥、显示 mock、执行动作分支。
"""
import ai_client
import actuators
import display
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
