from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.governance_types import EvidenceClass, RuleLifecycleStatus


class RuleCategory(StrEnum):
    EQUIPMENT = "EQUIPMENT"
    MATERIAL = "MATERIAL"
    PARAMETER = "PARAMETER"
    ELECTRODE = "ELECTRODE"
    MACHINE = "MACHINE"
    COOLING = "COOLING"
    OTHER = "OTHER"


class RuleOperator(StrEnum):
    MIN = "MIN"
    MAX = "MAX"
    RANGE = "RANGE"
    EQUALS = "EQUALS"
    DERIVED_MIN = "DERIVED_MIN"
    CUSTOM = "CUSTOM"


class RuleSourceType(StrEnum):
    OEM = "OEM"
    ISO = "ISO"
    AWS = "AWS"
    SEP = "SEP"
    COMPANY_STANDARD = "COMPANY_STANDARD"
    FIELD_MODEL = "FIELD_MODEL"
    LITERATURE = "LITERATURE"
    DERIVED = "DERIVED"


class SafeDefault(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class MissingHandling(StrEnum):
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
    SKIP_OPTIONAL = "SKIP_OPTIONAL"


class EvidenceAvailability(StrEnum):
    """Physical/reference availability only; never an authority assertion."""

    UNKNOWN = "UNKNOWN"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ApplicabilityDimension(StrEnum):
    """Design-approved categorical applicability dimensions for R2 storage."""

    MACHINE = "MACHINE"
    WELD_GUN = "WELD_GUN"
    STATION_ROBOT_OPERATION = "STATION_ROBOT_OPERATION"
    MATERIAL_FAMILY = "MATERIAL_FAMILY"
    SHEET_STACK = "SHEET_STACK"
    ELECTRODE_TIP = "ELECTRODE_TIP"
    PROCESS_PARAMETER_SCHEDULE = "PROCESS_PARAMETER_SCHEDULE"
    CUSTOMER_OEM_CONTEXT = "CUSTOMER_OEM_CONTEXT"
    CATEGORY = "CATEGORY"
    RULE_LIFECYCLE_EFFECTIVE_DATE = "RULE_LIFECYCLE_EFFECTIVE_DATE"
    EQUIPMENT_CONFIGURATION = "EQUIPMENT_CONFIGURATION"


@dataclass(frozen=True, slots=True)
class EvidenceReferenceDraft:
    evidence_id: str
    evidence_revision: str
    evidence_class: EvidenceClass
    lifecycle_status: RuleLifecycleStatus
    created_by_actor_id: str
    created_by_user_id: int | None = None
    source_type: RuleSourceType | None = None
    source_name: str | None = None
    source_document: str | None = None
    edition: str | None = None
    section_reference: str | None = None
    page_reference: str | None = None
    table_reference: str | None = None
    reference_uri: str | None = None
    reference_metadata: dict | None = None
    schema_version: str | None = None
    hash_algorithm: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceRevisionDraft(EvidenceReferenceDraft):
    """Append-only R2 evidence revision and correction input."""

    revision_number: int = 1
    availability: EvidenceAvailability = EvidenceAvailability.UNKNOWN
    supersedes_evidence_reference_id: int | None = None
