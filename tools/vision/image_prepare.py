"""Fixed-ROI cropping and JPEG preparation; deliberately contains no ML."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def prepare_rois(source: str | Path, output_dir: str | Path,
                 rois: list[Mapping[str, Any]], *, max_edge: int = 1280,
                 jpeg_quality: int = 85) -> list[dict[str, Any]]:
    try:
        import cv2  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("ROI preparation requires python3-opencv") from exc
    image = cv2.imread(str(source))
    if image is None:
        raise ValueError(f"cannot read image: {source}")
    height, width = image.shape[:2]
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    prepared = []
    for roi in rois:
        x, y = int(roi["x"]), int(roi["y"])
        w, h = int(roi["width"]), int(roi["height"])
        if x < 0 or y < 0 or w < 1 or h < 1 or x + w > width or y + h > height:
            raise ValueError(f'invalid ROI {roi.get("roi_id", roi.get("pot_id", "?"))}')
        crop = image[y:y + h, x:x + w]
        longest = max(crop.shape[:2])
        if longest > max_edge:
            scale = max_edge / longest
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        path = target_dir / f'{roi.get("roi_id", roi["pot_id"])}.jpg'
        if not cv2.imwrite(str(path), crop, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]):
            raise OSError(f"failed to write {path}")
        item = dict(roi)
        item["image_path"] = str(path)
        prepared.append(item)
    return prepared
