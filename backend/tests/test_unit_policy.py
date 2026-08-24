"""Stage 2A tests: threshold-free unit policy primitives.

All values/units are synthetic and non-engineering on purpose.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.domain.governance_types import ContentVersionMetadata
from app.domain.unit_policy import (
    DIMENSIONLESS_UNIT,
    ConversionEntry,
    UnitCompatibility,
    UnitPolicyCatalog,
    UnitPolicyContext,
    evaluate_unit_policy,
)


def _version(label: str = "v1") -> ContentVersionMetadata:
    return ContentVersionMetadata(
        schema_version="schema-1",
        canonicalization_version="canonical-1",
        hash_algorithm="synthetic-hash",
        content_hash=f"synthetic-{label}",
        software_version="software-1",
    )


def _ctx(expected: str, conversions: dict | None = None) -> UnitPolicyContext:
    return UnitPolicyContext(
        expected_unit=expected,
        conversion_factors=conversions or {},
        policy_version=_version() if conversions else None,
        rounding_policy="NO_ROUNDING" if conversions else None,
    )


def test_identical_units_are_comparable_without_value() -> None:
    result = evaluate_unit_policy("synthetic_u", _ctx("synthetic_u"))
    assert result.compatibility is UnitCompatibility.COMPATIBLE
    assert result.comparable
    assert not result.fail_closed
    assert result.converted_value is None


def test_identical_units_after_whitespace_normalization() -> None:
    result = evaluate_unit_policy("  synthetic_u  ", _ctx("synthetic_u"))
    assert result.comparable


def test_different_units_without_conversion_fail_closed() -> None:
    result = evaluate_unit_policy("alpha", _ctx("beta"))
    assert result.compatibility is UnitCompatibility.UNIT_MISMATCH
    assert result.fail_closed
    assert "fail-closed" in result.reason


def test_missing_observed_unit_fails_closed_even_with_declared_conversion() -> None:
    result = evaluate_unit_policy(
        "", _ctx("beta", {("alpha", "beta"): 2.0})
    )
    assert result.compatibility is UnitCompatibility.UNKNOWN_UNIT
    assert result.fail_closed


def test_none_expected_unit_fails_closed() -> None:
    context = UnitPolicyContext(expected_unit="")
    result = evaluate_unit_policy("alpha", context)
    assert result.compatibility is UnitCompatibility.UNKNOWN_UNIT
    assert not result.comparable


def test_both_units_missing_fails_closed() -> None:
    result = evaluate_unit_policy(None, UnitPolicyContext(expected_unit=""))
    assert result.compatibility is UnitCompatibility.UNKNOWN_UNIT
    assert result.fail_closed


def test_governed_snapshot_conversion_is_applied_explicitly() -> None:
    result = evaluate_unit_policy(
        "alpha", _ctx("beta", {("alpha", "beta"): 2.5}), observed_value=4.0
    )
    assert result.comparable
    assert result.converted_value == pytest.approx(10.0)
    assert "snapshot conversion" in result.reason
    assert result.provenance.conversion_occurred is True
    assert result.provenance.original_value == pytest.approx(4.0)
    assert result.provenance.original_unit == "alpha"
    assert result.provenance.comparison_value == pytest.approx(10.0)
    assert result.provenance.target_unit == "beta"
    assert result.provenance.factor == pytest.approx(2.5)
    assert result.provenance.policy_version == _version()
    assert result.provenance.rounding_policy == "NO_ROUNDING"


def test_snapshot_conversion_requires_value_to_convert() -> None:
    result = evaluate_unit_policy(
        "alpha", _ctx("beta", {("alpha", "beta"): 3.0})
    )
    assert result.comparable
    assert result.converted_value is None


def test_reverse_conversion_is_not_implicit() -> None:
    # Only (alpha -> beta) is declared; the reverse direction must fail closed.
    result = evaluate_unit_policy(
        "beta", _ctx("alpha", {("alpha", "beta"): 2.0}), observed_value=1.0
    )
    assert result.compatibility is UnitCompatibility.UNIT_MISMATCH
    assert result.fail_closed


def test_dimensionless_sentinel_is_comparable_when_both_declared() -> None:
    result = evaluate_unit_policy(DIMENSIONLESS_UNIT, _ctx(DIMENSIONLESS_UNIT))
    assert result.compatibility is UnitCompatibility.COMPATIBLE
    assert result.comparable
    assert result.provenance.conversion_occurred is False
    assert result.provenance.factor is None
    assert result.provenance.rounding_policy is None


def test_dimensionless_never_matches_named_unit() -> None:
    result = evaluate_unit_policy(DIMENSIONLESS_UNIT, _ctx("beta"))
    assert result.fail_closed


def test_evaluation_is_deterministic() -> None:
    first = evaluate_unit_policy(
        "alpha", _ctx("beta", {("alpha", "beta"): 2.0}), observed_value=7.0
    )
    second = evaluate_unit_policy(
        "alpha", _ctx("beta", {("alpha", "beta"): 2.0}), observed_value=7.0
    )
    assert first == second


def test_catalog_rejects_incomplete_version_metadata() -> None:
    with pytest.raises(ValueError):
        UnitPolicyCatalog(
            version=ContentVersionMetadata("", "c", "h", "x", "s"),
            rounding_policy="NO_ROUNDING",
        )


def test_catalog_rejects_free_standing_string_version() -> None:
    with pytest.raises(TypeError, match="ContentVersionMetadata"):
        UnitPolicyCatalog(version="v1", rounding_policy="NO_ROUNDING")


def test_conversion_entry_rejects_empty_or_identical_units() -> None:
    with pytest.raises(ValueError):
        ConversionEntry(from_unit="   ", to_unit="beta", factor=2.0)
    with pytest.raises(ValueError):
        ConversionEntry(from_unit="alpha", to_unit="", factor=2.0)
    with pytest.raises(ValueError):
        ConversionEntry(from_unit="alpha", to_unit=" alpha ", factor=2.0)


def test_conversion_entry_rejects_non_positive_or_non_finite_factor() -> None:
    for bad_factor in (0.0, -1.5, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            ConversionEntry(
                from_unit="alpha", to_unit="beta", factor=bad_factor
            )


def test_conversion_entry_rejects_non_numeric_factor() -> None:
    with pytest.raises(ValueError):
        ConversionEntry(from_unit="alpha", to_unit="beta", factor="2.0")


def test_conversion_entry_rejects_dimensionless_sides() -> None:
    with pytest.raises(ValueError):
        ConversionEntry(
            from_unit=DIMENSIONLESS_UNIT, to_unit="beta", factor=2.0
        )
    with pytest.raises(ValueError):
        ConversionEntry(
            from_unit="beta", to_unit=DIMENSIONLESS_UNIT, factor=2.0
        )


def test_conversion_entry_normalizes_whitespace_units() -> None:
    entry = ConversionEntry(
        from_unit=" alpha ", to_unit=" beta ", factor=2.0
    )
    assert (entry.from_unit, entry.to_unit) == ("alpha", "beta")


def test_conversion_entry_is_immutable() -> None:
    entry = ConversionEntry(from_unit="alpha", to_unit="beta", factor=2.0)
    with pytest.raises(FrozenInstanceError):
        entry.factor = 3.0


def test_catalog_rejects_duplicate_pairs_after_normalization() -> None:
    with pytest.raises(ValueError):
        UnitPolicyCatalog(
            version=_version(),
            rounding_policy="NO_ROUNDING",
            conversions=(
                ConversionEntry(from_unit="alpha", to_unit="beta", factor=2.0),
                ConversionEntry(
                    from_unit=" alpha ", to_unit="beta", factor=3.0
                ),
            ),
        )


def test_catalog_context_targets_only_the_expected_unit() -> None:
    catalog = UnitPolicyCatalog(
        version=_version(),
        rounding_policy="NO_ROUNDING",
        conversions=(
            ConversionEntry(from_unit="alpha", to_unit="beta", factor=2.0),
            ConversionEntry(from_unit="gamma", to_unit="delta", factor=4.0),
        ),
    )
    into_beta = catalog.context_for("beta")
    assert into_beta.expected_unit == "beta"
    assert dict(into_beta.conversion_factors) == {("alpha", "beta"): 2.0}

    into_delta = catalog.context_for(" delta ")
    assert into_delta.expected_unit == "delta"
    assert dict(into_delta.conversion_factors) == {
        ("gamma", "delta"): 4.0
    }


def test_catalog_unknown_expected_unit_yields_fail_closed_context() -> None:
    catalog = UnitPolicyCatalog(
        version=_version(),
        rounding_policy="NO_ROUNDING",
        conversions=(
            ConversionEntry(from_unit="alpha", to_unit="beta", factor=2.0),
        ),
    )
    context = catalog.context_for("omega")
    assert dict(context.conversion_factors) == {}
    result = evaluate_unit_policy("alpha", context, observed_value=1.0)
    assert result.compatibility is UnitCompatibility.UNIT_MISMATCH
    assert result.fail_closed


def test_catalog_supported_pairs_reports_normalized_pairs() -> None:
    catalog = UnitPolicyCatalog(
        version=_version(),
        rounding_policy="NO_ROUNDING",
        conversions=(
            ConversionEntry(from_unit="alpha", to_unit="beta", factor=2.0),
        ),
    )
    assert catalog.supported_pairs == frozenset({("alpha", "beta")})


def test_catalog_is_immutable() -> None:
    catalog = UnitPolicyCatalog(
        version=_version(), rounding_policy="NO_ROUNDING"
    )
    with pytest.raises(FrozenInstanceError):
        catalog.version = _version("v2")


def test_catalog_end_to_end_conversion_via_derived_context() -> None:
    catalog = UnitPolicyCatalog(
        version=_version(),
        rounding_policy="NO_ROUNDING",
        conversions=(
            ConversionEntry(
                from_unit="alpha", to_unit="beta", factor=10.0
            ),
        ),
    )
    result = evaluate_unit_policy(
        "alpha", catalog.context_for("beta"), observed_value=1.5
    )
    assert result.comparable
    assert result.converted_value == pytest.approx(15.0)
    assert "snapshot conversion" in result.reason


def test_context_copies_input_mapping_and_exposes_read_only_view() -> None:
    original = {("alpha", "beta"): 2.0}
    context = UnitPolicyContext(
        expected_unit="beta",
        conversion_factors=original,
        policy_version=_version(),
        rounding_policy="NO_ROUNDING",
    )
    original[("alpha", "beta")] = 99.0
    original[("gamma", "beta")] = 3.0
    assert dict(context.conversion_factors) == {("alpha", "beta"): 2.0}
    with pytest.raises(TypeError):
        context.conversion_factors[("alpha", "beta")] = 7.0


def test_context_refuses_anonymous_conversion_authority() -> None:
    with pytest.raises(ValueError, match="ContentVersionMetadata"):
        UnitPolicyContext(
            expected_unit="beta",
            conversion_factors={("alpha", "beta"): 2.0},
            rounding_policy="NO_ROUNDING",
        )


def test_catalog_copies_input_sequence_and_is_hash_stable() -> None:
    entries = [ConversionEntry("alpha", "beta", 2.0)]
    catalog = UnitPolicyCatalog(
        version=_version(),
        rounding_policy="NO_ROUNDING",
        conversions=entries,
    )
    initial_hash = hash(catalog)
    entries.clear()
    assert catalog.conversions == (ConversionEntry("alpha", "beta", 2.0),)
    assert hash(catalog) == initial_hash


def test_conversion_provenance_is_frozen() -> None:
    result = evaluate_unit_policy(
        "alpha", _ctx("beta", {("alpha", "beta"): 2.0}), observed_value=4.0
    )
    with pytest.raises(FrozenInstanceError):
        result.provenance.factor = 5.0
