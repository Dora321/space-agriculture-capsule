#!/usr/bin/env python3
"""Local AI proxy for ESP32.

ESP32 posts the normal OpenAI-compatible payload to this proxy over plain HTTP.
The proxy performs the HTTPS request to DeepSeek/OpenAI and returns only the
small decision JSON, avoiding TLS memory pressure on the ESP32.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "esp32_firmware" / "config.py"


def _load_project_config():
    if not CONFIG_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("space_farm_config", CONFIG_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROJECT_CONFIG = _load_project_config()


def _config_value(name: str, default: str = "") -> str:
    env_value = os.getenv(name)
    if env_value:
        return env_value
    if PROJECT_CONFIG is not None:
        return str(getattr(PROJECT_CONFIG, name, default))
    return default


API_URL = _config_value("AI_API_URL", "https://api.deepseek.com/chat/completions")
API_KEY = _config_value("AI_API_KEY")
API_MODEL = _config_value("AI_MODEL", "deepseek-v4-flash")
API_TIMEOUT = int(_config_value("AI_TIMEOUT", "20"))
PROXY_TOKEN = _config_value("AI_PROXY_TOKEN")
MAX_REQUEST_BYTES = int(os.getenv("AI_PROXY_MAX_REQUEST_BYTES", "8192"))


def _strip_code_fence(text: str) -> str:
    content = text.strip()
    if content.startswith("```json"):
        content = content[7:].strip()
    if content.startswith("```"):
        content = content[3:].strip()
    if content.endswith("```"):
        content = content[:-3].strip()
    return content


def _validate_decision(decision: dict) -> dict:
    action = decision.get("action")
    duration = decision.get("duration_sec")
    if action not in {"water", "nutrient", "idle"}:
        raise ValueError(f"invalid action: {action!r}")
    if not isinstance(duration, int):
        raise ValueError("duration_sec must be an int")
    duration = max(0, duration)
    if action == "idle":
        duration = 0
    return {
        "action": action,
        "duration_sec": duration,
        "reason": str(decision.get("reason", ""))[:120],
    }


def request_decision(payload: dict) -> dict:
    if not API_KEY or "YOUR_" in API_KEY or "API_KEY_HERE" in API_KEY or "你的" in API_KEY:
        raise RuntimeError("AI_API_KEY is not configured")

    payload = dict(payload)
    payload.setdefault("model", API_MODEL)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlopen(request, timeout=API_TIMEOUT) as response:
        raw = response.read().decode("utf-8")

    result = json.loads(raw)
    content = result["choices"][0]["message"].get("content", "")
    decision = json.loads(_strip_code_fence(content))
    return _validate_decision(decision)


class Handler(BaseHTTPRequestHandler):
    server_version = "SpaceFarmAIProxy/1.0"

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self._json_response({"ok": True, "model": API_MODEL})

    def do_POST(self):
        if self.path != "/decision":
            self.send_error(404)
            return
        if PROXY_TOKEN and self.headers.get("X-Proxy-Token") != PROXY_TOKEN:
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
            decision = request_decision(payload)
            self._json_response(decision)
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            self._json_response({"error": str(exc)}, status=502)

    def log_message(self, fmt, *args):
        print(f"[AI Proxy] {self.address_string()} - {fmt % args}")

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host",
        default=os.getenv("AI_PROXY_HOST", "127.0.0.1"),
        help="Bind address. Use 0.0.0.0 only on a trusted LAN or behind HTTPS.",
    )
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[AI Proxy] Listening on http://{args.host}:{args.port}/decision")
    print(f"[AI Proxy] Forwarding to {API_URL} model={API_MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
