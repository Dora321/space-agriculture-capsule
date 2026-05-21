"""System boot sequence orchestration."""

import time

import actuators
import sensors
import utils
import wifi_client


def init_system(
    state,
    demo_enabled=False,
    init_display=None,
    display=None,
    read_all_sensors=None,
    refresh_display=None,
    send_telemetry=None,
):
    """Initialize hardware modules, first sensor read, display, and telemetry."""
    print("=" * 50)
    if demo_enabled:
        print("[Demo] DEMO_MODE enabled: using simulated contest data")
    print("  Space Agriculture Growth Chamber System v1.0")
    print("=" * 50)

    state.start_time = time.time()
    state.action_count_start = time.time()

    print("[System] Initializing OLED display...")
    if init_display is not None:
        init_display()

    if display is not None:
        display().show_boot()

    print("[System] Initializing sensors...")
    sensors.init()

    print("[System] Initializing actuators...")
    actuators.init()

    print("[System] Initializing status LEDs...")
    utils.init_leds()

    state.wifi_connected = wifi_client.connect()

    if state.wifi_connected:
        print("[WiFi] Connected, IP:", wifi_client.get_ip())
        if display is not None:
            display().show_text("WiFi OK!", 20, 40)
    else:
        print("[WiFi] Connection failed, using local rules")
        if display is not None:
            display().show_text("WiFi Failed", 20, 40)

    time.sleep(1)

    if display is not None:
        display().show_text("System Ready!", 20, 40)
    time.sleep(1)

    if read_all_sensors is not None:
        read_all_sensors()
    print("[Plant] Current type:", state.plant_type)

    if refresh_display is not None:
        refresh_display(force=True, reset_page=True)
    if send_telemetry is not None:
        send_telemetry()

    print("[System] Initialization complete, starting main loop")
    print("=" * 50)

    return True
