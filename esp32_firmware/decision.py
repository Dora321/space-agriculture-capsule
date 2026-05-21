"""Decision orchestration for local rules and cloud AI."""

import gc
import time

import config
import utils


def _sensor_snapshot(state):
    stage = state.growth_stage or {}
    return {
        "soil": state.soil_moisture,
        "light": state.light_level,
        "temp": state.temperature,
        "hum": state.humidity,
        "plant": state.plant_type,
        "stage": stage.get("stage", ""),
    }


def _abs_delta(snapshot, prev, key, default=0):
    return abs(snapshot.get(key, default) - prev.get(key, snapshot.get(key, default)))


def _ai_input_changed(state, snapshot):
    prev = state.last_ai_snapshot
    if not prev:
        return False
    if snapshot["plant"] != prev.get("plant") or snapshot["stage"] != prev.get("stage"):
        return True
    return (
        _abs_delta(snapshot, prev, "soil") >= getattr(config, "AI_SOIL_DELTA", 8)
        or _abs_delta(snapshot, prev, "light") >= getattr(config, "AI_LIGHT_DELTA", 20)
        or _abs_delta(snapshot, prev, "temp") >= getattr(config, "AI_TEMP_DELTA", 3)
        or _abs_delta(snapshot, prev, "hum") >= getattr(config, "AI_HUM_DELTA", 12)
    )


def _should_request_ai(state, local_decision, plant_info):
    now = time.time()
    snapshot = _sensor_snapshot(state)
    last_ai = state.last_ai_request_time
    min_interval = getattr(config, "AI_MIN_REQUEST_INTERVAL", 900)
    force_interval = getattr(config, "AI_FORCE_REQUEST_INTERVAL", 3600)
    soil_threshold = plant_info.get("soil_threshold", 30)
    light_min = plant_info.get("light_min", 30)

    threshold_event = (
        state.soil_moisture < soil_threshold
        or state.light_level < light_min
        or local_decision.get("action") in ("water", "nutrient")
    )
    changed = _ai_input_changed(state, snapshot)
    forced = last_ai > 0 and now - last_ai >= force_interval

    if not (threshold_event or changed or forced):
        return False, "stable", snapshot
    if last_ai > 0 and now - last_ai < min_interval:
        remain = int(min_interval - (now - last_ai))
        return False, f"rate limited {remain}s", snapshot
    return True, "threshold" if threshold_event else ("changed" if changed else "periodic"), snapshot


def local_decision(state, plant_info):
    return utils.local_fallback_decision(
        soil=state.soil_moisture,
        plant_info=plant_info,
        last_nutrient=state.last_nutrient_time,
        current_time=time.time(),
        light=state.light_level,
        sun_minutes=state.sun_minutes_today,
        uptime_sec=time.time() - state.start_time,
    )


def make_decision(state, plant_info, demo_enabled=False, release_display=None):
    """Return a decision using cloud AI when warranted, otherwise local rules."""
    ai_plant_info = {
        "soil_threshold": plant_info["soil_threshold"],
        "light_min": plant_info.get("light_min", 30),
        "light_opt": plant_info.get("light_opt", 50),
        "light_hours": plant_info.get("light_hours", [6, 8]),
    }
    fallback = local_decision(state, plant_info)
    if demo_enabled:
        print("[Demo Decision] Using local rules for deterministic showcase")
        state.last_decision_source = "local"
        return fallback

    ai_result = None
    if state.wifi_connected:
        should_ai, skip_reason, snapshot = _should_request_ai(state, fallback, plant_info)
        if not should_ai:
            print(f"[AI] Skipped: {skip_reason}, using local rules")
            state.last_decision_source = "local"
            return fallback

        use_proxy = bool(getattr(config, "AI_PROXY_URL", ""))
        if not use_proxy and release_display is not None:
            release_display()
        gc.collect()
        free_mem = gc.mem_free()
        min_ai_mem = getattr(config, "AI_MIN_FREE_MEM", 110000)
        if use_proxy or free_mem >= min_ai_mem:
            import ai_client

            ai_result = ai_client.query_decision(
                plant_type=state.plant_type,
                soil_moisture=state.soil_moisture,
                light_level=state.light_level,
                temperature=state.temperature,
                humidity=state.humidity,
                plant_info=ai_plant_info,
                days_since_planting=state.days_since_planting,
                growth_stage=state.growth_stage,
                sun_minutes_today=state.sun_minutes_today,
            )
            state.last_ai_request_time = time.time()
            state.last_ai_snapshot = snapshot
        else:
            print(f"[AI] Low memory ({free_mem} bytes), using local rules")

    if ai_result:
        state.last_decision_source = "cloud"
        print(
            f"[AI Decision] action={ai_result['action']} "
            f"duration={ai_result['duration_sec']}s reason={ai_result['reason']}"
        )
        return ai_result

    print("[Local Rule] Cloud timeout, using local decision")
    state.last_decision_source = "local"
    return fallback
