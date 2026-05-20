#!/usr/bin/env python3
"""Local realtime dashboard server for the contest display.

ESP32 can POST telemetry to /api/state. The browser opens this server and
polls /api/state, falling back to the dashboard's built-in demo animation when
no live device has reported yet.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "deliverables" / "contest-demo-dashboard.html"
TOKEN = os.getenv("DASHBOARD_TOKEN", "")
MAX_REQUEST_BYTES = int(os.getenv("DASHBOARD_MAX_REQUEST_BYTES", "4096"))
STALE_AFTER_SEC = int(os.getenv("DASHBOARD_STALE_AFTER_SEC", "120"))

LATEST_STATE: dict = {
    "live": False,
    "updated_at": 0,
}


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
    }
    state["soil"] = max(0, min(100, state["soil"]))
    state["light"] = max(0, min(100, state["light"]))
    state["humidity"] = max(0, min(100, state["humidity"]))
    if state["action"] not in {"water", "nutrient", "idle"}:
        state["action"] = "idle"
    return state


class Handler(BaseHTTPRequestHandler):
    server_version = "SpaceFarmDashboard/1.0"

    def do_GET(self):
        path = urlparse(self.path).path
        if path in {"/", "/dashboard", "/dashboard.html"}:
            self._send_file(DASHBOARD_PATH, "text/html; charset=utf-8")
            return
        if path == "/api/state":
            data = dict(LATEST_STATE)
            data["live"] = bool(data.get("live")) and time.time() - data.get("updated_at", 0) <= STALE_AFTER_SEC
            self._json_response(data)
            return
        if path == "/health":
            self._json_response({"ok": True, "has_live_state": bool(LATEST_STATE.get("live"))})
            return
        self.send_error(404)

    def do_POST(self):
        global LATEST_STATE
        path = urlparse(self.path).path
        if path != "/api/state":
            self.send_error(404)
            return
        if TOKEN and self.headers.get("X-Dashboard-Token") != TOKEN:
            self._json_response({"error": "unauthorized"}, status=401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                self._json_response({"error": "empty request body"}, status=400)
                return
            if length > MAX_REQUEST_BYTES:
                self._json_response({"error": "request body too large"}, status=413)
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            LATEST_STATE = _validate_state(payload)
            self._json_response({"ok": True})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json_response({"error": str(exc)}, status=400)

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
        self.wfile.write(body)

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("DASHBOARD_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DASHBOARD_PORT", "8790")))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[Dashboard] Open http://127.0.0.1:{args.port}/")
    print(f"[Dashboard] ESP32 POST endpoint: http://<this-computer-ip>:{args.port}/api/state")
    server.serve_forever()


if __name__ == "__main__":
    main()
