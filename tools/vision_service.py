"""Run Camera Module 3 capture scheduling or the remote-analysis queue worker."""

from __future__ import annotations

import argparse
import json
import os
import time

from vision.api_worker import VisionApiWorker
from vision.camera import CameraModule3
from vision.capture_service import CaptureService
from vision.clients import OpenAICompatibleVisionClient
from vision.cloud_sync import VisionCloudSyncWorker
from vision.config import VisionConfig
from vision.image_prepare import prepare_rois
from vision.quality import inspect_image
from vision.scheduler import CaptureScheduler
from vision.store import VisionStore


def _load_experiment(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value.get("rois"), list) or len(value["rois"]) != 1:
        raise ValueError("single-plant mode requires exactly one overview ROI")
    pot_ids = [item.get("pot_id") for item in value["rois"]]
    if any(not pot for pot in pot_ids) or len(pot_ids) != len(set(pot_ids)):
        raise ValueError("ROI pot_id values must be present and unique")
    if any(bool(item.get("is_control")) for item in value["rois"]):
        raise ValueError("single-plant mode does not use control observations")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SpaceFarm Camera Module 3 services")
    parser.add_argument(
        "mode", choices=("capture", "api-once", "api-loop", "cloud-once", "cloud-loop"))
    parser.add_argument("--experiment", default=os.environ.get("SPACEFARM_VISION_EXPERIMENT", ""))
    args = parser.parse_args(argv)
    config = VisionConfig.from_env()
    store = VisionStore(config.data_dir / "vision.sqlite3")
    try:
        if args.mode == "capture":
            if not args.experiment:
                parser.error("capture mode requires --experiment")
            experiment = _load_experiment(args.experiment)
            scheduler = CaptureScheduler(
                config.capture_interval_sec, config.telemetry_stale_sec,
                config.capture_light_min,
            )
            with CameraModule3() as camera:
                service = CaptureService(
                    store=store, scheduler=scheduler, camera=camera,
                    experiment=experiment, data_dir=config.data_dir,
                    prepare=prepare_rois, inspect=inspect_image,
                    quality_retry_sec=config.schedule_check_sec,
                )
                while True:
                    print("[VISION]", json.dumps(service.tick(), ensure_ascii=False))
                    # Poll local manual-capture requests promptly while the scheduler
                    # still enforces the two-hour automatic capture interval.
                    time.sleep(min(config.schedule_check_sec, 10))
        elif args.mode in {"cloud-once", "cloud-loop"}:
            worker = VisionCloudSyncWorker(
                store,
                base_url=os.environ.get("SPACEFARM_CLOUD_BASE_URL", ""),
                token=os.environ.get("VISION_UPLOAD_TOKEN", ""),
                timeout_sec=float(os.environ.get("SPACEFARM_CLOUD_TIMEOUT_SEC", "10")),
                max_image_bytes=int(os.environ.get(
                    "SPACEFARM_CLOUD_MAX_IMAGE_BYTES", "120000")),
            )
            if args.mode == "cloud-once":
                print("[VISION CLOUD]", worker.run_once())
                return 0
            interval = max(5.0, float(os.environ.get("SPACEFARM_CLOUD_SYNC_INTERVAL", "15")))
            while True:
                print("[VISION CLOUD]", worker.run_once())
                time.sleep(interval)
        else:
            api_url = os.environ.get("SPACEFARM_VISION_API_URL", "")
            api_key = os.environ.get("SPACEFARM_VISION_API_KEY", "")
            model = os.environ.get("SPACEFARM_VISION_MODEL", "")
            if not all((api_url, api_key, model)):
                raise SystemExit("set SPACEFARM_VISION_API_URL, _API_KEY and _MODEL")
            client = OpenAICompatibleVisionClient(
                api_url=api_url, api_key=api_key, model=model,
                timeout_sec=config.api_timeout_sec,
                max_image_bytes=config.max_api_image_bytes,
            )
            worker = VisionApiWorker(
                store, client, daily_limit=config.daily_api_limit,
                max_attempts=config.max_attempts,
            )
            if args.mode == "api-once":
                print("[VISION API]", worker.run_once())
                return 0
            while True:
                print("[VISION API]", worker.run_once())
                time.sleep(10)
    except KeyboardInterrupt:
        return 0
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
