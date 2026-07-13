import http.client
import json
import threading
import time

from tools.vision import local_api
from tools.vision.store import VisionStore


def _request(server, method, path, *, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    request_headers = dict(headers or {})
    raw = body
    if isinstance(body, dict):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    connection.request(method, path, body=raw, headers=request_headers)
    response = connection.getresponse()
    data = response.read()
    result = response.status, dict(response.getheaders()), data
    connection.close()
    return result


def test_local_api_health_manual_capture_label_and_preview(tmp_path):
    local_api.DATA_DIR = tmp_path / "vision"
    local_api.DB_PATH = local_api.DATA_DIR / "vision.sqlite3"
    local_api.CHECK_SEC = 10
    local_api.DATA_DIR.mkdir(parents=True)
    overview = local_api.DATA_DIR / "captures" / "cap-1" / "overview.jpg"
    overview.parent.mkdir(parents=True)
    image = b"\xff\xd8\xffpreview\xff\xd9"
    overview.write_bytes(image)

    now = time.time()
    store = VisionStore(local_api.DB_PATH)
    store.create_capture({
        "capture_id": "cap-1", "captured_at": now - 10, "cycle_id": "c1",
        "overview_path": str(overview), "current_light": 60, "required_light": 50,
    }, [{
        "pot_id": "PLANT", "material_id": "current-plant", "is_control": False,
        "roi_id": "plant-overview", "image_path": str(overview), "quality": {"accepted": True},
    }])
    store.mark_succeeded("cap-1", {
        "capture_id": "cap-1",
        "observations": [{"pot_id": "PLANT", "analysis": {"plant": "白掌"}}],
    }, now=now - 5)
    for key, state in (
        ("health_capture", "WAITING_INTERVAL"),
        ("health_api", "idle"),
        ("health_cloud", "idle"),
    ):
        store.set_value(key, {
            "alive": True, "heartbeat_at": now, "state": state, "last_error": "",
        }, now=now)
    store.set_status({"state": "WAITING_INTERVAL"}, now=now)
    store.close()

    server = local_api.ThreadingHTTPServer(("127.0.0.1", 0), local_api.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, raw = _request(server, "GET", "/healthz")
        health = json.loads(raw)
        assert status == 200 and health["ok"] is True
        assert health["camera"]["available"] is True
        assert health["quota"]["remaining"] == local_api.DAILY_LIMIT

        status, _, raw = _request(
            server, "POST", "/v1/capture",
            body={"operator": "tester", "reason": "manual review"})
        request = json.loads(raw)
        assert status == 202 and request["status"] == "pending"
        status, _, raw = _request(
            server, "POST", "/v1/capture",
            body={"operator": "tester", "reason": "duplicate click"})
        assert status == 202 and json.loads(raw)["request_id"] == request["request_id"]

        status, _, raw = _request(
            server, "POST", "/v1/events/cap-1/label",
            body={
                "operator": "reviewer", "pot_id": "PLANT", "note": "目视复核",
                "label": {"plant": "白掌", "vigor": "normal", "certainty": "high"},
            })
        label = json.loads(raw)
        assert status == 201 and label["operator"] == "reviewer"

        status, _, raw = _request(server, "GET", "/v1/latest")
        latest = json.loads(raw)
        assert status == 200 and latest["human_labels"][0]["note"] == "目视复核"
        assert "overview_path" not in latest

        status, headers, raw = _request(server, "GET", "/v1/images/cap-1-thumb.jpg")
        assert status == 200 and raw == image
        assert headers["ETag"]
    finally:
        server.shutdown()
        server.server_close()


def test_local_api_rejects_missing_operator_and_unknown_label_target(tmp_path):
    local_api.DATA_DIR = tmp_path / "vision"
    local_api.DB_PATH = local_api.DATA_DIR / "vision.sqlite3"
    local_api.DATA_DIR.mkdir(parents=True)
    server = local_api.ThreadingHTTPServer(("127.0.0.1", 0), local_api.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert _request(server, "POST", "/v1/capture", body={})[0] == 400
        assert _request(server, "POST", "/v1/events/missing/label", body={
            "operator": "reviewer", "pot_id": "P1", "label": {},
        })[0] == 404
    finally:
        server.shutdown()
        server.server_close()
