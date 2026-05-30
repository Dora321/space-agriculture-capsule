"""System boot sequence orchestration (dual-layer: ESP32 flight controller).

ESP32 does not connect WiFi — the Raspberry Pi handles networking. Boot brings up
sensors, actuators, status LEDs, OLED and the first sensor read.
"""

import time

import sensors


def init_system(
    state,
    demo_enabled=False,
    init_display=None,
    display=None,
    read_all_sensors=None,
    refresh_display=None,
):
    """Initialize hardware modules, first sensor read and display."""
    print("=" * 50)
    if demo_enabled:
        print("[Demo] DEMO_MODE enabled: using simulated contest data")
    print("  Space Agriculture Growth Chamber System v2.0")
    print("=" * 50)

    state.start_time = time.time()
    state.action_count_start = time.time()

    print("[System] Initializing sensors...")
    sensors.init()

    # actuators / utils / status_strip 在轻量启动早期之后再 import
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

    print("[Net] ESP32 networking disabled: Raspberry Pi handles WiFi/AI/dashboard")
    time.sleep(0.8)

    if display is not None:
        display().show_boot_check(False, None)
    time.sleep(1.5)

    if read_all_sensors is not None:
        read_all_sensors()
    print("[Plant] Type (menu selected):", state.plant_type)

    if refresh_display is not None:
        refresh_display(force=True, reset_page=True)

    print("[System] Initialization complete, starting main loop")
    print("=" * 50)

    return True
