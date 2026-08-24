"""Deterministic, non-authoritative rule comparison primitives.

PURE DOMAIN module (no web-framework, no ORM, no I/O, deterministic only).

Design sources:
- docs/111_ENGINEERING_RULE_REGISTRY_DESIGN.md §6 (missing/conflict/unit
  handling) and §10 (safe-default / fail-closed behavior)
- docs/112_MACHINE_READINESS_CHECK_DESIGN.md §8–§9 (condition codes,
  unit-safe evaluation)

Semantics
---------
``compare_rule`` consumes an explicit :class:`RuleRequirement` (the caller's
declaration of one registry rule revision: identity, parameter, operator,
bounds, canonical unit, enabled flag) plus an optional :class:`Observation`,
and produces an explainable :class:`RuleComparison`. It never establishes
Registry eligibility or publication authority; those remain upstream duties.

* ``SATISFIED``      — the observation satisfied the declared comparison.
* ``NOT_SATISFIED``  — the observation contradicted the declared comparison.
* ``NOT_APPLICABLE`` — the requirement is disabled, so it must not evaluate.
* ``UNIT_MISMATCH``  — units are incompatible and no governed-snapshot conversion
  exists; comparison refused (document 111 §6.3).
* ``UNRESOLVED``     — evaluation cannot complete: required observation
  missing, wrong-parameter observation, missing unit metadata, or an operator
  this deterministic evaluator deliberately does not implement
  (``DERIVED_MIN``/``CUSTOM`` require separately approved formulas and
  engineering authority).

Fail-closed guarantees:

* missing required inputs never produce ``SATISFIED``;
* unit problems are decided by :mod:`app.domain.unit_policy` before any
  numeric comparison — no implicit coercion;
* malformed requirements (missing bounds for the operator, inverted ranges)
  raise ``ValueError`` at construction instead of evaluating.

THRESHOLD-FREE: no welding current, force, time, temperature, nugget,
electrode, thickness, or any other engineering value appears in this module.
Every bound is supplied by the caller; tests use synthetic arbitrary values.
The quarantined prototype rule engine is intentionally not imported here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.rule_registry_types import RuleOperator
from app.domain.unit_policy import (
    ConversionProvenance,
    UnitCompatibility,
    UnitPolicyCatalog,
    UnitPolicyContext,
    evaluate_unit_policy,
)

__all__ = [
    "ComparisonAuthorityScope",
    "Observation",
    "RuleComparison",
    "RuleComparisonOutcome",
    "RuleRequirement",
    "compare_rule",
]


class ComparisonAuthorityScope(StrEnum):
    """Explicit boundary separating comparison from Registry authority."""

    DETERMINISTIC_COMPARISON_ONLY = "DETERMINISTIC_COMPARISON_ONLY"


class RuleComparisonOutcome(StrEnum):
    """Deterministic outcome of comparing one declared requirement."""

    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class RuleRequirement:
    """Caller-declared requirement of one registry rule revision.

    This is a *description*, not engineering authority: bounds are supplied
    verbatim by the caller (in production, from a governed registry revision;
    in tests, synthetic values).

    ``unit`` is the canonical expected unit declared by the revision. Use
    ``unit_policy.DIMENSIONLESS_UNIT`` for explicitly dimensionless rules.

    Construction is fail-closed: operators must carry the bounds they need
    (``MIN`` requires ``min_value``, ``MAX`` requires ``max_value``,
    ``RANGE``/``EQUALS`` require both), ranges must not be inverted, identity
    fields must be non-empty. Unsupported operators are accepted but will
    deterministically evaluate to ``UNRESOLVED``.
    """

    rule_id: str
    revision: str
    parameter: str
    operator: RuleOperator
    unit: str
    min_value: float | None = None
    max_value: float | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        for name in ("rule_id", "revision", "parameter", "unit"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")

        needs_min = self.operator in (
            RuleOperator.MIN,
            RuleOperator.RANGE,
            RuleOperator.EQUALS,
        )
        needs_max = self.operator in (
            RuleOperator.MAX,
            RuleOperator.RANGE,
            RuleOperator.EQUALS,
        )
        if needs_min and self.min_value is None:
            raise ValueError(f"operator {self.operator.value} requires min_value")
        if needs_max and self.max_value is None:
            raise ValueError(f"operator {self.operator.value} requires max_value")
        if (
            self.operator is RuleOperator.RANGE
            and self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError("RANGE requires min_value <= max_value")
        if (
            self.operator is RuleOperator.EQUALS
            and self.min_value != self.max_value
        ):
            raise ValueError("EQUALS requires min_value == max_value")


@dataclass(frozen=True, slots=True)
class Observation:
    """One explicitly supplied observed measurement."""

    parameter: str
    value: float
    unit: str


@dataclass(frozen=True, slots=True)
class RuleComparison:
    """Explainable deterministic comparison, never an authoritative result.

    ``rule_id``/``revision`` preserve rule/revision identity so evaluations
    remain traceable to the exact registry revision they consumed.
    ``compared_value`` is the value actually used in the comparison (the
    converted value when a snapshot conversion was applied, otherwise the
    raw observed value); it is ``None`` unless a comparison was completed.
    """

    rule_id: str
    revision: str
    parameter: str
    operator: RuleOperator
    outcome: RuleComparisonOutcome
    reason: str
    conversion_provenance: ConversionProvenance
    observed_value: float | None = None
    observed_unit: str | None = None
    compared_value: float | None = None
    authority_scope: ComparisonAuthorityScope = field(
        default=ComparisonAuthorityScope.DETERMINISTIC_COMPARISON_ONLY,
        init=False,
    )


def _compare(
    operator: RuleOperator,
    compared_value: float,
    requirement: RuleRequirement,
) -> tuple[RuleComparisonOutcome, str]:
    if operator is RuleOperator.MIN:
        assert requirement.min_value is not None  # noqa: S101 - guaranteed by __post_init__
        passed = compared_value >= requirement.min_value
        bound_text = f">= {requirement.min_value}"
    elif operator is RuleOperator.MAX:
        assert requirement.max_value is not None  # noqa: S101 - guaranteed by __post_init__
        passed = compared_value <= requirement.max_value
        bound_text = f"<= {requirement.max_value}"
    elif operator is RuleOperator.RANGE:
        assert requirement.min_value is not None  # noqa: S101
        assert requirement.max_value is not None  # noqa: S101
        passed = requirement.min_value <= compared_value <= requirement.max_value
        bound_text = f"in [{requirement.min_value}, {requirement.max_value}]"
    else:  # RuleOperator.EQUALS
        assert requirement.min_value is not None  # noqa: S101 - guaranteed by __post_init__
        passed = compared_value == requirement.min_value
        bound_text = f"== {requirement.min_value}"

    expectation = f"{requirement.parameter} {bound_text} ({requirement.unit})"
    if passed:
        return (
            RuleComparisonOutcome.SATISFIED,
            f"observed {compared_value} satisfies {expectation}",
        )
    return (
        RuleComparisonOutcome.NOT_SATISFIED,
        f"observed {compared_value} violates {expectation}",
    )


def compare_rule(
    requirement: RuleRequirement,
    observation: Observation | None,
    *,
    unit_context: UnitPolicyContext | None = None,
    unit_catalog: UnitPolicyCatalog | None = None,
) -> RuleComparison:
    """Compare one explicit requirement against one explicit observation.

    Parameters
    ----------
    requirement:
        The caller-declared rule-revision requirement to apply.
    observation:
        The observed measurement, or ``None`` when the required observation
        is absent. Absence yields ``UNRESOLVED`` (never ``SATISFIED``).
    unit_context:
        Optional explicit unit-policy context. When omitted, a default
        context expecting exactly the requirement's canonical unit (with no
        conversion entries) is used, so only identical declared units are
        comparable.
    unit_catalog:
        Optional governed version snapshot of conversions; the policy slice
        derived for the requirement's canonical unit is used as the unit
        context. Mutually exclusive with ``unit_context`` — passing both
        raises ``ValueError``. Conversions whose target differs from the
        requirement's canonical unit are never exposed to the comparison.

    Returns
    -------
    RuleComparison
        Deterministic, explainable comparison preserving rule/revision
        identity and explicitly carrying no Registry authority.
    """
    if unit_context is not None and unit_catalog is not None:
        raise ValueError(
            "pass either an explicit unit context or a unit catalog, "
            "not both"
        )

    identity = {
        "rule_id": requirement.rule_id,
        "revision": requirement.revision,
        "parameter": requirement.parameter,
        "operator": requirement.operator,
    }

    policy_version = (
        unit_catalog.version
        if unit_catalog is not None
        else unit_context.policy_version
        if unit_context is not None
        else None
    )

    def _result(
        outcome: RuleComparisonOutcome,
        reason: str,
        *,
        observed_value: float | None = None,
        observed_unit: str | None = None,
        compared_value: float | None = None,
        conversion_provenance: ConversionProvenance | None = None,
    ) -> RuleComparison:
        provenance = conversion_provenance or ConversionProvenance(
            conversion_occurred=False,
            original_value=observed_value,
            original_unit=observed_unit,
            comparison_value=compared_value,
            target_unit=requirement.unit.strip(),
            factor=None,
            policy_version=policy_version,
            rounding_policy=None,
        )
        return RuleComparison(
            **identity,
            outcome=outcome,
            reason=reason,
            conversion_provenance=provenance,
            observed_value=observed_value,
            observed_unit=observed_unit,
            compared_value=compared_value,
        )

    if not requirement.enabled:
        return _result(
            RuleComparisonOutcome.NOT_APPLICABLE,
            "rule revision is disabled and must not be evaluated",
        )

    if requirement.operator in (RuleOperator.DERIVED_MIN, RuleOperator.CUSTOM):
        return _result(
            RuleComparisonOutcome.UNRESOLVED,
            (
                f"operator {requirement.operator.value} requires a separately "
                "approved formula and engineering authority; this "
                "deterministic evaluator does not implement it"
            ),
        )

    if observation is None:
        return _result(
            RuleComparisonOutcome.UNRESOLVED,
            "required observation is missing; evaluation refused (fail-closed)",
        )

    if observation.parameter.strip() != requirement.parameter.strip():
        return _result(
            RuleComparisonOutcome.UNRESOLVED,
            (
                f"observation parameter {observation.parameter!r} does not "
                f"match rule parameter {requirement.parameter!r}"
            ),
            observed_value=observation.value,
            observed_unit=observation.unit,
        )

    if unit_context is not None:
        context = unit_context
    elif unit_catalog is not None:
        context = unit_catalog.context_for(requirement.unit)
    else:
        context = UnitPolicyContext(expected_unit=requirement.unit)
    policy = evaluate_unit_policy(observation.unit, context, observation.value)
    if not policy.comparable:
        outcome = (
            RuleComparisonOutcome.UNIT_MISMATCH
            if policy.compatibility is UnitCompatibility.UNIT_MISMATCH
            else RuleComparisonOutcome.UNRESOLVED
        )
        return _result(
            outcome,
            f"unit policy refused comparison: {policy.reason}",
            observed_value=observation.value,
            observed_unit=observation.unit,
            conversion_provenance=policy.provenance,
        )

    compared_value = (
        policy.converted_value
        if policy.converted_value is not None
        else observation.value
    )
    outcome, reason = _compare(requirement.operator, compared_value, requirement)
    if policy.converted_value is not None:
        # Structured provenance is the canonical audit detail; prose remains
        # only for human readability. Neither form grants Registry authority.
        reason = f"{reason}; {policy.reason}"
    return _result(
        outcome,
        reason,
        observed_value=observation.value,
        observed_unit=observation.unit,
        compared_value=compared_value,
        conversion_provenance=policy.provenance,
    )
