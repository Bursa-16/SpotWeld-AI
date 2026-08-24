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
from enum import StrEnum

__all__ = [
    "READY_PREREQUISITES",
    "CheckCondition",
    "ReadinessContribution",
    "ReadinessResult",
    "ReadinessState",
    "aggregate_readiness",
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
            "zero applicable validated engineering rules; no validated basis "
            "for readiness",
        )
    elif not persistence_confirmed:
        # documents/112 sections 4.4 and 11.4 and 114 section 14.3: with no
        # safe decision/audit persistence there is no authoritative decision.
        # A would-be READY is refused and routed to controlled manual review;
        # other computed states are preserved verbatim for traceability.
        state = ReadinessState.MANUAL_REVIEW_REQUIRED
        reasons = (
            "READY refused: decision/audit persistence unavailable; result "
            "is non-authoritative (manual review required)",
        )
    elif not all(value for _, value in prerequisites):
        state = ReadinessState.MANUAL_REVIEW_REQUIRED
        reasons = (
            "READY refused: prerequisites lack affirmative contribution proof",
        )
    else:
        state = ReadinessState.READY
        reasons = (
            "all required applicable checks passed and every READY "
            "prerequisite is satisfied",
        )

    return ReadinessResult(
        state=state,
        reasons=reasons,
        prerequisites=prerequisites,
        authoritative=persistence_confirmed,
    )
