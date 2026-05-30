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

# Optional Raspberry Pi UART uplink/downlink. Kept disabled by config default so
# the existing WiFi-only runtime remains the stable baseline.
_uart_link = None


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


def _uart_enabled():
    return bool(getattr(config, "UART_ENABLED", False))


def _uart_skip_wifi():
    return _uart_enabled() and bool(getattr(config, "UART_SKIP_WIFI", True))


def _init_uart_link():
    """Initialize ESP32 UART2 for the Raspberry Pi payload computer."""
    global _uart_link
    if not _uart_enabled():
        return False
    if _uart_link is not None:
        return True
    try:
        from machine import UART
        import uart_link

        uart = UART(
            getattr(config, "UART_ID", 2),
            baudrate=getattr(config, "UART_BAUD", 115200),
            bits=8,
            parity=None,
            stop=1,
            tx=getattr(config, "UART_TX_PIN", 17),
            rx=getattr(config, "UART_RX_PIN", 16),
            rxbuf=getattr(config, "UART_RXBUF", 96),
            timeout=0,
        )
        _uart_link = uart_link.UartLink(
            uart,
            time.ticks_ms,
            offline_timeout_ms=getattr(config, "UART_OFFLINE_TIMEOUT_MS", 30000),
        )
        print("[UART] Pi link initialized")
        return True
    except Exception as e:
        print("[UART] init skipped:", e)
        _uart_link = None
        state.pi_online = False
        return False


def _guard_pi_decision(decision):
    """Apply local ESP32 guardrails to a Pi advisory decision."""
    if not decision:
        return None
    guarded = dict(decision)
    action = guarded.get("action", "idle")
    if action == "water":
        temp = state.temperature
        if temp >= getattr(config, "TEMP_HIGH_C", 35) or temp <= getattr(config, "TEMP_LOW_C", 8):
            guarded["action"] = "idle"
            guarded["duration_sec"] = 0
            guarded["reason"] = "pi advice rejected by temp guard"
            return guarded
    max_sec = (
        getattr(config, "LIGHT_MAX_RUN_SEC", 120)
        if action == "light"
        else getattr(config, "PUMP_MAX_RUN_SEC", 60)
    )
    try:
        duration = int(guarded.get("duration_sec", 0))
    except (ValueError, TypeError):
        duration = 0
    if duration < 0:
        duration = 0
    if duration > max_sec:
        duration = max_sec
    guarded["duration_sec"] = duration
    return guarded


def _poll_uart():
    """Poll Pi messages without letting serial noise crash the control loop."""
    if _uart_link is None:
        return False
    try:
        import uart_link

        msgs = _uart_link.poll()
        state.pi_online = _uart_link.is_online()
        for msg in msgs:
            if msg.get("t") == uart_link.MSG_ADVICE:
                decision = uart_link.advice_to_decision(msg)
                decision = _guard_pi_decision(decision)
                if decision is not None:
                    state.pending_pi_decision = decision
                    print("[UART] Pi advice queued:", decision.get("action"))
        return bool(msgs)
    except Exception as e:
        print("[UART] poll skipped:", e)
        state.pi_online = False
        return False


def _send_uart_report():
    if _uart_link is None:
        return False
    try:
        state.pi_online = _uart_link.is_online()
        return _uart_link.send_report(state, online=state.pi_online)
    except Exception as e:
        print("[UART] report skipped:", e)
        return False


def _take_pi_decision():
    decision = getattr(state, "pending_pi_decision", None)
    if decision is None:
        return None
    state.pending_pi_decision = None
    if _uart_link is not None and not _uart_link.is_online():
        print("[UART] stale Pi advice dropped")
        state.pi_online = False
        return None
    state.last_decision_source = "pi"
    return decision


_wifi_fail_streak = 0  # 连续 WiFi 失败次数，到阈值后 machine.reset() 兜底


def _send_telemetry():
    global _wifi_fail_streak
    if not getattr(config, "DASHBOARD_URL", ""):
        return False
    # 主循环里若 WiFi 已断，主动同步重连一次
    link_grace_ms = getattr(config, "WIFI_LINK_GRACE_MS", 5000)
    if not state.wifi_connected and not wifi_client.is_connected(grace_ms=0):
        print("[Telemetry] skipped: WiFi not ready")
        state.wifi_connected = False
        return False
        print("[Telemetry] WiFi lost, reconnecting before send...")
        try:
            ok = wifi_client.connect(
                timeout=getattr(config, "WIFI_RECONNECT_TIMEOUT", 20),
                allow_full_reset=False,
                reset=False,  # 软重连优先，避免 OOM；失败时函数内部自动回退硬复位
            )
        except Exception as e:
            print("[Telemetry] reconnect exc:", e)
            ok = False
        if not ok:
            _wifi_fail_streak += 1
            print("[Telemetry] reconnect failed (streak={})".format(_wifi_fail_streak))
            # 连续 3 次重连失败 → 硬复位（启动时 WiFi 总能连上，复位是有效的恢复手段）
            if _wifi_fail_streak >= 3:
                print("[Telemetry] WiFi unrecoverable, machine.reset()")
                time.sleep(1)
                machine.reset()
            state.wifi_connected = False
            return False
    _wifi_fail_streak = 0
    state.wifi_connected = True
    release_display = getattr(config, "TELEMETRY_RELEASE_DISPLAY", True)
    if release_display:
        _release_display()
    gc.collect()
    min_free = getattr(config, "TELEMETRY_MIN_FREE_MEM", 32000)
    if gc.mem_free() < min_free:
        print("[Telemetry] skipped: low memory")
        return False
    try:
        import telemetry
        ok = telemetry.send_state(state, ai_enabled=_ai_enabled())
        state.wifi_connected = bool(ok) or wifi_client.is_connected(grace_ms=0)
        return ok
    except Exception as e:
        print("[Telemetry] skipped:", e)
        state.wifi_connected = wifi_client.is_connected(grace_ms=0)
        return False
    finally:
        gc.collect()
        if release_display:
            try:
                _refresh_display(force=True)
            except Exception as e:
                print("[Telemetry] display restore skipped:", e)


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
        if not _setup_menu():
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

    # ── WiFi 在所有重模块加载前抢先连接；UART 双层模式下则跳过 ─────────
    # 双层架构让树莓派负责联网/大屏，ESP32 保留飞控职责，避免 WiFi 驱动
    # 占用堆内存导致 UART/OLED 初始化失败。
    if _uart_skip_wifi():
        print("[WiFi] Skipped: UART mode uses Raspberry Pi networking")
        state.wifi_connected = False
    else:
        # boot_runtime → utils → status_strip (~22KB) 尚未加载，堆碎片最少
        _gc.collect()
        _gc.collect()
        print("[WiFi] Free RAM before connect:", _gc.mem_free(), "bytes")
        try:
            state.wifi_connected = wifi_client.connect(
                timeout=getattr(config, "WIFI_CONNECT_TIMEOUT", 12),
                reset=True,
            )
        except OSError as e:
            print("[WiFi] WLAN init failed:", e)
            state.wifi_connected = False

    _init_uart_link()

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

    _setup_menu()
    if getattr(config, "STARTUP_MENU_ON_BOOT", False):
        # Optional startup menu. Competition-stable mode skips this so boot
        # cannot block forever waiting for button input.
        print("[Init] Starting plant selection...")
        _select_plant()

        print("[Init] Starting day selection...")
        _select_day()
    else:
        print("[Init] Startup menu skipped; press Blue for menu")

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
    if not _demo_enabled():
        pi_decision = _take_pi_decision()
        if pi_decision is not None:
            print("[UART Decision] using Pi advice")
            return pi_decision

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
        uart_poll=_poll_uart if _uart_link is not None else None,
        uart_send_report=_send_uart_report if _uart_link is not None else None,
        manage_wifi=not _uart_skip_wifi(),
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
