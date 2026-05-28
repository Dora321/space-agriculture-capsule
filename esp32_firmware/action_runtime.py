"""Actuator execution and action safety checks."""

import time

import actuators
import config
import utils


def execute_decision(
    state,
    decision,
    demo_enabled=False,
    demo_recover_soil=55,
    show_action=None,
    refresh_display=None,
):
    """Execute a water/light/idle decision and update runtime state.

    Decision Plane / Action Plane:
    - action = physical execution (pump/light)
    - signals = advisory signals broadcast on WS2812
    - breeding_observation = growth observation for telemetry
    """
    action = decision.get("action", "idle")
    duration = min(decision.get("duration_sec", 0), config.PUMP_MAX_RUN_SEC)
    reason = decision.get("reason", "")
    signals = decision.get("signals", [])
    breeding_observation = decision.get("breeding_observation", "")
    valid_actions = ("water", "light", "idle")

    # 兼容历史/AI 误返：把 nutrient 静默映射为 idle，避免单泵架构下行为不一致
    if action == "nutrient":
        print("[Action] 'nutrient' no longer supported (single-pump build), forcing idle")
        action = "idle"
        duration = 0
        reason = "nutrient deprecated"

    if action not in valid_actions:
        print(f"[Action] Unknown action '{action}', forcing idle")
        action = "idle"
        duration = 0
        reason = "unknown action"

    if action == "idle":
        print("[Action] Idle")
        actuators.all_off()
        state.last_action = "idle"
        state.last_action_duration = 0
        state.last_action_time = time.time()
        state.last_decision_reason = reason
        state.last_signals = signals
        state.last_breeding_observation = breeding_observation
        # 即使 idle 也播放 advisory signals（如 TEMP_HIGH、NEED_N 等）
        if signals:
            utils.play_signals(signals)
        if refresh_display is not None:
            refresh_display(force=True, reset_page=True)
        return

    print(f"[Action] Executing: {action} ({duration}s) Reason: {reason}")
    if signals:
        print(f"[Action] Signals: {signals}")

    # 播放主动作对应的信号动画（执行前短暂展示，告诉观察者即将做什么）
    if action == "water":
        utils.play_signal("WATER", duration_sec=min(3, duration))
    elif action == "light":
        utils.play_signal("LIGHT_LOW", duration_sec=min(3, duration))

    if show_action is not None:
        show_action(action, duration, reason)

    if action == "water":
        actuators.run_water_pump(duration)
        if demo_enabled:
            state.demo_soil_moisture = demo_recover_soil
            state.soil_moisture = int(state.demo_soil_moisture)

    if action == "light":
        actuators.run_light(duration)

    state.last_action = action
    state.last_action_duration = duration
    state.last_action_time = time.time()
    state.last_decision_reason = reason
    state.last_signals = signals
    state.last_breeding_observation = breeding_observation
    state.action_count += 1

    # 执行后播放 advisory signals（如 TEMP_HIGH、NEED_K 等）
    advisory = [s for s in signals if s not in ("WATER", "LIGHT_LOW")]
    if advisory:
        utils.play_signals(advisory)

    utils.set_led("green")
    if refresh_display is not None:
        refresh_display(force=True, reset_page=True)


def safety_check(state, demo_enabled=False):
    """Prevent overlapping actions and excessive actuator cycles."""
    now = time.time()

    if actuators.is_any_running():
        print("[Safety] Actuator running, skipped")
        return False

    if demo_enabled:
        return True

    if state.last_action != "idle":
        elapsed = now - state.last_action_time
        if elapsed < config.MIN_ACTION_INTERVAL:
            print(f"[Safety] Action interval too short ({elapsed:.0f}s), skipped")
            return False

    now = time.time()
    if now - state.action_count_start >= 3600:
        state.action_count_start = now
        state.action_count = 0

    if state.action_count >= config.MAX_ACTIONS_PER_HOUR:
        print("[Safety] Hourly action limit exceeded, waiting...")
        time.sleep(60)
        return False

    return True
