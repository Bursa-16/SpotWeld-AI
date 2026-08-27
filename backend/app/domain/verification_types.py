from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class VerificationCapability(StrEnum):
    EVIDENCE_VERIFICATION = "EVIDENCE_VERIFICATION"


class VerificationDelegationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class VerificationDecisionOutcome(StrEnum):
    VERIFIED = "VERIFIED"


@dataclass(frozen=True, slots=True)
class VerificationScopeSnapshot:
    customer: str | None = None
    project: str | None = None
    site: str | None = None
    machine: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "customer": self.customer,
            "project": self.project,
            "site": self.site,
            "machine": self.machine,
        }


@dataclass(frozen=True, slots=True)
class EvidenceVerificationCommand:
    evidence_reference_id: int
    verifier_user_id: int
    requested_scope: VerificationScopeSnapshot
    decision_reason: str


@dataclass(frozen=True, slots=True)
class EvidenceVerificationDelegationDraft:
    delegation_id: str
    revision_number: int
    verifier_user_id: int
    granted_by_user_id: int
    scope_snapshot: VerificationScopeSnapshot
    effective_from: datetime
    expires_at: datetime | None
    revoked_by_user_id: int | None
    revoked_at: datetime | None
    revoked_reason: str | None
    status: VerificationDelegationStatus = VerificationDelegationStatus.ACTIVE
    capability: VerificationCapability = VerificationCapability.EVIDENCE_VERIFICATION
    supersedes_delegation_id: int | None = None
    created_by_user_id: int | None = None
    created_by_actor_id: str = ""
    schema_version: str = ""
    canonicalization_version: str = ""
    hash_algorithm: str = ""
    content_hash: str = ""
    software_version: str = ""


@dataclass(frozen=True, slots=True)
class EvidenceVerificationDecisionDraft:
    verification_id: str
    revision_number: int
    evidence_reference_id: int
    evidence_verification_delegation_id: int
    verifier_user_id: int
    authority_snapshot: dict[str, object]
    decision_reason: str
    decided_at: datetime
    policy_identifier: str
    policy_version: str
    correlation_id: str
    supersedes_verification_decision_id: int | None = None
    created_by_user_id: int | None = None
    created_by_actor_id: str = ""
    schema_version: str = ""
    canonicalization_version: str = ""
    hash_algorithm: str = ""
    content_hash: str = ""
    software_version: str = ""
    decision_outcome: VerificationDecisionOutcome = VerificationDecisionOutcome.VERIFIED


@dataclass(frozen=True, slots=True)
class EvidenceVerificationAuthoritySnapshot:
    verifier_user_id: int
    verifier_role_snapshot: str
    capability: VerificationCapability
    resource_scope: VerificationScopeSnapshot
    delegation_id: str
    delegation_revision_number: int
    delegation_status: VerificationDelegationStatus
    delegation_effective_from: datetime
    delegation_expires_at: datetime | None
    delegation_revoked_at: datetime | None
    policy_identifier: str
    policy_version: str
    decision_at: datetime
    correlation_id: str
    schema_version: str
    canonicalization_version: str
    hash_algorithm: str
    content_hash: str
    software_version: str

    def as_dict(self) -> dict[str, object]:
        return {
            "verifier_user_id": self.verifier_user_id,
            "verifier_role_snapshot": self.verifier_role_snapshot,
            "capability": self.capability.value,
            "resource_scope": self.resource_scope.as_dict(),
            "delegation": {
                "delegation_id": self.delegation_id,
                "revision_number": self.delegation_revision_number,
                "status": self.delegation_status.value,
                "effective_from": self.delegation_effective_from.isoformat(),
                "expires_at": (
                    self.delegation_expires_at.isoformat()
                    if self.delegation_expires_at is not None
                    else None
                ),
                "revoked_at": (
                    self.delegation_revoked_at.isoformat()
                    if self.delegation_revoked_at is not None
                    else None
                ),
            },
            "policy": {
                "identifier": self.policy_identifier,
                "version": self.policy_version,
            },
            "decision_at": self.decision_at.isoformat(),
            "correlation_id": self.correlation_id,
            "integrity": {
                "schema_version": self.schema_version,
                "canonicalization_version": self.canonicalization_version,
                "hash_algorithm": self.hash_algorithm,
                "content_hash": self.content_hash,
                "software_version": self.software_version,
            },
        }
