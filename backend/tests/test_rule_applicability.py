"""Stage 2A tests: threshold-free rule applicability resolution.

Synthetic categorical dimensions only (no engineering values).
"""

from __future__ import annotations

from app.domain.rule_applicability import (
    ApplicabilityOutcome,
    evaluate_applicability,
)

_SCOPE = {
    "machine_type": ["TYPE_A", "TYPE_B"],
    "material_family": ["FAMILY_X"],
}


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
