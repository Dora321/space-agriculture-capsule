"""System boot sequence orchestration."""

import gc
import time

import sensors
import wifi_client


def init_system(
    state,
    demo_enabled=False,
    wifi_already_connected=False,
    init_display=None,
    display=None,
    release_display=None,
    read_all_sensors=None,
    refresh_display=None,
    send_telemetry=None,
):
    """Initialize hardware modules, first sensor read, display, and telemetry."""
    print("=" * 50)
    if demo_enabled:
        print("[Demo] DEMO_MODE enabled: using simulated contest data")
    print("  Space Agriculture Growth Chamber System v1.1")
    print("=" * 50)

    state.start_time = time.time()
    state.action_count_start = time.time()

    print("[System] Initializing sensors...")
    sensors.init()

    # actuators / utils / status_strip 在 WiFi 之后再 import，避免占用 WiFi 所需连续内存
    if wifi_already_connected:
        print("[WiFi] Using pre-established connection, IP:", wifi_client.get_ip())
    else:
        gc.collect()
        gc.collect()
        print("[WiFi] Free RAM before connect:", gc.mem_free(), "bytes")
        try:
            state.wifi_connected = wifi_client.connect()
        except OSError as e:
            print("[WiFi] WLAN init failed (low memory):", e)
            state.wifi_connected = False

    # WiFi 已处理完，现在加载重模块
    import actuators
    import utils

    print("[System] Initializing actuators...")
    actuators.init()

    print("[System] Initializing status LEDs...")
    utils.init_leds()

    print("[System] Initializing OLED display...")
    if init_display is not None:
        init_display()

    if display is not None:
        display().show_boot()

    if state.wifi_connected:
        print("[WiFi] Connected, IP:", wifi_client.get_ip())
    else:
        print("[WiFi] Connection failed, using local rules")

    time.sleep(0.8)

    if display is not None:
        ip = wifi_client.get_ip() if state.wifi_connected else None
        display().show_boot_check(state.wifi_connected, ip)
    time.sleep(1.5)

    if read_all_sensors is not None:
        read_all_sensors()
    print("[Plant] Type (menu selected):", state.plant_type)

    if refresh_display is not None:
        refresh_display(force=True, reset_page=True)
    if send_telemetry is not None:
        send_telemetry()

    print("[System] Initialization complete, starting main loop")
    print("=" * 50)

    return True
