"""Camera Module 3 adapter using Raspberry Pi's Picamera2 stack."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


class CameraModule3:
    def __init__(self, *, size: tuple[int, int] = (2304, 1296), autofocus: bool = True,
                 warmup_sec: float = 2.0, picamera: Any = None):
        if picamera is None:
            try:
                from picamera2 import Picamera2  # type: ignore
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("Camera Module 3 requires python3-picamera2") from exc
            picamera = Picamera2()
        self.camera = picamera
        self.warmup_sec = warmup_sec
        config = self.camera.create_still_configuration(main={"size": size, "format": "RGB888"})
        self.camera.configure(config)
        if autofocus:
            try:
                self.camera.set_controls({"AfMode": 2})
            except (AttributeError, RuntimeError):
                pass
        self.camera.start()
        if warmup_sec:
            time.sleep(warmup_sec)

    def capture(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.camera.capture_file(str(target))
        return target

    def close(self) -> None:
        self.camera.stop()

    def __enter__(self) -> "CameraModule3":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
