"""
执行器模块 - 控制水泵（12V 蠕动泵，单继电器低电平触发）

硬件改动 2026-05-27：移除营养液泵，单泵单继电器。
"""

import time
from machine import Pin
import config


_relay_water = None
_water_running = False


def init():
    """初始化执行器（仅水泵继电器）"""
    global _relay_water

    _relay_water = Pin(config.RELAY_WATER_PIN, Pin.OUT, value=1)  # 默认关闭（低电平触发）
    print("[Actuator] Initialization complete, water pump off")
    return True


def _validate_duration(duration):
    """返回安全执行时长（≤ PUMP_MAX_RUN_SEC）"""
    if duration <= 0:
        return 0
    return min(duration, config.PUMP_MAX_RUN_SEC)


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


def all_off():
    """关闭所有执行器（紧急停止）"""
    global _water_running
    print("[Actuator] Emergency OFF")
    _relay_off(_relay_water)
    _water_running = False


def is_any_running():
    """是否有执行器正在运行（直读硬件状态）"""
    return _relay_water.value() == 0


def get_status():
    return {
        "water": {
            "running": _water_running,
            "relay_state": "on" if _relay_water.value() == 0 else "off",
        }
    }


def test_sequence():
    """执行器自检：水泵 3 秒"""
    print("=== Actuator Test ===")
    print("\n[1/1] Testing water pump (3s)...")
    run_water_pump(3)
    time.sleep(1)
    print("\n=== Test Complete ===")
