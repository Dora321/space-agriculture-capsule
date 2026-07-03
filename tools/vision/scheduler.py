"""Two-hour, light-gated capture scheduling.

Scheduling consumes the latest ESP32 report mirrored by the Pi gateway.  It
never turns on the grow light merely to take a photograph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


WAITING_TELEMETRY = "WAITING_TELEMETRY"
WAITING_INTERVAL = "WAITING_INTERVAL"
WAITING_LIGHT = "WAITING_LIGHT"
READY = "READY"


@dataclass(frozen=True)
class ScheduleDecision:
    should_capture: bool
    state: str
    reason: str
    current_light: Optional[float]
    required_light: float
    next_eligible_at: float


class CaptureScheduler:
    def __init__(self, interval_sec: int = 7200, telemetry_stale_sec: int = 120,
                 fallback_light_min: int = 50):
        if interval_sec < 1:
            raise ValueError("interval_sec must be positive")
        if telemetry_stale_sec < 1:
            raise ValueError("telemetry_stale_sec must be positive")
        if not 0 <= fallback_light_min <= 100:
            raise ValueError("fallback_light_min must be between 0 and 100")
        self.interval_sec = interval_sec
        self.telemetry_stale_sec = telemetry_stale_sec
        self.fallback_light_min = fallback_light_min

    def evaluate(self, *, now: float, telemetry: Optional[Mapping[str, Any]],
                 plant_info: Optional[Mapping[str, Any]] = None,
                 last_accepted_capture_at: Optional[float] = None,
                 ignore_interval: bool = False) -> ScheduleDecision:
        required = self._required_light(telemetry, plant_info)
        next_eligible = (
            float(last_accepted_capture_at) + self.interval_sec
            if last_accepted_capture_at is not None else float(now)
        )

        if not telemetry:
            return ScheduleDecision(False, WAITING_TELEMETRY,
                                    "no telemetry available", None, required,
                                    next_eligible)

        received_at = telemetry.get("received_at", telemetry.get("updated_at"))
        try:
            received_at = float(received_at)
        except (TypeError, ValueError):
            received_at = None
        if received_at is None or now - received_at > self.telemetry_stale_sec:
            return ScheduleDecision(False, WAITING_TELEMETRY,
                                    "telemetry is stale", self._light(telemetry),
                                    required, next_eligible)

        current = self._light(telemetry)
        if current is None:
            return ScheduleDecision(False, WAITING_TELEMETRY,
                                    "light telemetry is invalid", None, required,
                                    next_eligible)

        if now < next_eligible and not ignore_interval:
            return ScheduleDecision(False, WAITING_INTERVAL,
                                    "two-hour interval has not elapsed", current,
                                    required, next_eligible)

        if current < required:
            return ScheduleDecision(False, WAITING_LIGHT,
                                    "light is below the capture threshold", current,
                                    required, next_eligible)

        return ScheduleDecision(True, READY, "capture conditions satisfied",
                                current, required, next_eligible)

    def _required_light(self, telemetry: Optional[Mapping[str, Any]],
                        plant_info: Optional[Mapping[str, Any]]) -> float:
        candidates = []
        if plant_info:
            candidates.append(plant_info.get("light_opt"))
        if telemetry:
            candidates.append(telemetry.get("light_opt"))
        candidates.append(self.fallback_light_min)
        for value in candidates:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if 0 <= number <= 100:
                return number
        return float(self.fallback_light_min)

    @staticmethod
    def _light(telemetry: Mapping[str, Any]) -> Optional[float]:
        try:
            value = float(telemetry.get("light"))
        except (TypeError, ValueError):
            return None
        return value if 0 <= value <= 100 else None
