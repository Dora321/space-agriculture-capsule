"""
太空农业种植舱 - ESP32 主控板固件
版本: v1.2
日期: 2026-05-28
说明: 基于 MicroPython 的智能种植舱控制系统
      交互方式：模拟键盘(ADC GPIO33) + OLED 菜单
      变更：四独立按钮 → 单ADC模拟键盘，节省 3 个 GPIO
"""

import machine
import time
import gc

# 本地模块（仅保留 WiFi init 前必需的轻量模块）
import config
import wifi_client
import display_runtime
from state import SystemState
# boot_runtime / sensor_runtime / action_runtime / decision / loop_runtime
# 均在首次调用时懒加载，确保 WiFi init 前堆碎片最少

# 全局状态
state = SystemState()

# 菜单系统（独立按钮 + OLED）
_menu = None


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


def _setup_menu():
    """初始化菜单输入系统。"""
    global _menu
    try:
        from menu import Menu

        from buttons import AnalogKeypad
        thresholds = getattr(config, "ANALOG_KEYPAD_THRESHOLDS", None)
        control = AnalogKeypad(config.ANALOG_KEYPAD_PIN, thresholds=thresholds)
        _menu = Menu(_display(), control, config.PLANT_LIST)
        print("[Menu] Button menu initialized")
        return True
    except Exception as e:
        print("[Menu] Failed to initialize:", e)
        _menu = None
        return False


def _select_plant():
    """启动时选择植物类型。"""
    global _menu
    if _menu is None:
        if not _setup_menu():
            return

    print("[Menu] Entering plant selection...")
    selected = _menu.run_plant_selection(
        default_index=_plant_index(state.plant_type)
    )
    state.plant_type = selected
    state.plant_info = config.get_plant_info(selected)
    print(f"[Menu] Plant selected: {selected}")


def _select_day():
    """启动时选择当前种植天数。"""
    global _menu
    if _menu is None:
        return

    import config as _cfg
    default_day = _cfg.calc_days_since_planting()
    print("[Menu] Entering day selection...")
    chosen = _menu.run_day_selection(
        current_day=default_day,
        plant_info=state.plant_info,
    )
    state.manual_day = chosen
    state.days_since_planting = chosen
    print(f"[Menu] Day selected: {chosen}")


def _plant_index(plant_name):
    """根据植物名获取索引。"""
    try:
        return config.PLANT_LIST.index(plant_name)
    except ValueError:
        return 0


def _check_menu():
    """主循环中检测按键：红/黄键切换页面，蓝键长按进入菜单。

    Returns:
        bool: True 表示进入并退出了菜单，调用方应刷新显示
    """
    global _menu
    if _menu is None:
        return False

    # 红键(UP=-1) / 黄键(DOWN=+1) → 手动切换 OLED 页面
    nav = _menu._control.update()
    if nav != 0:
        display_runtime.advance_page(nav)
        _refresh_display(force=True)
        return False

    # 蓝键单击 → 进入主菜单
    if _menu.check_menu_trigger():
        print("[Menu] Entering main menu...")
        _menu._display = display_runtime.display()
        _menu.run_main_menu(
            state,
            get_wifi_status=lambda: state.wifi_connected,
            get_ip=lambda: wifi_client.get_ip() if state.wifi_connected else None,
        )
        print("[Menu] Exited main menu")
        return True
    return False


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
    import gc as _gc

    # ── WiFi 在所有重模块加载前抢先连接 ──────────────────────
    # boot_runtime → utils → status_strip (~22KB) 尚未加载，堆碎片最少
    _gc.collect()
    _gc.collect()
    print("[WiFi] Free RAM before connect:", _gc.mem_free(), "bytes")
    try:
        state.wifi_connected = wifi_client.connect()
    except OSError as e:
        print("[WiFi] WLAN init failed:", e)
        state.wifi_connected = False

    # ── 现在再 import 重模块 ──────────────────────────────────
    import boot_runtime
    ok = boot_runtime.init_system(
        state,
        demo_enabled=_demo_enabled(),
        wifi_already_connected=True,
        init_display=_init_display,
        display=_display,
        release_display=_release_display,
        read_all_sensors=read_all_sensors,
        refresh_display=None,       # 不在这里渲染，避免仪表盘在选蔬菜前闪一下
        send_telemetry=_send_telemetry,
    )

    if not ok:
        return False

    # 启动菜单：选植物 → 选天数
    print("[Init] Starting plant selection...")
    _select_plant()

    print("[Init] Starting day selection...")
    _select_day()

    # 选完后首次渲染仪表盘
    _refresh_display(force=True, reset_page=True)

    return True


def read_all_sensors():
    """读取所有传感器数据，检测传感器离线"""
    import sensor_runtime
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
    import decision as decision_engine
    plant_info = _get_plant_info()
    return decision_engine.make_decision(
        state,
        plant_info,
        demo_enabled=_demo_enabled(),
        release_display=_release_display,
    )


def execute_decision(decision):
    """执行决策"""
    import action_runtime
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
    import action_runtime
    return action_runtime.safety_check(state, demo_enabled=_demo_enabled())


def watch_dog():
    """看门狗 - 检测系统异常"""
    if state.error_count > config.MAX_ERRORS:
        print("[Watchdog] Too many errors, system restarting")
        machine.reset()


def main_loop():
    """主循环"""
    import loop_runtime
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
        check_menu=_check_menu,
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
