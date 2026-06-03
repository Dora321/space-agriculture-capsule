"""Main runtime loop orchestration (dual-layer: ESP32 + Raspberry Pi over UART).

ESP32 does not manage WiFi or upload telemetry itself — the Raspberry Pi handles
networking, the dashboard and AI. The loop samples, decides (local rules + Pi
advice), acts, and exchanges report/advice with the Pi over UART.
"""

import gc
import time

import actuators
import config


def _demo_value(name, default):
    return getattr(config, name, default)


def _read_interval(state, demo_enabled):
    """每轮的传感器读取间隔（秒）。

    优先级：展示模式(state.fast_mode，读真实传感器但快速) > DEMO_MODE(假数据) > 正常。
    """
    if getattr(state, "fast_mode", False):
        return getattr(config, "FAST_READ_INTERVAL", 3)
    if demo_enabled:
        return getattr(config, "DEMO_READ_INTERVAL", config.READ_INTERVAL)
    return config.READ_INTERVAL


def _decision_interval(state, demo_enabled):
    """每轮的决策间隔（秒），展示模式同样缩短，保证遮挡传感器后快速响应。"""
    if getattr(state, "fast_mode", False):
        return getattr(config, "FAST_READ_INTERVAL", 3)
    if demo_enabled:
        return getattr(config, "DEMO_READ_INTERVAL", getattr(config, "DECISION_INTERVAL", 300))
    return getattr(config, "DECISION_INTERVAL", 300)


def run_loop(
    state,
    demo_enabled=False,
    display=None,
    refresh_display=None,
    read_all_sensors=None,
    safety_check=None,
    make_decision=None,
    execute_decision=None,
    watch_dog=None,
    check_menu=None,
    uart_poll=None,
    uart_send_report=None,
):
    """Run the periodic read, decision, action, and UART report/advice loop."""
    last_read = 0
    last_decision = 0

    while True:
        try:
            now = time.time()
            # 每轮按当前模式取间隔：展示模式(state.fast_mode)下读真实传感器但快速响应
            interval = _read_interval(state, demo_enabled)
            if uart_poll is not None:
                uart_poll()

            # 检查按键菜单触发
            if check_menu is not None:
                triggered = check_menu()
                if triggered:
                    # 菜单退出：重置 last_read，防止立刻触发传感器读取
                    last_read = int(time.time())
                    if refresh_display is not None:
                        refresh_display(force=True, reset_page=True)

            if refresh_display is not None:
                refresh_display()

            if now - last_read >= interval:
                last_read = now
                state.read_count += 1

                if display is not None:
                    display().show_overlay(f"R{state.read_count}", 0, 56)

                read_ok = read_all_sensors() if read_all_sensors is not None else False

                if not read_ok:
                    if display is not None:
                        display().show_overlay("ERR!", 0, 56)
                    print(f"[DEBUG] read_all_sensors failed, count={state.read_count}")
                    time.sleep(2)
                    if refresh_display is not None:
                        refresh_display(force=True)
                    continue

                # 采样后立即把 report 发给树莓派（动作前），保证 Pi/大屏拿到最新数据
                if uart_send_report is not None:
                    uart_send_report()

                decision_interval = _decision_interval(state, demo_enabled)
                if now - last_decision >= decision_interval:
                    last_decision = now

                    if safety_check is not None and not safety_check():
                        if display is not None:
                            display().show_overlay("SAFE", 0, 56)
                        if refresh_display is not None:
                            refresh_display(force=True)
                        continue

                    decision = make_decision() if make_decision is not None else {"action": "idle"}
                    if execute_decision is not None:
                        execute_decision(decision)
                    if uart_send_report is not None:
                        uart_send_report()
                else:
                    remain = int(decision_interval - (now - last_decision))
                    print(f"[Decision] Next decision in {remain}s")

                if refresh_display is not None:
                    try:
                        refresh_display(force=True)  # 刷新数据但保留当前页码
                    except Exception as e:
                        print("[Loop] refresh skipped:", e)

                gc.collect()

            # 以 100ms 间隔轮询按键，保证 1 秒内有 9 次检测机会
            _t0 = time.ticks_ms()
            while time.ticks_diff(time.ticks_ms(), _t0) < 900:
                if uart_poll is not None:
                    uart_poll()
                if check_menu is not None:
                    _triggered = check_menu()
                    if _triggered:
                        last_read = int(time.time())  # 同上，菜单退出后延迟传感器读取
                        if refresh_display is not None:
                            refresh_display(force=True, reset_page=True)
                time.sleep_ms(100)

        except KeyboardInterrupt:
            print("\n[System] User interrupted, turning off all actuators")
            actuators.all_off()
            break
        except Exception as e:
            print("[Error] Main loop exception:", e)
            state.error_count += 1
            if watch_dog is not None:
                watch_dog()
            time.sleep(5)
