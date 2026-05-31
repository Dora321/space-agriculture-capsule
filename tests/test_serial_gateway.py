"""Tests for the Pi-side UART gateway (tools/serial_gateway.py).

The pure GatewayCore is exercised with no hardware. The cross-side tests are the
important guarantee: a line encoded on one side must decode on the other, so the
two mirrored protocol implementations can never silently drift apart.
"""
import importlib.util
import pathlib
import sys

import uart_link  # ESP32 side (esp32_firmware on path via conftest)


def _load_gateway_module():
    spec = importlib.util.spec_from_file_location(
        "serial_gateway",
        str(pathlib.Path(__file__).resolve().parent.parent / "tools" / "serial_gateway.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["serial_gateway"] = module
    spec.loader.exec_module(module)
    return module


gw = _load_gateway_module()


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


# --------------------------------------------------------------------------
# encode / decode
# --------------------------------------------------------------------------

def test_encode_decode_roundtrip():
    line = gw.encode_line({"t": "advice", "seq": 1, "primary": "water"})
    assert line.endswith(b"\n")
    assert gw.decode_line(line) == {"t": "advice", "seq": 1, "primary": "water"}


def test_decode_line_rejects_malformed():
    assert gw.decode_line(b"") is None
    assert gw.decode_line(b"junk") is None
    assert gw.decode_line(b"[1,2]") is None
    assert gw.decode_line(b'{"no":"type"}') is None


# --------------------------------------------------------------------------
# feed / parse
# --------------------------------------------------------------------------

def test_feed_parses_report_and_fires_callback():
    seen = []
    core = gw.GatewayCore(now_fn=Clock(100), on_report=seen.append)
    msgs = core.feed(b'{"t":"report","soil":40,"plant":"basil"}\n')
    assert len(msgs) == 1
    assert seen and seen[0]["soil"] == 40


def test_feed_handles_partial_then_complete():
    core = gw.GatewayCore(now_fn=Clock(0))
    assert core.feed(b'{"t":"rep') == []
    msgs = core.feed(b'ort","soil":1}\n')
    assert len(msgs) == 1


def test_feed_skips_garbage_lines():
    core = gw.GatewayCore(now_fn=Clock(0))
    msgs = core.feed(b'oops\n{"t":"report","soil":2}\n\n')
    assert len(msgs) == 1
    assert msgs[0]["soil"] == 2


def test_feed_fires_pong_callback():
    pongs = []
    core = gw.GatewayCore(now_fn=Clock(0), on_pong=pongs.append)
    core.feed(b'{"t":"pong","ts":7}\n')
    assert pongs and pongs[0]["ts"] == 7


def test_feed_caps_runaway_buffer():
    core = gw.GatewayCore(now_fn=Clock(0), max_buf=32)
    assert core.feed(b"x" * 200) == []
    msgs = core.feed(b'\n{"t":"report","soil":3}\n')
    assert len(msgs) == 1


# --------------------------------------------------------------------------
# heartbeat / online
# --------------------------------------------------------------------------

def test_tick_emits_ping_when_due():
    clk = Clock(0)
    core = gw.GatewayCore(now_fn=clk, ping_interval_s=10)
    first = core.tick()                  # first ever tick -> ping immediately
    assert len(first) == 1
    assert gw.decode_line(first[0])["t"] == "ping"
    clk.t = 5
    assert core.tick() == []             # not due yet
    clk.t = 10
    assert len(core.tick()) == 1         # due again


def test_esp_online_tracks_reports():
    clk = Clock(0)
    core = gw.GatewayCore(now_fn=clk, offline_timeout_s=30)
    assert core.esp_online() is False
    core.feed(b'{"t":"report","soil":1}\n')
    assert core.esp_online() is True
    clk.t = 29.9
    assert core.esp_online() is True
    clk.t = 30.0
    assert core.esp_online() is False


def test_make_advice_increments_seq_and_filters_signals():
    core = gw.GatewayCore(now_fn=Clock(0))
    a1 = gw.decode_line(core.make_advice("water", 10, signals=["LIGHT_LOW", "BOGUS"]))
    a2 = gw.decode_line(core.make_advice("idle", 0))
    assert a1["seq"] == 1 and a2["seq"] == 2
    assert a1["signals"] == [{"sig": "LIGHT_LOW", "conf": 1.0}]


# --------------------------------------------------------------------------
# report -> dashboard state translation
# --------------------------------------------------------------------------

def test_report_to_dashboard_state_translation():
    report = {
        "t": "report", "soil": 40, "light": 55, "temp": 24.0, "hum": 60,
        "plant": "lettuce", "stage": "veg", "day": 5, "action": "water",
        "duration_sec": 8, "read_count": 11, "action_count": 2, "error_count": 1,
        "online": True, "ai_src": "pi",
    }
    state = gw._report_to_dashboard_state(report)
    assert state["soil"] == 40
    assert state["temperature"] == 24.0
    assert state["humidity"] == 60
    assert state["days"] == 5
    assert state["wifi"] is True
    assert state["ai"] is True
    assert state["duration"] == 8
    assert state["read_count"] == 11
    assert state["action_count"] == 2
    assert state["error_count"] == 1
    assert state["decision_source"] == "pi"


def test_dashboard_action_from_advice_normalizes_primary():
    assert gw._dashboard_action_from_advice({"primary": "water"}) == "water"
    assert gw._dashboard_action_from_advice({"primary": "light_on"}) == "light"
    assert gw._dashboard_action_from_advice({"primary": "idle"}) == "idle"


def test_heuristic_advice_waters_when_soil_low():
    advice = gw._heuristic_advice_from_report(
        {"soil": 20, "light": 80},
        soil_threshold=30,
        light_threshold=30,
        water_sec=9,
    )
    assert advice["primary"] == "water"
    assert advice["duration"] == 9
    assert advice["signals"] == ["WATER"]


def test_heuristic_advice_lights_when_light_low():
    advice = gw._heuristic_advice_from_report(
        {"soil": 80, "light": 10},
        soil_threshold=30,
        light_threshold=30,
        light_sec=50,
    )
    assert advice["primary"] == "light_on"
    assert advice["duration"] == 50
    assert advice["signals"] == ["LIGHT_LOW"]


def test_heuristic_advice_idles_when_stable():
    advice = gw._heuristic_advice_from_report({"soil": 80, "light": 80})
    assert advice["primary"] == "idle"
    assert advice["duration"] == 0


# --------------------------------------------------------------------------
# CROSS-SIDE wire compatibility (the key guarantee)
# --------------------------------------------------------------------------

def test_esp_report_decodes_on_pi():
    from state import SystemState
    s = SystemState()
    s.plant_type = "番茄"           # non-ASCII must survive the wire
    s.soil_moisture = 33
    s.last_decision_source = "local"
    line = uart_link.encode_line(uart_link.build_report(s, ts=999, online=True))

    core = gw.GatewayCore(now_fn=Clock(0))
    msgs = core.feed(line)
    assert len(msgs) == 1
    r = msgs[0]
    assert r["t"] == "report"
    assert r["plant"] == "番茄"
    assert r["soil"] == 33
    assert r["ts"] == 999
    assert core.esp_online() is True


def test_pi_advice_decodes_and_converts_on_esp():
    core = gw.GatewayCore(now_fn=Clock(0))
    line = core.make_advice("light_on", 45,
                            signals=["LIGHT_LOW", "NEED_K"], note="补光补钾")
    obj = uart_link.decode_line(line)
    assert obj["t"] == "advice"
    decision = uart_link.advice_to_decision(obj)
    assert decision["action"] == "light"        # light_on alias resolved
    assert decision["duration_sec"] == 45
    assert decision["reason"] == "补光补钾"
    assert decision["signals"] == ["LIGHT_LOW", "NEED_K"]
    assert decision["seq"] == 1


def test_pi_ping_decodes_and_esp_pongs():
    core = gw.GatewayCore(now_fn=Clock(0))
    ping = core.tick()[0]

    # feed the Pi's ping into an ESP32 link; it should pong back
    import test_uart_link as t
    uart = t.FakeUart()
    link = uart_link.UartLink(uart, t.Clock(0))
    uart.feed(ping)
    assert link.poll() == []                     # ping hidden from caller
    pong = uart_link.decode_line(uart.tx)
    assert pong["t"] == "pong"

    # and the Pi understands that pong
    pongs = []
    core2 = gw.GatewayCore(now_fn=Clock(0), on_pong=pongs.append)
    core2.feed(uart.tx)
    assert pongs and pongs[0]["t"] == "pong"


def test_signal_whitelists_match_between_sides():
    assert set(gw.VALID_SIGNALS) == set(uart_link.VALID_SIGNALS)
