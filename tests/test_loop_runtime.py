import loop_runtime
from state import SystemState


class DisplayRecorder:
    def __init__(self):
        self.overlays = []

    def show_overlay(self, text, x, y):
        self.overlays.append((text, x, y))


def test_loop_runs_one_successful_cycle_and_reconnects(monkeypatch):
    state = SystemState()
    display = DisplayRecorder()
    calls = []

    monkeypatch.setattr(loop_runtime.config, "READ_INTERVAL", 60, raising=False)
    monkeypatch.setattr(loop_runtime.config, "DECISION_INTERVAL", 60, raising=False)
    monkeypatch.setattr(loop_runtime.config, "WIFI_RECONNECT_AFTER_MISSES", 1, raising=False)
    monkeypatch.setattr(loop_runtime.time, "time", lambda: 60)
    monkeypatch.setattr(loop_runtime.gc, "collect", lambda: calls.append("gc"))
    monkeypatch.setattr(loop_runtime.wifi_client, "is_connected", lambda **kwargs: False)
    monkeypatch.setattr(loop_runtime.wifi_client, "smart_connect", lambda: True)
    monkeypatch.setattr(loop_runtime.wifi_client, "connect", lambda timeout=8, reset=False, allow_full_reset=True: True)
    monkeypatch.setattr(loop_runtime.actuators, "all_off", lambda: calls.append("all_off"))
    monkeypatch.setattr(loop_runtime.time, "ticks_ms", lambda: 0, raising=False)
    monkeypatch.setattr(loop_runtime.time, "ticks_diff", lambda now, start: 0, raising=False)

    def fake_sleep(seconds):
        calls.append(("sleep", seconds))

    def fake_sleep_ms(ms):
        raise KeyboardInterrupt

    monkeypatch.setattr(loop_runtime.time, "sleep", fake_sleep)
    monkeypatch.setattr(loop_runtime.time, "sleep_ms", fake_sleep_ms, raising=False)

    loop_runtime.run_loop(
        state,
        display=lambda: display,
        refresh_display=lambda *args, **kwargs: calls.append(("refresh", kwargs)),
        read_all_sensors=lambda: calls.append("read") or True,
        safety_check=lambda: calls.append("safe") or True,
        make_decision=lambda: calls.append("decision") or {"action": "idle"},
        execute_decision=lambda decision: calls.append(("execute", decision["action"])),
        send_telemetry=lambda: calls.append("telemetry"),
        watch_dog=lambda: calls.append("watchdog"),
    )

    assert state.read_count == 1
    assert state.wifi_connected is True
    assert ("R1", 0, 56) in display.overlays
    assert "read" in calls
    assert "safe" in calls
    assert "decision" in calls
    assert ("execute", "idle") in calls
    assert "telemetry" in calls
    assert "gc" in calls
    assert "watchdog" not in calls


def test_loop_reports_sensor_failure_without_decision(monkeypatch):
    state = SystemState()
    display = DisplayRecorder()
    calls = []
    sleep_calls = []

    monkeypatch.setattr(loop_runtime.config, "READ_INTERVAL", 60, raising=False)
    monkeypatch.setattr(loop_runtime.time, "time", lambda: 60)
    monkeypatch.setattr(loop_runtime.actuators, "all_off", lambda: calls.append("all_off"))
    monkeypatch.setattr(loop_runtime.time, "ticks_ms", lambda: 0, raising=False)
    monkeypatch.setattr(loop_runtime.time, "ticks_diff", lambda now, start: 0, raising=False)

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise KeyboardInterrupt

    def fake_sleep_ms(ms):
        raise KeyboardInterrupt

    monkeypatch.setattr(loop_runtime.time, "sleep", fake_sleep)
    monkeypatch.setattr(loop_runtime.time, "sleep_ms", fake_sleep_ms, raising=False)

    loop_runtime.run_loop(
        state,
        display=lambda: display,
        refresh_display=lambda *args, **kwargs: calls.append(("refresh", kwargs)),
        read_all_sensors=lambda: False,
        safety_check=lambda: calls.append("safe") or True,
        make_decision=lambda: calls.append("decision") or {"action": "idle"},
        execute_decision=lambda decision: calls.append(("execute", decision["action"])),
        send_telemetry=lambda: calls.append("telemetry"),
    )

    assert state.read_count == 1
    assert ("ERR!", 0, 56) in display.overlays
    assert ("refresh", {"force": True}) in calls
    assert "safe" not in calls
    assert "decision" not in calls
    assert "telemetry" not in calls


def test_loop_polls_uart_and_sends_reports(monkeypatch):
    state = SystemState()
    calls = []

    monkeypatch.setattr(loop_runtime.config, "READ_INTERVAL", 60, raising=False)
    monkeypatch.setattr(loop_runtime.config, "DECISION_INTERVAL", 60, raising=False)
    monkeypatch.setattr(loop_runtime.config, "WIFI_RECONNECT_AFTER_MISSES", 99, raising=False)
    monkeypatch.setattr(loop_runtime.time, "time", lambda: 60)
    monkeypatch.setattr(loop_runtime.wifi_client, "is_connected", lambda **kwargs: True)
    monkeypatch.setattr(loop_runtime.actuators, "all_off", lambda: calls.append("all_off"))
    monkeypatch.setattr(loop_runtime.gc, "collect", lambda: None)
    monkeypatch.setattr(loop_runtime.time, "ticks_ms", lambda: 0, raising=False)
    monkeypatch.setattr(loop_runtime.time, "ticks_diff", lambda now, start: 0, raising=False)
    monkeypatch.setattr(loop_runtime.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(loop_runtime.time, "sleep_ms", lambda ms: (_ for _ in ()).throw(KeyboardInterrupt), raising=False)

    loop_runtime.run_loop(
        state,
        read_all_sensors=lambda: True,
        safety_check=lambda: True,
        make_decision=lambda: {"action": "idle"},
        execute_decision=lambda decision: calls.append(("execute", decision["action"])),
        uart_poll=lambda: calls.append("uart_poll"),
        uart_send_report=lambda: calls.append("uart_report"),
    )

    assert "uart_poll" in calls
    assert calls.count("uart_report") == 2
    assert ("execute", "idle") in calls
