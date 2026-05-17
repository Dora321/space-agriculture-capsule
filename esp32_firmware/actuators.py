"""
执行器模块 - 控制水泵、营养液泵
"""

import machine
import time
from machine import Pin
import config


# ============ 全局继电器对象 ============
_relay_water = None
_relay_nutrient = None

# ============ 执行状态 ============
_water_running = False
_nutrient_running = False


def init():
    """初始化所有执行器"""
    global _relay_water, _relay_nutrient
    
    # 初始化继电器引脚（低电平触发）
    _relay_water = Pin(config.RELAY_WATER_PIN, Pin.OUT, value=1)  # 默认关闭
    _relay_nutrient = Pin(config.RELAY_NUTRIENT_PIN, Pin.OUT, value=1)
    
    print("[Actuator] Initialization complete, all devices off")
    return True


def _validate_duration(duration):
    """
    验证执行时长是否安全
    返回: 安全执行时长（秒）
    """
    if duration <= 0:
        return 0
    return min(duration, config.PUMP_MAX_RUN_SEC)


def _relay_on(relay):
    """继电器开启（低电平触发）"""
    relay.value(0)


def _relay_off(relay):
    """继电器关闭（低电平触发）"""
    relay.value(1)


def run_water_pump(duration_sec):
    """
    运行水泵浇水
    duration_sec: 运行时长（秒）
    """
    global _water_running
    
    duration = _validate_duration(duration_sec)
    if duration == 0:
        return False
    
    print(f"[Water Pump] Starting for {duration}s")
    _water_running = True
    
    try:
        _relay_on(_relay_water)
        
        # 分段执行，便于检测中断
        remaining = duration
        while remaining > 0:
            sleep_time = min(remaining, 1)  # 每秒检测一次
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


def run_nutrient_pump(duration_sec):
    """
    运行营养液泵
    duration_sec: 运行时长（秒）
    """
    global _nutrient_running
    
    duration = _validate_duration(duration_sec)
    if duration == 0:
        return False
    
    print(f"[Nutrient Pump] Starting for {duration}s")
    _nutrient_running = True
    
    try:
        _relay_on(_relay_nutrient)
        
        remaining = duration
        while remaining > 0:
            sleep_time = min(remaining, 1)
            time.sleep(sleep_time)
            remaining -= sleep_time
            print(f"[Nutrient Pump] {remaining}s remaining")
        
        _relay_off(_relay_nutrient)
        print("[Nutrient Pump] Complete")
        return True
        
    except Exception as e:
        print("[Nutrient Pump] Exception:", e)
        _relay_off(_relay_nutrient)
        return False
    finally:
        _nutrient_running = False


def water_pump_on():
    """开启水泵（持续运行，需手动关闭）"""
    global _water_running
    print("[Water Pump] Manual ON")
    _relay_on(_relay_water)
    _water_running = True


def water_pump_off():
    """关闭水泵"""
    global _water_running
    print("[Water Pump] Manual OFF")
    _relay_off(_relay_water)
    _water_running = False


def all_off():
    """关闭所有执行器"""
    global _water_running, _nutrient_running
    
    print("[Actuator] Emergency OFF all devices")
    _relay_off(_relay_water)
    _relay_off(_relay_nutrient)
    
    _water_running = False
    _nutrient_running = False


def is_any_running():
    """检查是否有执行器正在运行（直接读硬件引脚）"""
    return (_relay_water.value() == 0 or
            _relay_nutrient.value() == 0)


def get_status():
    """获取所有执行器状态"""
    return {
        "water": {
            "running": _water_running,
            "relay_state": "on" if _relay_water.value() == 0 else "off"
        },
        "nutrient": {
            "running": _nutrient_running,
            "relay_state": "on" if _relay_nutrient.value() == 0 else "off"
        }
    }


def test_sequence():
    """执行器测试序列"""
    print("=== Actuator Test ===")
    
    print("\n[1/2] Testing water pump (3s)...")
    run_water_pump(3)
    time.sleep(1)
    
    print("\n[2/2] Testing nutrient pump (3s)...")
    run_nutrient_pump(3)
    time.sleep(1)
    
    print("\n=== Test Complete ===")
    print("Confirm all actuators working normally")
