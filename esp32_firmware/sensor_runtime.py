"""Sensor read orchestration and growth counters."""

import time

import config
import sensors
import utils


def format_date():
    t = time.localtime()
    return f"{t[0]}-{t[1]}-{t[2]}"


def _demo_value(name, default):
    return getattr(config, name, default)


def _apply_reading(state, soil, light, temp, hum, plant, days_since_planting, sun_increment_minutes):
    state.soil_moisture = soil
    state.light_level = light
    state.temperature = temp
    state.humidity = hum
    state.plant_type = plant
    state.days_since_planting = days_since_planting
    state.plant_info = config.get_plant_info(plant)
    state.growth_stage = config.get_growth_stage(state.plant_info, state.days_since_planting)

    today = format_date()
    if today != state.sun_date:
        state.sun_date = today
        state.sun_minutes_today = 0
    light_min = state.plant_info.get("light_min", 30)
    if state.light_level >= light_min:
        state.sun_minutes_today += int(sun_increment_minutes)


def read_all_sensors(state, demo_enabled=False, show_error=None):
    """Read hardware sensors, downgrade offline values, and update runtime state."""
    if demo_enabled:
        return read_demo_sensors(state)

    try:
        soil = sensors.read_soil_moisture()
        light = sensors.read_light_level()
        temp, hum = sensors.read_dht22()
        # 植物类型由菜单系统设定，不再从硬件编码读取
        plant = state.plant_type if state.plant_type else "生菜"

        sensor_failures = []
        if soil is None:
            sensor_failures.append("Soil")
            soil = 0
        if light is None:
            sensor_failures.append("Light")
            light = 0
        if temp is None or hum is None:
            sensor_failures.append("DHT")
            temp = temp if temp is not None else 25.0
            hum = hum if hum is not None else 60.0

        if sensor_failures:
            fail_msg = "OFFLINE: " + ",".join(sensor_failures)
            print(f"[Alert] Sensor offline: {fail_msg}")
            utils.set_led("red")
            if show_error is not None:
                show_error(fail_msg)
            time.sleep(2)
            state.error_count += 1

        _apply_reading(
            state,
            soil,
            light,
            temp,
            hum,
            plant,
            config.calc_days_since_planting(),
            int(config.READ_INTERVAL / 60),
        )

        stage_name = state.growth_stage.get("stage", "unknown")
        fert = state.growth_stage.get("fert", "NPK")
        print(
            f"[Sensor] Soil:{state.soil_moisture}% | Light:{state.light_level}% | "
            f"Temp:{state.temperature}C | Hum:{state.humidity}%"
        )
        print(
            f"[Growth] Day {state.days_since_planting} | Stage: {stage_name} | "
            f"Fert: {fert} | Sun:{state.sun_minutes_today / 60:.1f}h"
        )

        state.error_count = 0
        return True
    except Exception as e:
        print("[Error] Sensor read failed:", e)
        state.error_count += 1
        return False


def read_demo_sensors(state):
    """Generate fast-changing contest demo data without physical sensor changes."""
    try:
        plant = _demo_value("DEMO_PLANT_TYPE", "\u751f\u83dc")
        if state.demo_soil_moisture is None:
            state.demo_soil_moisture = _demo_value("DEMO_START_SOIL", 42)
        else:
            drop = _demo_value("DEMO_SOIL_DROP", 7)
            state.demo_soil_moisture = max(0, state.demo_soil_moisture - drop)

        _apply_reading(
            state,
            int(state.demo_soil_moisture),
            _demo_value("DEMO_LIGHT_LEVEL", 72),
            _demo_value("DEMO_TEMPERATURE", 24.5),
            _demo_value("DEMO_HUMIDITY", 62),
            plant,
            max(0, state.read_count + 6),
            int(_demo_value("DEMO_READ_INTERVAL", 5)),
        )

        stage_name = state.growth_stage.get("stage", "unknown")
        print(
            f"[Demo Sensor] Soil:{state.soil_moisture}% | Light:{state.light_level}% | "
            f"Temp:{state.temperature}C | Hum:{state.humidity}% | Stage:{stage_name}"
        )
        state.error_count = 0
        return True
    except Exception as e:
        print("[Demo] Sensor simulation failed:", e)
        state.error_count += 1
        return False
