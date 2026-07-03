"""Strict validation for multimodal plant observations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


PLANTS = {"生菜", "小白菜", "菠菜", "韭菜", "番茄", "辣椒", "黄瓜", "茄子", "unknown"}
MATCH_VALUES = {"match", "mismatch", "unknown"}
CERTAINTY_VALUES = {"high", "medium", "low", "unknown"}
VIGOR_VALUES = {"strong", "normal", "weak", "unknown"}
LEAF_COLOR_VALUES = {"green", "yellowing", "pale", "mixed", "unknown"}
STAGE_VALUES = {"seedling", "vegetative", "flowering", "fruiting", "harvesting", "unknown"}


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
