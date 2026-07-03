"""Environment-backed configuration for the vision services."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class VisionConfig:
    data_dir: Path = Path("/var/lib/spacefarm/vision")
    capture_interval_sec: int = 7200
    schedule_check_sec: int = 600
    capture_light_min: int = 50
    telemetry_stale_sec: int = 120
    result_stale_sec: int = 10800
    daily_api_limit: int = 12
    api_timeout_sec: int = 30
    max_api_image_bytes: int = 500_000
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.capture_interval_sec < 1:
            raise ValueError("capture_interval_sec must be positive")
        if self.schedule_check_sec < 1:
            raise ValueError("schedule_check_sec must be positive")
        if not 0 <= self.capture_light_min <= 100:
            raise ValueError("capture_light_min must be between 0 and 100")
        if self.telemetry_stale_sec < 1 or self.result_stale_sec < 1:
            raise ValueError("stale timeouts must be positive")
        if self.daily_api_limit < 0:
            raise ValueError("daily_api_limit cannot be negative")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")

    @classmethod
    def from_env(cls) -> "VisionConfig":
        return cls(
            data_dir=Path(os.getenv("SPACEFARM_VISION_DATA_DIR", "/var/lib/spacefarm/vision")),
            capture_interval_sec=_env_int("SPACEFARM_VISION_INTERVAL_SEC", 7200),
            schedule_check_sec=_env_int("SPACEFARM_VISION_CHECK_SEC", 600),
            capture_light_min=_env_int("SPACEFARM_VISION_CAPTURE_LIGHT_MIN", 50),
            telemetry_stale_sec=_env_int("SPACEFARM_VISION_TELEMETRY_STALE_SEC", 120),
            result_stale_sec=_env_int("SPACEFARM_VISION_RESULT_STALE_SEC", 10800),
            daily_api_limit=_env_int("SPACEFARM_VISION_DAILY_LIMIT", 12),
            api_timeout_sec=_env_int("SPACEFARM_VISION_TIMEOUT_SEC", 30),
            max_api_image_bytes=_env_int("SPACEFARM_VISION_MAX_IMAGE_BYTES", 500_000),
            max_attempts=_env_int("SPACEFARM_VISION_MAX_ATTEMPTS", 3),
        )
