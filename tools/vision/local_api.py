"""Loopback-only operational and human-review API for Camera Module 3."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .schemas import validate_analysis
from .store import VisionStore


DATA_DIR = Path(os.getenv("SPACEFARM_VISION_DATA_DIR", "/var/lib/spacefarm/vision"))
DB_PATH = DATA_DIR / "vision.sqlite3"
DAILY_LIMIT = int(os.getenv("SPACEFARM_VISION_DAILY_LIMIT", "12"))
CHECK_SEC = int(os.getenv("SPACEFARM_VISION_CHECK_SEC", "600"))
MAX_JSON_BYTES = int(os.getenv("SPACEFARM_LOCAL_API_MAX_JSON_BYTES", "8192"))
MAX_PREVIEW_BYTES = int(os.getenv("SPACEFARM_LOCAL_PREVIEW_MAX_BYTES", str(2 * 1024 * 1024)))
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _public_capture(store: VisionStore, value: dict | None) -> dict:
    if not value:
        return {"available": False}
    result = {key: item for key, item in value.items() if not key.endswith("_path")}
    result["available"] = True
    result["event_id"] = value["capture_id"]
    result["thumbnail_url"] = f'/v1/images/{value["capture_id"]}-thumb.jpg'
    for observation in result.get("observations", []):
        observation.pop("image_path", None)
    result["human_labels"] = store.labels_for_capture(value["capture_id"])
    return result


def _worker_health(value: dict | None, *, now: float, stale_after: float) -> dict:
    if not value:
        return {"alive": False, "state": "unknown", "heartbeat_age_sec": None}
    heartbeat = float(value.get("heartbeat_at", 0) or 0)
    age = max(0.0, now - heartbeat) if heartbeat else None
    result = dict(value)
    result["alive"] = bool(value.get("alive")) and age is not None and age <= stale_after
    result["heartbeat_age_sec"] = None if age is None else round(age, 1)
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "SpaceFarmVisionLocal/1.0"

    def _store(self) -> VisionStore:
        return VisionStore(DB_PATH)

    def _allow_loopback(self) -> bool:
        if self.client_address[0] in {"127.0.0.1", "::1"}:
            return True
        self._json({"error": "loopback access only"}, status=403)
        return False

    def do_GET(self):
        if not self._allow_loopback():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            store = self._store()
            try:
                now = time.time()
                capture = _worker_health(
                    store.get_value("health_capture"), now=now,
                    stale_after=max(30, CHECK_SEC * 2 + 30))
                api = _worker_health(store.get_value("health_api"), now=now, stale_after=60)
                cloud = _worker_health(store.get_value("health_cloud"), now=now, stale_after=60)
                disk = shutil.disk_usage(DATA_DIR)
                disk_percent = round(disk.used / disk.total * 100, 1) if disk.total else 0
                value = {
                    "ok": capture["alive"] and api["alive"] and disk_percent < 90,
                    "camera": {
                        "available": capture["alive"] and capture.get("state") != "CAPTURE_ERROR",
                        "service": capture,
                    },
                    "api_worker": api,
                    "cloud_sync": cloud,
                    "quota": {
                        "calls_today": store.calls_today(now=now),
                        "daily_limit": DAILY_LIMIT,
                        "remaining": max(0, DAILY_LIMIT - store.calls_today(now=now)),
                    },
                    "disk": {
                        "used_percent": disk_percent,
                        "free_bytes": disk.free,
                        "stop_archive_at_percent": 90,
                    },
                    "capture_status": store.status() or {"state": "unknown"},
                    "last_accepted_capture_at": store.last_accepted_capture_at(),
                    "last_analysis_success_at": store.last_analysis_success_at(),
                    "checked_at": now,
                }
                self._json(value, status=200 if value["ok"] else 503)
            finally:
                store.close()
            return
        if path == "/v1/latest":
            store = self._store()
            try:
                self._json(_public_capture(store, store.latest_capture(succeeded_only=True)))
            finally:
                store.close()
            return
        if path == "/v1/events":
            try:
                limit = int(parse_qs(parsed.query).get("limit", ["10"])[0])
            except ValueError:
                limit = 10
            store = self._store()
            try:
                events = [_public_capture(store, item) for item in store.list_captures(
                    limit=max(1, min(20, limit)), succeeded_only=False)]
                self._json({"events": events})
            finally:
                store.close()
            return
        if path.startswith("/v1/images/") and path.endswith("-thumb.jpg"):
            event_id = path.removeprefix("/v1/images/").removesuffix("-thumb.jpg")
            if not _EVENT_ID_RE.fullmatch(event_id):
                self.send_error(400)
                return
            store = self._store()
            try:
                capture = store.get_capture(event_id)
                if not capture:
                    self.send_error(404)
                    return
                image_path = Path(capture["overview_path"]).resolve()
                if DATA_DIR.resolve() not in image_path.parents or not image_path.exists():
                    self.send_error(404)
                    return
                body = image_path.read_bytes()
                if len(body) > MAX_PREVIEW_BYTES:
                    self.send_error(413)
                    return
                self._jpeg(body)
            finally:
                store.close()
            return
        self.send_error(404)

    def do_POST(self):
        if not self._allow_loopback():
            return
        path = urlparse(self.path).path
        payload = self._read_json()
        if payload is None:
            return
        store = self._store()
        try:
            if path == "/v1/capture":
                operator = str(payload.get("operator", "")).strip()
                if not operator:
                    self._json({"error": "operator is required"}, status=400)
                    return
                try:
                    request = store.request_manual_capture(
                        operator=operator, reason=str(payload.get("reason", "")))
                except ValueError as exc:
                    self._json({"error": str(exc)}, status=429)
                    return
                self._json(request, status=202)
                return
            match = re.fullmatch(r"/v1/events/([A-Za-z0-9][A-Za-z0-9._-]{0,63})/label", path)
            if match:
                operator = str(payload.get("operator", "")).strip()
                pot_id = str(payload.get("pot_id", "")).strip()[:32]
                if not operator or not pot_id:
                    self._json({"error": "operator and pot_id are required"}, status=400)
                    return
                try:
                    label = validate_analysis(payload.get("label", {}))
                except ValueError as exc:
                    self._json({"error": str(exc)}, status=400)
                    return
                try:
                    value = store.add_human_label(
                        match.group(1), pot_id, operator=operator,
                        label=label, note=str(payload.get("note", "")))
                except KeyError as exc:
                    self._json({"error": str(exc)}, status=404)
                    return
                self._json(value, status=201)
                return
            self.send_error(404)
        finally:
            store.close()

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._json({"error": "empty request body"}, status=400)
            return None
        if length > MAX_JSON_BYTES:
            self._json({"error": "request body too large"}, status=413)
            return None
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json({"error": "invalid JSON"}, status=400)
            return None
        if not isinstance(value, dict):
            self._json({"error": "JSON body must be an object"}, status=400)
            return None
        return value

    def _jpeg(self, body: bytes):
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: dict, *, status: int = 200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[Vision Local] {self.address_string()} - {fmt % args}")


def serve(host: str = "127.0.0.1", port: int = 8791) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Vision local API must bind to loopback")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[Vision Local] listening on http://{host}:{port}")
    server.serve_forever()
