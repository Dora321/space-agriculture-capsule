"""
执行器模块 - 控制水泵（12V 蠕动泵）和补光灯（12V COB 灯条），均为继电器低电平触发

硬件改动 2026-05-27：移除营养液泵，单泵单继电器。
硬件改动 2026-05-27：增加补光灯继电器（GPIO18）。
"""

import time
from machine import Pin
import config


_relay_water = None
_water_running = False
_relay_light = None
_light_running = False


def init():
    """初始化执行器（水泵 + 补光灯继电器）"""
    global _relay_water, _relay_light

    _relay_water = Pin(config.RELAY_WATER_PIN, Pin.OUT, value=1)  # 默认关闭（低电平触发）
    _relay_light = Pin(config.RELAY_LIGHT_PIN, Pin.OUT, value=1)  # 默认关闭（低电平触发）
    print("[Actuator] Initialization complete, water pump off, light off")
    return True


def _validate_duration(duration, max_sec=None):
    """返回安全执行时长（≤ max_sec）"""
    if duration <= 0:
        return 0
    cap = max_sec if max_sec is not None else config.PUMP_MAX_RUN_SEC
    return min(duration, cap)


def _relay_on(relay):
    relay.value(0)


def _relay_off(relay):
    relay.value(1)


def run_water_pump(duration_sec):
    """运行水泵 duration_sec 秒。分段 sleep 便于检测中断。"""
    global _water_running

    duration = _validate_duration(duration_sec)
    if duration == 0:
        return False

    print(f"[Water Pump] Starting for {duration}s")
    _water_running = True

    try:
        _relay_on(_relay_water)
        remaining = duration
        while remaining > 0:
            sleep_time = min(remaining, 1)
            time.sleep(sleep_time)
            remaining -= sleep_time
            print(f"[Water Pump] {remaining}s remaining")
        _relay_off(_relay_water)
        print("[Water Pump] Complete")
        return True
    except Exception as e:
        print("[Water Pump] Exception:", e)
        _relay_off(_relay_water)
        return False
    finally:
        _water_running = False


def run_light(duration_sec):
    """运行补光灯 duration_sec 秒。分段 sleep 便于检测中断。"""
    global _light_running

    max_sec = getattr(config, "LIGHT_MAX_RUN_SEC", 20)
    duration = _validate_duration(duration_sec, max_sec=max_sec)
    if duration == 0:
        return False

    print(f"[Light] Starting for {duration}s")
    _light_running = True

    try:
        _relay_on(_relay_light)
        remaining = duration
        while remaining > 0:
            sleep_time = min(remaining, 1)
            time.sleep(sleep_time)
            remaining -= sleep_time
            print(f"[Light] {remaining}s remaining")
        _relay_off(_relay_light)
        print("[Light] Complete")
        return True
    except Exception as e:
        print("[Light] Exception:", e)
        _relay_off(_relay_light)
        return False
    finally:
        _light_running = False


def water_pump_on():
    """手动持续开启水泵（需手动关闭）"""
    global _water_running
    print("[Water Pump] Manual ON")
    _relay_on(_relay_water)
    _water_running = True


def water_pump_off():
    """手动关闭水泵"""
    global _water_running
    print("[Water Pump] Manual OFF")
    _relay_off(_relay_water)
    _water_running = False


def light_on():
    """手动持续开启补光灯（需手动关闭）"""
    global _light_running
    print("[Light] Manual ON")
    _relay_on(_relay_light)
    _light_running = True


def light_off():
    """手动关闭补光灯"""
    global _light_running
    print("[Light] Manual OFF")
    _relay_off(_relay_light)
    _light_running = False


def all_off():
    """关闭所有执行器（紧急停止）"""
    global _water_running, _light_running
    print("[Actuator] Emergency OFF")
    _relay_off(_relay_water)
    _relay_off(_relay_light)
    _water_running = False
    _light_running = False


def is_any_running():
    """是否有执行器正在运行（直读硬件状态）"""
    return _relay_water.value() == 0 or _relay_light.value() == 0


def get_status():
    return {
        "water": {
            "running": _water_running,
            "relay_state": "on" if _relay_water.value() == 0 else "off",
        },
        "light": {
            "running": _light_running,
            "relay_state": "on" if _relay_light.value() == 0 else "off",
        }
    }


def test_sequence():
    """执行器自检：水泵 3 秒 + 补光灯 3 秒"""
    print("=== Actuator Test ===")
    print("\n[1/2] Testing water pump (3s)...")
    run_water_pump(3)
    time.sleep(1)
    print("\n[2/2] Testing light (3s)...")
    run_light(3)
    time.sleep(1)
    print("\n=== Test Complete ===")
