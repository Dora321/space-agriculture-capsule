"""Deterministic image usability checks; no plant inference is performed."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class QualityResult:
    accepted: bool
    blur_score: float
    brightness: float
    clipped_fraction: float
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        return value


def evaluate_metrics(*, blur_score: float, brightness: float,
                     clipped_fraction: float = 0.0, occluded: bool = False,
                     min_blur: float = 80.0, min_brightness: float = 0.15,
                     max_brightness: float = 0.90,
                     max_clipped_fraction: float = 0.25) -> QualityResult:
    reasons = []
    if blur_score < min_blur:
        reasons.append("blurred")
    if brightness < min_brightness:
        reasons.append("underexposed")
    if brightness > max_brightness:
        reasons.append("overexposed")
    if clipped_fraction > max_clipped_fraction:
        reasons.append("excessive_clipping")
    if occluded:
        reasons.append("occluded")
    return QualityResult(not reasons, float(blur_score), float(brightness),
                         float(clipped_fraction), tuple(reasons))


def inspect_image(path: str | Path, **thresholds) -> QualityResult:
    """Inspect a JPEG with OpenCV when deployed on the Pi.

    OpenCV is imported lazily so unit tests and non-camera tools remain usable
    on machines where the Raspberry Pi image stack is not installed.
    """
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised on the Pi
        raise RuntimeError("image quality checks require python3-opencv and numpy") from exc

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"cannot read image: {path}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean() / 255.0)
    clipped = float(np.count_nonzero((gray <= 2) | (gray >= 253)) / gray.size)
    return evaluate_metrics(blur_score=blur, brightness=brightness,
                            clipped_fraction=clipped, **thresholds)
