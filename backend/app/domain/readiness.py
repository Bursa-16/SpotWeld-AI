"""Threshold-free Machine Readiness Check (MRC) aggregation primitives.

PURE DOMAIN module (no web-framework, no ORM, no I/O, deterministic only).

Design sources:
- docs/112_MACHINE_READINESS_CHECK_DESIGN.md section 4 (five-state model, exact
  READY prerequisites, mandatory invariants, deterministic aggregation
  precedence), section 8 (condition codes), section 11 (review distinction)
- docs/111_ENGINEERING_RULE_REGISTRY_DESIGN.md section 7 (MRC integration boundary)

Locked semantics (document 112 section 4)
----------------------------------
Five final states::

    READY, NOT_READY, ENGINEERING_REVIEW_REQUIRED,
    MANUAL_REVIEW_REQUIRED, NOT_EVALUATED

Deterministic aggregation precedence (first match wins)::

    1. NOT_READY                     -- any required applicable rule FAILED.
    2. ENGINEERING_REVIEW_REQUIRED   -- otherwise, any required UNRESOLVED
                                       rule, unavailable evidence, unresolved
                                       conflict, or wrong-version blocker.
    3. MANUAL_REVIEW_REQUIRED        -- otherwise, any DATA_INSUFFICIENT,
                                       OBSERVATION_MISSING, or
                                       CONTEXT_INSUFFICIENT condition (or an
                                       explicitly flagged manual judgment).
    4. NOT_EVALUATED                 -- otherwise, zero applicable validated
                                       engineering rules.
    5. READY                         -- otherwise, and only after all six
                                       READY prerequisites pass.

Mandatory invariants preserved: ``UNRESOLVED != PASS``; ``UNRESOLVED`` blocks
automatic ``READY``; ``DATA_INSUFFICIENT`` blocks automatic ``READY``;
``NOT_EVALUATED`` never maps to ``READY``; secondary blockers are retained in
the explanation even when a higher-precedence state wins.

THRESHOLD-FREE: no machine limits, numeric welding thresholds, or readiness
cutoffs appear here. Aggregation consumes only categorical condition codes
produced by callers (in production, from governed registry evaluations; in
tests, synthetic values). The quarantined prototype rule engine is
intentionally not imported here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.domain.governance_types import EvidenceClass
from app.domain.rule_applicability import (
    ApplicabilityResolutionOutcome,
    GovernedApplicabilityContext,
    GovernedApplicabilityResolution,
)

__all__ = [
    "READY_PREREQUISITES",
    "CheckCondition",
    "GovernedMachineReadinessCheck",
    "GovernedRuleEvaluationSnapshot",
    "MachineReadinessCheckTrace",
    "MachineReadinessResult",
    "ReadinessContribution",
    "ReadinessResult",
    "ReadinessState",
    "aggregate_readiness",
    "evaluate_machine_readiness",
]


class ReadinessState(StrEnum):
    """The five final MRC states (document 112 section 4)."""

    READY = "READY"
    NOT_READY = "NOT_READY"
    ENGINEERING_REVIEW_REQUIRED = "ENGINEERING_REVIEW_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    NOT_EVALUATED = "NOT_EVALUATED"


class CheckCondition(StrEnum):
    """Per-check evaluation conditions feeding aggregation (document 112 section 8).

    These are evaluation conditions, not final states: ``DATA_INSUFFICIENT``,
    for example, aggregates to ``MANUAL_REVIEW_REQUIRED`` while ``UNRESOLVED``
    aggregates to ``ENGINEERING_REVIEW_REQUIRED``.
    """

    PASSED = "PASSED"
    FAILED = "FAILED"
    UNRESOLVED = "UNRESOLVED"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
    CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"
    RULE_CONFLICT = "RULE_CONFLICT"
    NOT_APPLICABLE_VERSION = "NOT_APPLICABLE_VERSION"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    OBSERVATION_MISSING = "OBSERVATION_MISSING"
    NOT_EVALUATED = "NOT_EVALUATED"

    @property
    def is_engineering_blocker(self) -> bool:
        """Condition requires engineering resolution (precedence bucket 2)."""
        return self in (
            CheckCondition.UNRESOLVED,
            CheckCondition.EVIDENCE_UNAVAILABLE,
            CheckCondition.RULE_CONFLICT,
            CheckCondition.NOT_APPLICABLE_VERSION,
        )

    @property
    def is_manual_review_blocker(self) -> bool:
        """Condition requires controlled manual review (precedence bucket 3)."""
        return self in (
            CheckCondition.DATA_INSUFFICIENT,
            CheckCondition.OBSERVATION_MISSING,
            CheckCondition.CONTEXT_INSUFFICIENT,
        )


@dataclass(frozen=True, slots=True)
class ReadinessContribution:
    """One check/rule condition offered into the readiness aggregation.

    ``check_id`` is the stable contribution identity used to prove that a
    declared applicable-rule count is represented exactly once. ``required``
    mirrors the versioned check definition ("required" versus
    explicitly optional); ``applicable`` records whether the underlying rule
    was applicable to the stated context. Optional conditions do not determine
    engineering readiness, while every applicable identity still participates
    in integrity/count proof. Non-applicable items do neither.
    """

    check_id: str
    condition: CheckCondition
    required: bool = True
    applicable: bool = True
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """Deterministic, explainable readiness aggregate.

    ``authoritative`` records whether this decision may be published: it is
    ``False`` exactly when the caller reported that persistence/audit
    backing for the decision record was unavailable (document 112 sections
    4.4 and 11.4; document 114 section 14.3). A non-authoritative result
    never carries ``READY``.
    """

    state: ReadinessState
    reasons: tuple[str, ...]
    prerequisites: tuple[tuple[str, bool], ...]
    authoritative: bool


READY_PREREQUISITES: tuple[str, ...] = (
    "at least one applicable validated engineering rule exists",
    "every required applicable SOURCE_BACKED rule passes",
    "all required input data is available and valid",
    "no required applicable UNRESOLVED rule exists",
    "no unresolved conflict exists",
    "no manual-review condition exists",
)


def aggregate_readiness(
    contributions: Sequence[ReadinessContribution],
    *,
    validated_applicable_rule_count: int = 0,
    manual_judgment_flagged: bool = False,
    persistence_ok: bool,
) -> ReadinessResult:
    """Aggregate check conditions into one deterministic readiness state.

    Parameters
    ----------
    contributions:
        Every check/rule condition to consider. Optional and non-applicable
        items never block engineering readiness, but applicable contribution
        identities participate in declared-count integrity proof. Duplicate or
        missing identities fail closed.
    validated_applicable_rule_count:
        Number of applicable validated engineering rules backing this
        assessment. Zero means there is no validated basis for readiness
        (document 112 section 4.2 prerequisite 1).
    manual_judgment_flagged:
        Set by callers when an explicit manual-judgment condition exists that
        has no dedicated contribution record.
    persistence_ok:
        Required affirmative caller proof of safe decision/audit persistence;
        there is deliberately no success default.
        ``False`` marks the result non-authoritative: no authoritative
        decision is published, and a would-be ``READY`` is refused and
        remapped to ``MANUAL_REVIEW_REQUIRED`` (documents 112 sections
        4.4/11.4 and 114 section 14.3). Computed states other than READY
        are preserved verbatim for traceability, and prerequisite values
        are left untouched so the engineering checklist stays inspectable.

    Returns
    -------
    ReadinessResult
        The final state plus deterministic sorted reasons and the
        six-prerequisite checklist (document 112 section 4.2);
        ``authoritative`` reflects the persistence gate.
    """
    persistence_confirmed = persistence_ok is True
    blocking = [
        item
        for item in contributions
        if item.required and item.applicable
    ]
    represented = [
        item
        for item in contributions
        if item.applicable
        and item.condition is not CheckCondition.NOT_EVALUATED
    ]
    represented_ids = [item.check_id.strip() for item in represented]
    duplicate_ids = sorted(
        {
            check_id
            for check_id in represented_ids
            if check_id and represented_ids.count(check_id) > 1
        }
    )
    blank_ids = sum(not check_id for check_id in represented_ids)
    represented_count = len(set(represented_ids))
    declared_count_is_integer = isinstance(
        validated_applicable_rule_count, int
    ) and not isinstance(validated_applicable_rule_count, bool)
    declared_count_consistent = (
        declared_count_is_integer
        and validated_applicable_rule_count >= 0
        and validated_applicable_rule_count == represented_count
    )
    required_pass_evidence = [
        item
        for item in blocking
        if item.condition is CheckCondition.PASSED
    ]
    every_required_passed = bool(blocking) and len(required_pass_evidence) == len(
        blocking
    )

    proof_issues: list[str] = []
    if not declared_count_consistent:
        proof_issues.append(
            "applicable-rule evidence count inconsistent: "
            f"declared={validated_applicable_rule_count}, "
            f"represented_unique={represented_count}"
        )
    if duplicate_ids:
        proof_issues.append(
            "duplicate readiness contribution identity: "
            + ", ".join(duplicate_ids)
        )
    if blank_ids:
        proof_issues.append(
            f"{blank_ids} applicable contribution(s) have an empty identity"
        )
    if validated_applicable_rule_count > 0 and not required_pass_evidence:
        proof_issues.append(
            "declared validated applicable rules lack affirmative required "
            "passing contribution evidence"
        )

    failed = [
        item for item in blocking if item.condition is CheckCondition.FAILED
    ]
    engineering = [
        item for item in blocking if item.condition.is_engineering_blocker
    ]
    manual = [
        item for item in blocking if item.condition.is_manual_review_blocker
    ]
    manual_flagged = (
        bool(manual) or manual_judgment_flagged or bool(proof_issues)
    )
    not_evaluated = [
        item
        for item in blocking
        if item.condition is CheckCondition.NOT_EVALUATED
    ]

    def _reasons(
        items: Sequence[ReadinessContribution], prefix: str
    ) -> tuple[str, ...]:
        ordered = sorted(items, key=lambda entry: entry.check_id)
        return tuple(
            f"{prefix}: {item.check_id} ({item.condition.value})"
            + (f" -- {item.detail}" if item.detail else "")
            for item in ordered
        )

    prerequisite_values = (
        validated_applicable_rule_count >= 1
        and declared_count_consistent
        and not duplicate_ids
        and not blank_ids
        and bool(required_pass_evidence),
        every_required_passed,
        not manual and not manual_judgment_flagged and not proof_issues,
        not any(
            item.condition is CheckCondition.UNRESOLVED for item in engineering
        ),
        not any(
            item.condition is CheckCondition.RULE_CONFLICT for item in engineering
        ),
        not manual and not manual_judgment_flagged and not proof_issues,
    )
    prerequisites = tuple(
        zip(READY_PREREQUISITES, prerequisite_values, strict=True)
    )

    if failed:
        state = ReadinessState.NOT_READY
        reasons = _reasons(failed, "validated failure")
        # docs/112 section 4.4: secondary blockers are retained in the explanation
        # even when a higher-precedence state wins.
        secondary = (
            _reasons(engineering, "engineering blocker (secondary)")
            + _reasons(manual, "manual blocker (secondary)")
            + tuple(
                f"readiness proof blocker (secondary): {issue}"
                for issue in proof_issues
            )
        )
        reasons = (*reasons, *secondary)
    elif engineering:
        state = ReadinessState.ENGINEERING_REVIEW_REQUIRED
        reasons = _reasons(engineering, "engineering resolution required")
        # docs/112 section 4.4: secondary blockers are retained in the explanation
        # even when a higher-precedence state wins.
        reasons = (
            *reasons,
            *_reasons(manual, "manual blocker (secondary)"),
            *(
                f"readiness proof blocker (secondary): {issue}"
                for issue in proof_issues
            ),
        )
    elif manual_flagged:
        state = ReadinessState.MANUAL_REVIEW_REQUIRED
        explicit_reason = (
            ("explicit manual-judgment condition flagged",)
            if manual_judgment_flagged
            else ()
        )
        reasons = (
            *_reasons(manual, "manual review required"),
            *explicit_reason,
            *(f"readiness proof invalid: {issue}" for issue in proof_issues),
        )
    elif not_evaluated or validated_applicable_rule_count < 1:
        state = ReadinessState.NOT_EVALUATED
        reasons = _reasons(not_evaluated, "not evaluated") or (
            "zero applicable validated engineering rules; no validated basis for readiness",
        )
    elif not persistence_confirmed:
        # documents/112 sections 4.4 and 11.4 and 114 section 14.3: with no
        # safe decision/audit persistence there is no authoritative decision.
        # A would-be READY is refused and routed to controlled manual review;
        # other computed states are preserved verbatim for traceability.
        state = ReadinessState.MANUAL_REVIEW_REQUIRED
        reasons = (
            "READY refused: decision/audit persistence unavailable; result is non-authoritative (manual review required)",
        )
    elif not all(value for _, value in prerequisites):
        state = ReadinessState.MANUAL_REVIEW_REQUIRED
        reasons = (
            "READY refused: prerequisites lack affirmative contribution proof",
        )
    else:
        state = ReadinessState.READY
        reasons = (
            "all required applicable checks passed and every READY prerequisite is satisfied",
        )

    return ReadinessResult(
        state=state,
        reasons=reasons,
        prerequisites=prerequisites,
        authoritative=persistence_confirmed,
    )


@dataclass(frozen=True, slots=True)
class GovernedRuleEvaluationSnapshot:
    """Exact persisted governed rule-evaluation revision snapshot."""

    evaluation_id: str
    revision_number: int
    comparison: Any

    def __post_init__(self) -> None:
        if not self.evaluation_id.strip():
            raise ValueError("evaluation_id must be a non-empty string")
        if self.revision_number <= 0:
            raise ValueError("revision_number must be positive")


@dataclass(frozen=True, slots=True)
class GovernedMachineReadinessCheck:
    """One governed MRC check definition and its pinned evaluation snapshots."""

    check_id: str
    required: bool = True
    evaluations: tuple[GovernedRuleEvaluationSnapshot, ...] | Sequence[
        GovernedRuleEvaluationSnapshot
    ] = ()
    description: str | None = None

    def __post_init__(self) -> None:
        check_id = self.check_id.strip()
        if not check_id:
            raise ValueError("check_id must be a non-empty string")
        evaluations = (
            self.evaluations
            if isinstance(self.evaluations, tuple)
            else tuple(self.evaluations)
        )
        for evaluation in evaluations:
            if not isinstance(evaluation, GovernedRuleEvaluationSnapshot):
                raise TypeError(
                    "evaluations must contain GovernedRuleEvaluationSnapshot values"
                )
        description = self.description.strip() if self.description else None
        object.__setattr__(self, "check_id", check_id)
        object.__setattr__(self, "evaluations", evaluations)
        object.__setattr__(self, "description", description)


@dataclass(frozen=True, slots=True)
class MachineReadinessCheckTrace:
    """Immutable provenance for one governed MRC check."""

    check_id: str
    required: bool
    evaluations: tuple[GovernedRuleEvaluationSnapshot, ...]
    condition: CheckCondition
    reason: str


@dataclass(frozen=True, slots=True)
class MachineReadinessResult:
    """Deterministic, provenance-complete machine readiness aggregate."""

    state: ReadinessState
    reasons: tuple[str, ...]
    prerequisites: tuple[tuple[str, bool], ...]
    context: GovernedApplicabilityContext
    decision_time: datetime
    checks: tuple[MachineReadinessCheckTrace, ...]
    validated_applicable_basis_count: int


def _selected_candidate(
    applicability: GovernedApplicabilityResolution,
):
    for candidate in applicability.candidates:
        if candidate.candidate_id == applicability.selected_candidate_id:
            return candidate
    return None


def _canonicalize_evaluations(
    evaluations: Sequence[GovernedRuleEvaluationSnapshot],
) -> tuple[GovernedRuleEvaluationSnapshot, ...]:
    unique: dict[tuple[str, int], GovernedRuleEvaluationSnapshot] = {}
    for evaluation in evaluations:
        key = (evaluation.evaluation_id, evaluation.revision_number)
        existing = unique.get(key)
        if existing is not None and existing != evaluation:
            raise ValueError(
                "conflicting governed rule-evaluation snapshots supplied for the "
                "same evaluation_id/revision_number"
            )
        unique[key] = evaluation
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.evaluation_id,
                item.revision_number,
                item.comparison.rule_id,
                item.comparison.revision,
                item.comparison.outcome.value,
            ),
        )
    )


def _merge_checks(
    checks: Sequence[GovernedMachineReadinessCheck],
) -> tuple[GovernedMachineReadinessCheck, ...]:
    merged: dict[str, GovernedMachineReadinessCheck] = {}
    for check in checks:
        existing = merged.get(check.check_id)
        if existing is None:
            merged[check.check_id] = check
            continue
        if existing.required != check.required:
            raise ValueError(
                f"conflicting required flag supplied for check_id {check.check_id}"
            )
        if (
            existing.description is not None
            and check.description is not None
            and existing.description != check.description
        ):
            raise ValueError(
                f"conflicting description supplied for check_id {check.check_id}"
            )
        merged[check.check_id] = GovernedMachineReadinessCheck(
            check_id=existing.check_id,
            required=existing.required,
            evaluations=existing.evaluations + check.evaluations,
            description=existing.description or check.description,
        )
    return tuple(sorted(merged.values(), key=lambda item: item.check_id))


def _evaluate_snapshot(
    snapshot: GovernedRuleEvaluationSnapshot,
    *,
    context: GovernedApplicabilityContext,
) -> tuple[CheckCondition, str, bool]:
    comparison = snapshot.comparison
    applicability = comparison.applicability_result
    if applicability is None:
        return (
            CheckCondition.UNRESOLVED,
            "evaluation snapshot is missing the selected applicability result",
            False,
        )
    if applicability.outcome is not ApplicabilityResolutionOutcome.SELECTED:
        return (
            CheckCondition.RULE_CONFLICT,
            f"applicability result must be SELECTED; got {applicability.outcome.value}",
            False,
        )
    if applicability.context != context:
        return (
            CheckCondition.CONTEXT_INSUFFICIENT,
            "applicability context does not exactly match the MRC decision context",
            False,
        )
    if (
        applicability.selected_rule_id is None
        or applicability.selected_revision is None
    ):
        return (
            CheckCondition.UNRESOLVED,
            "selected applicability result is missing the governing rule identity",
            False,
        )
    if (
        applicability.selected_rule_id.strip() != comparison.rule_id.strip()
        or applicability.selected_revision.strip() != comparison.revision.strip()
    ):
        return (
            CheckCondition.UNRESOLVED,
            (
                "selected applicability pin does not match the supplied "
                "rule-evaluation revision identity"
            ),
            False,
        )

    selected = _selected_candidate(applicability)
    if selected is None:
        return (
            CheckCondition.UNRESOLVED,
            "selected applicability result does not carry a selected candidate snapshot",
            False,
        )
    if selected.evidence_class is not EvidenceClass.SOURCE_BACKED:
        return (
            CheckCondition.EVIDENCE_UNAVAILABLE,
            "selected candidate is not SOURCE_BACKED",
            False,
        )
    if not selected.enabled or not selected.active:
        return (
            CheckCondition.EVIDENCE_UNAVAILABLE,
            "selected candidate is not ENABLED and ACTIVE",
            False,
        )
    if selected.suspended or selected.revoked or selected.superseded:
        return (
            CheckCondition.EVIDENCE_UNAVAILABLE,
            "selected candidate basis is suspended, revoked, or superseded",
            False,
        )
    if not selected.basis_valid:
        return (
            CheckCondition.EVIDENCE_UNAVAILABLE,
            "selected candidate basis is invalidated",
            False,
        )
    if (
        selected.effective_from > applicability.decision_time
        or (
            selected.expires_at is not None
            and applicability.decision_time >= selected.expires_at
        )
    ):
        return (
            CheckCondition.EVIDENCE_UNAVAILABLE,
            "selected candidate basis is outside its effective window",
            False,
        )

    if comparison.outcome.value == "SATISFIED":
        return CheckCondition.PASSED, "evaluation snapshot is SATISFIED", True
    if comparison.outcome.value == "NOT_SATISFIED":
        return (
            CheckCondition.FAILED,
            "evaluation snapshot is NOT_SATISFIED",
            True,
        )
    if comparison.outcome.value == "UNRESOLVED":
        return CheckCondition.UNRESOLVED, "evaluation snapshot is UNRESOLVED", False
    if comparison.outcome.value == "UNIT_MISMATCH":
        return (
            CheckCondition.EVIDENCE_UNAVAILABLE,
            "evaluation snapshot has UNIT_MISMATCH",
            False,
        )
    return (
        CheckCondition.NOT_APPLICABLE_VERSION,
        "evaluation snapshot is NOT_APPLICABLE",
        False,
    )


def evaluate_machine_readiness(
    context: GovernedApplicabilityContext,
    decision_time: datetime,
    checks: Sequence[GovernedMachineReadinessCheck],
) -> MachineReadinessResult:
    """Aggregate governed check/evaluation snapshots into one MRC decision."""

    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise ValueError("decision_time must be timezone-aware")

    merged_checks = _merge_checks(checks)
    check_traces: list[MachineReadinessCheckTrace] = []
    valid_applicable_basis_count = 0
    required_satisfied = 0
    required_count = 0
    required_not_ready = False
    required_engineering = False
    required_manual = False
    required_missing = False

    for check in merged_checks:
        canonical_snapshots = _canonicalize_evaluations(check.evaluations)
        if check.required:
            required_count += 1

        if len(canonical_snapshots) > 1:
            condition = CheckCondition.RULE_CONFLICT
            reason = (
                "multiple distinct governed rule-evaluation snapshots were supplied "
                "for the same check"
            )
            if check.required:
                required_engineering = True
            check_traces.append(
                MachineReadinessCheckTrace(
                    check_id=check.check_id,
                    required=check.required,
                    evaluations=canonical_snapshots,
                    condition=condition,
                    reason=reason,
                )
            )
            continue

        if not canonical_snapshots:
            condition = CheckCondition.OBSERVATION_MISSING
            reason = "no governed rule-evaluation snapshot was supplied"
            if check.required:
                required_missing = True
            check_traces.append(
                MachineReadinessCheckTrace(
                    check_id=check.check_id,
                    required=check.required,
                    evaluations=(),
                    condition=condition,
                    reason=reason,
                )
            )
            continue

        snapshot = canonical_snapshots[0]
        condition, reason, basis_valid = _evaluate_snapshot(
            snapshot, context=context
        )
        if basis_valid and condition in (
            CheckCondition.PASSED,
            CheckCondition.FAILED,
        ):
            valid_applicable_basis_count += 1

        if check.required:
            if condition is CheckCondition.PASSED:
                required_satisfied += 1
            elif condition is CheckCondition.FAILED:
                required_not_ready = True
            elif condition in (
                CheckCondition.UNRESOLVED,
                CheckCondition.EVIDENCE_UNAVAILABLE,
                CheckCondition.RULE_CONFLICT,
                CheckCondition.NOT_APPLICABLE_VERSION,
            ):
                required_engineering = True
            elif condition in (
                CheckCondition.CONTEXT_INSUFFICIENT,
                CheckCondition.OBSERVATION_MISSING,
            ):
                required_manual = True
            else:
                required_manual = True

        check_traces.append(
            MachineReadinessCheckTrace(
                check_id=check.check_id,
                required=check.required,
                evaluations=canonical_snapshots,
                condition=condition,
                reason=reason,
            )
        )

    all_required_satisfied = required_count == 0 or required_satisfied == required_count
    any_required_applicable_basis = valid_applicable_basis_count > 0

    if required_not_ready:
        state = ReadinessState.NOT_READY
    elif required_engineering:
        state = ReadinessState.ENGINEERING_REVIEW_REQUIRED
    elif required_manual:
        state = ReadinessState.MANUAL_REVIEW_REQUIRED
    elif required_missing and not any_required_applicable_basis:
        state = ReadinessState.NOT_EVALUATED
    elif required_missing:
        state = ReadinessState.MANUAL_REVIEW_REQUIRED
    elif not any_required_applicable_basis:
        state = ReadinessState.NOT_EVALUATED
    elif not all_required_satisfied:
        state = ReadinessState.MANUAL_REVIEW_REQUIRED
    else:
        state = ReadinessState.READY

    if state is ReadinessState.NOT_READY:
        primary = [
            trace
            for trace in check_traces
            if trace.required and trace.condition is CheckCondition.FAILED
        ]
        secondary_engineering = [
            trace
            for trace in check_traces
            if trace.required
            and trace.condition
            in {
                CheckCondition.UNRESOLVED,
                CheckCondition.EVIDENCE_UNAVAILABLE,
                CheckCondition.RULE_CONFLICT,
                CheckCondition.NOT_APPLICABLE_VERSION,
            }
        ]
        secondary_manual = [
            trace
            for trace in check_traces
            if trace.required
            and trace.condition
            in {
                CheckCondition.CONTEXT_INSUFFICIENT,
                CheckCondition.OBSERVATION_MISSING,
            }
        ]
        reasons = (
            *(
                f"validated failure: {trace.check_id} "
                f"({trace.condition.value})"
                for trace in sorted(primary, key=lambda item: item.check_id)
            ),
            *(
                f"engineering blocker (secondary): {trace.check_id} "
                f"({trace.condition.value})"
                for trace in sorted(
                    secondary_engineering, key=lambda item: item.check_id
                )
            ),
            *(
                f"manual blocker (secondary): {trace.check_id} "
                f"({trace.condition.value})"
                for trace in sorted(secondary_manual, key=lambda item: item.check_id)
            ),
        )
    elif state is ReadinessState.ENGINEERING_REVIEW_REQUIRED:
        primary = [
            trace
            for trace in check_traces
            if trace.required
            and trace.condition
            in {
                CheckCondition.UNRESOLVED,
                CheckCondition.EVIDENCE_UNAVAILABLE,
                CheckCondition.RULE_CONFLICT,
                CheckCondition.NOT_APPLICABLE_VERSION,
            }
        ]
        secondary_manual = [
            trace
            for trace in check_traces
            if trace.required
            and trace.condition
            in {
                CheckCondition.CONTEXT_INSUFFICIENT,
                CheckCondition.OBSERVATION_MISSING,
            }
        ]
        reasons = (
            *(
                f"engineering resolution required: {trace.check_id} "
                f"({trace.condition.value})"
                for trace in sorted(primary, key=lambda item: item.check_id)
            ),
            *(
                f"manual blocker (secondary): {trace.check_id} "
                f"({trace.condition.value})"
                for trace in sorted(secondary_manual, key=lambda item: item.check_id)
            ),
        )
    elif state is ReadinessState.MANUAL_REVIEW_REQUIRED:
        primary = [
            trace
            for trace in check_traces
            if trace.required
            and trace.condition
            in {
                CheckCondition.CONTEXT_INSUFFICIENT,
                CheckCondition.OBSERVATION_MISSING,
            }
        ]
        secondary_engineering = [
            trace
            for trace in check_traces
            if trace.required
            and trace.condition
            in {
                CheckCondition.UNRESOLVED,
                CheckCondition.EVIDENCE_UNAVAILABLE,
                CheckCondition.RULE_CONFLICT,
                CheckCondition.NOT_APPLICABLE_VERSION,
            }
        ]
        reasons = (
            *(
                f"manual review required: {trace.check_id} "
                f"({trace.condition.value})"
                for trace in sorted(primary, key=lambda item: item.check_id)
            ),
            *(
                f"engineering blocker (secondary): {trace.check_id} "
                f"({trace.condition.value})"
                for trace in sorted(
                    secondary_engineering, key=lambda item: item.check_id
                )
            ),
        )
    elif state is ReadinessState.NOT_EVALUATED:
        reasons = (
            "zero applicable validated engineering rules; no validated basis for readiness",
        )
    else:
        reasons = (
            "all required applicable checks passed and every READY prerequisite is satisfied",
        )

    prerequisites = tuple(
        (
            name,
            value,
        )
        for name, value in (
            (READY_PREREQUISITES[0], any_required_applicable_basis),
            (READY_PREREQUISITES[1], all_required_satisfied),
            (
                READY_PREREQUISITES[2],
                not required_engineering and not required_manual and not required_not_ready,
            ),
            (READY_PREREQUISITES[3], not required_engineering),
            (READY_PREREQUISITES[4], not required_engineering),
            (READY_PREREQUISITES[5], not required_manual),
        )
    )

    return MachineReadinessResult(
        state=state,
        reasons=reasons,
        prerequisites=prerequisites,
        context=context,
        decision_time=decision_time,
        checks=tuple(sorted(check_traces, key=lambda item: item.check_id)),
        validated_applicable_basis_count=valid_applicable_basis_count,
    )
