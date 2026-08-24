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
from enum import StrEnum


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
