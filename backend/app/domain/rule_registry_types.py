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
