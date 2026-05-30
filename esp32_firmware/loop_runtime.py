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
    uart_poll=None,
    uart_send_report=None,
    manage_wifi=True,
):
    """Run the periodic read, decision, action, telemetry, and reconnect loop."""
    interval = _demo_value("DEMO_READ_INTERVAL", config.READ_INTERVAL) if demo_enabled else config.READ_INTERVAL
    last_read = 0
    last_decision = 0
    last_wifi_attempt = -getattr(config, "WIFI_RECONNECT_INTERVAL", 120)
    wifi_offline_cycles = 0

    while True:
        try:
            now = time.time()
            if uart_poll is not None:
                uart_poll()

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

                if uart_send_report is not None:
                    uart_send_report()

                # ★ 在决策/动作之前先发 telemetry：动作可能开 12V 灯/泵导致 WiFi
                #   不稳，提前发能保证 dashboard 每轮都能拿到最新传感器数据
                if send_telemetry is not None:
                    print("[Loop] >>> pre-action telemetry")
                    send_telemetry()
                    print("[Loop] <<< pre-action telemetry returned")

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
                        if refresh_display is not None:
                            refresh_display(force=True)
                        if send_telemetry is not None:
                            send_telemetry()
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
                        refresh_display(force=True)  # 刷新数据但保留当前页码，不强制跳回第 0 页
                    except Exception as e:
                        print("[Loop] refresh skipped:", e)
                if send_telemetry is not None:
                    send_telemetry()

                if manage_wifi:
                    link_grace_ms = getattr(config, "WIFI_LINK_GRACE_MS", 5000)
                    if wifi_client.is_connected(grace_ms=link_grace_ms):
                        wifi_offline_cycles = 0
                        state.wifi_connected = True
                    else:
                        wifi_offline_cycles += 1
                        state.wifi_connected = False
                        reconnect_after = getattr(config, "WIFI_RECONNECT_AFTER_MISSES", 2)
                        if wifi_offline_cycles < reconnect_after:
                            print(f"[WiFi] Offline sample {wifi_offline_cycles}/{reconnect_after}, waiting")
                            gc.collect()
                            continue
                        reconnect_interval = getattr(config, "WIFI_RECONNECT_INTERVAL", 120)
                        if now - last_wifi_attempt >= reconnect_interval:
                            last_wifi_attempt = now
                            print("[WiFi] Disconnected, attempting quick reconnect...")
                            # reset=True：上一次连接可能卡在 STA_CONNECTING，必须先把 STA 关掉
                            state.wifi_connected = wifi_client.connect(
                                timeout=getattr(config, "WIFI_RECONNECT_TIMEOUT", 12),
                                allow_full_reset=False,
                                reset=False,  # 软重连优先，避免 OOM；失败时函数内部自动回退硬复位
                            )
                        else:
                            remain = int(reconnect_interval - (now - last_wifi_attempt))
                            print(f"[WiFi] Offline, reconnect in {remain}s")

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
