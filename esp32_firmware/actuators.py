"""
执行器模块 - 控制水泵、营养液泵、风扇
"""

import machine
import time
from machine import Pin
import config


# ============ 全局继电器对象 ============
_relay_water = None
_relay_nutrient = None
_relay_fan = None

# ============ 执行状态 ============
_water_running = False
_nutrient_running = False
_fan_running = False


def init():
    """初始化所有执行器"""
    global _relay_water, _relay_nutrient, _relay_fan
    
    # 初始化继电器引脚（低电平触发）
    _relay_water = Pin(config.RELAY_WATER_PIN, Pin.OUT, value=1)  # 默认关闭
    _relay_nutrient = Pin(config.RELAY_NUTRIENT_PIN, Pin.OUT, value=1)
    _relay_fan = Pin(config.RELAY_FAN_PIN, Pin.OUT, value=1)
    
    print("[执行器] 初始化完成，所有设备已关闭")
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
    
    print(f"[水泵] 启动浇水 {duration}秒")
    _water_running = True
    
    try:
        _relay_on(_relay_water)
        
        # 分段执行，便于检测中断
        remaining = duration
        while remaining > 0:
            sleep_time = min(remaining, 1)  # 每秒检测一次
            time.sleep(sleep_time)
            remaining -= sleep_time
            print(f"[水泵] 剩余 {remaining}秒")
        
        _relay_off(_relay_water)
        print("[水泵] 浇水完成")
        return True
        
    except Exception as e:
        print("[水泵] 运行异常:", e)
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
    
    print(f"[营养液泵] 启动 {duration}秒")
    _nutrient_running = True
    
    try:
        _relay_on(_relay_nutrient)
        
        remaining = duration
        while remaining > 0:
            sleep_time = min(remaining, 1)
            time.sleep(sleep_time)
            remaining -= sleep_time
            print(f"[营养液泵] 剩余 {remaining}秒")
        
        _relay_off(_relay_nutrient)
        print("[营养液泵] 完成")
        return True
        
    except Exception as e:
        print("[营养液泵] 运行异常:", e)
        _relay_off(_relay_nutrient)
        return False
    finally:
        _nutrient_running = False


def run_fan(duration_sec):
    """
    运行换气风扇
    duration_sec: 运行时长（秒）
    """
    global _fan_running
    
    duration = _validate_duration(duration_sec)
    if duration == 0:
        return False
    
    print(f"[风扇] 启动换气 {duration}秒")
    _fan_running = True
    
    try:
        _relay_on(_relay_fan)
        
        remaining = duration
        while remaining > 0:
            sleep_time = min(remaining, 1)
            time.sleep(sleep_time)
            remaining -= sleep_time
            print(f"[风扇] 剩余 {remaining}秒")
        
        _relay_off(_relay_fan)
        print("[风扇] 换气完成")
        return True
        
    except Exception as e:
        print("[风扇] 运行异常:", e)
        _relay_off(_relay_fan)
        return False
    finally:
        _fan_running = False


def water_pump_on():
    """开启水泵（持续运行，需手动关闭）"""
    print("[水泵] 手动开启")
    _relay_on(_relay_water)


def water_pump_off():
    """关闭水泵"""
    print("[水泵] 手动关闭")
    _relay_off(_relay_water)


def fan_on():
    """开启风扇（持续运行，需手动关闭）"""
    print("[风扇] 手动开启")
    _relay_on(_relay_fan)


def fan_off():
    """关闭风扇"""
    print("[风扇] 手动关闭")
    _relay_off(_relay_fan)


def all_off():
    """关闭所有执行器"""
    global _water_running, _nutrient_running, _fan_running
    
    print("[执行器] 紧急关闭所有设备")
    _relay_off(_relay_water)
    _relay_off(_relay_nutrient)
    _relay_off(_relay_fan)
    
    _water_running = False
    _nutrient_running = False
    _fan_running = False


def is_any_running():
    """检查是否有执行器正在运行"""
    return _water_running or _nutrient_running or _fan_running


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
        },
        "fan": {
            "running": _fan_running,
            "relay_state": "on" if _relay_fan.value() == 0 else "off"
        }
    }


def test_sequence():
    """执行器测试序列"""
    print("=== 执行器测试 ===")
    
    print("\n[1/3] 测试水泵 (3秒)...")
    run_water_pump(3)
    time.sleep(1)
    
    print("\n[2/3] 测试营养液泵 (3秒)...")
    run_nutrient_pump(3)
    time.sleep(1)
    
    print("\n[3/3] 测试风扇 (3秒)...")
    run_fan(3)
    time.sleep(1)
    
    print("\n=== 测试完成 ===")
    print("确认所有执行器正常工作")
