#!/usr/bin/env python3
"""Local realtime dashboard server for the contest display.

ESP32 can POST telemetry to /api/state. The browser opens this server and
polls /api/state, falling back to the dashboard's built-in demo animation when
no live device has reported yet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

try:
    from experiment_clock import ExperimentStore
except ImportError:
    from tools.experiment_clock import ExperimentStore


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "deliverables" / "groundstation.html"
TOKEN = os.getenv("DASHBOARD_TOKEN", "")
EXPERIMENT_EDIT_TOKEN = os.getenv("SPACEFARM_EXPERIMENT_TOKEN", TOKEN)
VISION_UPLOAD_TOKEN = os.getenv("VISION_UPLOAD_TOKEN", TOKEN)
ALLOWED_ORIGIN = os.getenv("DASHBOARD_ALLOWED_ORIGIN", "").rstrip("/")
MAX_REQUEST_BYTES = int(os.getenv("DASHBOARD_MAX_REQUEST_BYTES", "4096"))
MAX_VISION_JSON_BYTES = int(os.getenv("VISION_MAX_JSON_BYTES", "65536"))
MAX_VISION_IMAGE_BYTES = int(os.getenv("VISION_MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))
STALE_AFTER_SEC = int(os.getenv("DASHBOARD_STALE_AFTER_SEC", "120"))
VISION_DATA_DIR = Path(os.getenv("SPACEFARM_VISION_DATA_DIR", "/var/lib/spacefarm/vision"))
VISION_DB_PATH = VISION_DATA_DIR / "vision.sqlite3"
VISION_IMAGE_DIR = VISION_DATA_DIR / "images"
EXPERIMENT_PATH = Path(os.getenv(
    "SPACEFARM_EXPERIMENT_FILE", "/var/lib/spacefarm/experiment.json"))
EXPERIMENT_STORE = ExperimentStore(EXPERIMENT_PATH)

LATEST_STATE: dict = {
    "live": False,
    "updated_at": 0,
}
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

try:
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
except Exception:
    pass


def _validate_state(data: dict) -> dict:
    state = {
        "live": True,
        "updated_at": time.time(),
        "soil": int(data.get("soil", data.get("soil_moisture", 0))),
        "light": int(data.get("light", data.get("light_level", 0))),
        "temperature": float(data.get("temperature", 0)),
        "humidity": float(data.get("humidity", 0)),
        "plant": str(data.get("plant", data.get("plant_type", "")))[:24],
        "stage": str(data.get("stage", ""))[:24],
        "days": int(data.get("days", data.get("days_since_planting", 0))),
        "action": str(data.get("action", "idle"))[:16],
        "duration": int(data.get("duration", data.get("duration_sec", 0))),
        "action_started_at": float(data.get("action_started_at", 0) or 0),
        "reason": str(data.get("reason", ""))[:160],
        "sun_hours": float(data.get("sun_hours", 0)),
        "wifi": bool(data.get("wifi", data.get("wifi_connected", False))),
        "ai": bool(data.get("ai", data.get("ai_enabled", False))),
        "read_count": int(data.get("read_count", 0)),
        "action_count": int(data.get("action_count", 0)),
        "error_count": int(data.get("error_count", 0)),
        "uptime_sec": int(data.get("uptime_sec", data.get("uptime", 0))),
        "decision_source": str(data.get("decision_source", data.get("source", "")))[:24],
        "soil_threshold": int(data.get("soil_threshold", 30)),
        "light_min": int(data.get("light_min", 30)),
        "light_opt": int(data.get("light_opt", 50)),
        "light_hours": data.get("light_hours", [6, 8]),
        "signals": [s for s in data.get("signals", []) if isinstance(s, str)][:8],
        "breeding_observation": str(data.get("breeding_observation", ""))[:200],
    }
    state["soil"] = max(0, min(100, state["soil"]))
    state["light"] = max(0, min(100, state["light"]))
    state["humidity"] = max(0, min(100, state["humidity"]))
    if state["action"] not in {"water", "light", "idle"}:
        state["action"] = "idle"
    return state


def _apply_experiment_state(state: dict) -> dict:
    """Overlay the cloud experiment calendar without mutating its input."""
    value = dict(state)
    experiment = EXPERIMENT_STORE.status()
    if experiment.get("configured"):
        value["days"] = experiment["plant_day"]
        value["experiment_id"] = experiment["experiment_id"]
        value["planting_date"] = experiment["planting_date"]
        value["day_offset"] = experiment["day_offset"]
        value["day_source"] = experiment["day_source"]
        value["experiment_elapsed_hours"] = experiment["experiment_elapsed_hours"]
    return value


def _validate_screening(data: dict) -> dict:
    try:
        from screening.schemas import validate_screening_submission
    except ImportError:
        from tools.screening.schemas import validate_screening_submission
    value = validate_screening_submission(data)
    value["updated_at"] = time.time()
    return value


def _validate_vision_status(data: dict) -> dict:
    try:
        from vision.schemas import validate_cloud_status
    except ImportError:
        from tools.vision.schemas import validate_cloud_status
    return validate_cloud_status(data)


def _validate_vision_event(data: dict) -> dict:
    try:
        from vision.schemas import validate_cloud_event
    except ImportError:
        from tools.vision.schemas import validate_cloud_event
    return validate_cloud_event(data)


def _open_vision_store(*, create: bool = False):
    if not create and not VISION_DB_PATH.exists():
        return None
    try:
        from vision.store import VisionStore
    except ImportError:
        from tools.vision.store import VisionStore
    return VisionStore(VISION_DB_PATH)


def _public_capture(value: dict | None) -> dict:
    if not value:
        return {"available": False}
    result = {k: v for k, v in value.items() if not k.endswith("_path")}
    result["available"] = True
    result["event_id"] = value["capture_id"]
    result["overview_url"] = "/api/vision/images/" + quote(value["capture_id"])
    for item in result.get("observations", []):
        item.pop("image_path", None)
        item["image_url"] = result["overview_url"]
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "SpaceFarmDashboard/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/dashboard", "/dashboard.html"}:
            self._send_file(DASHBOARD_PATH, "text/html; charset=utf-8")
            return
        if path == "/api/state":
            data = _apply_experiment_state(LATEST_STATE)
            data["live"] = bool(data.get("live")) and time.time() - data.get("updated_at", 0) <= STALE_AFTER_SEC
            self._json_response(data)
            return
        if path == "/api/experiment":
            self._json_response(EXPERIMENT_STORE.status())
            return
        if path.startswith("/api/vision/images/"):
            event_id = path.removeprefix("/api/vision/images/")
            if not _EVENT_ID_RE.fullmatch(event_id):
                self.send_error(400)
                return
            image_path = VISION_IMAGE_DIR / (event_id + ".jpg")
            if not image_path.exists():
                self.send_error(404)
                return
            self._send_immutable_image(image_path)
            return
        if path == "/api/vision/events":
            store = _open_vision_store()
            if store is None:
                self._json_response({"available": False, "events": []})
                return
            try:
                query = parse_qs(parsed.query)
                try:
                    limit = max(1, min(20, int(query.get("limit", ["4"])[0])))
                except ValueError:
                    limit = 4
                events = [_public_capture(item) for item in store.list_captures(limit=limit)]
                self._json_response({"available": bool(events), "events": events})
            finally:
                store.close()
            return
        if path in {"/api/vision/status", "/api/vision/latest", "/api/screening/latest"}:
            store = _open_vision_store()
            if store is None:
                self._json_response({"available": False})
                return
            try:
                if path == "/api/vision/status":
                    self._json_response(store.status() or {"available": False})
                elif path == "/api/vision/latest":
                    self._json_response(_public_capture(store.latest_capture()))
                else:
                    self._json_response(store.get_value("screening_latest") or {"available": False})
            finally:
                store.close()
            return
        if path == "/api/vision/image":
            store = _open_vision_store()
            if store is None:
                self.send_error(404)
                return
            try:
                query = parse_qs(parsed.query)
                capture_id = query.get("capture_id", [""])[0]
                capture = store.get_capture(capture_id)
                if not capture:
                    self.send_error(404)
                    return
                pot_id = query.get("pot_id", [""])[0]
                file_path = capture["overview_path"]
                if pot_id:
                    match = next((x for x in capture["observations"] if x["pot_id"] == pot_id), None)
                    if match is None:
                        self.send_error(404)
                        return
                    file_path = match["image_path"]
                resolved = Path(file_path).resolve()
                if VISION_DATA_DIR.resolve() not in resolved.parents:
                    self.send_error(403)
                    return
                self._send_file(resolved, "image/jpeg")
            finally:
                store.close()
            return
        if path == "/health":
            self._json_response({"ok": True, "has_live_state": bool(LATEST_STATE.get("live"))})
            return
        self.send_error(404)

    def do_POST(self):
        global LATEST_STATE
        path = urlparse(self.path).path
        allowed = {
            "/api/state", "/api/experiment", "/api/vision/status",
            "/api/vision/events", "/api/screening/latest", "/api/screening/results",
        }
        if path not in allowed:
            self.send_error(404)
            return
        if path == "/api/experiment":
            required_token = EXPERIMENT_EDIT_TOKEN
        elif path.startswith("/api/vision/") or path.startswith("/api/screening/"):
            required_token = VISION_UPLOAD_TOKEN
        else:
            required_token = TOKEN
        if not self._authorize_write(required_token):
            return
        try:
            max_bytes = (
                MAX_VISION_JSON_BYTES
                if path.startswith("/api/vision/") or path.startswith("/api/screening/")
                else MAX_REQUEST_BYTES
            )
            payload = self._read_json(max_bytes)
            if payload is None:
                return
            if path == "/api/state":
                LATEST_STATE = _apply_experiment_state(_validate_state(payload))
                response = {"ok": True}
            elif path == "/api/vision/status":
                store = _open_vision_store(create=True)
                try:
                    value = _validate_vision_status(payload)
                    value["available"] = True
                    store.set_status(value)
                finally:
                    store.close()
                response = {"ok": True}
            elif path == "/api/vision/events":
                event = _validate_vision_event(payload)
                image_path = VISION_IMAGE_DIR / (event["event_id"] + ".jpg")
                if not image_path.exists():
                    self._json_response({"error": "event image has not been uploaded"}, status=409)
                    return
                image_bytes = image_path.read_bytes()
                if len(image_bytes) != event["image"]["bytes"]:
                    self._json_response({"error": "image byte count mismatch"}, status=409)
                    return
                if hashlib.sha256(image_bytes).hexdigest() != event["image"]["sha256"]:
                    self._json_response({"error": "image sha256 mismatch"}, status=409)
                    return
                store = _open_vision_store(create=True)
                try:
                    store.import_remote_capture(
                        event, event["observations"], overview_path=image_path)
                finally:
                    store.close()
                response = {"ok": True, "event_id": event["event_id"]}
            elif path in {"/api/screening/latest", "/api/screening/results"}:
                store = _open_vision_store(create=True)
                try:
                    value = _validate_screening(payload)
                    store.set_value("screening_latest", value)
                finally:
                    store.close()
                response = value
            else:  # /api/experiment
                response = EXPERIMENT_STORE.save(
                    payload, updated_by=payload.get("updated_by", "operator"))
            self._json_response(response)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json_response({"error": str(exc)}, status=400)

    def do_PUT(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/vision/images/"):
            self.send_error(404)
            return
        if not self._authorize_write(VISION_UPLOAD_TOKEN):
            return
        event_id = path.removeprefix("/api/vision/images/")
        if not _EVENT_ID_RE.fullmatch(event_id):
            self._json_response({"error": "invalid event_id"}, status=400)
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "image/jpeg":
            self._json_response({"error": "only image/jpeg is accepted"}, status=415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._json_response({"error": "empty image"}, status=400)
            return
        if length > MAX_VISION_IMAGE_BYTES:
            self._json_response({"error": "image is too large"}, status=413)
            return
        body = self.rfile.read(length)
        if len(body) != length or not body.startswith(b"\xff\xd8\xff") or not body.endswith(b"\xff\xd9"):
            self._json_response({"error": "invalid JPEG signature"}, status=400)
            return
        digest = hashlib.sha256(body).hexdigest()
        claimed = self.headers.get("X-Content-SHA256", "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", claimed) or claimed != digest:
            self._json_response({"error": "sha256 mismatch"}, status=400)
            return
        VISION_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        destination = VISION_IMAGE_DIR / (event_id + ".jpg")
        temporary = VISION_IMAGE_DIR / (event_id + f".{time.time_ns()}.upload")
        temporary.write_bytes(body)
        temporary.replace(destination)
        self._json_response({"ok": True, "event_id": event_id, "sha256": digest})

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Dashboard-Token, X-Content-SHA256",
        )
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f"[Dashboard] {self.address_string()} - {fmt % args}")

    def _send_file(self, path: Path, content_type: str):
        if not path.exists():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_immutable_image(self, path: Path):
        body = path.read_bytes()
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self._send_cors_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _authorize_write(self, token: str) -> bool:
        if not token:
            # Safe development fallback: unauthenticated writes are loopback-only.
            if self.client_address[0] in {"127.0.0.1", "::1"}:
                return True
            self._json_response({"error": "write token is not configured"}, status=503)
            return False
        if self.headers.get("X-Dashboard-Token") != token:
            self._json_response({"error": "unauthorized"}, status=401)
            return False
        return True

    def _read_json(self, max_bytes: int):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._json_response({"error": "empty request body"}, status=400)
            return None
        if length > max_bytes:
            self._json_response({"error": "request body too large"}, status=413)
            return None
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_cors_headers(self):
        origin = self.headers.get("Origin", "").rstrip("/")
        if ALLOWED_ORIGIN and origin == ALLOWED_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
            self.send_header("Vary", "Origin")

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Dashboard-Token")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("DASHBOARD_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DASHBOARD_PORT", "8790")))
    args = parser.parse_args()

    class _Server(ThreadingHTTPServer):
        # 默认 backlog 仅 5，浏览器高频轮询 + 网关 POST 并发突发时会丢连接，
        # 经公网入口层放大为 502 → 网页"模拟/在线"横跳。提高 backlog 从源头减少。
        request_queue_size = 128
        daemon_threads = True
        allow_reuse_address = True

    server = _Server((args.host, args.port), Handler)
    print(f"[Dashboard] Open http://127.0.0.1:{args.port}/")
    print(f"[Dashboard] ESP32 POST endpoint: http://<this-computer-ip>:{args.port}/api/state")
    print(f"[Dashboard] Experiment settings: http://<this-computer-ip>:{args.port}/api/experiment")
    server.serve_forever()


if __name__ == "__main__":
    main()
