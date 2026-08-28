"""Stage 2A tests: threshold-free rule applicability resolution.

Synthetic categorical dimensions only (no engineering values).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest
from app.domain.rule_applicability import (
    ApplicabilityOutcome,
    ApplicabilityResolutionOutcome,
    GovernedApplicabilityCandidate,
    GovernedApplicabilityContext,
    evaluate_applicability,
    resolve_governed_applicability,
)

_SCOPE = {
    "machine_type": ["TYPE_A", "TYPE_B"],
    "material_family": ["FAMILY_X"],
}

_DECISION_TIME = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


def _candidate(
    candidate_id: str,
    *,
    scope: dict[str, list[str]],
    rule_id: str | None = None,
    revision: str = "1.0",
    enabled: bool = True,
    active: bool = True,
    evidence_class=None,
    effective_from: datetime | None = None,
    expires_at: datetime | None = None,
    suspended: bool = False,
    revoked: bool = False,
    superseded: bool = False,
    basis_valid: bool = True,
) -> GovernedApplicabilityCandidate:
    from app.domain.governance_types import EvidenceClass

    return GovernedApplicabilityCandidate(
        candidate_id=candidate_id,
        rule_id=rule_id or candidate_id,
        revision=revision,
        evidence_class=evidence_class or EvidenceClass.SOURCE_BACKED,
        enabled=enabled,
        active=active,
        scope_snapshot=scope,
        effective_from=effective_from or (_DECISION_TIME - timedelta(days=1)),
        expires_at=expires_at,
        suspended=suspended,
        revoked=revoked,
        superseded=superseded,
        basis_valid=basis_valid,
    )


def _context(
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


def test_all_constraints_satisfied_is_applicable() -> None:
    context = {"machine_type": "TYPE_A", "material_family": "FAMILY_X"}
    result = evaluate_applicability(_SCOPE, context)
    assert result.outcome is ApplicabilityOutcome.APPLICABLE
    assert result.matched_keys == ("machine_type", "material_family")
    assert result.unsatisfied_keys == ()
    assert result.missing_keys == ()


def test_empty_scope_is_applicable() -> None:
    result = evaluate_applicability({}, {"anything": "VALUE"})
    assert result.outcome is ApplicabilityOutcome.APPLICABLE


def test_none_scope_value_means_unconstrained() -> None:
    scope = {"machine_type": None}
    context = {"machine_type": "WHATEVER"}
    result = evaluate_applicability(scope, context)
    assert result.outcome is ApplicabilityOutcome.APPLICABLE
    assert result.matched_keys == ("machine_type",)


def test_context_outside_allowed_set_is_not_applicable() -> None:
    context = {"machine_type": "TYPE_C", "material_family": "FAMILY_X"}
    result = evaluate_applicability(_SCOPE, context)
    assert result.outcome is ApplicabilityOutcome.NOT_APPLICABLE
    assert result.unsatisfied_keys == ("machine_type",)
    assert result.matched_keys == ("material_family",)


def test_missing_context_key_never_resolves_to_applicable() -> None:
    context = {"machine_type": "TYPE_A"}  # material_family missing
    result = evaluate_applicability(_SCOPE, context)
    assert result.outcome is ApplicabilityOutcome.UNRESOLVED
    assert result.missing_keys == ("material_family",)


def test_none_context_value_is_unresolved() -> None:
    context = {"machine_type": None, "material_family": "FAMILY_X"}
    result = evaluate_applicability(_SCOPE, context)
    assert result.outcome is ApplicabilityOutcome.UNRESOLVED


def test_blank_context_value_is_unresolved() -> None:
    context = {"machine_type": "   ", "material_family": "FAMILY_X"}
    result = evaluate_applicability(_SCOPE, context)
    assert result.outcome is ApplicabilityOutcome.UNRESOLVED
    assert result.missing_keys == ("machine_type",)


def test_not_applicable_takes_precedence_over_unresolved() -> None:
    # machine_type contradicts AND material_family is missing.
    context = {"machine_type": "TYPE_C"}
    result = evaluate_applicability(_SCOPE, context)
    assert result.outcome is ApplicabilityOutcome.NOT_APPLICABLE
    assert result.unsatisfied_keys == ("machine_type",)
    assert result.missing_keys == ("material_family",)


def test_reason_names_the_deciding_dimensions_deterministically() -> None:
    scope = {"b_dim": ["V1"], "a_dim": ["V1"], "c_dim": ["OTHER"]}
    first = evaluate_applicability(scope, {})
    second = evaluate_applicability(dict(reversed(list(scope.items()))), {})
    assert first == second
    assert "a_dim" in first.reason and "c_dim" in first.reason


def test_membership_matching_is_exact_string_equality() -> None:
    context = {"machine_type": "type_a", "material_family": "FAMILY_X"}
    result = evaluate_applicability(_SCOPE, context)
    assert result.outcome is ApplicabilityOutcome.NOT_APPLICABLE


def test_repeated_evaluation_is_deterministic() -> None:
    context = {"machine_type": "TYPE_B", "material_family": "FAMILY_X"}
    assert evaluate_applicability(_SCOPE, context) == evaluate_applicability(
        _SCOPE, context
    )


def test_single_winner_selects_matching_candidate() -> None:
    candidate = _candidate(
        "rule-a:1",
        rule_id="rule-a",
        scope={"customer": ["customer-a"], "project": ["project-a"]},
    )
    resolution = resolve_governed_applicability(_context(), _DECISION_TIME, [candidate])

    assert resolution.outcome is ApplicabilityResolutionOutcome.SELECTED
    assert resolution.selected_candidate_id == "rule-a:1"
    assert resolution.selected_rule_id == "rule-a"
    assert resolution.selected_revision == "1.0"
    assert resolution.selected_specificity == 2
    assert resolution.candidates[0].scope_result is not None
    assert resolution.candidates[0].scope_result.outcome is ApplicabilityOutcome.APPLICABLE


def test_non_enabled_candidate_is_ineligible() -> None:
    resolution = resolve_governed_applicability(
        _context(),
        _DECISION_TIME,
        [
            _candidate(
                "rule-b:1",
                scope={"customer": ["customer-a"]},
                enabled=False,
            )
        ],
    )

    assert resolution.outcome is ApplicabilityResolutionOutcome.UNRESOLVED
    assert "ENABLED" in resolution.candidates[0].eligibility_reasons[0]


def test_non_active_candidate_is_ineligible() -> None:
    resolution = resolve_governed_applicability(
        _context(),
        _DECISION_TIME,
        [
            _candidate(
                "rule-c:1",
                scope={"customer": ["customer-a"]},
                active=False,
            )
        ],
    )

    assert resolution.outcome is ApplicabilityResolutionOutcome.UNRESOLVED
    assert "ACTIVE" in resolution.candidates[0].eligibility_reasons[0]


@pytest.mark.parametrize(
    ("effective_from", "expires_at"),
    [
        (_DECISION_TIME + timedelta(days=1), None),
        (_DECISION_TIME - timedelta(days=2), _DECISION_TIME - timedelta(days=1)),
    ],
)
def test_effective_window_fail_closed_for_not_yet_effective_and_expired_candidates(
    effective_from: datetime,
    expires_at: datetime | None,
) -> None:
    resolution = resolve_governed_applicability(
        _context(),
        _DECISION_TIME,
        [
            _candidate(
                "rule-d:1",
                scope={"customer": ["customer-a"]},
                effective_from=effective_from,
                expires_at=expires_at,
            )
        ],
    )

    assert resolution.outcome is ApplicabilityResolutionOutcome.UNRESOLVED
    assert any("effective_from" in reason or "expires_at" in reason for reason in resolution.candidates[0].eligibility_reasons)


def test_invalid_basis_is_rejected() -> None:
    resolution = resolve_governed_applicability(
        _context(),
        _DECISION_TIME,
        [
            _candidate(
                "rule-e:1",
                scope={"customer": ["customer-a"]},
                basis_valid=False,
            )
        ],
    )

    assert resolution.outcome is ApplicabilityResolutionOutcome.UNRESOLVED
    assert "invalidated" in resolution.candidates[0].eligibility_reasons[0]


def test_zero_match_is_unresolved() -> None:
    resolution = resolve_governed_applicability(
        _context(customer="customer-x"),
        _DECISION_TIME,
        [
            _candidate(
                "rule-f:1",
                scope={"customer": ["customer-a"]},
            )
        ],
    )

    assert resolution.outcome is ApplicabilityResolutionOutcome.UNRESOLVED
    assert resolution.selected_candidate_id is None


def test_equal_specificity_matches_conflict() -> None:
    resolution = resolve_governed_applicability(
        _context(),
        _DECISION_TIME,
        [
            _candidate("rule-g:1", scope={"customer": ["customer-a"], "project": ["project-a"]}),
            _candidate("rule-h:1", scope={"customer": ["customer-a"], "project": ["project-a"]}),
        ],
    )

    assert resolution.outcome is ApplicabilityResolutionOutcome.CONFLICT
    assert resolution.conflict_candidate_ids == ("rule-g:1", "rule-h:1")


def test_more_specific_explicit_scope_wins() -> None:
    resolution = resolve_governed_applicability(
        _context(),
        _DECISION_TIME,
        [
            _candidate("rule-i:1", scope={"customer": ["customer-a"]}),
            _candidate(
                "rule-i:2",
                scope={"customer": ["customer-a"], "project": ["project-a"]},
                revision="2.0",
            ),
        ],
    )

    assert resolution.outcome is ApplicabilityResolutionOutcome.SELECTED
    assert resolution.selected_candidate_id == "rule-i:2"
    assert resolution.selected_specificity == 2


def test_missing_and_unsupported_scope_are_fail_closed() -> None:
    resolution = resolve_governed_applicability(
        _context(site=None),
        _DECISION_TIME,
        [
            _candidate(
                "rule-j:1",
                scope={"customer": ["customer-a"], "site": ["site-a"]},
            )
        ],
    )

    assert resolution.outcome is ApplicabilityResolutionOutcome.UNRESOLVED
    assert resolution.candidates[0].scope_result is not None
    assert resolution.candidates[0].scope_result.outcome is ApplicabilityOutcome.UNRESOLVED

    with pytest.raises(ValueError, match="unsupported governed scope dimension"):
        _candidate("rule-j-unsupported:1", scope={"region": ["emea"]})


def test_empty_scope_is_rejected_no_wildcard_fallback() -> None:
    with pytest.raises(ValueError, match="at least one explicit scope dimension"):
        _candidate("rule-k:1", scope={})


def test_candidate_ordering_does_not_change_resolution() -> None:
    first = _candidate("rule-l:1", scope={"customer": ["customer-a"]})
    second = _candidate(
        "rule-l:2",
        scope={"customer": ["customer-a"], "project": ["project-a"]},
        revision="2.0",
    )

    ordered = resolve_governed_applicability(_context(), _DECISION_TIME, [first, second])
    reversed_resolution = resolve_governed_applicability(
        _context(),
        _DECISION_TIME,
        [second, first],
    )

    assert ordered == reversed_resolution
    assert ordered.candidates[0].candidate_id == "rule-l:1"
    assert ordered.candidates[1].candidate_id == "rule-l:2"


def test_resolution_result_is_immutable_and_provenance_complete() -> None:
    resolution = resolve_governed_applicability(
        _context(),
        _DECISION_TIME,
        [
            _candidate(
                "rule-m:1",
                scope={"customer": ["customer-a"], "project": ["project-a"]},
            )
        ],
    )

    with pytest.raises(FrozenInstanceError):
        resolution.reason = "changed"  # type: ignore[misc]
    assert resolution.candidates[0].candidate_id == "rule-m:1"
    assert resolution.candidates[0].scope_snapshot == (
        ("customer", ("customer-a",)),
        ("project", ("project-a",)),
    )
    assert resolution.candidates[0].scope_result is not None
    assert resolution.candidates[0].eligibility_reasons == ()
