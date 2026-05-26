"""OLED lifecycle and paged dashboard refresh."""

import gc
import sys
import time

import config

_display_ready = False
_page_index = 0
_last_page_time = 0


def init_display():
    """Initialize OLED on demand."""
    global _display_ready
    import display

    _display_ready = display.init()
    return display


def display():
    global _display_ready
    import display

    if not _display_ready:
        _display_ready = display.init()
    return display


def release_display():
    """Release OLED module and framebuffer before memory-heavy AI requests."""
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
        if "sh1106" in sys.modules:
            del sys.modules["sh1106"]
    except Exception as e:
        print("[Display] Release failed:", e)
    _display_ready = False
    gc.collect()


def refresh_display(state, plant_info, ai_enabled=False, ip=None, force=False, reset_page=False):
    """Refresh the three-page OLED rotation."""
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

    display().show_data(
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
        ai_enabled=ai_enabled,
        start_time=state.start_time,
        action_count=state.action_count,
        read_count=state.read_count,
        last_action_duration=state.last_action_duration,
        last_action_time=state.last_action_time,
        decision_reason=state.last_decision_reason,
    )
