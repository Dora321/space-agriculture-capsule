"""Decision orchestration: ESP32 local rule engine (resident fallback).

Cloud AI lives on the Raspberry Pi side now (it sends advice over UART, applied
in main.py). The ESP32 keeps only this local rule engine as the always-available
fallback when no online Pi advice is present.
"""

import time

import utils


def local_decision(state, plant_info):
    return utils.local_fallback_decision(
        soil=state.soil_moisture,
        plant_info=plant_info,
        current_time=time.time(),
        light=state.light_level,
        sun_minutes=state.sun_minutes_today,
        uptime_sec=time.time() - state.start_time,
        temperature=state.temperature,
    )


def make_decision(state, plant_info, demo_enabled=False):
    """Return the ESP32 local-rule decision (resident fallback)."""
    if demo_enabled:
        print("[Demo Decision] Using local rules for deterministic showcase")
    decision = local_decision(state, plant_info)
    state.last_decision_source = "local"
    return decision
