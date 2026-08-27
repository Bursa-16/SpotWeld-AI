"""Governed verification authority orchestration."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.application.governed_audit_service import GovernedAuditService
from app.application.governed_idempotency_service import GovernedIdempotencyService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import GovernedAuditMetadata
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
    CommandResultReference,
    IdempotencyDisposition,
)
from app.domain.verification_types import (
    EvidenceVerificationAuthoritySnapshot,
    EvidenceVerificationCommand,
    EvidenceVerificationDecisionDraft,
    VerificationCapability,
    VerificationDecisionOutcome,
    VerificationDelegationStatus,
)
from app.models.entities import User
from app.models.verification import EvidenceVerificationDelegation
from app.repositories.evidence_verification_repository import (
    EvidenceVerificationRepository,
)


class EvidenceVerificationService:
    """Create immutable VERIFIED decisions or auditable denials only."""

    COMMAND_NAMESPACE = "registry.evidence.verification"
    POLICY_IDENTIFIER = "SDS-115"
    POLICY_VERSION = "0.1 Draft"
    SNAPSHOT_SCHEMA_VERSION = "evidence-verification-authority-snapshot-v1"
    SNAPSHOT_CANONICALIZATION_VERSION = "canonical-v1"
    SNAPSHOT_HASH_ALGORITHM = "sha256"
    ROW_SCHEMA_VERSION = "evidence-verification-v1"
    ROW_CANONICALIZATION_VERSION = "canonical-v1"
    ROW_HASH_ALGORITHM = "sha256"

    def __init__(self, unit_of_work: GovernedUnitOfWork):
        self._unit_of_work = unit_of_work
        self._repository = EvidenceVerificationRepository(unit_of_work.session)
        self._idempotency = GovernedIdempotencyService(unit_of_work)
        self._audit = GovernedAuditService(unit_of_work)

    def verify_evidence(
        self,
        *,
        command: EvidenceVerificationCommand,
        receipt_id: str,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        audit: GovernedAuditMetadata,
        verification_id: str,
        completed_at: datetime,
    ) -> CommandResultReference:
        self._unit_of_work.ensure_open()
        decision = self._idempotency.reserve_or_inspect(
            receipt_id=receipt_id,
            identity=command_identity,
            request_hash=request_hash,
            correlation_id=audit.correlation_id,
            schema_version=audit.schema_version,
            software_version=audit.software_version,
            created_at=audit.created_at,
        )
        if decision.disposition is IdempotencyDisposition.REPLAY:
            if decision.result_reference is None:
                raise RuntimeError("completed verification replay has no durable result")
            return decision.result_reference
        if decision.disposition is IdempotencyDisposition.CONFLICT:
            raise ValueError("idempotency conflict for evidence verification command")
        if decision.disposition is IdempotencyDisposition.IN_PROGRESS:
            raise RuntimeError("evidence verification command is already in progress")

        evidence_reference = self._repository.get_evidence_reference(
            command.evidence_reference_id
        )
        if evidence_reference is None:
            return self._deny(
                command=command,
                evidence_reference_id=command.evidence_reference_id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="MISSING_EVIDENCE_REFERENCE",
                denial_reason="exact evidence reference does not exist",
                command_identity=command_identity,
                request_hash=request_hash,
            )

        verifier = self._repository.session.get(User, command.verifier_user_id)
        if verifier is None or not verifier.is_active:
            return self._deny(
                command=command,
                evidence_reference_id=evidence_reference.id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="MISSING_DURABLE_HUMAN_VERIFIER",
                denial_reason="durable human verifier could not be resolved",
                command_identity=command_identity,
                request_hash=request_hash,
            )

        if evidence_reference.created_by_user_id is None:
            return self._deny(
                command=command,
                evidence_reference_id=evidence_reference.id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="MISSING_SUBMITTER_IDENTITY",
                denial_reason="exact evidence revision lacks durable submitter identity",
                command_identity=command_identity,
                request_hash=request_hash,
                verifier=verifier,
            )
        if evidence_reference.created_by_user_id == command.verifier_user_id:
            return self._deny(
                command=command,
                evidence_reference_id=evidence_reference.id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="SEPARATION_OF_DUTIES_VIOLATION",
                denial_reason="creator/submitter must not verify the same evidence revision",
                command_identity=command_identity,
                request_hash=request_hash,
                verifier=verifier,
            )

        delegation = self._repository.find_matching_delegation(
            verifier_user_id=command.verifier_user_id,
            scope_snapshot=command.requested_scope.as_dict(),
        )
        if delegation is None:
            return self._deny(
                command=command,
                evidence_reference_id=evidence_reference.id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="NO_MATCHING_DELEGATION",
                denial_reason="no scoped verification delegation matches the request",
                command_identity=command_identity,
                request_hash=request_hash,
                verifier=verifier,
            )

        if delegation.capability is not VerificationCapability.EVIDENCE_VERIFICATION:
            return self._deny(
                command=command,
                evidence_reference_id=evidence_reference.id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="INVALID_CAPABILITY",
                denial_reason="delegation does not grant evidence verification capability",
                command_identity=command_identity,
                request_hash=request_hash,
                verifier=verifier,
                delegation=delegation,
            )
        if delegation.status is VerificationDelegationStatus.REVOKED:
            return self._deny(
                command=command,
                evidence_reference_id=evidence_reference.id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="DELEGATION_REVOKED",
                denial_reason="verification delegation has been revoked",
                command_identity=command_identity,
                request_hash=request_hash,
                verifier=verifier,
                delegation=delegation,
            )
        if delegation.status is VerificationDelegationStatus.EXPIRED or (
            self._utc(delegation.expires_at) is not None
            and self._utc(delegation.expires_at) <= self._utc(completed_at)
        ):
            return self._deny(
                command=command,
                evidence_reference_id=evidence_reference.id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="DELEGATION_EXPIRED",
                denial_reason="verification delegation is expired",
                command_identity=command_identity,
                request_hash=request_hash,
                verifier=verifier,
                delegation=delegation,
            )
        if self._utc(completed_at) < self._utc(delegation.effective_from):
            return self._deny(
                command=command,
                evidence_reference_id=evidence_reference.id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="DELEGATION_NOT_YET_EFFECTIVE",
                denial_reason="verification delegation is not yet effective",
                command_identity=command_identity,
                request_hash=request_hash,
                verifier=verifier,
                delegation=delegation,
            )
        if delegation.scope_snapshot != command.requested_scope.as_dict():
            return self._deny(
                command=command,
                evidence_reference_id=evidence_reference.id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="SCOPE_MISMATCH",
                denial_reason="requested scope does not match the effective delegation scope",
                command_identity=command_identity,
                request_hash=request_hash,
                verifier=verifier,
                delegation=delegation,
            )
        if delegation.revoked_by_user_id is not None and delegation.revoked_at is None:
            return self._deny(
                command=command,
                evidence_reference_id=evidence_reference.id,
                verification_id=verification_id,
                audit=audit,
                completed_at=completed_at,
                denial_code="REVOCATION_METADATA_INCOMPLETE",
                denial_reason="revoked delegation lacks a revocation timestamp",
                command_identity=command_identity,
                request_hash=request_hash,
                verifier=verifier,
                delegation=delegation,
            )

        authority_snapshot = EvidenceVerificationAuthoritySnapshot(
            verifier_user_id=verifier.id,
            verifier_role_snapshot=verifier.role,
            capability=VerificationCapability.EVIDENCE_VERIFICATION,
            resource_scope=command.requested_scope,
            delegation_id=delegation.delegation_id,
            delegation_revision_number=delegation.revision_number,
            delegation_status=delegation.status,
            delegation_effective_from=delegation.effective_from,
            delegation_expires_at=delegation.expires_at,
            delegation_revoked_at=delegation.revoked_at,
            policy_identifier=self.POLICY_IDENTIFIER,
            policy_version=self.POLICY_VERSION,
            decision_at=completed_at,
            correlation_id=audit.correlation_id,
            schema_version=self.SNAPSHOT_SCHEMA_VERSION,
            canonicalization_version=self.SNAPSHOT_CANONICALIZATION_VERSION,
            hash_algorithm=self.SNAPSHOT_HASH_ALGORITHM,
            content_hash="",
            software_version=audit.software_version,
        )
        authority_snapshot_hash = self._hash(authority_snapshot.as_dict())
        authority_snapshot = EvidenceVerificationAuthoritySnapshot(
            verifier_user_id=verifier.id,
            verifier_role_snapshot=verifier.role,
            capability=VerificationCapability.EVIDENCE_VERIFICATION,
            resource_scope=command.requested_scope,
            delegation_id=delegation.delegation_id,
            delegation_revision_number=delegation.revision_number,
            delegation_status=delegation.status,
            delegation_effective_from=delegation.effective_from,
            delegation_expires_at=delegation.expires_at,
            delegation_revoked_at=delegation.revoked_at,
            policy_identifier=self.POLICY_IDENTIFIER,
            policy_version=self.POLICY_VERSION,
            decision_at=completed_at,
            correlation_id=audit.correlation_id,
            schema_version=self.SNAPSHOT_SCHEMA_VERSION,
            canonicalization_version=self.SNAPSHOT_CANONICALIZATION_VERSION,
            hash_algorithm=self.SNAPSHOT_HASH_ALGORITHM,
            content_hash=authority_snapshot_hash,
            software_version=audit.software_version,
        )
        decision_row = self._repository.create_verification_decision(
            draft=EvidenceVerificationDecisionDraft(
                verification_id=verification_id,
                revision_number=1,
                evidence_reference_id=evidence_reference.id,
                evidence_verification_delegation_id=delegation.id,
                verifier_user_id=verifier.id,
                authority_snapshot=authority_snapshot.as_dict(),
                decision_reason=command.decision_reason,
                decided_at=completed_at,
                policy_identifier=self.POLICY_IDENTIFIER,
                policy_version=self.POLICY_VERSION,
                correlation_id=audit.correlation_id,
                created_by_user_id=audit.actor_user_id,
                created_by_actor_id=audit.actor_id,
                schema_version=self.ROW_SCHEMA_VERSION,
                canonicalization_version=self.ROW_CANONICALIZATION_VERSION,
                hash_algorithm=self.ROW_HASH_ALGORITHM,
                content_hash=self._hash(
                    {
                        "verification_id": verification_id,
                        "evidence_reference_id": evidence_reference.id,
                        "delegation_id": delegation.id,
                        "verifier_user_id": verifier.id,
                        "decision_reason": command.decision_reason,
                        "authority_snapshot_hash": authority_snapshot_hash,
                        "decision_outcome": VerificationDecisionOutcome.VERIFIED.value,
                        "decided_at": completed_at.isoformat(),
                    }
                ),
                software_version=audit.software_version,
            )
        )
        self._audit.record_event(
            event_id=audit.event_id,
            entity_type="evidence_verification_decision",
            entity_id=verification_id,
            entity_revision=str(decision_row.revision_number),
            action="CREATE_EVIDENCE_VERIFICATION_DECISION",
            actor_id=audit.actor_id,
            actor_type=audit.actor_type,
            reason=command.decision_reason,
            correlation_id=audit.correlation_id,
            schema_version=audit.schema_version,
            software_version=audit.software_version,
            canonicalization_version=audit.canonicalization_version,
            hash_algorithm=audit.hash_algorithm,
            created_at=audit.created_at,
            actor_user_id=audit.actor_user_id,
            actor_role=audit.actor_role,
            authority_scope=command.requested_scope.as_dict(),
            idempotency_key=command_identity.idempotency_key,
            detail={
                "command": "CREATE_EVIDENCE_VERIFICATION_DECISION",
                "evidence_reference_id": evidence_reference.id,
                "verification_id": verification_id,
                "delegation_id": delegation.id,
                "decision_outcome": VerificationDecisionOutcome.VERIFIED.value,
                "authority_snapshot_hash": authority_snapshot_hash,
            },
        )
        result = CommandResultReference(
            result_type="evidence_verification_decision",
            result_id=str(decision_row.id),
            result_revision=str(decision_row.revision_number),
        )
        completed = self._idempotency.complete(
            identity=command_identity,
            request_hash=request_hash,
            result_reference=result,
            completed_at=completed_at,
        )
        if completed.result_reference != result:
            raise RuntimeError("verification command idempotency completion failed")
        return result

    def _deny(
        self,
        *,
        command: EvidenceVerificationCommand,
        evidence_reference_id: int,
        verification_id: str,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
        denial_code: str,
        denial_reason: str,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        verifier: User | None = None,
        delegation: EvidenceVerificationDelegation | None = None,
    ) -> CommandResultReference:
        detail: dict[str, object] = {
            "command": "AUTHORIZE_EVIDENCE_VERIFICATION_DENIED",
            "denial_code": denial_code,
            "denial_reason": denial_reason,
            "evidence_reference_id": evidence_reference_id,
            "verification_id": verification_id,
            "requested_scope": command.requested_scope.as_dict(),
            "verifier_user_id": command.verifier_user_id,
        }
        if verifier is not None:
            detail["verifier_role_snapshot"] = verifier.role
        if delegation is not None:
            detail["delegation_id"] = delegation.id
            detail["delegation_revision_number"] = delegation.revision_number
            detail["delegation_status"] = delegation.status.value
        denial_event = self._audit.record_event(
            event_id=audit.event_id,
            entity_type="evidence_verification_denial",
            entity_id=f"evidence_reference:{evidence_reference_id}",
            entity_revision="denied",
            action="AUTHORIZE_EVIDENCE_VERIFICATION_DENIED",
            actor_id=audit.actor_id,
            actor_type=audit.actor_type,
            reason=denial_reason,
            correlation_id=audit.correlation_id,
            schema_version=audit.schema_version,
            software_version=audit.software_version,
            canonicalization_version=audit.canonicalization_version,
            hash_algorithm=audit.hash_algorithm,
            created_at=audit.created_at,
            actor_user_id=audit.actor_user_id,
            actor_role=audit.actor_role,
            authority_scope=command.requested_scope.as_dict(),
            idempotency_key=command_identity.idempotency_key,
            detail=detail,
        )
        result = CommandResultReference(
            result_type="evidence_verification_denial",
            result_id=str(denial_event.id),
            result_revision="denied",
        )
        completed = self._idempotency.complete(
            identity=command_identity,
            request_hash=request_hash,
            result_reference=result,
            completed_at=completed_at,
        )
        if completed.result_reference != result:
            raise RuntimeError("verification denial idempotency completion failed")
        return result

    @staticmethod
    def _hash(value: object) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
