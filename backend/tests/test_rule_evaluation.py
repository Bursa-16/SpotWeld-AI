"""Stage 2A tests: deterministic rule comparison primitives.

All bounds/observations are synthetic arbitrary values; none carries
engineering meaning.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

import app.domain.rule_evaluation as rule_comparison_module
from app.domain.governance_types import ContentVersionMetadata, EvidenceClass
from app.domain.rule_applicability import (
    ApplicabilityResolutionOutcome,
    GovernedApplicabilityCandidate,
    GovernedApplicabilityContext,
    GovernedApplicabilityResolution,
    resolve_governed_applicability,
)
from app.domain.rule_evaluation import (
    ComparisonAuthorityScope,
    Observation,
    RuleComparisonOutcome,
    RuleRequirement,
    compare_rule,
)
from app.domain.rule_registry_types import RuleOperator
from app.domain.unit_policy import (
    DIMENSIONLESS_UNIT,
    ConversionEntry,
    UnitPolicyCatalog,
    UnitPolicyContext,
)


def _version(label: str = "v1") -> ContentVersionMetadata:
    return ContentVersionMetadata(
        schema_version="schema-1",
        canonicalization_version="canonical-1",
        hash_algorithm="synthetic-hash",
        content_hash=f"synthetic-{label}",
        software_version="software-1",
    )


def _requirement(
    operator: RuleOperator = RuleOperator.MIN,
    *,
    unit: str = "synthetic_unit",
    min_value: float | None = 10.0,
    max_value: float | None = None,
    enabled: bool = True,
    parameter: str = "synthetic_parameter",
) -> RuleRequirement:
    return RuleRequirement(
        rule_id="SYN_RULE",
        revision="r1",
        parameter=parameter,
        operator=operator,
        unit=unit,
        min_value=min_value,
        max_value=max_value,
        enabled=enabled,
    )


def _observation(
    value: float,
    unit: str = "synthetic_unit",
    parameter: str = "synthetic_parameter",
) -> Observation:
    return Observation(parameter=parameter, value=value, unit=unit)


def _selected_applicability_result(
    *,
    rule_id: str = "SYN_RULE",
    revision: str = "r1",
) -> GovernedApplicabilityResolution:
    candidate = GovernedApplicabilityCandidate(
        candidate_id="candidate-1",
        rule_id=rule_id,
        revision=revision,
        evidence_class=EvidenceClass.SOURCE_BACKED,
        enabled=True,
        active=True,
        scope_snapshot={"customer": ["customer-a"]},
        effective_from=datetime(2029, 12, 31, 0, 0, tzinfo=timezone.utc),
    )
    return resolve_governed_applicability(
        GovernedApplicabilityContext(customer="customer-a"),
        datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc),
        [candidate],
    )


def test_min_requirement_passes_at_and_above_bound() -> None:
    at_bound = compare_rule(_requirement(), _observation(10.0))
    above_bound = compare_rule(_requirement(), _observation(12.5))
    assert at_bound.outcome is RuleComparisonOutcome.SATISFIED
    assert above_bound.outcome is RuleComparisonOutcome.SATISFIED
    assert at_bound.compared_value == 10.0


def test_min_requirement_fails_below_bound() -> None:
    evaluation = compare_rule(_requirement(), _observation(9.999))
    assert evaluation.outcome is RuleComparisonOutcome.NOT_SATISFIED


def test_max_requirement_passes_below_and_fails_above() -> None:
    requirement = _requirement(RuleOperator.MAX, min_value=None, max_value=7.0)
    assert (
        compare_rule(requirement, _observation(6.0)).outcome
        is RuleComparisonOutcome.SATISFIED
    )
    assert (
        compare_rule(requirement, _observation(7.5)).outcome
        is RuleComparisonOutcome.NOT_SATISFIED
    )


def test_range_requirement_inside_and_outside() -> None:
    requirement = _requirement(
        RuleOperator.RANGE, min_value=2.0, max_value=4.0
    )
    inside = compare_rule(requirement, _observation(3.0))
    below = compare_rule(requirement, _observation(1.0))
    above = compare_rule(requirement, _observation(4.1))
    assert inside.outcome is RuleComparisonOutcome.SATISFIED
    assert below.outcome is RuleComparisonOutcome.NOT_SATISFIED
    assert above.outcome is RuleComparisonOutcome.NOT_SATISFIED


def test_equals_requirement() -> None:
    requirement = _requirement(
        RuleOperator.EQUALS, min_value=5.0, max_value=5.0
    )
    assert (
        compare_rule(requirement, _observation(5.0)).outcome
        is RuleComparisonOutcome.SATISFIED
    )
    assert (
        compare_rule(requirement, _observation(5.5)).outcome
        is RuleComparisonOutcome.NOT_SATISFIED
    )


def test_missing_observation_is_unresolved_never_passed() -> None:
    evaluation = compare_rule(_requirement(), None)
    assert evaluation.outcome is RuleComparisonOutcome.UNRESOLVED
    assert "missing" in evaluation.reason.lower()


def test_wrong_parameter_observation_is_unresolved() -> None:
    evaluation = compare_rule(
        _requirement(), _observation(11.0, parameter="other_parameter")
    )
    assert evaluation.outcome is RuleComparisonOutcome.UNRESOLVED


def test_disabled_rule_is_not_applicable_without_evaluation() -> None:
    evaluation = compare_rule(
        _requirement(enabled=False), _observation(99.0)
    )
    assert evaluation.outcome is RuleComparisonOutcome.NOT_APPLICABLE
    assert evaluation.compared_value is None


def test_unit_mismatch_blocks_comparison() -> None:
    evaluation = compare_rule(_requirement(), _observation(11.0, unit="other"))
    assert evaluation.outcome is RuleComparisonOutcome.UNIT_MISMATCH
    assert "fail-closed" in evaluation.reason
    assert evaluation.compared_value is None


def test_missing_observation_unit_is_unresolved() -> None:
    evaluation = compare_rule(_requirement(), _observation(11.0, unit=""))
    assert evaluation.outcome is RuleComparisonOutcome.UNRESOLVED


def test_governed_snapshot_conversion_feeds_the_comparison() -> None:
    context = UnitPolicyContext(
        expected_unit="synthetic_unit",
        conversion_factors={("raw_unit", "synthetic_unit"): 0.5},
        policy_version=_version(),
        rounding_policy="NO_ROUNDING",
    )
    # raw 30 -> synthetic 15, which satisfies MIN 10.
    passed = compare_rule(
        _requirement(), _observation(30.0, unit="raw_unit"), unit_context=context
    )
    # raw 10 -> synthetic 5, which violates MIN 10.
    failed = compare_rule(
        _requirement(), _observation(10.0, unit="raw_unit"), unit_context=context
    )
    assert passed.outcome is RuleComparisonOutcome.SATISFIED
    assert passed.compared_value == pytest.approx(15.0)
    assert failed.outcome is RuleComparisonOutcome.NOT_SATISFIED
    assert failed.compared_value == pytest.approx(5.0)


def test_dimensionless_rule_evaluates_on_declared_dimensionless() -> None:
    requirement = _requirement(unit=DIMENSIONLESS_UNIT)
    evaluation = compare_rule(
        requirement,
        Observation(
            parameter="synthetic_parameter",
            value=11.0,
            unit=DIMENSIONLESS_UNIT,
        ),
    )
    assert evaluation.outcome is RuleComparisonOutcome.SATISFIED


def test_derived_min_operator_is_unresolved_not_evaluated() -> None:
    requirement = _requirement(RuleOperator.DERIVED_MIN, min_value=None)
    evaluation = compare_rule(requirement, _observation(1.0))
    assert evaluation.outcome is RuleComparisonOutcome.UNRESOLVED
    assert "authority" in evaluation.reason or "formula" in evaluation.reason


def test_custom_operator_is_unresolved() -> None:
    requirement = _requirement(RuleOperator.CUSTOM, min_value=None)
    assert (
        compare_rule(requirement, _observation(1.0)).outcome
        is RuleComparisonOutcome.UNRESOLVED
    )


@pytest.mark.parametrize(
    ("operator", "min_value", "max_value"),
    [
        (RuleOperator.MIN, None, None),
        (RuleOperator.MAX, None, None),
        (RuleOperator.RANGE, None, 4.0),
        (RuleOperator.RANGE, 6.0, 4.0),  # inverted
        (RuleOperator.EQUALS, 2.0, 3.0),  # not equal
    ],
)
def test_malformed_requirements_fail_closed_at_construction(
    operator: RuleOperator,
    min_value: float | None,
    max_value: float | None,
) -> None:
    with pytest.raises(ValueError):
        RuleRequirement(
            rule_id="SYN_RULE",
            revision="r1",
            parameter="synthetic_parameter",
            operator=operator,
            unit="synthetic_unit",
            min_value=min_value,
            max_value=max_value,
        )


def test_empty_identity_fields_rejected() -> None:
    with pytest.raises(ValueError):
        _requirement().__class__(
            rule_id="  ",
            revision="r1",
            parameter="p",
            operator=RuleOperator.MIN,
            unit="u",
            min_value=1.0,
        )


def test_evaluation_preserves_rule_and_revision_identity() -> None:
    requirement = RuleRequirement(
        rule_id="SYN_RULE_ID",
        revision="rev-7",
        parameter="synthetic_parameter",
        operator=RuleOperator.MIN,
        unit="synthetic_unit",
        min_value=10.0,
    )
    evaluation = compare_rule(requirement, _observation(11.0))
    assert evaluation.rule_id == "SYN_RULE_ID"
    assert evaluation.revision == "rev-7"
    assert evaluation.operator is RuleOperator.MIN


def test_repeated_evaluation_is_deterministic() -> None:
    requirement = _requirement()
    first = compare_rule(requirement, _observation(11.0))
    second = compare_rule(requirement, _observation(11.0))
    assert first == second


@pytest.mark.parametrize(
    ("operator", "min_value", "max_value", "observed_value", "expected"),
    [
        (RuleOperator.MIN, 10.0, None, 10.0, RuleComparisonOutcome.SATISFIED),
        (RuleOperator.MIN, 10.0, None, 9.0, RuleComparisonOutcome.NOT_SATISFIED),
        (RuleOperator.MAX, None, 7.0, 7.0, RuleComparisonOutcome.SATISFIED),
        (RuleOperator.MAX, None, 7.0, 7.5, RuleComparisonOutcome.NOT_SATISFIED),
        (RuleOperator.RANGE, 2.0, 4.0, 3.0, RuleComparisonOutcome.SATISFIED),
        (RuleOperator.RANGE, 2.0, 4.0, 5.0, RuleComparisonOutcome.NOT_SATISFIED),
        (RuleOperator.EQUALS, 5.0, 5.0, 5.0, RuleComparisonOutcome.SATISFIED),
        (RuleOperator.EQUALS, 5.0, 5.0, 5.5, RuleComparisonOutcome.NOT_SATISFIED),
    ],
)
def test_governed_applicability_selected_pins_exact_revision_and_evaluates(
    operator: RuleOperator,
    min_value: float | None,
    max_value: float | None,
    observed_value: float,
    expected: RuleComparisonOutcome,
) -> None:
    requirement = _requirement(
        operator,
        min_value=min_value,
        max_value=max_value,
    )
    applicability_result = _selected_applicability_result()
    comparison = compare_rule(
        requirement,
        _observation(observed_value),
        applicability_result=applicability_result,
    )

    assert comparison.outcome is expected
    assert comparison.applicability_result == applicability_result
    assert comparison.applicability_result.outcome is (
        ApplicabilityResolutionOutcome.SELECTED
    )
    assert comparison.rule_id == requirement.rule_id
    assert comparison.revision == requirement.revision


def test_governed_applicability_conflict_is_unresolved() -> None:
    candidate_a = GovernedApplicabilityCandidate(
        candidate_id="candidate-a",
        rule_id="SYN_RULE",
        revision="r1",
        evidence_class=EvidenceClass.SOURCE_BACKED,
        enabled=True,
        active=True,
        scope_snapshot={"customer": ["customer-a"]},
        effective_from=datetime(2029, 12, 31, 0, 0, tzinfo=timezone.utc),
    )
    candidate_b = GovernedApplicabilityCandidate(
        candidate_id="candidate-b",
        rule_id="SYN_RULE",
        revision="r1",
        evidence_class=EvidenceClass.SOURCE_BACKED,
        enabled=True,
        active=True,
        scope_snapshot={"customer": ["customer-a"]},
        effective_from=datetime(2029, 12, 31, 0, 0, tzinfo=timezone.utc),
    )
    applicability_result = resolve_governed_applicability(
        GovernedApplicabilityContext(customer="customer-a"),
        datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc),
        [candidate_a, candidate_b],
    )

    comparison = compare_rule(
        _requirement(),
        _observation(11.0),
        applicability_result=applicability_result,
    )

    assert applicability_result.outcome is ApplicabilityResolutionOutcome.CONFLICT
    assert comparison.outcome is RuleComparisonOutcome.UNRESOLVED
    assert "SELECTED" in comparison.reason


def test_governed_applicability_pin_mismatch_fails_closed() -> None:
    applicability_result = _selected_applicability_result(rule_id="OTHER_RULE")
    comparison = compare_rule(
        _requirement(),
        _observation(11.0),
        applicability_result=applicability_result,
    )

    assert comparison.outcome is RuleComparisonOutcome.UNRESOLVED
    assert "pin" in comparison.reason


def test_governed_applicability_result_is_provenance_complete_and_immutable() -> None:
    applicability_result = _selected_applicability_result()
    comparison = compare_rule(
        _requirement(),
        _observation(11.0),
        applicability_result=applicability_result,
    )

    assert comparison.applicability_result == applicability_result
    assert comparison.conversion_provenance.policy_version is None
    with pytest.raises(FrozenInstanceError):
        comparison.rule_id = "changed"  # type: ignore[misc]


def test_raw_requirement_produces_comparison_not_authoritative_evaluation() -> None:
    comparison = compare_rule(_requirement(), _observation(11.0))
    assert comparison.outcome is RuleComparisonOutcome.SATISFIED
    assert (
        comparison.authority_scope
        is ComparisonAuthorityScope.DETERMINISTIC_COMPARISON_ONLY
    )
    assert not hasattr(comparison, "authoritative")
    assert not hasattr(comparison, "evidence_class")
    assert not hasattr(comparison, "lifecycle_status")
    assert not hasattr(rule_comparison_module, "RuleEvaluation")
    assert not hasattr(rule_comparison_module, "evaluate_rule")


def test_no_conversion_has_explicit_structured_provenance() -> None:
    comparison = compare_rule(_requirement(), _observation(11.0))
    provenance = comparison.conversion_provenance
    assert provenance.conversion_occurred is False
    assert provenance.original_value == pytest.approx(11.0)
    assert provenance.original_unit == "synthetic_unit"
    assert provenance.comparison_value == pytest.approx(11.0)
    assert provenance.target_unit == "synthetic_unit"
    assert provenance.factor is None
    assert provenance.rounding_policy is None


def test_catalog_driven_conversion_feeds_the_comparison() -> None:
    requirement = _requirement(unit="dst_u", min_value=50.0)
    observation = _observation(0.75, unit="src_u")
    catalog = UnitPolicyCatalog(
        version=_version("v9"),
        rounding_policy="NO_ROUNDING",
        conversions=(
            ConversionEntry(
                from_unit="src_u", to_unit="dst_u", factor=100.0
            ),
        ),
    )
    evaluation = compare_rule(requirement, observation, unit_catalog=catalog)
    assert evaluation.outcome is RuleComparisonOutcome.SATISFIED
    assert evaluation.observed_value == pytest.approx(0.75)
    assert evaluation.observed_unit == "src_u"
    assert evaluation.compared_value == pytest.approx(75.0)
    assert "snapshot conversion" in evaluation.reason
    assert evaluation.conversion_provenance.conversion_occurred is True
    assert evaluation.conversion_provenance.original_value == pytest.approx(0.75)
    assert evaluation.conversion_provenance.original_unit == "src_u"
    assert evaluation.conversion_provenance.comparison_value == pytest.approx(75.0)
    assert evaluation.conversion_provenance.target_unit == "dst_u"
    assert evaluation.conversion_provenance.factor == pytest.approx(100.0)
    assert evaluation.conversion_provenance.policy_version == _version("v9")
    assert evaluation.conversion_provenance.rounding_policy == "NO_ROUNDING"


def test_without_context_or_catalog_mismatch_fails_closed() -> None:
    evaluation = compare_rule(
        _requirement(unit="dst_u"), _observation(1.0, unit="src_u")
    )
    assert evaluation.outcome is RuleComparisonOutcome.UNIT_MISMATCH
    assert evaluation.compared_value is None


def test_wrong_direction_catalog_entry_does_not_enable_comparison() -> None:
    catalog = UnitPolicyCatalog(
        version=_version("v9"),
        rounding_policy="NO_ROUNDING",
        conversions=(
            ConversionEntry(
                from_unit="dst_u", to_unit="src_u", factor=100.0
            ),
        ),
    )
    evaluation = compare_rule(
        _requirement(unit="dst_u"),
        _observation(1.0, unit="src_u"),
        unit_catalog=catalog,
    )
    assert evaluation.outcome is RuleComparisonOutcome.UNIT_MISMATCH
    assert evaluation.compared_value is None


def test_passing_both_unit_context_and_catalog_is_rejected() -> None:
    with pytest.raises(ValueError):
        compare_rule(
            _requirement(),
            _observation(11.0),
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
            unit_catalog=UnitPolicyCatalog(
                version=_version("v9"), rounding_policy="NO_ROUNDING"
            ),
        )


def test_disabled_rule_ignores_the_catalog() -> None:
    catalog = UnitPolicyCatalog(
        version=_version("v9"),
        rounding_policy="NO_ROUNDING",
        conversions=(
            ConversionEntry(
                from_unit="other_u", to_unit="synthetic_unit", factor=7.0
            ),
        ),
    )
    evaluation = compare_rule(
        _requirement(enabled=False),
        _observation(5.0, unit="other_u"),
        unit_catalog=catalog,
    )
    assert evaluation.outcome is RuleComparisonOutcome.NOT_APPLICABLE
