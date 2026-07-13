"""Server-side validation and recomputation for phenotype screening uploads."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .aggregator import compare_candidate_to_control
from .rubric import PHENOTYPE_WEIGHTS, score_phenotype


_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_STAGES = {"seedling", "vegetative", "flowering", "fruiting", "harvesting", "unknown"}
_RECOMMENDATION = {
    "A": "strong_rescreen_candidate",
    "B": "rescreen_candidate",
    "C": "continue_observation",
    "D": "do_not_prioritize",
    "insufficient_data": "insufficient_data",
}


def _identifier(value: Any, name: str) -> str:
    text = str(value or "")
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"invalid {name}")
    return text


def _ratio(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric")
    if not 0 <= number <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _cycles(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError(f"{name} must contain 1-20 cycles")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{name} items must be objects")
        cycle_id = _identifier(item.get("cycle_id"), "cycle_id")
        if cycle_id in seen:
            raise ValueError(f"duplicate cycle_id in {name}")
        seen.add(cycle_id)
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            raise ValueError("cycle score must be numeric")
        if not 0 <= score <= 100:
            raise ValueError("cycle score must be between 0 and 100")
        result.append({"cycle_id": cycle_id, "score": score})
    return result


def validate_screening_submission(data: Mapping[str, Any]) -> dict[str, Any]:
    """Whitelist input and recompute every scientific derived field."""
    if not isinstance(data, Mapping) or data.get("schema") != "screening.input.v1":
        raise ValueError("screening schema must be screening.input.v1")
    material_id = _identifier(data.get("material_id"), "material_id")
    control_material_id = _identifier(data.get("control_material_id"), "control_material_id")
    cycle_group_id = _identifier(data.get("cycle_group_id"), "cycle_group_id")
    candidate = _cycles(data.get("candidate_cycles"), "candidate_cycles")
    control = _cycles(data.get("control_cycles"), "control_cycles")
    coverage = _ratio(data.get("data_coverage", 1), "data_coverage")
    agreement = _ratio(data.get("ai_human_agreement", 1), "ai_human_agreement")
    comparison = compare_candidate_to_control(
        candidate, control, data_coverage=coverage, ai_human_agreement=agreement)

    raw_versions = data.get("versions")
    versions = raw_versions if isinstance(raw_versions, Mapping) else {}
    raw_limitations = data.get("limitations")
    limitations = raw_limitations if isinstance(raw_limitations, list) else []
    result = {
        **comparison,
        "schema": "phenotype_screen.v1",
        "result_id": _identifier(data.get("result_id", material_id + "-latest"), "result_id"),
        "material_id": material_id,
        "control_material_id": control_material_id,
        "cycle_group_id": cycle_group_id,
        "crop": str(data.get("crop", ""))[:24],
        "stage": str(data.get("stage", "unknown")),
        "status": "screened" if comparison["independent_cycles"] else "insufficient_data",
        "delta_control": {
            "median": comparison.get("delta_control_median"),
            "iqr": comparison.get("delta_control_iqr", []),
            "better_ratio": comparison.get("better_than_control_ratio", 0),
            "total_cycles": comparison["independent_cycles"],
        },
        "recommendation": _RECOMMENDATION[comparison["evidence_grade"]],
        "summary": str(data.get("summary", ""))[:240],
        "limitations": [str(x)[:120] for x in limitations if isinstance(x, str)][:8],
        "versions": {
            str(k)[:32]: str(v)[:80]
            for k, v in list(versions.items())[:12]
            if isinstance(k, str) and isinstance(v, (str, int, float))
        },
    }
    if result["stage"] not in _STAGES:
        result["stage"] = "unknown"

    dimensions = data.get("dimensions")
    if dimensions is not None:
        if not isinstance(dimensions, Mapping):
            raise ValueError("dimensions must be an object")
        scores = {}
        for key in PHENOTYPE_WEIGHTS:
            raw = dimensions.get(key)
            if isinstance(raw, Mapping):
                raw = raw.get("score")
            scores[key] = raw
        phenotype = score_phenotype(scores)
        result["dimensions"] = {
            key: {"score": phenotype["axes"][key], "weight": PHENOTYPE_WEIGHTS[key]}
            for key in PHENOTYPE_WEIGHTS
        }
        result["phenotype_score"] = phenotype["score"]
        result["rubric_version"] = phenotype["rubric_version"]
    return result
