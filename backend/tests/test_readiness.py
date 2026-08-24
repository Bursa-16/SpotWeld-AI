"""Stage 2A tests: threshold-free readiness aggregation (document 112 §4).

Synthetic condition codes only; no machine limits or welding thresholds.
"""

from __future__ import annotations

import pytest

from app.domain.readiness import (
    CheckCondition,
    ReadinessContribution,
    ReadinessState,
    aggregate_readiness as _aggregate_readiness,
)


def aggregate_readiness(*args, **kwargs):  # noqa: ANN002, ANN003, ANN201
    """Test helper that affirmatively supplies successful persistence."""
    kwargs.setdefault("persistence_ok", True)
    return _aggregate_readiness(*args, **kwargs)


def _contribution(
    check_id: str,
    condition: CheckCondition,
    *,
    required: bool = True,
    applicable: bool = True,
) -> ReadinessContribution:
    return ReadinessContribution(
        check_id=check_id,
        condition=condition,
        required=required,
        applicable=applicable,
    )


def test_zero_rules_and_no_contributions_is_not_evaluated() -> None:
    result = aggregate_readiness([], validated_applicable_rule_count=0)
    assert result.state is ReadinessState.NOT_EVALUATED
    assert result.prerequisites[0][1] is False


def test_positive_declared_count_without_contributions_fails_closed() -> None:
    result = aggregate_readiness([], validated_applicable_rule_count=1)
    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED
    assert any("count inconsistent" in reason for reason in result.reasons)


def test_declared_count_must_match_distinct_contribution_evidence() -> None:
    result = aggregate_readiness(
        [_contribution("CHECK_1", CheckCondition.PASSED)],
        validated_applicable_rule_count=2,
    )
    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED
    assert result.state is not ReadinessState.READY


def test_boolean_declared_count_is_not_accepted_as_integer_proof() -> None:
    result = aggregate_readiness(
        [_contribution("CHECK_1", CheckCondition.PASSED)],
        validated_applicable_rule_count=True,
    )
    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED


def test_duplicate_contribution_identity_cannot_satisfy_ready_proof() -> None:
    duplicate = _contribution("CHECK_1", CheckCondition.PASSED)
    result = aggregate_readiness(
        [duplicate, duplicate], validated_applicable_rule_count=2
    )
    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED
    assert any("duplicate" in reason for reason in result.reasons)


def test_unresolved_with_positive_count_never_becomes_ready() -> None:
    result = aggregate_readiness(
        [_contribution("CHECK_1", CheckCondition.UNRESOLVED)],
        validated_applicable_rule_count=1,
    )
    assert result.state is ReadinessState.ENGINEERING_REVIEW_REQUIRED
    assert result.state is not ReadinessState.READY


def test_all_passing_checks_with_validated_rule_is_ready() -> None:
    contributions = [
        _contribution("CHECK_1", CheckCondition.PASSED),
        _contribution("CHECK_2", CheckCondition.PASSED),
    ]
    result = aggregate_readiness(contributions, validated_applicable_rule_count=2)
    assert result.state is ReadinessState.READY
    assert all(satisfied for _, satisfied in result.prerequisites)


def test_single_required_failure_is_not_ready() -> None:
    contributions = [
        _contribution("GOOD_CHECK", CheckCondition.PASSED),
        _contribution("BAD_CHECK", CheckCondition.FAILED),
    ]
    result = aggregate_readiness(contributions, validated_applicable_rule_count=2)
    assert result.state is ReadinessState.NOT_READY
    assert any("BAD_CHECK" in reason for reason in result.reasons)


def test_not_ready_retains_secondary_unresolved_blocker() -> None:
    contributions = [
        _contribution("FAILING", CheckCondition.FAILED),
        _contribution("UNCERTAIN", CheckCondition.UNRESOLVED),
    ]
    result = aggregate_readiness(contributions, validated_applicable_rule_count=2)
    assert result.state is ReadinessState.NOT_READY
    joined = "\n".join(result.reasons)
    assert "FAILING" in joined and "UNCERTAIN" in joined


@pytest.mark.parametrize(
    "condition",
    [
        CheckCondition.UNRESOLVED,
        CheckCondition.EVIDENCE_UNAVAILABLE,
        CheckCondition.RULE_CONFLICT,
        CheckCondition.NOT_APPLICABLE_VERSION,
    ],
)
def test_engineering_blockers_aggregate_to_engineering_review(
    condition: CheckCondition,
) -> None:
    result = aggregate_readiness(
        [_contribution("CHECK_X", condition)], validated_applicable_rule_count=1
    )
    assert result.state is ReadinessState.ENGINEERING_REVIEW_REQUIRED


@pytest.mark.parametrize(
    "condition",
    [
        CheckCondition.DATA_INSUFFICIENT,
        CheckCondition.OBSERVATION_MISSING,
        CheckCondition.CONTEXT_INSUFFICIENT,
    ],
)
def test_manual_blockers_aggregate_to_manual_review(
    condition: CheckCondition,
) -> None:
    result = aggregate_readiness(
        [_contribution("CHECK_Y", condition)], validated_applicable_rule_count=1
    )
    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED


def test_manual_judgment_flag_blocks_ready() -> None:
    result = aggregate_readiness(
        [_contribution("OK", CheckCondition.PASSED)],
        validated_applicable_rule_count=1,
        manual_judgment_flagged=True,
    )
    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED


def test_failure_outranks_engineering_review_outranks_manual_review() -> None:
    base = [
        _contribution("C_FAIL", CheckCondition.FAILED),
        _contribution("C_UNRES", CheckCondition.UNRESOLVED),
        _contribution("C_DATA", CheckCondition.DATA_INSUFFICIENT),
    ]
    assert (
        aggregate_readiness(base, validated_applicable_rule_count=3).state
        is ReadinessState.NOT_READY
    )
    without_fail = [
        item for item in base if item.condition is not CheckCondition.FAILED
    ]
    assert (
        aggregate_readiness(without_fail, validated_applicable_rule_count=2).state
        is ReadinessState.ENGINEERING_REVIEW_REQUIRED
    )
    without_unres = [
        item
        for item in without_fail
        if item.condition is not CheckCondition.UNRESOLVED
    ]
    assert (
        aggregate_readiness(without_unres, validated_applicable_rule_count=1).state
        is ReadinessState.MANUAL_REVIEW_REQUIRED
    )


def test_optional_check_does_not_block_ready() -> None:
    contributions = [
        _contribution("REQUIRED_OK", CheckCondition.PASSED),
        _contribution("OPTIONAL_FAIL", CheckCondition.FAILED, required=False),
    ]
    result = aggregate_readiness(contributions, validated_applicable_rule_count=2)
    assert result.state is ReadinessState.READY


def test_non_applicable_check_does_not_block_ready() -> None:
    contributions = [
        _contribution("REQUIRED_OK", CheckCondition.PASSED),
        _contribution(
            "OTHER_CONTEXT_FAIL", CheckCondition.FAILED, applicable=False
        ),
    ]
    result = aggregate_readiness(contributions, validated_applicable_rule_count=1)
    assert result.state is ReadinessState.READY


def test_pass_evidence_with_zero_declared_validated_rules_requires_review() -> None:
    contributions = [_contribution("CHECK_OK", CheckCondition.PASSED)]
    result = aggregate_readiness(contributions, validated_applicable_rule_count=0)
    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED
    assert any("count inconsistent" in reason for reason in result.reasons)


def test_not_evaluated_condition_contributes_not_evaluated_state() -> None:
    result = aggregate_readiness(
        [_contribution("UNBACKED_CHECK", CheckCondition.NOT_EVALUATED)],
        validated_applicable_rule_count=0,
    )
    assert result.state is ReadinessState.NOT_EVALUATED


def test_prerequisites_report_six_entries_in_documented_order() -> None:
    result = aggregate_readiness([], validated_applicable_rule_count=0)
    assert [name for name, _ in result.prerequisites] == [
        "at least one applicable validated engineering rule exists",
        "every required applicable SOURCE_BACKED rule passes",
        "all required input data is available and valid",
        "no required applicable UNRESOLVED rule exists",
        "no unresolved conflict exists",
        "no manual-review condition exists",
    ]


def test_aggregation_is_deterministic_regardless_of_input_order() -> None:
    ordered = [
        _contribution("A_CHECK", CheckCondition.PASSED),
        _contribution("B_CHECK", CheckCondition.UNRESOLVED),
        _contribution("C_CHECK", CheckCondition.DATA_INSUFFICIENT),
    ]
    shuffled = list(reversed(ordered))
    first = aggregate_readiness(ordered, validated_applicable_rule_count=3)
    second = aggregate_readiness(shuffled, validated_applicable_rule_count=3)
    assert first.state is second.state
    assert first.reasons == second.reasons


def _all_passing() -> list[ReadinessContribution]:
    return [
        _contribution("CHECK_1", CheckCondition.PASSED),
        _contribution("CHECK_2", CheckCondition.PASSED),
    ]


def test_ready_is_authoritative_when_persistence_ok() -> None:
    result = _aggregate_readiness(
        _all_passing(),
        validated_applicable_rule_count=2,
        persistence_ok=True,
    )
    assert result.state is ReadinessState.READY
    assert result.authoritative is True


def test_omitted_persistence_proof_is_rejected_by_contract() -> None:
    with pytest.raises(TypeError, match="persistence_ok"):
        _aggregate_readiness(
            _all_passing(), validated_applicable_rule_count=2
        )


def test_ready_refused_when_persistence_unavailable() -> None:
    result = aggregate_readiness(
        _all_passing(),
        validated_applicable_rule_count=2,
        persistence_ok=False,
    )
    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED
    assert result.authoritative is False
    assert "READY refused" in result.reasons[0]
    assert "non-authoritative" in result.reasons[0]
    # READY is never published non-authoritatively.
    assert result.state is not ReadinessState.READY


def test_non_boolean_persistence_value_is_not_affirmative_proof() -> None:
    result = _aggregate_readiness(
        _all_passing(),
        validated_applicable_rule_count=2,
        persistence_ok="yes",
    )
    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED
    assert result.authoritative is False


def test_engineering_review_state_survives_persistence_failure() -> None:
    contributions = [
        _contribution("CHECK_1", CheckCondition.PASSED),
        _contribution("CHECK_2", CheckCondition.UNRESOLVED),
    ]
    result = aggregate_readiness(
        contributions,
        validated_applicable_rule_count=2,
        persistence_ok=False,
    )
    # Precedence bucket 2 is preserved verbatim for traceability.
    assert result.state is ReadinessState.ENGINEERING_REVIEW_REQUIRED
    assert result.authoritative is False


def test_failed_check_stays_not_ready_when_persistence_unavailable() -> None:
    contributions = [
        _contribution("GOOD_CHECK", CheckCondition.PASSED),
        _contribution("BAD_CHECK", CheckCondition.FAILED),
    ]
    result = aggregate_readiness(
        contributions,
        validated_applicable_rule_count=2,
        persistence_ok=False,
    )
    assert result.state is ReadinessState.NOT_READY
    assert result.authoritative is False


def test_non_authoritative_result_keeps_prerequisites_inspectable() -> None:
    result = aggregate_readiness(
        _all_passing(),
        validated_applicable_rule_count=2,
        persistence_ok=False,
    )
    # The engineering checklist stays untouched so the would-be READY
    # condition remains fully inspectable even though it is not published.
    assert result.state is not ReadinessState.READY
    assert result.prerequisites
    assert all(satisfied for _, satisfied in result.prerequisites)
    assert len(result.prerequisites) == 6
