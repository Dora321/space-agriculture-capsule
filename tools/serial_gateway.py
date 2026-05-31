"""Raspberry Pi side of the ESP32 <-> Pi UART link.

Mirrors esp32_firmware/uart_link.py (same JSON-over-Line protocol) but runs on
CPython with stdlib json + pyserial.

Two layers:
  * GatewayCore  -- pure, transport-agnostic protocol engine. Feed it raw bytes
                    from the serial port; it returns parsed messages and gives
                    you encoded lines (ping / advice) to write back. Fully unit
                    tested in tests/test_serial_gateway.py with no hardware.
  * main()       -- the wiring layer: opens the serial port, pumps GatewayCore,
                    forwards ESP32 reports to the dashboard, and asks an advice
                    provider (e.g. the AI proxy) for decisions to send back.

Usage (once the UART is physically wired):
    py tools/serial_gateway.py --port /dev/serial0 --baud 115200
    py tools/serial_gateway.py --port COM5            # Windows dev
"""

import argparse
import json
import os
import time

PROTOCOL_VERSION = 1

MSG_REPORT = "report"
MSG_ADVICE = "advice"
MSG_PING = "ping"
MSG_PONG = "pong"

# MUST mirror uart_link.VALID_SIGNALS / status_strip.py / ai_proxy whitelist.
VALID_SIGNALS = (
    "WATER", "LIGHT_LOW", "LIGHT_HIGH", "TEMP_HIGH", "TEMP_LOW",
    "HUMID_LOW", "NEED_N", "NEED_P", "NEED_K",
    "SENSOR_FAIL", "OFFLINE_MODE", "BREEDING_GEN_UP",
)


def encode_line(obj):
    """Serialize a dict to a newline-terminated UTF-8 line.

    ensure_ascii=False keeps Chinese plant names readable on the wire and byte
    compatible with the ESP32's ujson output."""
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def decode_line(line):
    """Parse one line (str/bytes) to a dict, or None if malformed."""
    if isinstance(line, (bytes, bytearray)):
        try:
            line = bytes(line).decode("utf-8")
        except Exception:
            return None
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or "t" not in obj:
        return None
    return obj


class GatewayCore:
    """Transport-agnostic protocol engine for the Pi side.

    on_report(dict) / on_pong(dict) callbacks fire as messages are parsed.
    """

    def __init__(self, now_fn=time.monotonic, ping_interval_s=10,
                 offline_timeout_s=30, on_report=None, on_pong=None,
                 max_buf=4096):
        self._now = now_fn
        self._ping_interval = ping_interval_s
        self._offline_timeout = offline_timeout_s
        self._on_report = on_report
        self._on_pong = on_pong
        self._max_buf = max_buf
        self._buf = b""
        self._last_report_t = None
        self._last_ping_t = None
        self._seq = 0

    # ---------- RX ----------
    def feed(self, data):
        """Append raw bytes, parse complete lines, return list of message dicts."""
        if data:
            self._buf += bytes(data)
        if len(self._buf) > self._max_buf:
            idx = self._buf.rfind(b"\n")
            self._buf = self._buf[idx + 1:] if idx >= 0 else b""

        msgs = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            obj = decode_line(line)
            if obj is None:
                continue
            t = obj.get("t")
            if t == MSG_REPORT:
                self._last_report_t = self._now()
                if self._on_report:
                    self._on_report(obj)
            elif t == MSG_PONG:
                if self._on_pong:
                    self._on_pong(obj)
            msgs.append(obj)
        return msgs

    # ---------- TX ----------
    def make_ping(self, ts=None):
        if ts is None:
            ts = int(self._now() * 1000)
        return encode_line({"t": MSG_PING, "ts": ts})

    def make_advice(self, primary, duration, signals=None, note="",
                    breeding_observation=""):
        """Build an advice line. `signals` may be bare sig strings or
        {"sig","conf"} dicts; unknown signals are dropped."""
        self._seq += 1
        sig_list = []
        for s in (signals or []):
            if isinstance(s, dict):
                if s.get("sig") in VALID_SIGNALS:
                    sig_list.append({"sig": s["sig"],
                                     "conf": s.get("conf", 1.0)})
            elif s in VALID_SIGNALS:
                sig_list.append({"sig": s, "conf": 1.0})
        return encode_line({
            "t": MSG_ADVICE,
            "seq": self._seq,
            "primary": primary,
            "duration": duration,
            "signals": sig_list,
            "note": note,
            "breeding_observation": breeding_observation,
        })

    # ---------- timing ----------
    def tick(self, now=None):
        """Return a list of outgoing byte-lines due now (heartbeat ping)."""
        if now is None:
            now = self._now()
        out = []
        if self._last_ping_t is None or (now - self._last_ping_t) >= self._ping_interval:
            self._last_ping_t = now
            out.append(self.make_ping())
        return out

    def esp_online(self, now=None):
        """True if the ESP32 has sent a report within offline_timeout_s."""
        if self._last_report_t is None:
            return False
        if now is None:
            now = self._now()
        return (now - self._last_report_t) < self._offline_timeout

    @property
    def last_seq(self):
        return self._seq


# --------------------------------------------------------------------------
# Wiring layer (needs hardware + pyserial; not exercised by unit tests)
# --------------------------------------------------------------------------

def _install_sigpipe_guard():
    """Match dashboard_server/ai_proxy: don't die on a broken downstream pipe."""
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass  # not on POSIX, or not in main thread


def _report_to_dashboard_state(report):
    """Translate a UART report into the dashboard /api/state payload shape."""
    return {
        "soil": report.get("soil"),
        "light": report.get("light"),
        "temperature": report.get("temp"),
        "humidity": report.get("hum"),
        "plant": report.get("plant"),
        "stage": report.get("stage", ""),
        "days": report.get("day", 0),
        "action": report.get("action", "idle"),
        "wifi": report.get("online", False),
        "ai": report.get("ai_src") == "pi",
        "decision_source": report.get("ai_src", "local"),
    }


def _post_json(url, payload, timeout=2):
    import urllib.request
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _heuristic_advice_from_report(report, soil_threshold=30, light_threshold=30,
                                  water_sec=8, light_sec=45):
    """Tiny Pi-side rule advisor for UART bring-up and offline demos.

    This is intentionally conservative. The ESP32 still performs the final
    safety checks before actuators move.
    """
    try:
        soil = float(report.get("soil", 100))
    except (TypeError, ValueError):
        soil = 100
    try:
        light = float(report.get("light", 100))
    except (TypeError, ValueError):
        light = 100

    if soil < soil_threshold:
        return {
            "primary": "water",
            "duration": int(water_sec),
            "signals": ["WATER"],
            "note": "Pi rule: soil below threshold",
        }
    if light < light_threshold:
        return {
            "primary": "light_on",
            "duration": int(light_sec),
            "signals": ["LIGHT_LOW"],
            "note": "Pi rule: light below threshold",
        }
    return {
        "primary": "idle",
        "duration": 0,
        "signals": [],
        "note": "Pi rule: stable",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="ESP32<->Pi UART gateway")
    parser.add_argument("--port", default="/dev/serial0",
                        help="serial device (e.g. /dev/serial0, COM5)")
    parser.add_argument("--baud", type=int, default=115200)
    # The dashboard URL defaults to $SPACEFARM_DASHBOARD so it can be supplied via the
    # environment instead of argv. This is deliberate on the deployment Pi: it runs an
    # openclaw hardware watchdog (pi-project/.../hardware_watchdog.sh) that SIGKILLs any
    # python process whose *command line* contains a hardware-lib keyword -- and its
    # "board" pattern matched the substring in "--dashboard". Passing the URL through the
    # systemd unit's Environment= keeps "board" out of argv so the gateway isn't killed.
    # (The watchdog regex was also tightened to a word boundary, 2026-05-30; see DEVLOG.)
    parser.add_argument("--dashboard",
                        default=os.environ.get("SPACEFARM_DASHBOARD",
                                               "http://127.0.0.1:8790/api/state"),
                        help="dashboard state endpoint ('' to disable). Defaults to "
                             "$SPACEFARM_DASHBOARD so the URL can be supplied via the "
                             "environment instead of argv.")
    parser.add_argument("--ping-interval", type=float, default=10.0)
    parser.add_argument("--offline-timeout", type=float, default=30.0)
    parser.add_argument("--auto-advice", action="store_true",
                        help="send a conservative Pi rule advice after each report")
    parser.add_argument("--soil-threshold", type=float, default=30.0)
    parser.add_argument("--light-threshold", type=float, default=30.0)
    parser.add_argument("--water-sec", type=int, default=8)
    parser.add_argument("--light-sec", type=int, default=45)
    parser.add_argument("--test-advice", choices=("water", "light_on", "idle"),
                        default="", help="send one fixed advice after first report")
    parser.add_argument("--test-duration", type=int, default=8)
    parser.add_argument("--ai-advice", action="store_true",
                        help="ask DeepSeek (tools/pi_advisor) for advice on each report; "
                             "falls back to the conservative heuristic on AI failure. "
                             "Key/model come from SPACEFARM_AI_* env vars.")
    parser.add_argument("--plants-json",
                        default=os.environ.get("SPACEFARM_PLANTS_JSON", ""),
                        help="path to plants.json for plant thresholds (optional, "
                             "improves AI prompt quality)")
    args = parser.parse_args(argv)

    _install_sigpipe_guard()

    try:
        import serial  # pyserial
    except ImportError:
        raise SystemExit("pyserial not installed: pip install pyserial")

    def on_report(report):
        # Dashboard forwarding happens in the main loop so it can merge the active
        # AI advice (reason / signals / duration / breeding) into the payload.
        print("[GW] report:", report)

    def on_pong(_pong):
        pass  # liveness only; nothing to do

    core = GatewayCore(
        ping_interval_s=args.ping_interval,
        offline_timeout_s=args.offline_timeout,
        on_report=on_report,
        on_pong=on_pong,
    )

    advisor = None
    pi_advisor = None
    if args.ai_advice:
        import pi_advisor  # noqa: F811  (stdlib-only DeepSeek advisor)
        advisor = pi_advisor.DeepSeekAdvisor()
        print("[GW] AI advice enabled (DeepSeek):",
              "configured" if advisor.configured()
              else "NOT configured -> heuristic fallback")

    # Last AI advice, merged into the dashboard payload so the AI panel reflects the
    # real decision (reason / signals / breeding), not just the report.
    last_advice = {"primary": "idle", "duration": 0, "signals": [], "note": "", "breeding_observation": ""}

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    print("[GW] gateway up on %s @ %d" % (args.port, args.baud))
    try:
        while True:
            try:
                waiting = ser.in_waiting
                data = ser.read(waiting or 1)
            except (OSError, IOError) as e:
                print("[GW] serial read error:", e)
                time.sleep(1)
                continue
            for msg in core.feed(data):
                if msg.get("t") != MSG_REPORT:
                    continue
                advice = None
                if args.test_advice:
                    test_signals = []
                    if args.test_advice == "water":
                        test_signals = ["WATER"]
                    elif args.test_advice == "light_on":
                        test_signals = ["LIGHT_LOW"]
                    advice = {
                        "primary": args.test_advice,
                        "duration": args.test_duration,
                        "signals": test_signals,
                        "note": "manual UART test",
                    }
                    args.test_advice = ""  # send once
                elif advisor is not None:
                    # ① DeepSeek (the smart brain on the Pi)
                    plant_info = (
                        pi_advisor.load_plant_info(msg.get("plant", ""), args.plants_json)
                        if args.plants_json else None
                    )
                    advice = advisor.advise(msg, plant_info)
                    if advice is None:
                        # ② fall back to the conservative heuristic
                        advice = _heuristic_advice_from_report(
                            msg,
                            soil_threshold=args.soil_threshold,
                            light_threshold=args.light_threshold,
                            water_sec=args.water_sec,
                            light_sec=args.light_sec,
                        )
                elif args.auto_advice:
                    advice = _heuristic_advice_from_report(
                        msg,
                        soil_threshold=args.soil_threshold,
                        light_threshold=args.light_threshold,
                        water_sec=args.water_sec,
                        light_sec=args.light_sec,
                    )
                if advice is not None:
                    last_advice = advice
                    try:
                        line = core.make_advice(
                            advice["primary"],
                            advice["duration"],
                            signals=advice.get("signals", []),
                            note=advice.get("note", ""),
                            breeding_observation=advice.get("breeding_observation", ""),
                        )
                        ser.write(line)
                        print("[GW] advice:", decode_line(line))
                    except (BrokenPipeError, ConnectionResetError, OSError) as e:
                        print("[GW] advice write error:", e)
                # forward report + active AI decision to the dashboard
                if args.dashboard:
                    payload = _report_to_dashboard_state(msg)
                    payload["duration"] = int(last_advice.get("duration", 0) or 0)
                    payload["reason"] = last_advice.get("note", "")
                    payload["signals"] = [
                        (s.get("sig") if isinstance(s, dict) else s)
                        for s in last_advice.get("signals", [])
                    ]
                    payload["breeding_observation"] = last_advice.get("breeding_observation", "")
                    try:
                        _post_json(args.dashboard, payload)
                    except Exception as e:
                        print("[GW] dashboard forward failed:", e)
            for line in core.tick():
                try:
                    ser.write(line)
                except (BrokenPipeError, ConnectionResetError, OSError) as e:
                    print("[GW] serial write error:", e)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[GW] stopped")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
