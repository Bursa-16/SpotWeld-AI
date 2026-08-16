from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvidenceClass(StrEnum):
    SOURCE_BACKED = "SOURCE_BACKED"
    PROPOSED = "PROPOSED"
    UNRESOLVED = "UNRESOLVED"


class RuleLifecycleStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DEPRECATED = "DEPRECATED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class ContentVersionMetadata:
    schema_version: str
    canonicalization_version: str
    hash_algorithm: str
    content_hash: str
    software_version: str


class ImmutableRecordError(RuntimeError):
    """Raised when append-only governed persistence is changed destructively."""


class RegistryAuthorityError(ValueError):
    """Raised when Phase 1 persistence is asked to create engineering authority."""
