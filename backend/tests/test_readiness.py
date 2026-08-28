"""Stage 2A tests: threshold-free readiness aggregation (document 112 §4).

Synthetic condition codes only; no machine limits or welding thresholds.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.governance_types import EvidenceClass
from app.domain.readiness import (
    aggregate_readiness as _aggregate_readiness,
    CheckCondition,
    GovernedApplicabilityContext,
    GovernedMachineReadinessCheck,
    GovernedRuleEvaluationSnapshot,
    ReadinessContribution,
    ReadinessState,
    evaluate_machine_readiness,
)
from app.domain.rule_applicability import (
    GovernedApplicabilityCandidate,
    GovernedApplicabilityResolution,
    resolve_governed_applicability,
)
from app.domain.rule_evaluation import (
    Observation,
    RuleComparison,
    RuleRequirement,
    compare_rule,
)
from app.domain.rule_registry_types import RuleOperator
from app.domain.unit_policy import (
    ContentVersionMetadata,
    ConversionEntry,
    UnitPolicyCatalog,
)


def aggregate_readiness(*args, **kwargs):
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


_MRC_DECISION_TIME = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


def _mrc_context(
    customer: str | None = "customer-a",
    project: str | None = "project-a",
    site: str | None = "site-a",
    machine: str | None = "machine-a",
) -> GovernedApplicabilityContext:
    return GovernedApplicabilityContext(
        customer=customer,
        project=project,
        site=site,
        machine=machine,
    )


def _mrc_candidate(
    candidate_id: str,
    *,
    scope: dict[str, list[str]],
    rule_id: str | None = None,
    revision: str = "1.0",
    enabled: bool = True,
    active: bool = True,
    evidence_class: EvidenceClass = EvidenceClass.SOURCE_BACKED,
    effective_from: datetime | None = None,
    expires_at: datetime | None = None,
    suspended: bool = False,
    revoked: bool = False,
    superseded: bool = False,
    basis_valid: bool = True,
) -> GovernedApplicabilityCandidate:
    return GovernedApplicabilityCandidate(
        candidate_id=candidate_id,
        rule_id=rule_id or candidate_id,
        revision=revision,
        evidence_class=evidence_class,
        enabled=enabled,
        active=active,
        scope_snapshot=scope,
        effective_from=effective_from or (_MRC_DECISION_TIME - timedelta(days=1)),
        expires_at=expires_at,
        suspended=suspended,
        revoked=revoked,
        superseded=superseded,
        basis_valid=basis_valid,
    )


def _selected_applicability_result(
    *,
    rule_id: str = "RULE_A",
    revision: str = "1.0",
    context: GovernedApplicabilityContext | None = None,
    scope: dict[str, list[str]] | None = None,
    effective_from: datetime | None = None,
    expires_at: datetime | None = None,
    enabled: bool = True,
    active: bool = True,
    evidence_class: EvidenceClass = EvidenceClass.SOURCE_BACKED,
    suspended: bool = False,
    revoked: bool = False,
    superseded: bool = False,
    basis_valid: bool = True,
) -> tuple[GovernedApplicabilityContext, GovernedApplicabilityResolution]:
    context = context or _mrc_context()
    scope = scope or {
        "customer": [context.customer or ""],
        "project": [context.project or ""],
        "site": [context.site or ""],
        "machine": [context.machine or ""],
    }
    resolution = resolve_governed_applicability(
        context,
        _MRC_DECISION_TIME,
        [
            _mrc_candidate(
                "candidate-1",
                scope=scope,
                rule_id=rule_id,
                revision=revision,
                enabled=enabled,
                active=active,
                evidence_class=evidence_class,
                effective_from=effective_from,
                expires_at=expires_at,
                suspended=suspended,
                revoked=revoked,
                superseded=superseded,
                basis_valid=basis_valid,
            )
        ],
    )
    return context, resolution


def _requirement(
    *,
    rule_id: str = "RULE_A",
    revision: str = "1.0",
    parameter: str = "temperature",
    operator: RuleOperator = RuleOperator.MIN,
    unit: str = "synthetic_unit",
    min_value: float | None = 10.0,
    max_value: float | None = None,
    enabled: bool = True,
) -> RuleRequirement:
    return RuleRequirement(
        rule_id=rule_id,
        revision=revision,
        parameter=parameter,
        operator=operator,
        unit=unit,
        min_value=min_value,
        max_value=max_value,
        enabled=enabled,
    )


def _observation(
    value: float | None,
    *,
    parameter: str = "temperature",
    unit: str = "synthetic_unit",
) -> Observation | None:
    if value is None:
        return None
    return Observation(parameter=parameter, value=value, unit=unit)


def _comparison(
    *,
    rule_id: str = "RULE_A",
    revision: str = "1.0",
    context: GovernedApplicabilityContext | None = None,
    value: float | None = 11.0,
    unit: str = "synthetic_unit",
    operator: RuleOperator = RuleOperator.MIN,
    enabled: bool = True,
    unit_catalog: UnitPolicyCatalog | None = None,
) -> tuple[GovernedApplicabilityContext, RuleComparison]:
    context, applicability = _selected_applicability_result(
        rule_id=rule_id,
        revision=revision,
        context=context,
    )
    comparison = compare_rule(
        _requirement(
            rule_id=rule_id,
            revision=revision,
            operator=operator,
            enabled=enabled,
        ),
        _observation(value, unit=unit),
        applicability_result=applicability,
        unit_catalog=unit_catalog,
    )
    return context, comparison


def _snapshot(
    check_id: str,
    comparison: RuleComparison,
    *,
    revision_number: int = 1,
    evaluation_id: str | None = None,
) -> GovernedRuleEvaluationSnapshot:
    return GovernedRuleEvaluationSnapshot(
        evaluation_id=evaluation_id or f"{check_id}:evaluation",
        revision_number=revision_number,
        comparison=comparison,
    )


def _check(
    check_id: str,
    *,
    required: bool = True,
    evaluations: tuple[GovernedRuleEvaluationSnapshot, ...] = (),
    description: str | None = None,
) -> GovernedMachineReadinessCheck:
    return GovernedMachineReadinessCheck(
        check_id=check_id,
        required=required,
        evaluations=evaluations,
        description=description,
    )


def test_mrc_ready_when_every_required_check_satisfies_and_optional_is_nonblocking(
) -> None:
    version = ContentVersionMetadata(
        schema_version="1",
        canonicalization_version="1",
        hash_algorithm="sha256",
        content_hash="conversion-proof",
        software_version="test",
    )
    catalog = UnitPolicyCatalog(
        version=version,
        rounding_policy="NO_ROUNDING",
        conversions=(
            ConversionEntry(
                from_unit="source_unit",
                to_unit="synthetic_unit",
                factor=2.0,
            ),
        ),
    )
    context, satisfied = _comparison(
        value=5.0,
        unit="source_unit",
        unit_catalog=catalog,
    )
    _, optional_not_applicable = _comparison(
        rule_id="RULE_B",
        revision="1.0",
        enabled=False,
    )
    result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [
            _check("required-check", evaluations=(_snapshot("required-check", satisfied),)),
            _check(
                "optional-check",
                required=False,
                evaluations=(_snapshot("optional-check", optional_not_applicable),),
            ),
        ],
    )

    assert result.state is ReadinessState.READY
    assert result.validated_applicable_basis_count == 1
    assert [trace.check_id for trace in result.checks] == [
        "optional-check",
        "required-check",
    ]


def test_required_not_satisfied_forces_not_ready() -> None:
    context, not_satisfied = _comparison(value=5.0)
    result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [_check("required-check", evaluations=(_snapshot("required-check", not_satisfied),))],
    )

    assert result.state is ReadinessState.NOT_READY
    assert any("required-check" in reason for reason in result.reasons)


def test_unresolved_and_unit_mismatch_force_engineering_review() -> None:
    context, unresolved = _comparison(value=None)
    _, unit_mismatch = _comparison(unit="other_unit")

    unresolved_result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [_check("required-unresolved", evaluations=(_snapshot("required-unresolved", unresolved),))],
    )
    mismatch_result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [_check("required-unit-mismatch", evaluations=(_snapshot("required-unit-mismatch", unit_mismatch),))],
    )

    assert unresolved_result.state is ReadinessState.ENGINEERING_REVIEW_REQUIRED
    assert mismatch_result.state is ReadinessState.ENGINEERING_REVIEW_REQUIRED


def test_required_not_applicable_fails_closed() -> None:
    context, not_applicable = _comparison(enabled=False)
    result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [_check("required-not-applicable", evaluations=(_snapshot("required-not-applicable", not_applicable),))],
    )

    assert result.state is ReadinessState.ENGINEERING_REVIEW_REQUIRED
    assert result.checks[0].condition is CheckCondition.NOT_APPLICABLE_VERSION


def test_optional_not_applicable_does_not_block_readiness() -> None:
    context, satisfied = _comparison()
    _, optional_not_applicable = _comparison(rule_id="RULE_B", enabled=False)
    result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [
            _check("required-check", evaluations=(_snapshot("required-check", satisfied),)),
            _check(
                "optional-not-applicable",
                required=False,
                evaluations=(
                    _snapshot("optional-not-applicable", optional_not_applicable),
                ),
            ),
        ],
    )

    assert result.state is ReadinessState.READY
    assert result.checks[0].condition is CheckCondition.NOT_APPLICABLE_VERSION


def test_missing_all_basis_is_not_evaluated() -> None:
    result = evaluate_machine_readiness(
        _mrc_context(),
        _MRC_DECISION_TIME,
        [],
    )

    assert result.state is ReadinessState.NOT_EVALUATED
    assert result.validated_applicable_basis_count == 0


def test_missing_one_required_with_other_valid_basis_is_manual_review() -> None:
    context, satisfied = _comparison()
    result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [
            _check(
                "required-missing",
                evaluations=(),
            ),
            _check(
                "optional-satisfied",
                required=False,
                evaluations=(_snapshot("optional-satisfied", satisfied),),
            ),
        ],
    )

    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED
    assert any("required-missing" in reason for reason in result.reasons)


def test_stale_or_invalidated_basis_is_rejected() -> None:
    _, _satisfied = _comparison()
    invalid_context, invalid = _selected_applicability_result(basis_valid=False)
    invalid_comparison = compare_rule(
        _requirement(),
        _observation(11.0),
        applicability_result=invalid,
    )
    result = evaluate_machine_readiness(
        invalid_context,
        _MRC_DECISION_TIME,
        [
            _check(
                "required-invalid",
                evaluations=(_snapshot("required-invalid", invalid_comparison),),
            )
        ],
    )

    assert result.state is ReadinessState.ENGINEERING_REVIEW_REQUIRED


def test_conflicting_inputs_force_engineering_review() -> None:
    context, satisfied = _comparison()
    _, failed = _comparison(value=5.0)
    result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [
            _check(
                "conflicting-check",
                evaluations=(
                    _snapshot(
                        "conflicting-check",
                        satisfied,
                        evaluation_id="conflict-a",
                    ),
                    _snapshot(
                        "conflicting-check",
                        failed,
                        evaluation_id="conflict-b",
                    ),
                ),
            )
        ],
    )

    assert result.state is ReadinessState.ENGINEERING_REVIEW_REQUIRED
    assert result.checks[0].condition is CheckCondition.RULE_CONFLICT


def test_precedence_and_secondary_blockers_are_retained() -> None:
    context, failed = _comparison(value=5.0)
    _, unresolved = _comparison(value=None)
    result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [
            _check("required-failed", evaluations=(_snapshot("required-failed", failed),)),
            _check(
                "required-unresolved",
                evaluations=(_snapshot("required-unresolved", unresolved),),
            ),
            _check("required-missing", evaluations=()),
        ],
    )

    assert result.state is ReadinessState.NOT_READY
    assert "required-failed" in "\n".join(result.reasons)
    assert "required-unresolved" in "\n".join(result.reasons)
    assert "required-missing" in "\n".join(result.reasons)


def test_permutation_invariance_and_canonical_ordering() -> None:
    context, satisfied = _comparison()
    _, optional_unresolved = _comparison(value=None, rule_id="RULE_B")
    _, optional_not_applicable = _comparison(rule_id="RULE_C", enabled=False)

    ordered = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [
            _check("a-check", evaluations=(_snapshot("a-check", satisfied),)),
            _check(
                "b-check",
                required=False,
                evaluations=(_snapshot("b-check", optional_unresolved),),
            ),
            _check(
                "c-check",
                required=False,
                evaluations=(_snapshot("c-check", optional_not_applicable),),
            ),
        ],
    )
    reversed_result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [
            _check(
                "c-check",
                required=False,
                evaluations=(_snapshot("c-check", optional_not_applicable),),
            ),
            _check(
                "b-check",
                required=False,
                evaluations=(_snapshot("b-check", optional_unresolved),),
            ),
            _check("a-check", evaluations=(_snapshot("a-check", satisfied),)),
        ],
    )

    assert ordered == reversed_result
    assert [trace.check_id for trace in ordered.checks] == [
        "a-check",
        "b-check",
        "c-check",
    ]


def test_result_is_immutable_and_provenance_complete() -> None:
    context, satisfied = _comparison()
    result = evaluate_machine_readiness(
        context,
        _MRC_DECISION_TIME,
        [_check("immutable-check", evaluations=(_snapshot("immutable-check", satisfied),))],
    )

    with pytest.raises(FrozenInstanceError):
        result.state = ReadinessState.NOT_READY  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.checks[0].reason = "changed"  # type: ignore[misc]
    assert result.checks[0].evaluations[0].comparison.applicability_result is not None


def test_default_rules_and_rules_engine_are_not_authority() -> None:
    from app.domain import rules_engine

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            rules_engine,
            "evaluate_compliance",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("rules_engine should not be used")
            ),
            raising=False,
        )
        monkeypatch.setattr(
            rules_engine,
            "DEFAULT_RULES",
            object(),
            raising=False,
        )

        context, satisfied = _comparison()
        result = evaluate_machine_readiness(
            context,
            _MRC_DECISION_TIME,
            [_check("authority-check", evaluations=(_snapshot("authority-check", satisfied),))],
        )
        assert result.state is ReadinessState.READY
    finally:
        monkeypatch.undo()
