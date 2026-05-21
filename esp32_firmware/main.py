"""
太空农业种植舱 - ESP32 主控板固件
版本: v1.0
日期: 2026-05-13
说明: 基于 MicroPython 的智能种植舱控制系统
"""

import machine
import time
import gc

# 本地模块
import config
import wifi_client
import action_runtime
import boot_runtime
import decision as decision_engine
import display_runtime
import loop_runtime
import sensor_runtime
from state import SystemState

# 全局状态
state = SystemState()


def _init_display():
    """按需初始化 OLED，避免显示模块长期占用 AI TLS 所需内存。"""
    return display_runtime.init_display()


def _display():
    return display_runtime.display()


def _release_display():
    """AI 请求前释放 OLED 模块和帧缓冲，给 TLS 握手腾出堆内存。"""
    display_runtime.release_display()


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
    plant_info = _get_plant_info()
    ip = wifi_client.get_ip() if state.wifi_connected else None
    display_runtime.refresh_display(
        state,
        plant_info=plant_info,
        ip=ip,
        ai_enabled=_ai_enabled(),
        force=force,
        reset_page=reset_page,
    )


def init_system():
    """系统初始化"""
    return boot_runtime.init_system(
        state,
        demo_enabled=_demo_enabled(),
        init_display=_init_display,
        display=_display,
        read_all_sensors=read_all_sensors,
        refresh_display=_refresh_display,
        send_telemetry=_send_telemetry,
    )


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
    return loop_runtime.run_loop(
        state,
        demo_enabled=_demo_enabled(),
        display=_display,
        refresh_display=_refresh_display,
        read_all_sensors=read_all_sensors,
        safety_check=safety_check,
        make_decision=make_decision,
        execute_decision=execute_decision,
        send_telemetry=_send_telemetry,
        watch_dog=watch_dog,
    )


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
