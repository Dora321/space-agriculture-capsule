"""Control-relative evidence aggregation; one planting cycle equals one replicate."""

from __future__ import annotations

from statistics import median
from typing import Any, Iterable, Mapping


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    amount = position - lower
    return ordered[lower] * (1 - amount) + ordered[upper] * amount


def _grade(n: int, delta_median: float, better_ratio: float,
           coverage: float, agreement: float) -> tuple[str, str]:
    if coverage < 0.6:
        return "insufficient_data", "data coverage is below 60%"
    if delta_median <= 0 or better_ratio < 0.5:
        return "D", "candidate has not shown a stable advantage over control"
    if n >= 5 and better_ratio >= 0.8 and coverage >= 0.85 and agreement >= 0.8:
        return "A", "advantage repeated across at least five independent cycles"
    if n >= 3 and better_ratio >= 2 / 3 and coverage >= 0.75 and agreement >= 0.7:
        return "B", "preliminary advantage repeated across at least three cycles"
    return "C", "promising signal; more independent planting cycles are required"


def compare_candidate_to_control(
    candidate: Iterable[Mapping[str, Any]],
    control: Iterable[Mapping[str, Any]], *,
    data_coverage: float = 1.0,
    ai_human_agreement: float = 1.0,
) -> dict[str, Any]:
    """Pair scores by cycle_id; repeated photos within a cycle never increase n."""
    candidate_by_cycle = {str(x["cycle_id"]): float(x["score"]) for x in candidate}
    control_by_cycle = {str(x["cycle_id"]): float(x["score"]) for x in control}
    cycle_ids = sorted(candidate_by_cycle.keys() & control_by_cycle.keys())
    if not cycle_ids:
        return {
            "schema": "screening.result.v1", "evidence_grade": "insufficient_data",
            "reason": "no candidate/control observations share an independent cycle",
            "independent_cycles": 0, "deltas": [],
        }
    deltas = [candidate_by_cycle[x] - control_by_cycle[x] for x in cycle_ids]
    center = float(median(deltas))
    q1, q3 = _percentile(deltas, 0.25), _percentile(deltas, 0.75)
    better_ratio = sum(value > 0 for value in deltas) / len(deltas)
    grade, reason = _grade(
        len(deltas), center, better_ratio, float(data_coverage), float(ai_human_agreement)
    )
    return {
        "schema": "screening.result.v1",
        "evidence_grade": grade,
        "reason": reason,
        "independent_cycles": len(deltas),
        "cycle_ids": cycle_ids,
        "delta_control_median": round(center, 2),
        "delta_control_iqr": [round(q1, 2), round(q3, 2)],
        "better_than_control_ratio": round(better_ratio, 3),
        "data_coverage": round(float(data_coverage), 3),
        "ai_human_agreement": round(float(ai_human_agreement), 3),
        "deltas": [round(value, 2) for value in deltas],
        "scientific_note": "n counts independent planting cycles, not two-hour photographs",
    }
