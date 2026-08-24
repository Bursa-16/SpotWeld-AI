"""Threshold-free unit-policy primitives for future rule evaluation.

This module is PURE DOMAIN:
- no web framework imports
- no ORM imports
- no repository / database / session imports
- no I/O and no network access
- deterministic logic only

Design sources:
- docs/111_ENGINEERING_RULE_REGISTRY_DESIGN.md §6.3 (Unit Mismatch Handling)
- docs/112_MACHINE_READINESS_CHECK_DESIGN.md §9 (Unit-safe evaluation)

Policy (fail-closed, per document 111 §6.3):

* identical declared units             -> comparable; evaluate directly;
* different units + governed entry     -> comparable ONLY via the explicitly
  conversion                             supplied snapshot conversion; the
                                         conversion is reported in the result;
* different units, no governed entry   -> ``UNIT_MISMATCH``; never evaluated;
  conversion
* missing / undefined unit information -> ``UNKNOWN_UNIT``; never evaluated.

There is no implicit coercion of any kind. Declared dimensionless values are
supported through :data:`DIMENSIONLESS_UNIT`; an empty or ``None`` unit string
means "unit information is missing", which fails closed instead.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from app.domain.governance_types import ContentVersionMetadata

__all__ = [
    "DIMENSIONLESS_UNIT",
    "ConversionEntry",
    "ConversionProvenance",
    "UnitCompatibility",
    "UnitPolicyCatalog",
    "UnitPolicyContext",
    "UnitPolicyResult",
    "evaluate_unit_policy",
]

DIMENSIONLESS_UNIT = "dimensionless"
"""Explicit sentinel for values declared as unitless by their definition.

Using this sentinel is the only way to compare values that have no physical
unit. An empty or ``None`` unit string means "unit information is missing",
which fails closed instead.
"""


class UnitCompatibility(StrEnum):
    """Outcome of the unit policy for one observed-vs-expected pair."""

    COMPATIBLE = "COMPATIBLE"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    UNKNOWN_UNIT = "UNKNOWN_UNIT"


@dataclass(frozen=True, slots=True)
class ConversionProvenance:
    """Immutable structured trace of unit normalization and conversion.

    This value records deterministic transformation facts only. It does not
    assert that a policy was approved; upstream Registry/application code is
    responsible for supplying a governed snapshot and publishing authority.
    """

    conversion_occurred: bool
    original_value: float | None
    original_unit: str | None
    comparison_value: float | None
    target_unit: str
    factor: float | None
    policy_version: ContentVersionMetadata | None
    rounding_policy: str | None

    def __post_init__(self) -> None:
        if self.conversion_occurred:
            if (
                self.original_value is None
                or not self.original_unit
                or self.comparison_value is None
                or not self.target_unit
                or self.factor is None
                or self.policy_version is None
                or not self.rounding_policy
            ):
                raise ValueError(
                    "completed conversion provenance requires values, units, "
                    "factor, governed policy version, and rounding identity"
                )
        elif self.factor is not None:
            raise ValueError(
                "non-conversion provenance must not contain a conversion factor"
            )


@dataclass(frozen=True, slots=True)
class UnitPolicyResult:
    """Result of applying the unit policy to an observed value and unit.

    ``comparable`` is True only for ``COMPATIBLE``. Both ``UNIT_MISMATCH`` and
    ``UNKNOWN_UNIT`` are fail-closed: the values must not be compared directly.
    ``converted_value`` is populated only when a governed-snapshot conversion
    was applied; it is ``None`` for exact matches, ``UNKNOWN_UNIT``, and
    ``UNIT_MISMATCH``.
    """

    compatibility: UnitCompatibility
    reason: str
    comparable: bool
    provenance: ConversionProvenance
    converted_value: float | None = None

    @property
    def fail_closed(self) -> bool:
        """True when comparison must be refused (incompatible or unknown)."""
        return not self.comparable


@dataclass(frozen=True, slots=True)
class UnitPolicyContext:
    """Immutable governed-snapshot slice for one comparison.

    ``expected_unit`` is the canonical unit declared by the rule revision.
    ``conversion_factors`` is copied into an immutable map. A non-empty map
    requires the existing shared :class:`ContentVersionMetadata` contract and
    an explicit rounding-policy identity. These inputs describe a governed
    snapshot supplied upstream; constructing this pure DTO grants no approval.
    """

    expected_unit: str
    conversion_factors: Mapping[tuple[str, str], float] = field(
        default_factory=dict
    )
    policy_version: ContentVersionMetadata | None = None
    rounding_policy: str | None = None

    def __post_init__(self) -> None:
        expected = _normalize_unit(self.expected_unit)
        copied: dict[tuple[str, str], float] = {}
        for pair, factor in self.conversion_factors.items():
            if len(pair) != 2:
                raise ValueError("conversion key must contain source and target units")
            entry = ConversionEntry(pair[0], pair[1], factor)
            key = (entry.from_unit, entry.to_unit)
            if key in copied:
                raise ValueError(f"duplicate conversion entry for {key}")
            copied[key] = entry.factor
        if self.policy_version is not None and not isinstance(
            self.policy_version, ContentVersionMetadata
        ):
            raise TypeError("policy_version must be ContentVersionMetadata")
        if copied and self.policy_version is None:
            raise ValueError(
                "conversion factors require governed ContentVersionMetadata"
            )
        rounding = (self.rounding_policy or "").strip() or None
        if copied and rounding is None:
            raise ValueError(
                "conversion factors require an explicit rounding-policy identity"
            )
        object.__setattr__(self, "expected_unit", expected)
        object.__setattr__(
            self, "conversion_factors", MappingProxyType(copied)
        )
        object.__setattr__(self, "rounding_policy", rounding)


@dataclass(frozen=True, slots=True)
class ConversionEntry:
    """One neutral structural conversion entry in a governed snapshot.

    ``factor`` multiplies a value expressed in ``from_unit`` to produce the
    equivalent value in ``to_unit``. Construction is fail-closed and
    normalizing: units are stripped and must be non-empty and distinct, the
    factor must be finite and strictly positive, and the dimensionless
    sentinel is refused on either side (dimensionless values have no unit to
    convert; they only ever compare by identical declaration).
    """

    from_unit: str
    to_unit: str
    factor: float

    def __post_init__(self) -> None:
        from_unit = _normalize_unit(self.from_unit)
        to_unit = _normalize_unit(self.to_unit)
        if not from_unit or not to_unit:
            raise ValueError(
                "conversion entry units must be non-empty "
                f"(got from_unit={self.from_unit!r}, to_unit={self.to_unit!r})"
            )
        if from_unit == to_unit:
            raise ValueError(
                "conversion entry must connect two distinct units "
                f"(got {from_unit!r} on both sides)"
            )
        if DIMENSIONLESS_UNIT in (from_unit, to_unit):
            raise ValueError(
                "conversion entry must not involve the dimensionless "
                "sentinel; dimensionless comparisons require identical units"
            )
        if (
            isinstance(self.factor, bool)
            or not isinstance(self.factor, (int, float))
            or not math.isfinite(self.factor)
            or self.factor <= 0
        ):
            raise ValueError(
                "conversion factor must be finite and strictly "
                f"positive (got {self.factor!r})"
            )
        object.__setattr__(self, "from_unit", from_unit)
        object.__setattr__(self, "to_unit", to_unit)


@dataclass(frozen=True, slots=True)
class UnitPolicyCatalog:
    """Immutable input snapshot of a governed unit-conversion catalog.

    The catalog is caller-supplied data, never engineering authority. Its
    version identity directly reuses :class:`ContentVersionMetadata`; no
    free-standing or shadow version token exists here. Upstream governance
    establishes approval before supplying this snapshot. Construction only
    validates and freezes structural data.
    """

    version: ContentVersionMetadata
    rounding_policy: str
    conversions: Sequence[ConversionEntry] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.version, ContentVersionMetadata):
            raise TypeError("unit policy version must be ContentVersionMetadata")
        for name in (
            "schema_version",
            "canonicalization_version",
            "hash_algorithm",
            "content_hash",
            "software_version",
        ):
            if not getattr(self.version, name).strip():
                raise ValueError(f"unit policy version {name} must be non-empty")
        rounding = self.rounding_policy.strip()
        if not rounding:
            raise ValueError("unit policy rounding identity must be non-empty")
        conversions = tuple(self.conversions)
        seen: set[tuple[str, str]] = set()
        for entry in conversions:
            if not isinstance(entry, ConversionEntry):
                raise TypeError("catalog conversions must be ConversionEntry values")
            key = (entry.from_unit, entry.to_unit)
            if key in seen:
                raise ValueError(
                    f"duplicate conversion entry declared for {key}"
                )
            seen.add(key)
        object.__setattr__(self, "rounding_policy", rounding)
        object.__setattr__(self, "conversions", conversions)

    @property
    def supported_pairs(self) -> frozenset[tuple[str, str]]:
        """All governed-snapshot ``(from_unit, to_unit)`` pairs."""
        return frozenset(
            (entry.from_unit, entry.to_unit) for entry in self.conversions
        )

    def context_for(self, expected_unit: str) -> UnitPolicyContext:
        """Derive the policy context expecting ``expected_unit``.

        Only conversions whose declared target equals the normalized
        expected unit are exposed; every other entry stays out of the
        comparison slice, so unexpected directions fail closed exactly as
        when no catalog is supplied at all.
        """
        expected = _normalize_unit(expected_unit)
        mapping = {
            (entry.from_unit, entry.to_unit): entry.factor
            for entry in self.conversions
            if entry.to_unit == expected
        }
        return UnitPolicyContext(
            expected_unit=expected,
            conversion_factors=mapping,
            policy_version=self.version,
            rounding_policy=self.rounding_policy,
        )


def _normalize_unit(unit: str | None) -> str:
    return (unit or "").strip()


def _no_conversion_provenance(
    *,
    observed_value: float | None,
    observed_unit: str | None,
    comparison_value: float | None,
    target_unit: str,
    policy_version: ContentVersionMetadata | None,
) -> ConversionProvenance:
    return ConversionProvenance(
        conversion_occurred=False,
        original_value=observed_value,
        original_unit=observed_unit,
        comparison_value=comparison_value,
        target_unit=target_unit,
        factor=None,
        policy_version=policy_version,
        rounding_policy=None,
    )


def evaluate_unit_policy(
    observed_unit: str | None,
    context: UnitPolicyContext,
    observed_value: float | None = None,
) -> UnitPolicyResult:
    """Apply the fail-closed unit policy to one observed value/unit pair.

    Comparison is allowed (``comparable=True``) only when the normalized units
    are identical — including both sides explicitly declared as
    :data:`DIMENSIONLESS_UNIT` — or when a governed-snapshot conversion exists
    in ``context.conversion_factors``. The observed *value* is required only to
    compute a converted value; it is never required merely to decide
    comparability for identical units.

    Missing (empty/None) unit information always fails closed as
    ``UNKNOWN_UNIT``, even when conversions are declared: absence of unit
    metadata is insufficient input (document 111 §6.3), not a convertible
    difference.
    """
    expected = _normalize_unit(context.expected_unit)
    observed = _normalize_unit(observed_unit)

    if observed == expected:
        if observed == "":
            return UnitPolicyResult(
                compatibility=UnitCompatibility.UNKNOWN_UNIT,
                reason="observed and expected units are both missing/undefined",
                comparable=False,
                provenance=_no_conversion_provenance(
                    observed_value=observed_value,
                    observed_unit=observed_unit,
                    comparison_value=None,
                    target_unit=expected,
                    policy_version=context.policy_version,
                ),
            )
        return UnitPolicyResult(
            compatibility=UnitCompatibility.COMPATIBLE,
            reason=f"units identical ({observed})",
            comparable=True,
            provenance=_no_conversion_provenance(
                observed_value=observed_value,
                observed_unit=observed_unit,
                comparison_value=observed_value,
                target_unit=expected,
                policy_version=context.policy_version,
            ),
        )

    if observed == "" or expected == "":
        return UnitPolicyResult(
            compatibility=UnitCompatibility.UNKNOWN_UNIT,
            reason=(
                "unit information is missing "
                f"(observed={observed!r}, expected={expected!r}); "
                "comparison refused (fail-closed)"
            ),
            comparable=False,
            provenance=_no_conversion_provenance(
                observed_value=observed_value,
                observed_unit=observed_unit,
                comparison_value=None,
                target_unit=expected,
                policy_version=context.policy_version,
            ),
        )

    factor = context.conversion_factors.get((observed, expected))
    if factor is None:
        return UnitPolicyResult(
            compatibility=UnitCompatibility.UNIT_MISMATCH,
            reason=(
                f"units differ ({observed} vs {expected}) and no governed "
                "snapshot conversion is supplied; comparison refused "
                "(fail-closed)"
            ),
            comparable=False,
            provenance=_no_conversion_provenance(
                observed_value=observed_value,
                observed_unit=observed_unit,
                comparison_value=None,
                target_unit=expected,
                policy_version=context.policy_version,
            ),
        )

    if observed_value is None:
        return UnitPolicyResult(
            compatibility=UnitCompatibility.COMPATIBLE,
            reason=(
                f"snapshot conversion declared ({observed} -> {expected}) but "
                "no observed value supplied; converted value unavailable"
            ),
            comparable=True,
            provenance=_no_conversion_provenance(
                observed_value=None,
                observed_unit=observed_unit,
                comparison_value=None,
                target_unit=expected,
                policy_version=context.policy_version,
            ),
        )

    converted_value = observed_value * factor
    return UnitPolicyResult(
        compatibility=UnitCompatibility.COMPATIBLE,
        reason=(
            f"units differ ({observed} vs {expected}); governed snapshot conversion "
            f"applied ({observed} -> {expected}, factor {factor})"
        ),
        comparable=True,
        provenance=ConversionProvenance(
            conversion_occurred=True,
            original_value=observed_value,
            original_unit=observed_unit,
            comparison_value=converted_value,
            target_unit=expected,
            factor=factor,
            policy_version=context.policy_version,
            rounding_policy=context.rounding_policy,
        ),
        converted_value=converted_value,
    )
