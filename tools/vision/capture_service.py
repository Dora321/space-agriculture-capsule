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
                 inspect: Callable[..., Any], clock=time.time):
        self.store = store
        self.scheduler = scheduler
        self.camera = camera
        self.experiment = experiment
        self.data_dir = Path(data_dir)
        self.prepare = prepare
        self.inspect = inspect
        self.clock = clock

    def tick(self) -> dict[str, Any]:
        now = self.clock()
        telemetry = self.store.latest_telemetry()
        decision = self.scheduler.evaluate(
            now=now,
            telemetry=telemetry,
            plant_info=self.experiment.get("plant_info"),
            last_success_at=self.store.last_capture_at(),
        )
        status = {
            "state": decision.state,
            "reason": decision.reason,
            "current_light": decision.current_light,
            "required_light": decision.required_light,
            "next_eligible_at": decision.next_eligible_at,
        }
        self.store.set_status(status, now=now)
        if not decision.should_capture:
            return status

        capture_id = datetime.fromtimestamp(now, timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
        capture_dir = self.data_dir / "captures" / capture_id
        overview = capture_dir / "overview.jpg"
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
                self.store.set_status(quality_status, now=self.clock())
                return quality_status
            self.store.create_capture({
                "capture_id": capture_id,
                "captured_at": now,
                "cycle_id": self.experiment.get("cycle_id", "unassigned"),
                "overview_path": str(overview),
                "current_light": decision.current_light,
                "required_light": decision.required_light,
                "context": {
                    "plant_info": self.experiment.get("plant_info", {}),
                    "day": (telemetry or {}).get("day", (telemetry or {}).get("days")),
                    "stage": (telemetry or {}).get("stage"),
                },
            }, observations)
        except Exception as exc:
            error_status = {**status, "state": "CAPTURE_ERROR", "reason": f"{type(exc).__name__}: {exc}"}
            self.store.set_status(error_status, now=self.clock())
            return error_status
        captured = {**status, "state": "QUEUED_FOR_ANALYSIS", "capture_id": capture_id}
        self.store.set_status(captured, now=self.clock())
        return captured
