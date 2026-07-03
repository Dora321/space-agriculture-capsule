"""Versioned 100-point early-phenotype rubric."""

from __future__ import annotations

from typing import Mapping


RUBRIC_VERSION = "early-phenotype-v1"
PHENOTYPE_WEIGHTS = {
    "vigor": 30,
    "morphology": 20,
    "leaf_health": 15,
    "visible_resilience": 15,
    "consistency": 15,
    # Shared pump/light and one soil sensor cannot support per-pot efficiency claims.
    "resource_response_reference": 5,
}


def score_phenotype(metrics: Mapping[str, float]) -> dict:
    """Combine normalized 0..100 axis scores without inventing missing axes."""
    missing = set(PHENOTYPE_WEIGHTS) - set(metrics)
    if missing:
        raise ValueError("missing phenotype axes: " + ", ".join(sorted(missing)))
    normalized = {}
    total = 0.0
    for key, weight in PHENOTYPE_WEIGHTS.items():
        value = float(metrics[key])
        if not 0 <= value <= 100:
            raise ValueError(f"{key} must be between 0 and 100")
        normalized[key] = value
        total += value * weight / 100
    return {
        "rubric_version": RUBRIC_VERSION,
        "score": round(total, 2),
        "axes": normalized,
        "weights": dict(PHENOTYPE_WEIGHTS),
    }
