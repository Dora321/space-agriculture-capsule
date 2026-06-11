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


def play_signal(signal, duration_sec=None):
    """播放决策信号对应的 WS2812 动画。"""
    status_strip.play_signal(signal, duration_sec)


def play_signals(signals, max_signals=3):
    """依次播放多个决策信号动画。"""
    status_strip.play_signals(signals, max_signals)


# ============ 本地决策规则 ============

def _collect_signals(soil, plant_info, temperature, light, sun_minutes):
    """收集 advisory signals（WS2812 广播用，不影响动作决策）。"""
    signals = []
    temp_high = getattr(config, "TEMP_HIGH_C", 35)
    temp_low = getattr(config, "TEMP_LOW_C", 8)

    # 温度信号
    if temperature is not None:
        if temperature >= temp_high:
            signals.append("TEMP_HIGH")
        if temperature <= temp_low:
            signals.append("TEMP_LOW")

    # 缺肥信号（根据当前生长阶段 fert 字段）
    stages = plant_info.get("growth_stages", [])
    current_stage = stages[-1] if stages else {}
    fert = current_stage.get("fert", "")
    if "N" in fert and "P" not in fert and "K" not in fert:
        signals.append("NEED_N")
    elif "PK" in fert or ("P" in fert and "K" in fert):
        signals.append("NEED_P")
    elif "K" in fert and "N" not in fert:
        signals.append("NEED_K")

    # 光照信号
    if light is not None:
        light_min = plant_info.get('light_min', 30)
        if light < light_min:
            signals.append("LIGHT_LOW")

    return signals


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
        dict: {"action": str, "duration_sec": int, "reason": str,
               "signals": list, "breeding_observation": str}

    架构升级 2026-05-28：Decision Plane / Action Plane 分离。
        signals 列表包含 advisory signals（WS2812 广播用）。
        breeding_observation 记录生长观察（1 句话）。
    """

    soil_threshold = plant_info['soil_threshold']
    water_sec = plant_info['water_sec']
    temp_high = getattr(config, "TEMP_HIGH_C", 35)
    temp_low = getattr(config, "TEMP_LOW_C", 8)

    # 收集 advisory signals
    signals = _collect_signals(soil, plant_info, temperature, light, sun_minutes)
    observation = ""

    # 决策优先级
    # 1. 土壤极度干燥 -> 立即浇水（即使温度异常也要救命）
    if soil < soil_threshold - 15:
        action_signals = ["WATER"] + [s for s in signals if s != "WATER"]
        return {
            "action": "water",
            "duration_sec": water_sec + 3,
            "reason": "soil very dry",
            "signals": action_signals,
            "breeding_observation": observation,
        }

    # 2. 低温 -> 跳过所有执行器动作（补光灯升温对低温植物不利）
    if temperature is not None and temperature <= temp_low:
        return {
            "action": "idle",
            "duration_sec": 0,
            "reason": f"temp LOW {temperature}C<={temp_low}C, skip all actions",
            "signals": signals,
            "breeding_observation": observation,
        }

    # 3. 高温标记：仅跳过浇水（避免闷根），补光不受影响
    high_temp_skip_water = False
    if temperature is not None and temperature >= temp_high:
        high_temp_skip_water = True

    # 4. 土壤干燥（非极度）-> 温度安全时浇水
    if soil < soil_threshold and not high_temp_skip_water:
        action_signals = ["WATER"] + [s for s in signals if s != "WATER"]
        return {
            "action": "water",
            "duration_sec": water_sec,
            "reason": "soil dry",
            "signals": action_signals,
            "breeding_observation": observation,
        }

    # 5. 光照不足 -> 补光（不受高温浇水限制影响）
    if light is not None:
        light_min = plant_info.get('light_min', 30)
        light_hours = plant_info.get('light_hours', [6, 8])
        light_max_run = getattr(config, "LIGHT_MAX_RUN_SEC", 20)
        sun_hours = sun_minutes / 60
        if light < light_min:
            deficit_h = max(0, light_hours[0] - sun_hours)
            light_dur = int(min(light_max_run, max(30, deficit_h * 3600 / 2)))
            action_signals = ["LIGHT_LOW"] + [s for s in signals if s != "LIGHT_LOW"]
            return {
                "action": "light",
                "duration_sec": light_dur,
                "reason": f"light LOW {light}%<{light_min}%",
                "signals": action_signals,
                "breeding_observation": observation,
            }
    # 6. 高温但土壤不干、光照也不缺 -> 跳过浇水
    if high_temp_skip_water:
        return {
            "action": "idle",
            "duration_sec": 0,
            "reason": f"temp HIGH {temperature}C>={temp_high}C, skip watering",
            "signals": signals,
            "breeding_observation": observation,
        }

    # 7. 一切正常
    return {
        "action": "idle",
        "duration_sec": 0,
        "reason": "status normal",
        "signals": signals,
        "breeding_observation": observation,
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
    values.append(new_value)
    if len(values) > window:
        values.pop(0)
    return sum(values) / len(values)


def smooth_value(current, target, factor=0.3):
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
