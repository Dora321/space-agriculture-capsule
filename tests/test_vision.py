import json

from tools.vision.api_worker import VisionApiWorker
from tools.vision.camera import CameraModule3
from tools.vision.capture_service import CaptureService
from tools.vision.clients import OpenAICompatibleVisionClient
from tools.vision.cloud_sync import VisionCloudSyncWorker
from tools.vision.quality import evaluate_metrics
from tools.vision.scheduler import (
    CaptureScheduler, READY, WAITING_INTERVAL, WAITING_LIGHT, WAITING_TELEMETRY,
)
from tools.vision.store import VisionStore


def test_scheduler_requires_fresh_telemetry_interval_and_light():
    scheduler = CaptureScheduler(interval_sec=7200, telemetry_stale_sec=120, fallback_light_min=50)
    assert scheduler.evaluate(now=100, telemetry=None).state == WAITING_TELEMETRY
    telemetry = {"received_at": 100, "light": 49}
    assert scheduler.evaluate(now=100, telemetry=telemetry).state == WAITING_LIGHT
    telemetry["light"] = 50
    assert scheduler.evaluate(now=100, telemetry=telemetry).state == READY
    assert scheduler.evaluate(now=200, telemetry={"received_at": 200, "light": 80},
                              last_success_at=100).state == WAITING_INTERVAL
    assert scheduler.evaluate(now=7300, telemetry={"received_at": 7300, "light": 80},
                              last_success_at=100).state == READY


def test_scheduler_uses_crop_light_optimum_without_actuator_action():
    decision = CaptureScheduler().evaluate(
        now=10, telemetry={"received_at": 10, "light": 59},
        plant_info={"light_opt": 60},
    )
    assert decision.state == WAITING_LIGHT
    assert decision.should_capture is False
    assert not hasattr(decision, "light_action")


def test_quality_checks_are_deterministic():
    assert evaluate_metrics(blur_score=100, brightness=0.5).accepted
    result = evaluate_metrics(blur_score=20, brightness=0.1)
    assert result.accepted is False
    assert result.reasons == ("blurred", "underexposed")


def _capture(tmp_path):
    image = tmp_path / "p1.jpg"
    image.write_bytes(b"jpeg")
    return {
        "capture_id": "cap-1", "captured_at": 100, "cycle_id": "c1",
        "overview_path": str(tmp_path / "overview.jpg"), "current_light": 60,
        "required_light": 50,
    }, [{
        "pot_id": "P1", "material_id": "control", "is_control": True,
        "roi_id": "roi-1", "image_path": str(image), "quality": {"accepted": True},
    }]


def test_store_queues_leases_retries_and_persists_analysis(tmp_path):
    store = VisionStore(tmp_path / "vision.sqlite3")
    capture, observations = _capture(tmp_path)
    store.create_capture(capture, observations)
    assert store.last_capture_at() == 100
    job = store.lease_next("worker", now=100)
    assert job["status"] == "leased"
    assert job["observations"][0]["quality"]["accepted"] is True
    assert store.mark_retry("cap-1", "network", now=101, available_at=102) == "retry"
    job = store.lease_next("worker", now=102)
    result = {
        "capture_id": "cap-1", "observations": [{"pot_id": "P1", "analysis": {"vigor": "normal"}}]
    }
    store.mark_succeeded("cap-1", result, now=103)
    saved = store.get_capture("cap-1")
    assert saved["status"] == "succeeded"
    assert saved["observations"][0]["analysis"]["vigor"] == "normal"
    assert store.last_success_at() == 100
    store.close()


def test_multimodal_client_sends_image_and_does_not_trust_model_metadata(tmp_path):
    capture, observations = _capture(tmp_path)
    capture["observations"] = observations
    seen = {}

    def post(url, headers, body, timeout):
        seen["payload"] = json.loads(body)
        answer = {
            "capture_id": "model-invented",
            "observations": [{
                "pot_id": "P1", "material_id": "wrong", "is_control": False,
                "roi_id": "wrong", "analysis": {"plant": "生菜", "vigor": "strong"},
            }],
        }
        return json.dumps({"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]}).encode()

    client = OpenAICompatibleVisionClient(
        api_url="https://example.invalid/v1/chat/completions", api_key="secret",
        model="vision-test", post=post,
    )
    result, image_bytes = client.analyze(capture)
    assert image_bytes == 4
    assert result["capture_id"] == "cap-1"
    assert result["observations"][0]["material_id"] == "control"
    assert result["observations"][0]["is_control"] is True
    serialized = json.dumps(seen["payload"])
    assert "data:image/jpeg;base64," in serialized
    assert "secret" not in serialized


def test_multimodal_client_accepts_a_compatible_api_base_url():
    client = OpenAICompatibleVisionClient(
        api_url="https://example.invalid/compatible-mode/v1/",
        api_key="secret", model="vision-test",
    )
    assert client.api_url.endswith("/compatible-mode/v1/chat/completions")


def test_api_worker_retries_without_raising(tmp_path):
    store = VisionStore(tmp_path / "vision.sqlite3")
    capture, observations = _capture(tmp_path)
    store.create_capture(capture, observations)

    class BrokenClient:
        def analyze(self, _job):
            raise TimeoutError("offline")

    worker = VisionApiWorker(store, BrokenClient(), clock=lambda: 100)
    assert worker.run_once() == "retry"
    assert store.get_capture("cap-1")["status"] == "retry"
    store.close()


def test_camera_module_3_adapter_uses_picamera2_contract(tmp_path):
    calls = []

    class FakeCamera:
        def create_still_configuration(self, **kwargs):
            calls.append(("config", kwargs))
            return kwargs
        def configure(self, value): calls.append(("configure", value))
        def set_controls(self, value): calls.append(("controls", value))
        def start(self): calls.append(("start", None))
        def capture_file(self, path): calls.append(("capture", path))
        def stop(self): calls.append(("stop", None))

    camera = CameraModule3(picamera=FakeCamera(), warmup_sec=0)
    camera.capture(tmp_path / "shot.jpg")
    camera.close()
    assert ("controls", {"AfMode": 2}) in calls
    assert any(name == "capture" for name, _ in calls)
    assert calls[-1][0] == "stop"


def test_capture_service_persists_context_after_quality_gate(tmp_path):
    store = VisionStore(tmp_path / "vision.sqlite3")
    store.save_telemetry({"light": 70, "day": 8, "stage": "seedling"}, received_at=100)

    class Camera:
        def capture(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"overview")

    def prepare(_source, output_dir, rois):
        output_dir.mkdir(parents=True, exist_ok=True)
        result = []
        for roi in rois:
            path = output_dir / (roi["pot_id"] + ".jpg")
            path.write_bytes(b"roi")
            result.append({**roi, "image_path": str(path)})
        return result

    service = CaptureService(
        store=store, scheduler=CaptureScheduler(), camera=Camera(),
        experiment={
            "cycle_id": "cycle-1", "plant_info": {"plant": "生菜", "light_opt": 50},
            "rois": [{"pot_id": "P1", "roi_id": "r1", "material_id": "control",
                      "is_control": True, "x": 0, "y": 0, "width": 1, "height": 1}],
        },
        data_dir=tmp_path, prepare=prepare,
        inspect=lambda _path: evaluate_metrics(blur_score=100, brightness=.5),
        clock=lambda: 100,
    )
    status = service.tick()
    assert status["state"] == "QUEUED_FOR_ANALYSIS"
    capture = store.latest_capture()
    assert capture["context"]["plant_info"]["plant"] == "生菜"
    assert capture["context"]["day"] == 8
    store.close()


def test_capture_service_does_not_queue_rejected_images(tmp_path):
    store = VisionStore(tmp_path / "vision.sqlite3")
    store.save_telemetry({"light": 70}, received_at=100)

    class Camera:
        def capture(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"overview")

    def prepare(_source, output_dir, rois):
        return [{**rois[0], "image_path": str(output_dir / "bad.jpg")}]

    service = CaptureService(
        store=store, scheduler=CaptureScheduler(), camera=Camera(),
        experiment={"rois": [{"pot_id": "P1", "roi_id": "r1"}]},
        data_dir=tmp_path, prepare=prepare,
        inspect=lambda _path: evaluate_metrics(blur_score=1, brightness=.5),
        clock=lambda: 100,
    )
    assert service.tick()["state"] == "QUALITY_REJECTED"
    assert store.latest_capture() is None
    store.close()


def test_cloud_sync_worker_uploads_one_event_and_marks_outbox(tmp_path):
    store = VisionStore(tmp_path / "vision.sqlite3")
    capture, observations = _capture(tmp_path)
    overview = tmp_path / "overview.jpg"
    overview.write_bytes(b"\xff\xd8\xffoverview\xff\xd9")
    capture["overview_path"] = str(overview)
    capture["context"] = {"day": 8, "stage": "vegetative"}
    store.create_capture(capture, observations)
    store.mark_succeeded("cap-1", {
        "capture_id": "cap-1", "model": {"name": "vision-test"},
        "observations": [{
            "pot_id": "P1", "analysis": {"plant": "生菜", "vigor": "normal"},
        }],
    }, now=101)
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self): return b'{"ok":true}'

    def request_json(url, **kwargs):
        calls.append((kwargs["method"], url, json.loads(kwargs["body"])))
        return {"ok": True}

    def urlopen(request, timeout):
        calls.append((request.method, request.full_url, request.data))
        return Response()

    worker = VisionCloudSyncWorker(
        store, base_url="https://cloud.example", token="secret", clock=lambda: 200,
        request_json=request_json, urlopen=urlopen,
    )
    assert worker.run_once() == "succeeded"
    assert worker.run_once() == "idle"
    methods = [item[0] for item in calls]
    assert "PUT" in methods and methods.count("POST") >= 1
    event = next(item[2] for item in calls if item[0] == "POST" and item[1].endswith("/events"))
    assert event["schema"] == "vision.event.v1"
    assert event["event_id"] == "cap-1"
    assert len(event["image"]["sha256"]) == 64
    store.close()


def test_cloud_outbox_retry_survives_reopen_and_uses_backoff(tmp_path):
    db_path = tmp_path / "vision.sqlite3"
    store = VisionStore(db_path)
    capture, observations = _capture(tmp_path)
    store.create_capture(capture, observations)
    store.mark_succeeded("cap-1", {
        "capture_id": "cap-1", "observations": [{"pot_id": "P1", "analysis": {}}],
    }, now=100)
    assert store.lease_cloud_sync("worker", now=100)["capture_id"] == "cap-1"
    assert store.mark_cloud_retry("cap-1", "offline", now=100) == 130
    store.close()

    reopened = VisionStore(db_path)
    assert reopened.lease_cloud_sync("worker", now=129) is None
    assert reopened.lease_cloud_sync("worker", now=130)["capture_id"] == "cap-1"
    reopened.close()
