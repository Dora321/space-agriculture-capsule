"""
太空农业种植舱 - ESP32 主控板固件
版本: v1.0
日期: 2026-05-13
说明: 基于 MicroPython 的智能种植舱控制系统
"""

import machine
import time
import gc
import sys

# 本地模块
import config
import wifi_client
import sensors
import actuators
import utils

# 全局状态
class SystemState:
    def __init__(self):
        self.wifi_connected = False
        self.soil_moisture = 0
        self.light_level = 0
        self.temperature = 0.0
        self.humidity = 0.0
        self.plant_type = "生菜"
        self.plant_info = None
        self.days_since_planting = 0   # 种植天数
        self.growth_stage = None       # 当前生长阶段
        self.sun_minutes_today = 0     # 今日累计达标光照分钟数
        self.sun_date = ""             # 今日日期字符串，用于零点重置
        self.last_action = "idle"
        self.last_action_duration = 0
        self.last_action_time = 0
        self.last_decision_reason = "status normal"
        self.last_nutrient_time = 0
        self.action_count = 0
        self.action_count_start = 0  # 当前计数窗口起始时间
        self.read_count = 0
        self.error_count = 0
        self.start_time = 0

state = SystemState()
_display_ready = False
_page_index = 0
_last_page_time = 0


def _init_display():
    """按需初始化 OLED，避免显示模块长期占用 AI TLS 所需内存。"""
    global _display_ready
    import display
    _display_ready = display.init()
    return display


def _display():
    global _display_ready
    import display
    if not _display_ready:
        _display_ready = display.init()
    return display


def _release_display():
    """AI 请求前释放 OLED 模块和帧缓冲，给 TLS 握手腾出堆内存。"""
    global _display_ready
    try:
        mod = sys.modules.get("display")
        if mod:
            try:
                mod.power_off()
            except Exception:
                pass
            try:
                mod._oled = None
            except Exception:
                pass
            del sys.modules["display"]
        if "ssd1306" in sys.modules:
            del sys.modules["ssd1306"]
    except Exception as e:
        print("[Display] Release failed:", e)
    _display_ready = False
    gc.collect()


def _format_date():
    t = time.localtime()
    return f"{t[0]}-{t[1]}-{t[2]}"


def _get_plant_info():
    if state.plant_info is None:
        state.plant_info = config.get_plant_info(state.plant_type)
    return state.plant_info


def _ai_enabled():
    return bool(getattr(config, "AI_PROXY_URL", "") or getattr(config, "AI_API_KEY", ""))


def _refresh_display(force=False, reset_page=False):
    """刷新 OLED 三页轮播。force=True 时立即重绘当前页。"""
    global _page_index, _last_page_time

    now = time.time()
    rotate_sec = getattr(config, "PAGE_ROTATE_SEC", 5)

    if reset_page:
        _page_index = 0
        _last_page_time = now
        force = True
    elif _last_page_time == 0:
        _last_page_time = now
        force = True
    elif now - _last_page_time >= rotate_sec:
        _page_index = (_page_index + 1) % 3
        _last_page_time = now
        force = True

    if not force:
        return

    plant_info = _get_plant_info()
    ip = wifi_client.get_ip() if state.wifi_connected else None
    _display().show_data(
        soil=state.soil_moisture,
        light=state.light_level,
        temp=state.temperature,
        hum=state.humidity,
        plant=state.plant_type,
        action=state.last_action,
        page_index=_page_index,
        plant_info=plant_info,
        growth_stage=state.growth_stage,
        days_since_planting=state.days_since_planting,
        sun_minutes_today=state.sun_minutes_today,
        wifi_connected=state.wifi_connected,
        ip=ip,
        ai_enabled=_ai_enabled(),
        start_time=state.start_time,
        action_count=state.action_count,
        read_count=state.read_count,
        last_action_duration=state.last_action_duration,
        last_action_time=state.last_action_time,
        decision_reason=state.last_decision_reason,
    )


def init_system():
    """系统初始化"""
    print("=" * 50)
    print("  Space Agriculture Growth Chamber System v1.0")
    print("=" * 50)
    
    state.start_time = time.time()
    state.action_count_start = time.time()
    
    # 初始化各模块（按依赖顺序：显示→传感器→执行器）
    print("[System] Initializing OLED display...")
    _init_display()
    
    # 显示启动信息
    _display().show_boot()
    
    print("[System] Initializing sensors...")
    sensors.init()
    
    print("[System] Initializing actuators...")
    actuators.init()
    
    print("[System] Initializing status LEDs...")
    utils.init_leds()
    
    # 连接WiFi
    state.wifi_connected = wifi_client.connect()
    
    if state.wifi_connected:
        print("[WiFi] Connected, IP:", wifi_client.get_ip())
        _display().show_text("WiFi OK!", 20, 40)
    else:
        print("[WiFi] Connection failed, using local rules")
        _display().show_text("WiFi Failed", 20, 40)
    
    time.sleep(1)
    
    _display().show_text("System Ready!", 20, 40)
    time.sleep(1)

    # 首次完整读取传感器（确保屏幕立刻显示真实数据而非默认0）
    read_all_sensors()
    print("[Plant] Current type:", state.plant_type)

    # 显示初始待机画面
    _refresh_display(force=True, reset_page=True)

    print("[System] Initialization complete, starting main loop")
    print("=" * 50)

    return True


def read_all_sensors():
    """读取所有传感器数据，检测传感器离线"""
    try:
        soil = sensors.read_soil_moisture()
        light = sensors.read_light_level()
        temp, hum = sensors.read_dht22()
        plant = sensors.read_plant_type()
        
        # 检测传感器离线（返回 None 表示故障）
        sensor_failures = []
        if soil is None:
            sensor_failures.append("Soil")
            soil = 0  # 降级为 0，触发本地规则的安全浇水
        if light is None:
            sensor_failures.append("Light")
            light = 0
        if temp is None or hum is None:
            sensor_failures.append("DHT")
            temp = temp if temp is not None else 25.0
            hum = hum if hum is not None else 60.0
        
        # 传感器离线告警
        if sensor_failures:
            fail_msg = "OFFLINE: " + ",".join(sensor_failures)
            print(f"[Alert] Sensor offline: {fail_msg}")
            utils.set_led("red")
            _display().show_error(fail_msg)
            time.sleep(2)  # 告警显示 2 秒
            state.error_count += 1
        
        state.soil_moisture = soil
        state.light_level = light
        state.temperature = temp
        state.humidity = hum
        state.plant_type = plant
        
        # 计算生长天数和当前阶段
        state.days_since_planting = config.calc_days_since_planting()
        state.plant_info = config.get_plant_info(plant)
        state.growth_stage = config.get_growth_stage(state.plant_info, state.days_since_planting)

        # 累计当日达标光照时长，跨日自动清零
        today = _format_date()
        if today != state.sun_date:
            state.sun_date = today
            state.sun_minutes_today = 0
        light_min = state.plant_info.get("light_min", 30)
        if state.light_level >= light_min:
            state.sun_minutes_today += int(config.READ_INTERVAL / 60)
        
        stage_name = state.growth_stage.get("stage", "unknown")
        fert = state.growth_stage.get("fert", "NPK")
        print(f"[Sensor] Soil:{state.soil_moisture}% | Light:{state.light_level}% | Temp:{state.temperature}C | Hum:{state.humidity}%")
        print(f"[Growth] Day {state.days_since_planting} | Stage: {stage_name} | Fert: {fert} | Sun:{state.sun_minutes_today / 60:.1f}h")
        
        # 成功读取，重置连续错误计数（看门狗只追踪连续错误）
        state.error_count = 0
        return True
    except Exception as e:
        print("[Error] Sensor read failed:", e)
        state.error_count += 1
        return False


def make_decision():
    """AI决策 + 本地规则兜底"""
    plant_info = _get_plant_info()
    ai_plant_info = {
        "soil_threshold": plant_info["soil_threshold"],
        "light_min": plant_info.get("light_min", 30),
        "light_opt": plant_info.get("light_opt", 50),
        "light_hours": plant_info.get("light_hours", [6, 8]),
    }
    
    # 尝试云端AI
    ai_result = None
    if state.wifi_connected:
        plant_info = None
        use_proxy = bool(getattr(config, "AI_PROXY_URL", ""))
        if not use_proxy:
            _release_display()
        gc.collect()
        free_mem = gc.mem_free()
        min_ai_mem = getattr(config, "AI_MIN_FREE_MEM", 110000)
        if use_proxy or free_mem >= min_ai_mem:
            import ai_client
            ai_result = ai_client.query_decision(
                plant_type=state.plant_type,
                soil_moisture=state.soil_moisture,
                light_level=state.light_level,
                temperature=state.temperature,
                humidity=state.humidity,
                plant_info=ai_plant_info,
                days_since_planting=state.days_since_planting,
                growth_stage=state.growth_stage,
                sun_minutes_today=state.sun_minutes_today
            )
        else:
            print(f"[AI] Low memory ({free_mem} bytes), using local rules")
    
    if ai_result:
        print(f"[AI Decision] action={ai_result['action']} duration={ai_result['duration_sec']}s reason={ai_result['reason']}")
        return ai_result
    
    # 本地规则兜底
    print("[Local Rule] Cloud timeout, using local decision")
    if plant_info is None:
        plant_info = _get_plant_info()
    decision = utils.local_fallback_decision(
        soil=state.soil_moisture,
        plant_info=plant_info,
        last_nutrient=state.last_nutrient_time,
        current_time=time.time(),
        light=state.light_level,
        sun_minutes=state.sun_minutes_today,
        uptime_sec=time.time() - state.start_time
    )
    return decision


def execute_decision(decision):
    """执行决策"""
    action = decision.get('action', 'idle')
    duration = min(decision.get('duration_sec', 0), config.PUMP_MAX_RUN_SEC)  # 安全上限
    reason = decision.get('reason', '')
    
    if action == 'idle':
        print("[Action] Idle")
        actuators.all_off()
        state.last_action = 'idle'
        state.last_action_duration = 0
        state.last_action_time = time.time()
        state.last_decision_reason = reason
        _refresh_display(force=True, reset_page=True)
        return
    
    # 执行动作
    print(f"[Action] Executing: {action} ({duration}s) Reason: {reason}")
    
    # 状态LED设为黄色（执行中）
    utils.set_led("yellow")

    # 执行动作期间覆盖轮播，动作完成后恢复
    _display().show_action(action, duration, reason)
    
    if action == "water":
        actuators.run_water_pump(duration)
    elif action == "nutrient":
        actuators.run_nutrient_pump(duration)
    # 更新动作记录
    state.last_action = action
    state.last_action_duration = duration
    state.last_action_time = time.time()
    state.last_decision_reason = reason
    state.action_count += 1
    
    if action == "nutrient":
        state.last_nutrient_time = state.last_action_time
    
    # 状态LED设为绿色（完成）
    utils.set_led("green")
    
    _refresh_display(force=True, reset_page=True)


def safety_check():
    """安全检查 - 防止连续动作导致系统损坏"""
    now = time.time()

    # 检查执行器实际硬件状态（防止状态脱节）
    if actuators.is_any_running():
        print("[Safety] Actuator running, skipped")
        return False

    # 检查距离上次动作是否过短（防抖）
    if state.last_action != "idle":
        elapsed = now - state.last_action_time
        if elapsed < config.MIN_ACTION_INTERVAL:
            print(f"[Safety] Action interval too short ({elapsed:.0f}s), skipped")
            return False
    
    # 检查动作次数（每小时最多N次）
    now = time.time()
    if now - state.action_count_start >= 3600:
        # 超过1小时，重置计数窗口
        state.action_count_start = now
        state.action_count = 0

    if state.action_count >= config.MAX_ACTIONS_PER_HOUR:
        print("[Safety] Hourly action limit exceeded, waiting...")
        time.sleep(60)
        return False
    
    return True


def watch_dog():
    """看门狗 - 检测系统异常"""
    if state.error_count > config.MAX_ERRORS:
        print("[Watchdog] Too many errors, system restarting")
        machine.reset()


def main_loop():
    """主循环"""
    interval = config.READ_INTERVAL  # 读取间隔（秒）
    last_read = 0

    while True:
        try:
            now = time.time()

            # 空闲时按 PAGE_ROTATE_SEC 轮播 OLED 页面
            _refresh_display()

            # 定期读取传感器
            if now - last_read >= interval:
                last_read = now
                state.read_count += 1

                # 读取前提示用户，避免在 DHT 慢速读取时误以为卡死
                _display().show_overlay(f"R{state.read_count}", 0, 56)

                # 读取传感器
                read_ok = read_all_sensors()

                if not read_ok:
                    # [DEBUG] 读取失败时显示错误，而不是静默跳过
                    _display().show_overlay("ERR!", 0, 56)
                    print(f"[DEBUG] read_all_sensors failed, count={state.read_count}")
                    time.sleep(2)
                    # 即使失败也刷新显示（用旧值），让用户看到系统还在跑
                    _refresh_display(force=True)
                    continue

                # 安全检查
                if not safety_check():
                    _display().show_overlay("SAFE", 0, 56)
                    continue

                # AI决策
                decision = make_decision()

                # 执行决策
                execute_decision(decision)

                # 显示传感器数据
                _refresh_display(force=True, reset_page=True)

                # 检查是否需要重连WiFi
                if not wifi_client.is_connected():
                    print("[WiFi] Disconnected, attempting reconnect...")
                    state.wifi_connected = wifi_client.smart_connect()

                # 释放内存
                gc.collect()

            # 空闲时短暂休眠
            time.sleep(1)

        except KeyboardInterrupt:
            print("\n[System] User interrupted, turning off all actuators")
            actuators.all_off()
            break
        except Exception as e:
            print("[Error] Main loop exception:", e)
            state.error_count += 1
            watch_dog()
            time.sleep(5)


def run():
    """入口函数"""
    if init_system():
        main_loop()
    else:
        print("[Fatal] System initialization failed")
        machine.reset()


# 运行
if __name__ == "__main__":
    run()
