import importlib.util
import hashlib
import http.client
import json
import pathlib
import threading
import time


def _load_dashboard_server():
    root = pathlib.Path(__file__).resolve().parent.parent
    path = root / "tools" / "dashboard_server.py"
    spec = importlib.util.spec_from_file_location("dashboard_server_test", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_state_clamps_values_and_normalizes_action():
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "soil": 140,
        "light": -3,
        "temperature": 24.5,
        "humidity": 120,
        "plant": "Lettuce",
        "stage": "seedling",
        "action": "unknown",
        "action_started_at": 123.5,
        "reason": "status normal",
        "soil_threshold": 35,
        "light_min": 50,
        "light_opt": 70,
        "light_hours": [8, 12],
        "uptime_sec": 300,
        "decision_source": "cloud",
    })

    assert state["live"] is True
    assert state["soil"] == 100
    assert state["light"] == 0
    assert state["humidity"] == 100
    assert state["action"] == "idle"
    assert state["action_started_at"] == 123.5
    assert state["soil_threshold"] == 35
    assert state["light_min"] == 50
    assert state["light_opt"] == 70
    assert state["light_hours"] == [8, 12]
    assert state["uptime_sec"] == 300
    assert state["decision_source"] == "cloud"


def test_validate_state_remaps_legacy_nutrient_action():
    """单泵架构：dashboard 收到旧设备的 nutrient action 应归一到 idle"""
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "action": "nutrient",
        "soil": 30,
        "light": 50,
        "temperature": 24,
        "humidity": 50,
    })
    assert state["action"] == "idle"


def test_validate_state_passes_through_signals():
    """Decision Plane：signals 列表从遥测数据透传到前端"""
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "soil": 42,
        "light": 50,
        "temperature": 24,
        "humidity": 60,
        "signals": ["WATER", "TEMP_HIGH", "NEED_N"],
    })
    assert state["signals"] == ["WATER", "TEMP_HIGH", "NEED_N"]


def test_validate_state_filters_non_string_signals():
    """signals 列表中只保留字符串类型"""
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "soil": 42,
        "light": 50,
        "temperature": 24,
        "humidity": 60,
        "signals": ["WATER", 123, None, "TEMP_HIGH"],
    })
    assert state["signals"] == ["WATER", "TEMP_HIGH"]


def test_validate_state_limits_signals_to_8():
    """signals 列表最多保留 8 个，防止滥用"""
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "soil": 42,
        "light": 50,
        "temperature": 24,
        "humidity": 60,
        "signals": [f"SIG_{i}" for i in range(12)],
    })
    assert len(state["signals"]) == 8


def test_validate_state_passes_through_breeding_observation():
    """育种观察从遥测数据透传到前端"""
    dashboard_server = _load_dashboard_server()
    state = dashboard_server._validate_state({
        "soil": 42,
        "light": 50,
        "temperature": 24,
        "humidity": 60,
        "breeding_observation": "叶片展开，进入营养生长阶段",
    })
    assert state["breeding_observation"] == "叶片展开，进入营养生长阶段"


def test_validate_state_truncates_long_breeding_observation():
    """育种观察最多 200 字符"""
    dashboard_server = _load_dashboard_server()
    long_text = "x" * 300
    state = dashboard_server._validate_state({
        "soil": 42,
        "light": 50,
        "temperature": 24,
        "humidity": 60,
        "breeding_observation": long_text,
    })
    assert len(state["breeding_observation"]) == 200


def _screening_input():
    return {
        "schema": "screening.input.v1",
        "result_id": "result-1",
        "material_id": "candidate-A",
        "control_material_id": "control",
        "cycle_group_id": "group-1",
        "candidate_cycles": [
            {"cycle_id": cycle, "score": 80} for cycle in ("c1", "c2", "c3")
        ],
        "control_cycles": [
            {"cycle_id": cycle, "score": 70} for cycle in ("c1", "c2", "c3")
        ],
        "data_coverage": .8,
        "ai_human_agreement": .75,
    }


def test_validate_screening_recomputes_grade_and_drops_untrusted_fields():
    dashboard_server = _load_dashboard_server()
    payload = _screening_input()
    payload.update({"evidence_grade": "A", "delta_control_median": 999, "attacker": "x"})
    result = dashboard_server._validate_screening(payload)
    assert result["evidence_grade"] == "B"
    assert result["delta_control_median"] == 10
    assert "attacker" not in result
    assert result["updated_at"] > 0


def test_public_capture_does_not_expose_local_paths():
    dashboard_server = _load_dashboard_server()
    result = dashboard_server._public_capture({
        "capture_id": "cap-1",
        "overview_path": "/private/overview.jpg",
        "observations": [{
            "pot_id": "P1", "image_path": "/private/p1.jpg", "analysis": None,
        }],
    })
    assert "overview_path" not in result
    assert "image_path" not in result["observations"][0]
    assert result["overview_url"] == "/api/vision/images/cap-1"


def test_apply_experiment_state_uses_authoritative_day():
    dashboard_server = _load_dashboard_server()
    class FakeStore:
        @staticmethod
        def status():
            return {
                "configured": True, "experiment_id": "EXP-1",
                "planting_date": "2026-07-03", "plant_day": 8,
                "day_offset": 2, "day_source": "adjusted",
                "experiment_elapsed_hours": 48.0,
            }

    dashboard_server.EXPERIMENT_STORE = FakeStore()
    state = dashboard_server._apply_experiment_state({"days": 1, "soil": 40})
    assert state["days"] == 8
    assert state["experiment_id"] == "EXP-1"
    assert state["day_source"] == "adjusted"


def _http_request(server, method, path, *, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    raw = body
    request_headers = dict(headers or {})
    if isinstance(body, dict):
        raw = json.dumps(body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    connection.request(method, path, body=raw, headers=request_headers)
    response = connection.getresponse()
    data = response.read()
    result = (response.status, dict(response.getheaders()), data)
    connection.close()
    return result


def _start_server(module, tmp_path):
    module.VISION_DATA_DIR = tmp_path / "vision"
    module.VISION_DB_PATH = module.VISION_DATA_DIR / "vision.sqlite3"
    module.VISION_IMAGE_DIR = module.VISION_DATA_DIR / "images"
    module.TOKEN = "state-secret"
    module.VISION_UPLOAD_TOKEN = "vision-secret"
    module.MANUAL_CAPTURE_TOKEN = "manual-secret"
    module.ALLOWED_ORIGIN = "http://dashboard.example"
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_manual_capture_command_is_authenticated_and_dispatchable(tmp_path):
    dashboard_server = _load_dashboard_server()
    server = _start_server(dashboard_server, tmp_path)
    try:
        assert _http_request(
            server, "POST", "/api/vision/capture",
            body={"operator": "dashboard"})[0] == 401
        status, _, raw = _http_request(
            server, "POST", "/api/vision/capture",
            body={"operator": "dashboard", "reason": "manual test"},
            headers={"X-Dashboard-Token": "manual-secret"})
        request = json.loads(raw)
        assert status == 200 and request["status"] == "pending"

        status, _, raw = _http_request(
            server, "GET", "/api/vision/capture/request",
            headers={"X-Dashboard-Token": "vision-secret"})
        command = json.loads(raw)
        assert status == 200 and command["available"] is True
        assert command["request"]["request_id"] == request["request_id"]

        status, _, raw = _http_request(
            server, "POST", "/api/vision/capture/dispatch",
            body={"request_id": request["request_id"], "accepted": True},
            headers={"X-Dashboard-Token": "vision-secret"})
        assert status == 200 and json.loads(raw)["updated"] is True
        _, _, raw = _http_request(
            server, "GET", "/api/vision/capture/request",
            headers={"X-Dashboard-Token": "vision-secret"})
        assert json.loads(raw)["available"] is False
    finally:
        server.shutdown()
        server.server_close()


def test_cloud_vision_upload_is_authenticated_idempotent_and_persistent(tmp_path):
    dashboard_server = _load_dashboard_server()
    server = _start_server(dashboard_server, tmp_path)
    image = b"\xff\xd8\xffcloud-jpeg\xff\xd9"
    digest = hashlib.sha256(image).hexdigest()
    event = {
        "schema": "vision.event.v1", "event_id": "cap-1",
        "captured_at": time.time(), "cycle_id": "cycle-1",
        "current_light": 70, "required_light": 50,
        "context": {"day": 8, "stage": "vegetative"},
        "observations": [{
            "pot_id": "PLANT", "material_id": "current-plant", "is_control": False,
            "roi_id": "plant-overview", "quality": {"accepted": True, "brightness": .5},
            "analysis": {"plant": "白掌", "vigor": "normal"},
        }],
        "model": {"name": "test-model", "ignored": "drop-me"},
        "image": {"sha256": digest, "bytes": len(image)},
    }
    try:
        status, _, _ = _http_request(server, "PUT", "/api/vision/images/cap-1", body=image, headers={
            "Content-Type": "image/jpeg", "X-Content-SHA256": digest,
        })
        assert status == 401
        upload_headers = {
            "Content-Type": "image/jpeg", "X-Content-SHA256": digest,
            "X-Dashboard-Token": "vision-secret",
        }
        assert _http_request(
            server, "PUT", "/api/vision/images/..bad", body=image,
            headers=upload_headers)[0] == 400
        bad_headers = dict(upload_headers, **{"X-Content-SHA256": "0" * 64})
        assert _http_request(
            server, "PUT", "/api/vision/images/bad-sha", body=image,
            headers=bad_headers)[0] == 400
        assert _http_request(
            server, "PUT", "/api/vision/images/cap-1", body=image,
            headers=upload_headers)[0] == 200
        assert _http_request(
            server, "POST", "/api/vision/events", body=event,
            headers={"X-Dashboard-Token": "vision-secret"})[0] == 200
        # Replaying the same event must update, not duplicate or fail.
        assert _http_request(
            server, "POST", "/api/vision/events", body=event,
            headers={"X-Dashboard-Token": "vision-secret"})[0] == 200

        status, headers, raw = _http_request(server, "GET", "/api/vision/latest")
        latest = json.loads(raw)
        assert status == 200 and latest["available"] is True
        assert latest["event_id"] == "cap-1"
        assert "overview_path" not in latest
        status, headers, raw = _http_request(server, "GET", "/api/vision/images/cap-1")
        assert status == 200 and raw == image
        assert headers["Cache-Control"].endswith("immutable")
        assert headers["ETag"]
        status, _, raw = _http_request(
            server, "GET", "/api/vision/images/cap-1",
            headers={"If-None-Match": headers["ETag"]})
        assert status == 304 and raw == b""
        status, _, raw = _http_request(server, "GET", "/api/vision/events?limit=4")
        assert status == 200 and len(json.loads(raw)["events"]) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_production_cors_is_explicit_and_state_write_requires_token(tmp_path):
    dashboard_server = _load_dashboard_server()
    server = _start_server(dashboard_server, tmp_path)
    try:
        status, _, _ = _http_request(server, "POST", "/api/state", body={"soil": 40})
        assert status == 401
        status, headers, _ = _http_request(
            server, "GET", "/api/state", headers={"Origin": "http://evil.example"})
        assert status == 200 and "Access-Control-Allow-Origin" not in headers
        status, headers, _ = _http_request(
            server, "GET", "/api/state", headers={"Origin": "http://dashboard.example"})
        assert headers["Access-Control-Allow-Origin"] == "http://dashboard.example"
        assert headers["Access-Control-Allow-Origin"] != "*"
    finally:
        server.shutdown()
        server.server_close()
