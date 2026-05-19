"""Optional realtime dashboard telemetry for the contest display."""

import ujson
import config


def enabled():
    return bool(getattr(config, "DASHBOARD_URL", ""))


def send_state(state, ai_enabled=False):
    """Post a compact state snapshot to the local dashboard server."""
    url = getattr(config, "DASHBOARD_URL", "")
    if not url:
        return False

    response = None
    try:
        import urequests

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

        response = urequests.post(
            url,
            data=ujson.dumps(payload).encode("utf-8"),
            headers=headers,
            timeout=getattr(config, "DASHBOARD_TIMEOUT", 2),
        )
        ok = response.status_code == 200
        if not ok:
            print("[Telemetry] HTTP error:", response.status_code)
        return ok
    except Exception as e:
        print("[Telemetry] send failed:", e)
        return False
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
