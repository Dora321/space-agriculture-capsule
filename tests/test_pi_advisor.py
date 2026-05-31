"""Tests for the Pi-side DeepSeek advisor (tools/pi_advisor.py).

The HTTP call is injected, so prompt-building, response parsing and validation
are exercised with no network. The signal-whitelist cross-check guards against
the ESP32 side and the advisor drifting apart.
"""
import importlib.util
import json
import pathlib
import sys

import pytest

import uart_link  # ESP32 side (esp32_firmware on path via conftest)


def _load_advisor_module():
    spec = importlib.util.spec_from_file_location(
        "pi_advisor",
        str(pathlib.Path(__file__).resolve().parent.parent / "tools" / "pi_advisor.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["pi_advisor"] = module
    spec.loader.exec_module(module)
    return module


pa = _load_advisor_module()

REPORT = {
    "t": "report", "plant": "生菜", "soil": 20, "light": 25, "temp": 24,
    "hum": 55, "day": 5, "stage": "seedling", "action": "idle",
}


def _deepseek_response(content):
    return json.dumps({"choices": [{"message": {"content": content}}]})


class TestBuildMessages:
    def test_includes_sensor_values_and_system_prompt(self):
        msgs = pa.build_messages(REPORT)
        assert msgs[0]["role"] == "system"
        assert "space agriculture" in msgs[0]["content"].lower()
        user = msgs[1]["content"]
        assert "生菜" in user
        assert "20%" in user          # soil value
        assert "Day 5" in user

    def test_uses_plant_info_thresholds_when_given(self):
        info = {"soil_threshold": 45, "light_min": 60, "light_opt": 80, "light_hours": [4, 6]}
        user = pa.build_messages(REPORT, info)[1]["content"]
        assert "thr: 45%" in user
        assert "min: 60%" in user


class TestValidateDecision:
    def test_normalizes_to_advice_shape(self):
        out = pa.validate_decision({
            "action": "water", "duration_sec": 8, "reason": "dry",
            "signals": ["WATER", "BOGUS"], "breeding_observation": "ok",
        })
        assert out["primary"] == "water"
        assert out["duration"] == 8
        assert out["signals"] == ["WATER"]      # unknown signal filtered out
        assert out["note"] == "dry"
        assert out["breeding_observation"] == "ok"

    def test_idle_zeroes_duration(self):
        out = pa.validate_decision({"action": "idle", "duration_sec": 30})
        assert out["primary"] == "idle"
        assert out["duration"] == 0

    def test_nutrient_remapped_to_idle(self):
        out = pa.validate_decision({"action": "nutrient", "duration_sec": 5})
        assert out["primary"] == "idle"
        assert out["duration"] == 0

    def test_invalid_action_raises(self):
        with pytest.raises(ValueError):
            pa.validate_decision({"action": "ventilate", "duration_sec": 5})


class TestAdvisor:
    def test_advise_returns_validated_advice_via_injected_http(self):
        captured = {}

        def fake_post(url, data, headers, timeout):
            captured["url"] = url
            captured["headers"] = headers
            return _deepseek_response(
                '{"action":"water","duration_sec":8,"reason":"soil low",'
                '"signals":["WATER"],"breeding_observation":"healthy"}')

        adv = pa.DeepSeekAdvisor(api_key="sk-test", http_post=fake_post)
        out = adv.advise(REPORT)
        assert out["primary"] == "water"
        assert out["duration"] == 8
        assert out["signals"] == ["WATER"]
        assert captured["headers"]["Authorization"] == "Bearer sk-test"

    def test_advise_handles_code_fenced_json(self):
        def fake_post(url, data, headers, timeout):
            return _deepseek_response('```json\n{"action":"light","duration_sec":45,"reason":"dark"}\n```')

        adv = pa.DeepSeekAdvisor(api_key="sk-test", http_post=fake_post)
        out = adv.advise(REPORT)
        assert out["primary"] == "light"
        assert out["duration"] == 45

    def test_advise_returns_none_on_http_error(self):
        def fake_post(url, data, headers, timeout):
            raise RuntimeError("network down")

        adv = pa.DeepSeekAdvisor(api_key="sk-test", http_post=fake_post)
        assert adv.advise(REPORT) is None

    def test_advise_skips_when_key_not_configured(self):
        adv = pa.DeepSeekAdvisor(api_key="YOUR_API_KEY_HERE", http_post=lambda *a: "")
        assert adv.advise(REPORT) is None


def test_signal_whitelist_matches_uart_link():
    """Advisor signals must stay in lock-step with the ESP32 UART protocol."""
    assert set(pa.VALID_SIGNALS) == set(uart_link.VALID_SIGNALS)
