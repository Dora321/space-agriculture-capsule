"""Tests for the ESP32-side UART link layer (esp32_firmware/uart_link.py).

conftest.py mocks ujson->json and machine, and puts esp32_firmware/ on the path,
so uart_link imports cleanly here. We inject a FakeUart + a controllable clock
instead of touching real hardware.
"""
import uart_link
from state import SystemState


class FakeUart:
    """Minimal UART double: .write/.any/.read plus test-only .feed()."""

    def __init__(self):
        self.tx = b""      # bytes the link wrote (toward the Pi)
        self._rx = b""     # bytes queued for the link to read (from the Pi)

    def write(self, data):
        self.tx += bytes(data)
        return len(data)

    def feed(self, data):
        """Test helper: simulate the Pi sending bytes to the ESP32."""
        self._rx += bytes(data)

    def any(self):
        return len(self._rx)

    def read(self, n=None):
        if n is None:
            n = len(self._rx)
        out, self._rx = self._rx[:n], self._rx[n:]
        return out if out else None


class Clock:
    def __init__(self, t=0):
        self.t = t

    def __call__(self):
        return self.t


# --------------------------------------------------------------------------
# pure encode / decode
# --------------------------------------------------------------------------

def test_encode_line_is_single_newline_terminated():
    line = uart_link.encode_line({"t": "ping", "ts": 5})
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
    assert uart_link.decode_line(line) == {"t": "ping", "ts": 5}


def test_decode_line_rejects_malformed():
    assert uart_link.decode_line(b"") is None
    assert uart_link.decode_line(b"   \n") is None
    assert uart_link.decode_line(b"not json") is None
    assert uart_link.decode_line(b"[1,2,3]") is None       # not a dict
    assert uart_link.decode_line(b'{"x":1}') is None       # missing "t"
    assert uart_link.decode_line(b'{"t":"ping"}') == {"t": "ping"}


def test_decode_line_tolerates_bad_utf8():
    assert uart_link.decode_line(b"\xff\xfe\x00") is None


# --------------------------------------------------------------------------
# report building
# --------------------------------------------------------------------------

def test_build_report_maps_state_fields():
    s = SystemState()
    s.plant_type = "lettuce"
    s.days_since_planting = 12
    s.growth_stage = {"stage": "vegetative"}
    s.soil_moisture = 42
    s.light_level = 55
    s.temperature = 24.3
    s.humidity = 65
    s.last_action = "water"
    s.last_decision_source = "local"

    r = uart_link.build_report(s, ts=1234, online=True)
    assert r["t"] == "report"
    assert r["ts"] == 1234
    assert r["plant"] == "lettuce"
    assert r["day"] == 12
    assert r["stage"] == "vegetative"
    assert r["soil"] == 42
    assert r["light"] == 55
    assert r["temp"] == 24.3
    assert r["hum"] == 65
    assert r["action"] == "water"
    assert r["ai_src"] == "local"
    assert r["online"] is True


def test_build_report_maps_cloud_source_to_pi():
    s = SystemState()
    s.last_decision_source = "cloud"
    assert uart_link.build_report(s, 0, False)["ai_src"] == "pi"
    s.last_decision_source = "pi"
    assert uart_link.build_report(s, 0, False)["ai_src"] == "pi"


def test_build_report_handles_missing_growth_stage():
    s = SystemState()
    s.growth_stage = None
    assert uart_link.build_report(s, 0, False)["stage"] == ""


# --------------------------------------------------------------------------
# advice -> decision
# --------------------------------------------------------------------------

def test_advice_to_decision_basic():
    d = uart_link.advice_to_decision({
        "t": "advice", "seq": 7, "primary": "water", "duration": 12,
        "signals": [{"sig": "LIGHT_LOW", "conf": 0.8}], "note": "dry soil",
    })
    assert d["action"] == "water"
    assert d["duration_sec"] == 12
    assert d["reason"] == "dry soil"
    assert d["signals"] == ["LIGHT_LOW"]
    assert d["seq"] == 7


def test_advice_light_on_alias_maps_to_light():
    assert uart_link.advice_to_decision(
        {"primary": "light_on", "duration": 60})["action"] == "light"


def test_advice_invalid_primary_returns_none():
    assert uart_link.advice_to_decision({"primary": "nutrient"}) is None
    assert uart_link.advice_to_decision({"primary": "explode"}) is None
    assert uart_link.advice_to_decision("nope") is None


def test_advice_duration_coercion_and_clamp():
    assert uart_link.advice_to_decision(
        {"primary": "water", "duration": "8"})["duration_sec"] == 8
    assert uart_link.advice_to_decision(
        {"primary": "water", "duration": -5})["duration_sec"] == 0
    assert uart_link.advice_to_decision(
        {"primary": "water", "duration": "bad"})["duration_sec"] == 0
    assert uart_link.advice_to_decision(
        {"primary": "idle"})["duration_sec"] == 0


def test_advice_filters_unknown_and_dedups_signals():
    d = uart_link.advice_to_decision({
        "primary": "idle",
        "signals": ["NEED_K", "BOGUS", {"sig": "NEED_K"}, {"sig": "TEMP_HIGH"}],
    })
    assert d["signals"] == ["NEED_K", "TEMP_HIGH"]


def test_advice_accepts_bare_string_signals():
    d = uart_link.advice_to_decision(
        {"primary": "idle", "signals": ["WATER", "LIGHT_LOW"]})
    assert d["signals"] == ["WATER", "LIGHT_LOW"]


# --------------------------------------------------------------------------
# UartLink framing / polling
# --------------------------------------------------------------------------

def test_send_report_writes_encoded_line():
    uart = FakeUart()
    clk = Clock(1000)
    link = uart_link.UartLink(uart, clk)
    s = SystemState()
    s.plant_type = "basil"
    link.send_report(s, online=True)
    assert uart.tx.endswith(b"\n")
    decoded = uart_link.decode_line(uart.tx)
    assert decoded["t"] == "report"
    assert decoded["ts"] == 1000
    assert decoded["plant"] == "basil"


def test_poll_buffers_partial_line_until_newline():
    uart = FakeUart()
    link = uart_link.UartLink(uart, Clock(0))
    uart.feed(b'{"t":"adv')
    assert link.poll() == []            # incomplete, nothing yet
    uart.feed(b'ice","primary":"idle"}\n')
    msgs = link.poll()
    assert len(msgs) == 1
    assert msgs[0]["primary"] == "idle"


def test_poll_returns_multiple_lines_in_one_read():
    uart = FakeUart()
    link = uart_link.UartLink(uart, Clock(0))
    uart.feed(b'{"t":"advice","seq":1,"primary":"water"}\n'
              b'{"t":"advice","seq":2,"primary":"idle"}\n')
    msgs = link.poll()
    assert [m["seq"] for m in msgs] == [1, 2]
    assert link.last_seq == 2


def test_poll_skips_garbage_between_good_lines():
    uart = FakeUart()
    link = uart_link.UartLink(uart, Clock(0))
    uart.feed(b'garbage!!!\n{"t":"advice","primary":"light"}\n\n')
    msgs = link.poll()
    assert len(msgs) == 1
    assert msgs[0]["primary"] == "light"


def test_poll_auto_replies_to_ping_with_pong_and_hides_ping():
    uart = FakeUart()
    clk = Clock(42)
    link = uart_link.UartLink(uart, clk)
    uart.feed(b'{"t":"ping","ts":99}\n')
    msgs = link.poll()
    assert msgs == []                   # ping is consumed, not surfaced
    pong = uart_link.decode_line(uart.tx)
    assert pong == {"t": "pong", "ts": 99}


def test_ping_refreshes_online_even_though_hidden():
    uart = FakeUart()
    clk = Clock(0)
    link = uart_link.UartLink(uart, clk, offline_timeout_ms=30000)
    assert link.is_online() is False    # nothing received yet
    uart.feed(b'{"t":"ping","ts":1}\n')
    link.poll()
    assert link.is_online() is True


def test_is_online_times_out():
    uart = FakeUart()
    clk = Clock(0)
    link = uart_link.UartLink(uart, clk, offline_timeout_ms=30000)
    uart.feed(b'{"t":"advice","primary":"idle"}\n')
    link.poll()                          # last_rx at t=0
    clk.t = 29999
    assert link.is_online() is True
    clk.t = 30000
    assert link.is_online() is False


def test_poll_caps_runaway_buffer():
    uart = FakeUart()
    link = uart_link.UartLink(uart, Clock(0), max_buf=64)
    uart.feed(b"x" * 500)                # no newline -> would grow unbounded
    assert link.poll() == []
    # after the cap, a real line still parses
    uart.feed(b'\n{"t":"advice","primary":"idle"}\n')
    msgs = link.poll()
    assert len(msgs) == 1


# --------------------------------------------------------------------------
# whitelist mirror guard
# --------------------------------------------------------------------------

def test_signal_whitelist_has_no_legacy_nutrient_token():
    assert "NEED_NUTRIENT" not in uart_link.VALID_SIGNALS
    assert "nutrient" not in uart_link.VALID_ACTIONS
