"""Strict validation for multimodal plant observations."""

from __future__ import annotations

from copy import deepcopy
import re
import time
from typing import Any, Mapping


PLANTS = {"生菜", "小白菜", "菠菜", "韭菜", "番茄", "辣椒", "黄瓜", "茄子", "unknown"}
MATCH_VALUES = {"match", "mismatch", "unknown"}
CERTAINTY_VALUES = {"high", "medium", "low", "unknown"}
VIGOR_VALUES = {"strong", "normal", "weak", "unknown"}
LEAF_COLOR_VALUES = {"green", "yellowing", "pale", "mixed", "unknown"}
STAGE_VALUES = {"seedling", "vegetative", "flowering", "fruiting", "harvesting", "unknown"}
VISION_STATUS_VALUES = {
    "WAITING_TELEMETRY", "WAITING_INTERVAL", "WAITING_LIGHT", "READY",
    "QUEUED_FOR_ANALYSIS", "CAPTURE_ERROR", "QUALITY_REJECTED", "API_ERROR",
}
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SchemaError(ValueError):
    pass


def _short_text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


def _enum(value: Any, allowed: set[str], default: str = "unknown") -> str:
    text = str(value or default)
    return text if text in allowed else default


def _text_list(value: Any, *, limit: int = 8, item_limit: int = 120) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_short_text(item, item_limit) for item in value if isinstance(item, str)][:limit]


def validate_analysis(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise SchemaError("analysis must be an object")
    return {
        "plant": _enum(data.get("plant"), PLANTS),
        "plant_match": _enum(data.get("plant_match"), MATCH_VALUES),
        "certainty": _enum(data.get("certainty"), CERTAINTY_VALUES),
        "visible_stage": _enum(data.get("visible_stage"), STAGE_VALUES),
        "vigor": _enum(data.get("vigor"), VIGOR_VALUES),
        "leaf_color": _enum(data.get("leaf_color"), LEAF_COLOR_VALUES),
        "visible_findings": _text_list(data.get("visible_findings")),
        "possible_issues": _text_list(data.get("possible_issues")),
        "breeding_observation": _short_text(data.get("breeding_observation"), 240),
        "needs_human_review": bool(data.get("needs_human_review", False)),
    }


def validate_capture_analysis(data: Mapping[str, Any], expected_pots: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise SchemaError("response must be an object")
    observations = data.get("observations")
    if not isinstance(observations, list) or not observations:
        raise SchemaError("observations must be a non-empty list")
    normalized = []
    seen = set()
    for raw in observations[:8]:
        if not isinstance(raw, Mapping):
            raise SchemaError("each observation must be an object")
        pot_id = _short_text(raw.get("pot_id"), 32)
        if not pot_id or pot_id in seen:
            raise SchemaError("pot_id must be present and unique")
        seen.add(pot_id)
        normalized.append({
            "pot_id": pot_id,
            "material_id": _short_text(raw.get("material_id"), 64),
            "is_control": bool(raw.get("is_control", False)),
            "roi_id": _short_text(raw.get("roi_id", pot_id), 32),
            "analysis": validate_analysis(raw.get("analysis", {})),
        })
    if expected_pots is not None and seen != set(expected_pots):
        raise SchemaError("response pot set does not match the experiment")
    result = {
        "schema": "vision.capture.v1",
        "capture_id": _short_text(data.get("capture_id"), 64),
        "observations": normalized,
    }
    if not result["capture_id"]:
        raise SchemaError("capture_id is required")
    model = data.get("model", {})
    result["model"] = deepcopy(model) if isinstance(model, Mapping) else {}
    return result


def _number(value: Any, *, minimum: float, maximum: float, name: str,
            default: float | None = None) -> float | None:
    if value is None and default is not None:
        return default
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SchemaError(f"{name} must be numeric")
    if not minimum <= number <= maximum:
        raise SchemaError(f"{name} is out of range")
    return number


def validate_cloud_status(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise SchemaError("vision status must be an object")
    state = str(data.get("state", ""))
    if state not in VISION_STATUS_VALUES:
        raise SchemaError("invalid vision status state")
    return {
        "schema": "vision.status.v1",
        "state": state,
        "reason": _short_text(data.get("reason"), 240),
        "current_light": _number(
            data.get("current_light"), minimum=0, maximum=100, name="current_light"),
        "required_light": _number(
            data.get("required_light"), minimum=0, maximum=100, name="required_light"),
        "next_eligible_at": _number(
            data.get("next_eligible_at"), minimum=0, maximum=4102444800,
            name="next_eligible_at"),
        "reported_at": _number(
            data.get("reported_at", time.time()), minimum=1577836800,
            maximum=time.time() + 300, name="reported_at"),
    }


def validate_cloud_event(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping) or data.get("schema") != "vision.event.v1":
        raise SchemaError("vision event schema must be vision.event.v1")
    event_id = str(data.get("event_id", ""))
    if not _EVENT_ID_RE.fullmatch(event_id):
        raise SchemaError("invalid event_id")
    captured_at = _number(
        data.get("captured_at"), minimum=1577836800, maximum=time.time() + 300,
        name="captured_at")
    image = data.get("image")
    if not isinstance(image, Mapping):
        raise SchemaError("image metadata is required")
    sha256 = str(image.get("sha256", "")).lower()
    if not _SHA256_RE.fullmatch(sha256):
        raise SchemaError("invalid image sha256")
    image_bytes = int(_number(
        image.get("bytes"), minimum=4, maximum=20 * 1024 * 1024,
        name="image bytes"))

    raw_observations = data.get("observations")
    if not isinstance(raw_observations, list) or not 1 <= len(raw_observations) <= 8:
        raise SchemaError("observations must contain 1-8 items")
    observations = []
    seen = set()
    for raw in raw_observations:
        if not isinstance(raw, Mapping):
            raise SchemaError("each observation must be an object")
        pot_id = _short_text(raw.get("pot_id"), 32)
        if not pot_id or pot_id in seen:
            raise SchemaError("pot_id must be present and unique")
        seen.add(pot_id)
        quality = raw.get("quality") if isinstance(raw.get("quality"), Mapping) else {}
        observations.append({
            "pot_id": pot_id,
            "material_id": _short_text(raw.get("material_id"), 64),
            "is_control": bool(raw.get("is_control", False)),
            "roi_id": _short_text(raw.get("roi_id", pot_id), 32),
            "quality": {
                "accepted": bool(quality.get("accepted", False)),
                "blur_score": _number(
                    quality.get("blur_score"), minimum=0, maximum=1_000_000,
                    name="blur_score", default=0),
                "brightness": _number(
                    quality.get("brightness"), minimum=0, maximum=1,
                    name="brightness", default=0),
                "reasons": _text_list(quality.get("reasons"), limit=6, item_limit=40),
            },
            "analysis": validate_analysis(raw.get("analysis", {})),
        })
    if sum(item["is_control"] for item in observations) != 1:
        raise SchemaError("exactly one control observation is required")

    context = data.get("context") if isinstance(data.get("context"), Mapping) else {}
    day = context.get("day")
    if day is not None:
        day = int(_number(day, minimum=1, maximum=999, name="day"))
    model = data.get("model") if isinstance(data.get("model"), Mapping) else {}
    return {
        "schema": "vision.event.v1",
        "event_id": event_id,
        "capture_id": event_id,
        "captured_at": captured_at,
        "cycle_id": _short_text(data.get("cycle_id"), 64) or "unassigned",
        "current_light": _number(
            data.get("current_light"), minimum=0, maximum=100, name="current_light"),
        "required_light": _number(
            data.get("required_light"), minimum=0, maximum=100, name="required_light"),
        "context": {
            "day": day,
            "stage": _enum(context.get("stage"), STAGE_VALUES),
            "experiment_id": _short_text(context.get("experiment_id"), 48),
        },
        "observations": observations,
        "model": {
            "name": _short_text(model.get("name", model.get("model")), 80),
            "prompt_version": _short_text(model.get("prompt_version"), 40),
        },
        "image": {"sha256": sha256, "bytes": image_bytes},
    }
