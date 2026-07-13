"""Light-gated Camera Module 3 capture orchestration."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


class CaptureService:
    def __init__(self, *, store: Any, scheduler: Any, camera: Any,
                 experiment: Mapping[str, Any], data_dir: str | Path,
                 prepare: Callable[..., list[dict[str, Any]]],
                 inspect: Callable[..., Any], quality_retry_sec: float = 600,
                 clock=time.time):
        self.store = store
        self.scheduler = scheduler
        self.camera = camera
        self.experiment = experiment
        self.data_dir = Path(data_dir)
        self.prepare = prepare
        self.inspect = inspect
        self.quality_retry_sec = max(1.0, float(quality_retry_sec))
        self.clock = clock

    def _publish(self, status: Mapping[str, Any], *, now: float | None = None) -> dict[str, Any]:
        timestamp = self.clock() if now is None else float(now)
        value = dict(status)
        self.store.set_status(value, now=timestamp)
        self.store.set_value("health_capture", {
            "alive": True,
            "heartbeat_at": timestamp,
            "state": value.get("state", "unknown"),
            "last_error": value.get("reason", "") if value.get("state") == "CAPTURE_ERROR" else "",
        }, now=timestamp)
        return value

    def tick(self) -> dict[str, Any]:
        now = self.clock()
        telemetry = self.store.latest_telemetry()
        manual_request = self.store.pending_manual_capture()
        # The ESP32 menu is authoritative for the plant currently installed.
        # Keep the experiment file only as a cold-start fallback.
        plant_info = dict(self.experiment.get("plant_info") or {})
        if telemetry:
            if telemetry.get("plant"):
                plant_info["plant"] = str(telemetry["plant"])
            if telemetry.get("light_opt") is not None:
                plant_info["light_opt"] = telemetry["light_opt"]
        decision = self.scheduler.evaluate(
            now=now,
            telemetry=telemetry,
            plant_info=plant_info,
            last_accepted_capture_at=self.store.last_accepted_capture_at(),
            ignore_interval=manual_request is not None,
            force_capture=manual_request is not None,
        )
        status = {
            "state": decision.state,
            "reason": decision.reason,
            "current_light": decision.current_light,
            "required_light": decision.required_light,
            "next_eligible_at": decision.next_eligible_at,
            "trigger": "manual" if manual_request else "automatic",
            "manual_request_id": (
                manual_request.get("request_id") if manual_request else None),
        }
        if not decision.should_capture:
            return self._publish(status, now=now)

        # The service polls every ten seconds so manual requests feel immediate.
        # Persist a separate physical-attempt cooldown to prevent a rejected or
        # failed automatic image from making the camera retry on every poll.
        last_attempt = self.store.get_value("last_capture_attempt") or {}
        last_attempt_at = float(last_attempt.get("attempted_at", 0) or 0)
        if (not manual_request and last_attempt_at
                and now < last_attempt_at + self.quality_retry_sec):
            return self._publish({
                **status,
                "state": "WAITING_INTERVAL",
                "reason": "waiting for capture retry cooldown",
                "next_eligible_at": last_attempt_at + self.quality_retry_sec,
            }, now=now)

        capture_id = datetime.fromtimestamp(now, timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
        capture_dir = self.data_dir / "captures" / capture_id
        overview = capture_dir / "overview.jpg"
        self.store.set_value(
            "last_capture_attempt", {"attempted_at": now, "capture_id": capture_id},
            now=now,
        )
        try:
            self.camera.capture(overview)
            prepared = self.prepare(overview, capture_dir / "rois", list(self.experiment["rois"]))
            observations = []
            for item in prepared:
                quality = self.inspect(item["image_path"])
                observations.append({
                    **item,
                    "quality": quality.as_dict() if hasattr(quality, "as_dict") else dict(quality),
                })
            rejected = [item["pot_id"] for item in observations if not item["quality"].get("accepted")]
            if rejected:
                quality_status = {
                    **status, "state": "QUALITY_REJECTED",
                    "reason": "image quality rejected for: " + ", ".join(rejected),
                }
                if manual_request:
                    self.store.finish_manual_capture(
                        manual_request["request_id"], error=quality_status["reason"],
                        now=self.clock())
                return self._publish(quality_status)
            self.store.create_capture({
                "capture_id": capture_id,
                "captured_at": now,
                "cycle_id": self.experiment.get("cycle_id", "unassigned"),
                "overview_path": str(overview),
                "current_light": decision.current_light,
                "required_light": decision.required_light,
                "context": {
                    "plant_info": plant_info,
                    "day": (telemetry or {}).get("day", (telemetry or {}).get("days")),
                    "stage": (telemetry or {}).get("stage"),
                    "experiment_id": (telemetry or {}).get("experiment_id", ""),
                },
            }, observations)
        except Exception as exc:
            error_status = {**status, "state": "CAPTURE_ERROR", "reason": f"{type(exc).__name__}: {exc}"}
            if manual_request:
                self.store.finish_manual_capture(
                    manual_request["request_id"], error=error_status["reason"],
                    now=self.clock())
            return self._publish(error_status)
        captured = {**status, "state": "QUEUED_FOR_ANALYSIS", "capture_id": capture_id}
        if manual_request:
            self.store.finish_manual_capture(
                manual_request["request_id"], capture_id=capture_id, now=self.clock())
        return self._publish(captured)
