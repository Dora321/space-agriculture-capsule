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
import display
import ai_client
import utils

# 全局状态
class SystemState:
    def __init__(self):
        self.wifi_connected = False
        self.soil_moisture = 0
        self.co2_ppm = 0
        self.temperature = 0.0
        self.humidity = 0.0
        self.plant_type = "生菜"
        self.days_since_planting = 0   # 种植天数
        self.growth_stage = None       # 当前生长阶段
        self.last_action = "idle"
        self.last_action_time = 0
        self.last_nutrient_time = 0
        self.action_count = 0
        self.action_count_start = 0  # 当前计数窗口起始时间
        self.error_count = 0
        self.start_time = 0

state = SystemState()


def init_system():
    """系统初始化"""
    print("=" * 50)
    print("  Space Agriculture Growth Chamber System v1.0")
    print("=" * 50)
    
    state.start_time = time.time()
    state.action_count_start = time.time()
    
    # 初始化各模块（按依赖顺序：显示→传感器→执行器）
    print("[System] Initializing OLED display...")
    display.init()
    
    # 显示启动信息
    display.show_boot()
    
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
        display.show_text("WiFi OK!", 20, 40)
    else:
        print("[WiFi] Connection failed, using local rules")
        display.show_text("WiFi Failed", 20, 40)
    
    time.sleep(1)
    
    # CO2传感器预热
    warmup = config.CO2_WARMUP_TIME
    print(f"[System] CO2 sensor warming up ({warmup}s)...")
    display.show_text("CO2 Warming...", 20, 40)
    for i in range(warmup):
        time.sleep(1)
        if i % 5 == 0:
            display.show_text(f"CO2 Warming...{i+1}s", 20, 40)

    # 预热结束后立即显示就绪状态，避免用户误以为卡住
    display.show_text("System Ready!", 20, 40)
    time.sleep(1)

    # 首次完整读取传感器（确保屏幕立刻显示真实数据而非默认0）
    read_all_sensors()
    print("[Plant] Current type:", state.plant_type)

    # 显示初始待机画面
    display.show_idle(state.soil_moisture, state.co2_ppm, state.plant_type, state.temperature, state.humidity)

    print("[System] Initialization complete, starting main loop")
    print("=" * 50)

    return True


def read_all_sensors():
    """读取所有传感器数据，检测传感器离线"""
    try:
        soil = sensors.read_soil_moisture()
        co2 = sensors.read_co2()
        temp, hum = sensors.read_dht22()
        plant = sensors.read_plant_type()
        
        # 检测传感器离线（返回 None 表示故障）
        sensor_failures = []
        if soil is None:
            sensor_failures.append("Soil")
            soil = 0  # 降级为 0，触发本地规则的安全浇水
        if co2 is None:
            sensor_failures.append("CO2")
            co2 = config.CO2_NORMAL  # 降级为基线值，跳过换气决策（避免风扇无限运转）
        if temp is None or hum is None:
            sensor_failures.append("DHT")
            temp = temp if temp is not None else 25.0
            hum = hum if hum is not None else 60.0
        
        # 传感器离线告警
        if sensor_failures:
            fail_msg = "OFFLINE: " + ",".join(sensor_failures)
            print(f"[Alert] Sensor offline: {fail_msg}")
            utils.set_led("red")
            display.show_error(fail_msg)
            time.sleep(2)  # 告警显示 2 秒
            state.error_count += 1
        
        state.soil_moisture = soil
        state.co2_ppm = co2
        state.temperature = temp
        state.humidity = hum
        state.plant_type = plant
        
        # 计算生长天数和当前阶段
        state.days_since_planting = config.calc_days_since_planting()
        plant_info = config.get_plant_info(plant)
        state.growth_stage = config.get_growth_stage(plant_info, state.days_since_planting)
        
        stage_name = state.growth_stage.get("stage", "unknown")
        fert = state.growth_stage.get("fert", "NPK")
        print(f"[Sensor] Soil:{state.soil_moisture}% | CO2:{state.co2_ppm}ppm | Temp:{state.temperature}C | Hum:{state.humidity}%")
        print(f"[Growth] Day {state.days_since_planting} | Stage: {stage_name} | Fert: {fert}")
        
        # 成功读取，重置连续错误计数（看门狗只追踪连续错误）
        state.error_count = 0
        return True
    except Exception as e:
        print("[Error] Sensor read failed:", e)
        state.error_count += 1
        return False


def make_decision():
    """AI决策 + 本地规则兜底"""
    plant_info = config.get_plant_info(state.plant_type)
    
    # 尝试云端AI
    ai_result = None
    if state.wifi_connected:
        ai_result = ai_client.query_decision(
            plant_type=state.plant_type,
            soil_moisture=state.soil_moisture,
            co2=state.co2_ppm,
            temperature=state.temperature,
            humidity=state.humidity,
            plant_info=plant_info,
            days_since_planting=state.days_since_planting,
            growth_stage=state.growth_stage
        )
    
    if ai_result:
        print(f"[AI Decision] action={ai_result['action']} duration={ai_result['duration_sec']}s reason={ai_result['reason']}")
        return ai_result
    
    # 本地规则兜底
    print("[Local Rule] Cloud timeout, using local decision")
    decision = utils.local_fallback_decision(
        soil=state.soil_moisture,
        co2=state.co2_ppm,
        plant_info=plant_info,
        last_nutrient=state.last_nutrient_time,
        current_time=time.time()
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
        display.show_idle(state.soil_moisture, state.co2_ppm, state.plant_type, state.temperature, state.humidity)
        state.last_action = 'idle'
        state.last_action_time = time.time()
        return
    
    # 执行动作
    print(f"[Action] Executing: {action} ({duration}s) Reason: {reason}")
    
    # 状态LED设为黄色（执行中）
    utils.set_led("yellow")
    
    if action == "water":
        actuators.run_water_pump(duration)
    elif action == "nutrient":
        actuators.run_nutrient_pump(duration)
    elif action == "ventilate":
        actuators.run_fan(duration)
    
    # 更新动作记录
    state.last_action = action
    state.last_action_time = time.time()
    state.action_count += 1
    
    if action == "nutrient":
        state.last_nutrient_time = state.last_action_time
    
    # 状态LED设为绿色（完成）
    utils.set_led("green")
    
    # 显示执行结果
    display.show_action(action, duration, reason)


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
    last_heartbeat = 0
    heartbeat_toggle = False
    read_count = 0  # [DEBUG] 读取计数器

    while True:
        try:
            now = time.time()

            # 每 10 秒刷新一次心跳，证明系统没死且 OLED 没卡住
            if now - last_heartbeat >= 10:
                last_heartbeat = now
                heartbeat_toggle = not heartbeat_toggle
                # 在画面右下角显示一个跳动符号，不影响主数据显示
                if heartbeat_toggle:
                    display.show_overlay("*", 120, 56)
                else:
                    display.show_overlay(" ", 120, 56)

            # 定期读取传感器
            if now - last_read >= interval:
                last_read = now
                read_count += 1

                # 读取前提示用户，避免在 DHT 慢速读取时误以为卡死
                display.show_overlay(f"R{read_count}", 0, 56)

                # 读取传感器
                read_ok = read_all_sensors()

                if not read_ok:
                    # [DEBUG] 读取失败时显示错误，而不是静默跳过
                    display.show_overlay("ERR!", 0, 56)
                    print(f"[DEBUG] read_all_sensors failed, count={read_count}")
                    time.sleep(2)
                    # 即使失败也刷新显示（用旧值），让用户看到系统还在跑
                    display.show_data(
                        soil=state.soil_moisture,
                        co2=state.co2_ppm,
                        temp=state.temperature,
                        hum=state.humidity,
                        plant=state.plant_type,
                        action=state.last_action
                    )
                    continue

                # 安全检查
                if not safety_check():
                    display.show_overlay("SAFE", 0, 56)
                    continue

                # AI决策
                decision = make_decision()

                # 执行决策
                execute_decision(decision)

                # 显示传感器数据
                display.show_data(
                    soil=state.soil_moisture,
                    co2=state.co2_ppm,
                    temp=state.temperature,
                    hum=state.humidity,
                    plant=state.plant_type,
                    action=state.last_action
                )

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
