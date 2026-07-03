import pytest

from tools.screening import PHENOTYPE_WEIGHTS, compare_candidate_to_control, score_phenotype


def test_rubric_weights_total_100_and_resource_reference_is_only_5_points():
    assert sum(PHENOTYPE_WEIGHTS.values()) == 100
    assert PHENOTYPE_WEIGHTS["resource_response_reference"] == 5
    result = score_phenotype({name: 80 for name in PHENOTYPE_WEIGHTS})
    assert result["score"] == 80


def test_rubric_rejects_missing_or_out_of_range_axis():
    with pytest.raises(ValueError):
        score_phenotype({})
    values = {name: 80 for name in PHENOTYPE_WEIGHTS}
    values["vigor"] = 101
    with pytest.raises(ValueError):
        score_phenotype(values)


def test_comparison_pairs_independent_cycles_not_photo_count():
    candidate = [{"cycle_id": f"c{i}", "score": 80 + i} for i in range(1, 6)]
    control = [{"cycle_id": f"c{i}", "score": 70 + i} for i in range(1, 6)]
    result = compare_candidate_to_control(candidate, control, data_coverage=.9, ai_human_agreement=.85)
    assert result["independent_cycles"] == 5
    assert result["delta_control_median"] == 10
    assert result["evidence_grade"] == "A"


def test_three_cycles_can_only_reach_preliminary_grade_b():
    candidate = [{"cycle_id": x, "score": 80} for x in "abc"]
    control = [{"cycle_id": x, "score": 70} for x in "abc"]
    result = compare_candidate_to_control(candidate, control, data_coverage=.8, ai_human_agreement=.75)
    assert result["evidence_grade"] == "B"


def test_no_paired_control_is_insufficient_data():
    result = compare_candidate_to_control(
        [{"cycle_id": "candidate-only", "score": 90}],
        [{"cycle_id": "another-cycle", "score": 70}],
    )
    assert result["evidence_grade"] == "insufficient_data"
    assert result["independent_cycles"] == 0
