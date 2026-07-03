"""Durable, rate-limited Raspberry Pi to cloud vision synchronization."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _request(url: str, *, method: str, token: str, body: bytes,
             content_type: str, timeout: float) -> dict[str, Any]:
    headers = {"Content-Type": content_type, "X-Dashboard-Token": token}
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {"ok": True}


def capture_to_cloud_event(capture: dict[str, Any], image_bytes: bytes) -> dict[str, Any]:
    result = capture.get("result") if isinstance(capture.get("result"), dict) else {}
    model = result.get("model") if isinstance(result.get("model"), dict) else {}
    return {
        "schema": "vision.event.v1",
        "event_id": capture["capture_id"],
        "captured_at": capture["captured_at"],
        "cycle_id": capture.get("cycle_id", "unassigned"),
        "current_light": capture.get("current_light"),
        "required_light": capture.get("required_light"),
        "context": capture.get("context", {}),
        "observations": [
            {
                "pot_id": item["pot_id"],
                "material_id": item.get("material_id", ""),
                "is_control": bool(item.get("is_control")),
                "roi_id": item.get("roi_id", item["pot_id"]),
                "quality": item.get("quality", {}),
                "analysis": item.get("analysis", {}),
            }
            for item in capture.get("observations", [])
        ],
        "model": model,
        "human_labels": capture.get("human_labels", [])[:20],
        "image": {
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
            "bytes": len(image_bytes),
        },
    }


class VisionCloudSyncWorker:
    def __init__(self, store: Any, *, base_url: str, token: str,
                 timeout_sec: float = 10, clock=time.time,
                 request_json=_request, urlopen=urllib.request.urlopen):
        self.store = store
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_sec = timeout_sec
        self.clock = clock
        self.request_json = request_json
        self.urlopen = urlopen

    def _finish(self, outcome: str, *, error: str = "") -> str:
        now = self.clock()
        self.store.set_value("health_cloud", {
            "alive": True, "heartbeat_at": now, "state": outcome,
            "last_error": str(error)[:240],
        }, now=now)
        return outcome

    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _post_status(self) -> None:
        status = self.store.status()
        if not status:
            return
        payload = dict(status)
        payload["schema"] = "vision.status.v1"
        payload["reported_at"] = self.clock()
        self.request_json(
            self.base_url + "/api/vision/status", method="POST", token=self.token,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            content_type="application/json", timeout=self.timeout_sec,
        )

    def run_once(self) -> str:
        if not self.configured():
            return self._finish("disabled", error="cloud sync is not configured")
        status_error = None
        try:
            self._post_status()
        except Exception as exc:
            # Latest-value status is best effort; durable capture events continue below.
            status_error = exc

        now = self.clock()
        capture = self.store.lease_cloud_sync("vision-cloud", now=now)
        if capture is None:
            if status_error is not None:
                return self._finish("status_retry", error=f"{type(status_error).__name__}: {status_error}")
            return self._finish("idle")
        capture_id = capture["capture_id"]
        try:
            image_bytes = Path(capture["overview_path"]).read_bytes()
            event = capture_to_cloud_event(capture, image_bytes)
            image_url = self.base_url + "/api/vision/images/" + quote(capture_id)
            image_headers_body = image_bytes
            headers = {
                "Content-Type": "image/jpeg",
                "X-Dashboard-Token": self.token,
                "X-Content-SHA256": event["image"]["sha256"],
            }
            request = urllib.request.Request(
                image_url, data=image_headers_body, headers=headers, method="PUT")
            with self.urlopen(request, timeout=self.timeout_sec) as response:
                response.read()
            self.request_json(
                self.base_url + "/api/vision/events", method="POST", token=self.token,
                body=json.dumps(event, ensure_ascii=False).encode("utf-8"),
                content_type="application/json", timeout=self.timeout_sec,
            )
            self.store.mark_cloud_synced(capture_id, now=self.clock())
            return self._finish("succeeded")
        except Exception as exc:
            self.store.mark_cloud_retry(
                capture_id, f"{type(exc).__name__}: {exc}", now=self.clock())
            return self._finish("retry", error=f"{type(exc).__name__}: {exc}")
