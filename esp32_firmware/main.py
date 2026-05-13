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
    print("  太空农业种植舱控制系统 v1.0")
    print("=" * 50)
    
    state.start_time = time.time()
    state.action_count_start = time.time()
    
    # 初始化各模块（按依赖顺序：显示→传感器→执行器）
    print("[系统] 初始化 OLED 显示...")
    display.init()
    
    # 显示启动信息
    display.show_boot()
    
    print("[系统] 初始化传感器...")
    sensors.init()
    
    print("[系统] 初始化执行器...")
    actuators.init()
    
    print("[系统] 初始化状态LED...")
    utils.init_leds()
    
    # 连接WiFi
    state.wifi_connected = wifi_client.connect()
    
    if state.wifi_connected:
        print("[WiFi] 已连接，IP地址:", wifi_client.get_ip())
        display.show_text("WiFi OK!", 20, 40)
    else:
        print("[WiFi] 连接失败，将使用本地规则")
        display.show_text("WiFi Failed", 20, 40)
    
    time.sleep(1)
    
    # CO2传感器预热
    print("[系统] CO2传感器预热中 (30秒)...")
    display.show_text("CO2 Warming...", 20, 40)
    for i in range(30):
        time.sleep(1)
        if i % 5 == 0:
            display.show_text(f"CO2 Warming...{i+1}s", 20, 40)
    
    # 读取初始植物类型
    state.plant_type = sensors.read_plant_type()
    print("[植物] 当前类型:", state.plant_type)
    
    print("[系统] 初始化完成，开始主循环")
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
            co2 = config.CO2_DANGER_HIGH  # 降级为高值，触发本地规则的安全换气
        if temp is None or hum is None:
            sensor_failures.append("DHT22")
            temp = temp if temp is not None else 25.0
            hum = hum if hum is not None else 60.0
        
        # 传感器离线告警
        if sensor_failures:
            fail_msg = "OFFLINE: " + ",".join(sensor_failures)
            print(f"[告警] 传感器离线: {fail_msg}")
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
        print(f"[传感器] 土壤:{state.soil_moisture}% | CO2:{state.co2_ppm}ppm | 温:{state.temperature}C | 湿:{state.humidity}%")
        print(f"[生长] 第{state.days_since_planting}天 | 阶段:{stage_name} | 推荐肥:{fert}")
        
        return True
    except Exception as e:
        print("[错误] 传感器读取失败:", e)
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
        print(f"[AI决策] action={ai_result['action']} duration={ai_result['duration_sec']}s reason={ai_result['reason']}")
        return ai_result
    
    # 本地规则兜底
    print("[本地规则] 云端超时，使用本地决策")
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
    duration = decision.get('duration_sec', 0)
    reason = decision.get('reason', '')
    
    if action == 'idle':
        print("[动作] 待机")
        actuators.all_off()
        display.show_idle(state.soil_moisture, state.co2_ppm, state.plant_type)
        state.last_action = 'idle'
        state.last_action_time = time.time()
        return
    
    # 执行动作
    print(f"[动作] 执行: {action} ({duration}秒) 原因: {reason}")
    
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
        print("[安全] 执行器运行中，跳过")
        return False

    # 检查距离上次动作是否过短（防抖）
    if state.last_action != "idle":
        elapsed = now - state.last_action_time
        if elapsed < config.MIN_ACTION_INTERVAL:
            print(f"[安全] 动作间隔过短({elapsed:.0f}s)，跳过")
            return False
    
    # 检查动作次数（每小时最多N次）
    now = time.time()
    if now - state.action_count_start >= 3600:
        # 超过1小时，重置计数窗口
        state.action_count_start = now
        state.action_count = 0

    if state.action_count > config.MAX_ACTIONS_PER_HOUR:
        print("[安全] 本小时动作次数超限，等待...")
        time.sleep(60)
        return False
    
    return True


def watch_dog():
    """看门狗 - 检测系统异常"""
    if state.error_count > config.MAX_ERRORS:
        print("[看门狗] 错误次数过多，系统重启")
        machine.reset()


def main_loop():
    """主循环"""
    interval = config.READ_INTERVAL  # 读取间隔（秒）
    last_read = 0
    
    while True:
        try:
            now = time.time()
            
            # 定期读取传感器
            if now - last_read >= interval:
                last_read = now
                
                # 读取传感器
                if not read_all_sensors():
                    continue
                
                # 安全检查
                if not safety_check():
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
                    print("[WiFi] 断开，尝试重连...")
                    state.wifi_connected = wifi_client.connect()
                
                # 释放内存
                gc.collect()
            
            # 空闲时短暂休眠
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n[系统] 用户中断，关闭所有执行器")
            actuators.all_off()
            break
        except Exception as e:
            print("[错误] 主循环异常:", e)
            state.error_count += 1
            watch_dog()
            time.sleep(5)


def run():
    """入口函数"""
    if init_system():
        main_loop()
    else:
        print("[致命] 系统初始化失败")
        machine.reset()


# 运行
if __name__ == "__main__":
    run()
