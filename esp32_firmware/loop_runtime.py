"""Main runtime loop orchestration."""

import gc
import time

import actuators
import config
import wifi_client


def _demo_value(name, default):
    return getattr(config, name, default)


def run_loop(
    state,
    demo_enabled=False,
    display=None,
    refresh_display=None,
    read_all_sensors=None,
    safety_check=None,
    make_decision=None,
    execute_decision=None,
    send_telemetry=None,
    watch_dog=None,
    check_menu=None,
):
    """Run the periodic read, decision, action, telemetry, and reconnect loop."""
    interval = _demo_value("DEMO_READ_INTERVAL", config.READ_INTERVAL) if demo_enabled else config.READ_INTERVAL
    last_read = 0
    last_decision = 0

    while True:
        try:
            now = time.time()

            # 检查按键菜单触发
            if check_menu is not None:
                triggered = check_menu()
                if triggered:
                    # 菜单退出：重置 last_read，防止立刻触发传感器读取 + AI 请求
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

                decision_interval = (
                    _demo_value("DEMO_READ_INTERVAL", getattr(config, "DECISION_INTERVAL", 300))
                    if demo_enabled
                    else getattr(config, "DECISION_INTERVAL", 300)
                )
                if now - last_decision >= decision_interval:
                    last_decision = now

                    if safety_check is not None and not safety_check():
                        if display is not None:
                            display().show_overlay("SAFE", 0, 56)
                        if send_telemetry is not None:
                            send_telemetry()
                        continue

                    decision = make_decision() if make_decision is not None else {"action": "idle"}
                    if execute_decision is not None:
                        execute_decision(decision)
                    if send_telemetry is not None:
                        send_telemetry()
                else:
                    remain = int(decision_interval - (now - last_decision))
                    print(f"[Decision] Next decision in {remain}s")
                    if send_telemetry is not None:
                        send_telemetry()

                if refresh_display is not None:
                    refresh_display(force=True)  # 刷新数据但保留当前页码，不强制跳回第 0 页
                if send_telemetry is not None:
                    send_telemetry()

                if not wifi_client.is_connected():
                    print("[WiFi] Disconnected, attempting reconnect...")
                    state.wifi_connected = wifi_client.smart_connect()

                gc.collect()

            # 以 100ms 间隔轮询按键，保证 1 秒内有 9 次检测机会
            _t0 = time.ticks_ms()
            while time.ticks_diff(time.ticks_ms(), _t0) < 900:
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
