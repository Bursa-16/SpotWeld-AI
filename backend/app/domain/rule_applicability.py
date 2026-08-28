"""Threshold-free rule applicability resolution.

PURE DOMAIN module (no web-framework, no ORM, no I/O, deterministic only).

Design sources:
- docs/111_ENGINEERING_RULE_REGISTRY_DESIGN.md (applicability scope fields,
  safe-default / fail-closed behavior)
- docs/112_MACHINE_READINESS_CHECK_DESIGN.md §10 (Rule applicability)

Semantics
---------
Applicability is decided ONLY from explicitly declared scope constraints and
explicitly supplied context values. Three outcomes exist and are always
distinguishable:

* ``APPLICABLE``     — every declared constraint is satisfied by the context.
* ``NOT_APPLICABLE`` — at least one declared constraint is contradicted by the
  context (the context value is present but outside the allowed set).
* ``UNRESOLVED``     — at least one declared constraint cannot be decided
  because the context value for that dimension is missing, empty, or None.

Fail-closed rule: **missing context is never silently treated as
applicable.** An unresolved applicability blocks downstream evaluation rather
than permitting it.

Only categorical membership constraints are supported (context value must be
one of the allowed strings). No numeric thresholds, no engineering values, and
no implicit coercion appear in this module. Scope dimensions follow document
112 §10 (machine, weld gun, station/robot/operation, material family, sheet
stack/count, electrode/tip, process parameters, customer/OEM context,
category, lifecycle/effective date, equipment configuration) but this module
is dimension-agnostic: callers declare whatever keys their versioned
check/rule definitions require.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.governance_types import EvidenceClass

GOVERNED_SCOPE_DIMENSIONS: tuple[str, ...] = ("customer", "project", "site", "machine")


class ApplicabilityOutcome(StrEnum):
    """Deterministic outcome of resolving one rule's applicability."""

    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class ApplicabilityResult:
    """Explainable result of one applicability resolution.

    ``matched_keys`` / ``unsatisfied_keys`` / ``missing_keys`` are sorted
    tuples so repeated resolutions of identical inputs compare equal.

    * ``matched_keys``     — constrained dimensions satisfied by the context.
    * ``unsatisfied_keys`` — constrained dimensions whose context value is
      present but not among the allowed values (drives ``NOT_APPLICABLE``).
    * ``missing_keys``     — constrained dimensions with missing/empty/None
      context values (drives ``UNRESOLVED``).
    """

    outcome: ApplicabilityOutcome
    reason: str
    matched_keys: tuple[str, ...] = ()
    unsatisfied_keys: tuple[str, ...] = ()
    missing_keys: tuple[str, ...] = ()


class ApplicabilityResolutionOutcome(StrEnum):
    """Deterministic outcome of selecting one governed candidate revision."""

    SELECTED = "SELECTED"
    CONFLICT = "CONFLICT"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class GovernedApplicabilityContext:
    """Explicit governed resource context used by the pure resolver."""

    customer: str | None = None
    project: str | None = None
    site: str | None = None
    machine: str | None = None

    def as_mapping(self) -> dict[str, str | None]:
        return {
            "customer": self.customer,
            "project": self.project,
            "site": self.site,
            "machine": self.machine,
        }


def _freeze_scope_snapshot(
    scope: Mapping[str, Sequence[str] | None],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    frozen: list[tuple[str, tuple[str, ...]]] = []
    for key in sorted(scope):
        allowed = scope[key]
        if key not in GOVERNED_SCOPE_DIMENSIONS:
            raise ValueError(f"unsupported governed scope dimension: {key}")
        if allowed is None:
            raise ValueError(f"scope dimension {key} must declare explicit values")
        values = tuple(
            sorted(
                {
                    candidate.strip()
                    for candidate in allowed
                    if candidate is not None and candidate.strip()
                }
            )
        )
        if not values:
            raise ValueError(f"scope dimension {key} must declare explicit values")
        frozen.append((key, values))
    if not frozen:
        raise ValueError(
            "governed candidate revisions require at least one explicit scope dimension"
        )
    return tuple(frozen)


def _unfreeze_scope_snapshot(
    scope: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict[str, tuple[str, ...]]:
    return {key: values for key, values in scope}


@dataclass(frozen=True, slots=True)
class GovernedApplicabilityCandidate:
    """One governed candidate revision considered by the pure resolver."""

    candidate_id: str
    rule_id: str
    revision: str
    evidence_class: EvidenceClass
    enabled: bool
    active: bool
    scope_snapshot: Mapping[str, Sequence[str] | None] | tuple[tuple[str, tuple[str, ...]], ...]
    effective_from: datetime
    expires_at: datetime | None = None
    suspended: bool = False
    revoked: bool = False
    superseded: bool = False
    basis_valid: bool = True

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must be a non-empty string")
        if not self.rule_id.strip():
            raise ValueError("rule_id must be a non-empty string")
        if not self.revision.strip():
            raise ValueError("revision must be a non-empty string")
        if self.effective_from.tzinfo is None or self.effective_from.utcoffset() is None:
            raise ValueError("effective_from must be timezone-aware")
        if self.expires_at is not None and (
            self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None
        ):
            raise ValueError("expires_at must be timezone-aware when provided")

        if isinstance(self.scope_snapshot, Mapping):
            frozen_scope = _freeze_scope_snapshot(self.scope_snapshot)
            object.__setattr__(self, "scope_snapshot", frozen_scope)
        else:
            frozen_scope = self.scope_snapshot
            if not frozen_scope:
                raise ValueError(
                    "governed candidate revisions require at least one explicit scope dimension"
                )
            for key, values in frozen_scope:
                if key not in GOVERNED_SCOPE_DIMENSIONS:
                    raise ValueError(f"unsupported governed scope dimension: {key}")
                if not values:
                    raise ValueError(f"scope dimension {key} must declare explicit values")


@dataclass(frozen=True, slots=True)
class GovernedApplicabilityCandidateResult:
    """Immutable provenance record for one evaluated governed candidate."""

    candidate_id: str
    rule_id: str
    revision: str
    evidence_class: EvidenceClass
    enabled: bool
    active: bool
    suspended: bool
    revoked: bool
    superseded: bool
    basis_valid: bool
    effective_from: datetime
    expires_at: datetime | None
    specificity: int
    scope_snapshot: tuple[tuple[str, tuple[str, ...]], ...]
    scope_result: ApplicabilityResult | None
    eligible: bool
    eligibility_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GovernedApplicabilityResolution:
    """Immutable provenance-complete result of governed applicability selection."""

    outcome: ApplicabilityResolutionOutcome
    reason: str
    decision_time: datetime
    context: GovernedApplicabilityContext
    candidates: tuple[GovernedApplicabilityCandidateResult, ...]
    selected_candidate_id: str | None = None
    selected_rule_id: str | None = None
    selected_revision: str | None = None
    selected_specificity: int | None = None
    conflict_candidate_ids: tuple[str, ...] = ()


def _is_missing(value: str | None) -> bool:
    return value is None or not value.strip()


def evaluate_applicability(
    scope: Mapping[str, Sequence[str] | None],
    context: Mapping[str, str | None],
) -> ApplicabilityResult:
    """Resolve applicability of one scoped rule against explicit context.

    Parameters
    ----------
    scope:
        Declared applicability constraints of a rule revision. Keys are
        context dimension names; values are the allowed context values for
        that dimension. A key mapped to ``None`` or an empty sequence means
        "any value is acceptable" — the dimension is then unconstrained and
        does not participate in the decision. Key iteration order does not
        affect the outcome; reported key tuples are sorted.
    context:
        The caller-supplied evaluation context. Values are categorical
        strings; ``None`` or an empty/whitespace string means the dimension
        is unknown for this assessment and yields ``UNRESOLVED`` whenever the
        scope constrains that dimension.

    Returns
    -------
    ApplicabilityResult
        Deterministic, explainable outcome. Precedence: any unsatisfied
        constraint produces ``NOT_APPLICABLE``; otherwise any missing
        constrained context produces ``UNRESOLVED``; otherwise
        ``APPLICABLE``. Missing context therefore never resolves to
        ``APPLICABLE``.
    """
    matched: list[str] = []
    unsatisfied: list[str] = []
    missing: list[str] = []

    for key in sorted(scope):
        allowed = scope[key]
        if allowed is None or len(allowed) == 0:
            matched.append(key)
            continue

        value = context.get(key)
        if _is_missing(value):
            missing.append(key)
            continue

        normalized = value.strip()
        if any(normalized == candidate for candidate in allowed):
            matched.append(key)
        else:
            unsatisfied.append(key)

    if unsatisfied:
        return ApplicabilityResult(
            outcome=ApplicabilityOutcome.NOT_APPLICABLE,
            reason=(
                "context contradicts the declared scope for dimension(s): "
                + ", ".join(unsatisfied)
            ),
            matched_keys=tuple(matched),
            unsatisfied_keys=tuple(unsatisfied),
            missing_keys=tuple(missing),
        )

    if missing:
        return ApplicabilityResult(
            outcome=ApplicabilityOutcome.UNRESOLVED,
            reason=(
                "applicability cannot be resolved; required context "
                "missing for dimension(s): " + ", ".join(missing)
            ),
            matched_keys=tuple(matched),
            unsatisfied_keys=tuple(unsatisfied),
            missing_keys=tuple(missing),
        )

    return ApplicabilityResult(
        outcome=ApplicabilityOutcome.APPLICABLE,
        reason="all declared scope constraints are satisfied by the context",
        matched_keys=tuple(matched),
        unsatisfied_keys=tuple(unsatisfied),
        missing_keys=tuple(missing),
    )


def _validate_decision_time(decision_time: datetime) -> None:
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise ValueError("decision_time must be timezone-aware")


def _evaluate_governed_candidate(
    candidate: GovernedApplicabilityCandidate,
    *,
    context: GovernedApplicabilityContext,
    decision_time: datetime,
) -> GovernedApplicabilityCandidateResult:
    context_mapping = context.as_mapping()
    scope_mapping = _unfreeze_scope_snapshot(candidate.scope_snapshot)
    scope_result = evaluate_applicability(scope_mapping, context_mapping)
    eligibility_reasons: list[str] = []

    if candidate.evidence_class is not EvidenceClass.SOURCE_BACKED:
        eligibility_reasons.append("evidence class is not SOURCE_BACKED")
    if not candidate.enabled:
        eligibility_reasons.append("candidate is not ENABLED")
    if not candidate.active:
        eligibility_reasons.append("candidate is not ACTIVE")
    if candidate.suspended:
        eligibility_reasons.append("candidate is suspended")
    if candidate.revoked:
        eligibility_reasons.append("candidate is revoked")
    if candidate.superseded:
        eligibility_reasons.append("candidate is superseded")
    if not candidate.basis_valid:
        eligibility_reasons.append("candidate basis is invalidated")
    if decision_time < candidate.effective_from:
        eligibility_reasons.append("decision time is before effective_from")
    if candidate.expires_at is not None and decision_time >= candidate.expires_at:
        eligibility_reasons.append("decision time is on or after expires_at")

    if scope_result.outcome is not ApplicabilityOutcome.APPLICABLE:
        eligibility_reasons.append(scope_result.reason)

    return GovernedApplicabilityCandidateResult(
        candidate_id=candidate.candidate_id,
        rule_id=candidate.rule_id,
        revision=candidate.revision,
        evidence_class=candidate.evidence_class,
        enabled=candidate.enabled,
        active=candidate.active,
        suspended=candidate.suspended,
        revoked=candidate.revoked,
        superseded=candidate.superseded,
        basis_valid=candidate.basis_valid,
        effective_from=candidate.effective_from,
        expires_at=candidate.expires_at,
        specificity=len(scope_mapping),
        scope_snapshot=candidate.scope_snapshot,
        scope_result=scope_result,
        eligible=not eligibility_reasons,
        eligibility_reasons=tuple(eligibility_reasons),
    )


def resolve_governed_applicability(
    context: GovernedApplicabilityContext,
    decision_time: datetime,
    candidates: Sequence[GovernedApplicabilityCandidate],
) -> GovernedApplicabilityResolution:
    """Select the governing candidate revision for a concrete resource context.

    The resolver is pure and deterministic:

    * only SOURCE_BACKED, ENABLED, ACTIVE candidates can win;
    * explicit exact scope matches only;
    * more-specific explicit scope wins;
    * equal-specificity winners conflict;
    * zero winners resolve to UNRESOLVED;
    * candidate ordering in the input does not affect the result.
    """

    _validate_decision_time(decision_time)
    if not candidates:
        return GovernedApplicabilityResolution(
            outcome=ApplicabilityResolutionOutcome.UNRESOLVED,
            reason="no governed candidate revisions were supplied",
            decision_time=decision_time,
            context=context,
            candidates=(),
        )

    evaluated: list[GovernedApplicabilityCandidateResult] = []
    candidate_ids: set[str] = set()
    for candidate in candidates:
        if candidate.candidate_id in candidate_ids:
            raise ValueError("governed candidate revision identifiers must be unique")
        candidate_ids.add(candidate.candidate_id)
        evaluated.append(
            _evaluate_governed_candidate(
                candidate,
                context=context,
                decision_time=decision_time,
            )
        )

    evaluated = sorted(evaluated, key=lambda item: item.candidate_id)
    eligible_candidates = [candidate for candidate in evaluated if candidate.eligible]
    if not eligible_candidates:
        return GovernedApplicabilityResolution(
            outcome=ApplicabilityResolutionOutcome.UNRESOLVED,
            reason=(
                "no governed candidate revision matched the explicit scope "
                "and lifecycle gates"
            ),
            decision_time=decision_time,
            context=context,
            candidates=tuple(evaluated),
        )

    highest_specificity = max(candidate.specificity for candidate in eligible_candidates)
    winners = [
        candidate
        for candidate in eligible_candidates
        if candidate.specificity == highest_specificity
    ]
    if len(winners) > 1:
        winner_ids = tuple(sorted(candidate.candidate_id for candidate in winners))
        return GovernedApplicabilityResolution(
            outcome=ApplicabilityResolutionOutcome.CONFLICT,
            reason=(
                "multiple governed candidate revisions matched with equal "
                "specificity: " + ", ".join(winner_ids)
            ),
            decision_time=decision_time,
            context=context,
            candidates=tuple(evaluated),
            conflict_candidate_ids=winner_ids,
        )

    winner = winners[0]
    return GovernedApplicabilityResolution(
        outcome=ApplicabilityResolutionOutcome.SELECTED,
        reason=(
            "selected governed candidate revision " f"{winner.rule_id}:{winner.revision}"
        ),
        decision_time=decision_time,
        context=context,
        candidates=tuple(evaluated),
        selected_candidate_id=winner.candidate_id,
        selected_rule_id=winner.rule_id,
        selected_revision=winner.revision,
        selected_specificity=winner.specificity,
    )
