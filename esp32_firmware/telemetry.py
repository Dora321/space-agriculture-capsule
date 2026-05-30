"""Optional realtime dashboard telemetry for the contest display."""

import ujson
import config

_fail_count = 0
_backoff_until = 0


def _parse_http_url(url):
    if not url.startswith("http://"):
        raise ValueError("only http:// dashboard URLs are supported")
    rest = url[7:]
    if "/" in rest:
        host_port, path = rest.split("/", 1)
        path = "/" + path
    else:
        host_port = rest
        path = "/"
    if ":" in host_port:
        host, port_text = host_port.rsplit(":", 1)
        port = int(port_text)
    else:
        host = host_port
        port = 80
    return host, port, path


def _post_http_json(url, data, headers, timeout):
    import socket

    host, port, path = _parse_http_url(url)
    sock = None
    try:
        addr = socket.getaddrinfo(host, port)[0][-1]
        sock = socket.socket()
        sock.settimeout(timeout)
        sock.connect(addr)
        header_lines = [
            "POST %s HTTP/1.0" % path,
            "Host: %s" % host,
            "Content-Length: %d" % len(data),
            "Connection: close",
        ]
        for key, value in headers.items():
            header_lines.append("%s: %s" % (key, value))
        request_head = ("\r\n".join(header_lines) + "\r\n\r\n").encode("utf-8")
        sock.write(request_head)
        sock.write(data)
        response_head = sock.recv(64)
        return 200 if b" 200 " in response_head[:20] else 0
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def enabled():
    return bool(getattr(config, "DASHBOARD_URL", ""))


def send_state(state, ai_enabled=False):
    """Post a compact state snapshot to the local dashboard server."""
    global _fail_count, _backoff_until
    url = getattr(config, "DASHBOARD_URL", "")
    if not url:
        return False

    try:
        import time
        now = time.time()
        if _backoff_until and now < _backoff_until:
            return False
    except Exception:
        now = 0

    try:
        import gc
        gc.collect()

        growth_stage = state.growth_stage or {}
        payload = {
            "soil": state.soil_moisture,
            "light": state.light_level,
            "temperature": state.temperature,
            "humidity": state.humidity,
            "plant": state.plant_type,
            "stage": growth_stage.get("stage", ""),
            "days": state.days_since_planting,
            "action": state.last_action,
            "duration": state.last_action_duration,
            "reason": state.last_decision_reason,
            "sun_hours": state.sun_minutes_today / 60,
            "wifi": state.wifi_connected,
            "ai": ai_enabled,
            "read_count": state.read_count,
            "action_count": state.action_count,
            "error_count": getattr(state, "error_count", 0),
            "uptime_sec": 0,
            "decision_source": getattr(state, "last_decision_source", ""),
        }
        plant_info = getattr(state, "plant_info", None) or {}
        payload["soil_threshold"] = plant_info.get("soil_threshold", 30)
        payload["light_min"] = plant_info.get("light_min", 30)
        payload["light_opt"] = plant_info.get("light_opt", 50)
        payload["light_hours"] = plant_info.get("light_hours", [6, 8])
        payload["signals"] = getattr(state, "last_signals", [])
        payload["breeding_observation"] = getattr(state, "last_breeding_observation", "")
        try:
            import time
            if getattr(state, "start_time", 0):
                payload["uptime_sec"] = max(0, int(time.time() - state.start_time))
        except Exception:
            pass
        headers = {"Content-Type": "application/json"}
        token = getattr(config, "DASHBOARD_TOKEN", "")
        if token:
            headers["X-Dashboard-Token"] = token

        data = ujson.dumps(payload).encode("utf-8")
        del payload
        gc.collect()
        status_code = _post_http_json(
            url,
            data,
            headers,
            getattr(config, "DASHBOARD_TIMEOUT", 2),
        )
        ok = status_code == 200
        if not ok:
            print("[Telemetry] HTTP error:", status_code)
            _fail_count += 1
        else:
            _fail_count = 0
            _backoff_until = 0
            print("[Telemetry] sent")
        return ok
    except Exception as e:
        print("[Telemetry] send failed:", e)
        _fail_count += 1
        if _fail_count >= getattr(config, "TELEMETRY_BACKOFF_AFTER", 2):
            try:
                _backoff_until = now + getattr(config, "TELEMETRY_BACKOFF_SEC", 180)
                print("[Telemetry] backing off")
            except Exception:
                pass
        return False
    finally:
        try:
            gc.collect()
        except Exception:
            pass
