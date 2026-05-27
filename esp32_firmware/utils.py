"""
工具模块 - 通用工具函数

状态指示由 status_strip（WS2812 灯条）承担；set_led / blink_led 保留为
向后兼容的薄壳函数。
"""

import machine
import time
import config
import status_strip


def init_leds():
    """初始化状态灯条（WS2812）"""
    status_strip.init()


def set_led(color):
    """切换状态灯条颜色。color: "red" / "green" / "yellow" / "off" """
    status_strip.set_status(color)


def blink_led(color, times=3, interval_ms=500):
    """状态灯条闪烁"""
    status_strip.blink(color, times=times, interval_ms=interval_ms)


def show_soil_indicator(pct):
    """土壤湿度温度计：按百分比点亮对应数量灯珠 + 颜色梯度。

    pct=None 或 <0 表示传感器离线，灯条会显示警示状态。
    """
    status_strip.show_moisture(pct)


# ============ 本地决策规则 ============

def local_fallback_decision(
    soil, plant_info, last_nutrient=0, current_time=0,
    light=None, sun_minutes=0, uptime_sec=0,
    temperature=None
):
    """
    本地备用决策逻辑（云端超时/失败时使用）

    参数:
        soil: 土壤湿度百分比
        plant_info: 植物参数字典
        last_nutrient: 已废弃（保留以兼容旧测试调用），单泵后不再使用
        current_time: 当前时间戳（保留参数以避免破坏既有调用签名）
        light: 当前光照百分比
        sun_minutes: 今日累计达标光照分钟数
        uptime_sec: 系统运行秒数
        temperature: 当前舱内温度（℃），None 表示传感器离线

    返回:
        dict: {"action": str, "duration_sec": int, "reason": str}

    硬件改动 2026-05-27：单水泵架构，不再产出 "nutrient" 动作。
    """

    soil_threshold = plant_info['soil_threshold']
    water_sec = plant_info['water_sec']
    temp_high = getattr(config, "TEMP_HIGH_C", 35)
    temp_low = getattr(config, "TEMP_LOW_C", 8)

    # 决策优先级
    # 1. 土壤极度干燥 -> 立即浇水（即使温度异常也要救命）
    if soil < soil_threshold - 15:
        return {
            "action": "water",
            "duration_sec": water_sec + 3,  # 延长一点
            "reason": "soil very dry"
        }

    # 2. 温度异常 -> 在非极度干旱场景下推迟浇水，避免闷根/冻根
    if temperature is not None:
        if temperature >= temp_high:
            return {
                "action": "idle",
                "duration_sec": 0,
                "reason": f"temp HIGH {temperature}C>={temp_high}C, skip watering"
            }
        if temperature <= temp_low:
            return {
                "action": "idle",
                "duration_sec": 0,
                "reason": f"temp LOW {temperature}C<={temp_low}C, skip watering"
            }

    # 3. 土壤干燥 -> 浇水
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
    
    # 4. 一切正常
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
