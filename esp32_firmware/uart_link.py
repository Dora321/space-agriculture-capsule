"""UART link layer between ESP32 (flight controller) and Raspberry Pi (payload
computer).

Protocol: JSON-over-Line. One JSON object per line, terminated by '\n'.
Direction vocabulary:
  ESP32 -> Pi : report (sensors+state, ~every READ_INTERVAL), pong (reply to ping)
  Pi -> ESP32 : advice (AI decision, on demand), ping (heartbeat, ~every 10s)

ESP32 autonomy contract:
  - The Pi is an *advisor*. Every advice must still pass the ESP32-side safety
    check (rate limit / max run / temperature guard) before it touches an
    actuator. The ESP32 is the driver; the Pi only suggests.
  - If no Pi message arrives within `offline_timeout_ms`, `is_online()` goes
    False and the caller must fall back to the resident local rule engine.

This module is pure and dependency-injected: the real `machine.UART` is wired in
main.py, but tests pass a fake object exposing the same .any()/.read()/.write().
The clock is injected as `time_ms` so tests are deterministic. (`time_ms` is
expected to be monotonic-ish, e.g. time.ticks_ms; the 30s online window is short
enough that ticks_ms wrap is a non-issue for the contest timescale.)
"""

import ujson

PROTOCOL_VERSION = 1

MSG_REPORT = "report"
MSG_ADVICE = "advice"
MSG_PING = "ping"
MSG_PONG = "pong"

VALID_ACTIONS = ("water", "light", "idle")

# Pi advice "primary" -> internal action. "light_on" is accepted as an alias
# because the design doc uses it; both map to the firmware's "light" action.
_PRIMARY_TO_ACTION = {
    "water": "water",
    "light": "light",
    "light_on": "light",
    "idle": "idle",
}

# Advisory signal whitelist. MUST mirror status_strip.py signal constants and
# tools/ai_proxy._validate_decision / serial_gateway VALID_SIGNALS.
VALID_SIGNALS = (
    "WATER", "LIGHT_LOW", "LIGHT_HIGH", "TEMP_HIGH", "TEMP_LOW",
    "HUMID_LOW", "NEED_N", "NEED_P", "NEED_K",
    "SENSOR_FAIL", "OFFLINE_MODE", "BREEDING_GEN_UP",
)


def build_report(state, ts, online):
    """Build a report dict from SystemState. `ts` is a millisecond timestamp."""
    stage = getattr(state, "growth_stage", None) or {}
    src = getattr(state, "last_decision_source", "local")
    # wire vocabulary: decision came from the Pi ("pi") or local rules ("local")
    ai_src = "pi" if src in ("pi", "cloud") else "local"
    return {
        "t": MSG_REPORT,
        "ts": ts,
        "plant": state.plant_type,
        "day": state.days_since_planting,
        "stage": stage.get("stage", ""),
        "soil": state.soil_moisture,
        "light": state.light_level,
        "temp": state.temperature,
        "hum": state.humidity,
        "action": state.last_action,
        "duration_sec": getattr(state, "last_action_duration", 0),
        "action_time": getattr(state, "last_action_time", 0),
        "read_count": getattr(state, "read_count", 0),
        "action_count": getattr(state, "action_count", 0),
        "error_count": getattr(state, "error_count", 0),
        "ai_src": ai_src,
        "online": bool(online),
    }


def build_pong(ts):
    return {"t": MSG_PONG, "ts": ts}


def encode_line(obj):
    """Serialize a dict to a single newline-terminated UTF-8 line."""
    return (ujson.dumps(obj) + "\n").encode("utf-8")


def decode_line(line):
    """Parse one line (str/bytes) to a dict, or None if malformed.

    Tolerant by design: serial noise / partial frames must never raise."""
    if isinstance(line, (bytes, bytearray)):
        try:
            line = bytes(line).decode("utf-8")
        except Exception:
            return None
    line = line.strip()
    if not line:
        return None
    try:
        obj = ujson.loads(line)
    except (ValueError, TypeError, OSError):
        return None
    if not isinstance(obj, dict) or "t" not in obj:
        return None
    return obj


def advice_to_decision(advice):
    """Convert a Pi 'advice' message to the internal decision dict that
    action_runtime understands, or None if invalid.

    NOTE: the returned decision has NOT been safety-checked. The caller must
    still run it through the ESP32 safety gate before execution."""
    if not isinstance(advice, dict):
        return None
    action = _PRIMARY_TO_ACTION.get(advice.get("primary", "idle"))
    if action is None:
        return None
    try:
        duration = int(advice.get("duration", 0))
    except (ValueError, TypeError):
        duration = 0
    if duration < 0:
        duration = 0
    signals = []
    for item in advice.get("signals", []) or []:
        sig = item.get("sig") if isinstance(item, dict) else item
        if sig in VALID_SIGNALS and sig not in signals:
            signals.append(sig)
    return {
        "action": action,
        "duration_sec": duration,
        "reason": advice.get("note", "pi advice"),
        "signals": signals,
        "breeding_observation": advice.get("breeding_observation", ""),
        "seq": advice.get("seq"),
    }


class UartLink:
    """Framing + heartbeat/online tracking over an injected UART-like object.

    The uart must expose .any() -> int, .read(n) -> bytes|None, .write(bytes).
    """

    def __init__(self, uart, time_ms, offline_timeout_ms=30000, max_buf=512):
        self._uart = uart
        self._time_ms = time_ms
        self._offline_timeout_ms = offline_timeout_ms
        self._max_buf = max_buf
        self._rx = b""
        self._last_rx_ms = None
        self._last_seq = None

    # ---------- TX ----------
    def _send(self, obj):
        try:
            self._uart.write(encode_line(obj))
            return True
        except Exception as e:  # serial write must never crash the loop
            print("[UART] write failed:", e)
            return False

    def send_report(self, state, online=None):
        if online is None:
            online = self.is_online()
        return self._send(build_report(state, self._time_ms(), online))

    def send_pong(self, ts):
        return self._send(build_pong(ts))

    # ---------- RX ----------
    def poll(self):
        """Drain available bytes and return a list of actionable messages.

        Auto-replies to ping with pong (ping is not returned). Any decoded
        message refreshes the online timestamp."""
        try:
            n = self._uart.any()
        except Exception:
            n = 0
        if n:
            try:
                data = self._uart.read(n)
            except Exception:
                data = None
            if data:
                self._rx += bytes(data)

        # Bound the buffer: a flood with no newline must not grow forever.
        if len(self._rx) > self._max_buf:
            idx = self._rx.rfind(b"\n")
            self._rx = self._rx[idx + 1:] if idx >= 0 else b""

        msgs = []
        while b"\n" in self._rx:
            line, self._rx = self._rx.split(b"\n", 1)
            obj = decode_line(line)
            if obj is None:
                continue
            self._last_rx_ms = self._time_ms()
            t = obj.get("t")
            if t == MSG_PING:
                self.send_pong(obj.get("ts", 0))
                continue  # liveness recorded above; nothing for the caller to do
            if t == MSG_ADVICE:
                self._last_seq = obj.get("seq")
            msgs.append(obj)
        return msgs

    def is_online(self, now_ms=None):
        if self._last_rx_ms is None:
            return False
        if now_ms is None:
            now_ms = self._time_ms()
        return (now_ms - self._last_rx_ms) < self._offline_timeout_ms

    @property
    def last_seq(self):
        return self._last_seq
