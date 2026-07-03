"""One-job multimodal worker. Run repeatedly from a service loop or systemd timer."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


class VisionApiWorker:
    def __init__(self, store: Any, client: Any, *, worker_id: str = "vision-api",
                 daily_limit: int = 12, max_attempts: int = 3, clock=time.time):
        self.store = store
        self.client = client
        self.worker_id = worker_id
        self.daily_limit = daily_limit
        self.max_attempts = max_attempts
        self.clock = clock

    def run_once(self) -> str:
        now = self.clock()
        if self.store.calls_today(now=now) >= self.daily_limit:
            return "daily_limit"
        job = self.store.lease_next(self.worker_id, now=now)
        if job is None:
            return "idle"
        try:
            image_bytes = sum(Path(item["image_path"]).stat().st_size for item in job["observations"])
            # Count attempted requests too: outages/retries must not bypass the cost cap.
            self.store.record_usage(job["capture_id"], image_bytes, now=now)
            result, image_bytes = self.client.analyze(job)
            self.store.mark_succeeded(job["capture_id"], result, now=self.clock())
            return "succeeded"
        except Exception as exc:
            self.store.mark_retry(
                job["capture_id"], f"{type(exc).__name__}: {exc}",
                max_attempts=self.max_attempts, now=self.clock(),
            )
            return "retry"
