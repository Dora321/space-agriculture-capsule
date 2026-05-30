"""On-device heap profiler: measure total-free vs largest-contiguous-block at
each stage of the firmware bring-up, to locate the fragmentation that drives the
OOM seen in the 2026-05-30 retest.

Run from PC (does a clean soft-reset VM, skips main.py):
    py -m mpremote connect COM3 run esp32_firmware/diagnostics/mem_profile.py

Key metric: when `free` stays high but `largest` collapses, the heap is
fragmented (MicroPython GC does not compact). That is the real failure mode,
not absolute exhaustion.
"""

import gc


def _largest_block():
    """Binary-search the largest single bytearray we can allocate."""
    gc.collect()
    lo = 0
    hi = gc.mem_free()
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if mid == 0:
            break
        try:
            b = bytearray(mid)
            best = mid
            del b
            lo = mid + 1
        except MemoryError:
            hi = mid - 1
        gc.collect()
    return best


def stage(label):
    gc.collect()
    free = gc.mem_free()
    alloc = gc.mem_alloc()
    largest = _largest_block()
    frag = 100 - (largest * 100 // free) if free else 0
    print("[MEM] %-26s free=%6d alloc=%6d largest=%6d frag=%2d%%"
          % (label, free, alloc, largest, frag))
    return free, largest


def main():
    print("=== mem_profile start ===")
    stage("0 boot/baseline")

    import config
    import state
    stage("1 +config +state")

    s = state.SystemState()
    s.soil_moisture = 42
    s.light_level = 55
    s.temperature = 24
    s.humidity = 65
    s.plant_type = "lettuce"
    s.growth_stage = {"stage": "seedling"}
    s.plant_info = {"soil_threshold": 30, "light_min": 30,
                    "light_opt": 50, "light_hours": [6, 8], "name": "lettuce"}
    stage("2 +SystemState obj")

    try:
        import sh1106
        import display
        display.init()
        stage("3 +OLED display.init")
    except Exception as e:
        print("[MEM] OLED init skipped:", e)

    try:
        import sensors
        import actuators
        import utils
        import status_strip
        stage("4 +sensors/act/utils/strip")
    except Exception as e:
        print("[MEM] group4 import err:", e)

    try:
        import telemetry
        import decision
        import ai_client
        stage("5 +telemetry/decision/ai")
    except Exception as e:
        print("[MEM] group5 import err:", e)

    # --- simulate one telemetry payload build (what runs every loop) ---
    try:
        import ujson
        payload = {
            "soil": s.soil_moisture, "light": s.light_level,
            "temperature": s.temperature, "humidity": s.humidity,
            "plant": s.plant_type, "stage": "seedling", "days": 0,
            "action": "idle", "duration": 0, "reason": "ok",
            "sun_hours": 0, "wifi": True, "ai": False,
            "read_count": 1, "action_count": 0, "error_count": 0,
            "uptime_sec": 60, "decision_source": "local",
            "soil_threshold": 30, "light_min": 30, "light_opt": 50,
            "light_hours": [6, 8], "signals": [], "breeding_observation": "",
        }
        data = ujson.dumps(payload).encode("utf-8")
        print("[MEM] telemetry json bytes =", len(data))
        del payload, data
        stage("6 after telemetry json")
    except Exception as e:
        print("[MEM] telemetry sim err:", e)

    # --- simulate AI proxy body + the (currently wasteful) full payload build ---
    try:
        import ai_client
        full = ai_client._build_payload(
            s.plant_type, s.soil_moisture, s.light_level, s.temperature,
            s.humidity, s.plant_info, s.days_since_planting,
            s.growth_stage, s.sun_minutes_today,
        )
        fb = ujson.dumps(full)
        print("[MEM] cloud payload json bytes =", len(fb))
        del full, fb
        stage("7 after ai _build_payload")
    except Exception as e:
        print("[MEM] ai sim err:", e)

    # --- simulate response accumulation fragmentation (resp += chunk) ---
    try:
        resp = b""
        for _ in range(40):
            resp += b"x" * 256
        print("[MEM] simulated resp bytes =", len(resp))
        del resp
        stage("8 after resp+=chunk x40")
    except Exception as e:
        print("[MEM] resp sim err:", e)

    print("=== mem_profile done ===")


main()
