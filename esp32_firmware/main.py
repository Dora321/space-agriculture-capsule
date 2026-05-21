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
import action_runtime
import decision as decision_engine
import sensor_runtime
from state import SystemState

# 全局状态
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


def _get_plant_info():
    if state.plant_info is None:
        state.plant_info = config.get_plant_info(state.plant_type)
    return state.plant_info


def _ai_enabled():
    return bool(getattr(config, "AI_PROXY_URL", "") or getattr(config, "AI_API_KEY", ""))


def _demo_enabled():
    return bool(getattr(config, "DEMO_MODE", False))


def _demo_value(name, default):
    return getattr(config, name, default)


def _send_telemetry():
    if not getattr(config, "DASHBOARD_URL", ""):
        return
    try:
        import telemetry
        telemetry.send_state(state, ai_enabled=_ai_enabled())
    except Exception as e:
        print("[Telemetry] skipped:", e)


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
    if _demo_enabled():
        print("[Demo] DEMO_MODE enabled: using simulated contest data")
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
    _send_telemetry()

    print("[System] Initialization complete, starting main loop")
    print("=" * 50)

    return True


def read_all_sensors():
    """读取所有传感器数据，检测传感器离线"""
    return sensor_runtime.read_all_sensors(
        state,
        demo_enabled=_demo_enabled(),
        show_error=lambda fail_msg: _display().show_error(fail_msg),
    )


def read_demo_sensors():
    """Generate fast-changing contest demo data without physical sensor changes."""
    return sensor_runtime.read_demo_sensors(state)


def make_decision():
    """AI 决策 + 本地规则兜底。保留入口以兼容测试和 REPL 调用。"""
    plant_info = _get_plant_info()
    return decision_engine.make_decision(
        state,
        plant_info,
        demo_enabled=_demo_enabled(),
        release_display=_release_display,
    )


def execute_decision(decision):
    """执行决策"""
    return action_runtime.execute_decision(
        state,
        decision,
        demo_enabled=_demo_enabled(),
        demo_recover_soil=_demo_value("DEMO_RECOVER_SOIL", 55),
        show_action=lambda action, duration, reason: _display().show_action(action, duration, reason),
        refresh_display=_refresh_display,
    )


def safety_check():
    """安全检查 - 防止连续动作导致系统损坏"""
    return action_runtime.safety_check(state, demo_enabled=_demo_enabled())


def watch_dog():
    """看门狗 - 检测系统异常"""
    if state.error_count > config.MAX_ERRORS:
        print("[Watchdog] Too many errors, system restarting")
        machine.reset()


def main_loop():
    """主循环"""
    interval = _demo_value("DEMO_READ_INTERVAL", config.READ_INTERVAL) if _demo_enabled() else config.READ_INTERVAL
    last_read = 0
    last_decision = 0

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

                decision_interval = _demo_value("DEMO_READ_INTERVAL", getattr(config, "DECISION_INTERVAL", 300)) if _demo_enabled() else getattr(config, "DECISION_INTERVAL", 300)
                if now - last_decision >= decision_interval:
                    last_decision = now

                    # 安全检查
                    if not safety_check():
                        _display().show_overlay("SAFE", 0, 56)
                        _send_telemetry()
                        continue

                    # AI决策
                    decision = make_decision()

                    # 执行决策
                    execute_decision(decision)
                    _send_telemetry()
                else:
                    remain = int(decision_interval - (now - last_decision))
                    print(f"[Decision] Next decision in {remain}s")
                    _send_telemetry()

                # 显示传感器数据
                _refresh_display(force=True, reset_page=True)
                _send_telemetry()

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
