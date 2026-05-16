"""
工具模块 - 通用工具函数
"""

import machine
import time
import config
from machine import Pin


# ============ 全局 LED 对象 ============
_led_red = None
_led_green = None
_led_yellow = None  # 红+绿组合


def init_leds():
    """初始化状态 LED"""
    global _led_red, _led_green
    
    try:
        _led_red = Pin(config.LED_RED_PIN, Pin.OUT, value=1)
        _led_green = Pin(config.LED_GREEN_PIN, Pin.OUT, value=1)
        print("[LED] Status LED initialized")
    except Exception as e:
        print(f"[LED] Initialization failed: {e}")


def set_led(color):
    """
    设置状态 LED 颜色
    color: "red", "green", "yellow", "off"
    """
    if _led_red is None or _led_green is None:
        return
    
    if color == "red":
        _led_red.value(0)    # 低电平亮
        _led_green.value(1)  # 高电平灭
    elif color == "green":
        _led_red.value(1)
        _led_green.value(0)
    elif color == "yellow":
        _led_red.value(0)
        _led_green.value(0)
    else:  # off
        _led_red.value(1)
        _led_green.value(1)


def blink_led(color, times=3, interval_ms=500):
    """
    LED 闪烁
    color: 颜色
    times: 闪烁次数
    interval_ms: 间隔（毫秒）
    """
    for _ in range(times):
        set_led(color)
        time.sleep_ms(interval_ms)
        set_led("off")
        time.sleep_ms(interval_ms)


# ============ 本地决策规则 ============

def local_fallback_decision(
    soil, plant_info, last_nutrient, current_time,
    light=None, sun_minutes=0, uptime_sec=0
):
    """
    本地备用决策逻辑（云端超时/失败时使用）
    
    参数:
        soil: 土壤湿度百分比
        plant_info: 植物参数字典
        last_nutrient: 上次营养液时间戳
        current_time: 当前时间戳
        light: 当前光照百分比
        sun_minutes: 今日累计达标光照分钟数
        uptime_sec: 系统运行秒数
    
    返回:
        dict: {"action": str, "duration_sec": int, "reason": str}
    """
    
    soil_threshold = plant_info['soil_threshold']
    water_sec = plant_info['water_sec']
    nutrient_sec = plant_info['nutrient_sec']
    nutrient_interval = plant_info.get('nutrient_interval', 259200)  # 默认3天
    
    # 决策优先级
    # 1. 土壤极度干燥 -> 立即浇水
    if soil < soil_threshold - 15:
        return {
            "action": "water",
            "duration_sec": water_sec + 3,  # 延长一点
            "reason": "soil very dry"
        }
    
    # 2. 土壤干燥 -> 浇水
    if soil < soil_threshold:
        return {
            "action": "water",
            "duration_sec": water_sec,
            "reason": "soil dry"
        }

    # 3. 光照不足 -> 仅提示用户移位，不自动执行补光
    if light is not None:
        light_min = plant_info.get('light_min', 30)
        light_hours = plant_info.get('light_hours', [6, 8])
        sun_hours = sun_minutes / 60
        if light < light_min:
            return {
                "action": "idle",
                "duration_sec": 0,
                "reason": f"light LOW {light}%<{light_min}%"
            }
        if uptime_sec > 43200 and sun_hours < light_hours[0]:
            return {
                "action": "idle",
                "duration_sec": 0,
                "reason": f"sun LOW {sun_hours:.1f}h/{light_hours[0]}h"
            }
    
    # 4. 需要补充营养液（定时）
    time_since_nutrient = current_time - last_nutrient
    if time_since_nutrient > nutrient_interval:
        # 土壤不太干时可以补营养
        if soil < soil_threshold + 15:
            return {
                "action": "nutrient",
                "duration_sec": nutrient_sec,
                "reason": "nutrient due"
            }
    
    # 5. 一切正常
    return {
        "action": "idle",
        "duration_sec": 0,
        "reason": "status normal"
    }


# ============ 时间工具 ============

def format_uptime(seconds):
    """格式化运行时间"""
    if seconds < 60:
        return f"{seconds}秒"
    elif seconds < 3600:
        return f"{seconds // 60}分{seconds % 60}秒"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}小时{mins}分"


def get_timestamp():
    """获取格式化时间戳"""
    t = time.localtime()
    return f"{t[0]}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"


def is_daytime():
    """判断是否白天（用于光周期控制）"""
    hour = time.localtime()[3]
    return 6 <= hour < 18


# ============ 数据处理 ============

def moving_average(values, new_value, window=5):
    """
    计算移动平均
    values: 历史值列表
    new_value: 新值
    window: 窗口大小
    返回: 平均值
    """
    values.append(new_value)
    if len(values) > window:
        values.pop(0)
    return sum(values) / len(values)


def smooth_value(current, target, factor=0.3):
    """
    平滑值变化（用于显示）
    current: 当前值
    target: 目标值
    factor: 平滑因子 (0-1)
    """
    return current + (target - current) * factor


# ============ 系统工具 ============

def get_free_memory():
    """获取可用内存（字节）"""
    import gc
    gc.collect()
    return gc.mem_free()


def system_info(start_time=0):
    """获取系统信息"""
    import sys
    
    uptime_seconds = time.time() - start_time if start_time > 0 else 0
    
    info = {
        "platform": sys.platform,
        "python_version": sys.version,
        "free_memory": get_free_memory(),
        "uptime": format_uptime(uptime_seconds),
    }
    
    try:
        import machine
        info["chip"] = machine.reset_cause()
    except:
        pass
    
    return info


def soft_reset():
    """软重启"""
    print("[System] Performing soft reset...")
    machine.reset()


def deep_sleep(seconds):
    """深度睡眠（省电模式）"""
    print(f"[System] Entering deep sleep for {seconds}s...")
    machine.deepsleep(seconds * 1000)


# ============ 调试工具 ============

def dump_pins():
    """打印所有 GPIO 引脚状态（调试用）"""
    print("=== GPIO Status ===")
    
    # 可以扩展为读取所有引脚状态
    print("Note: ESP32 ADC/GPIO check simplified")
    print("Suggest using digitalio for detailed check")


def memory_stats():
    """打印内存统计"""
    import gc
    gc.collect()
    print(f"=== Memory Stats ===")
    print(f"Free: {gc.mem_free()} bytes")
    print(f"Allocated: {gc.mem_alloc()} bytes")


def benchmark(func, iterations=100):
    """性能基准测试"""
    import time
    
    start = time.ticks_us()
    for _ in range(iterations):
        func()
    end = time.ticks_us()
    
    avg_us = time.ticks_diff(end, start) / iterations
    print(f"[Benchmark] {func.__name__}: {avg_us:.2f}us (avg, {iterations} iterations)")
    return avg_us


# ============ 数据存储（使用文件系统） ============

def save_data(filename, data):
    """保存数据到文件"""
    try:
        with open(filename, 'w') as f:
            f.write(str(data))
        return True
    except Exception as e:
        print(f"[Storage] Save failed: {e}")
        return False


def load_data(filename, default=None):
    """从文件读取数据"""
    try:
        with open(filename, 'r') as f:
            return f.read()
    except:
        return default
