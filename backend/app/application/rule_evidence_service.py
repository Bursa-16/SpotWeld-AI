"""Governed orchestration for non-authoritative DRAFT evidence correction."""

from __future__ import annotations

from datetime import datetime

from app.application.governed_audit_service import GovernedAuditService
from app.application.governed_idempotency_service import GovernedIdempotencyService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import GovernedAuditMetadata
from app.domain.governance_types import EvidenceClass, RegistryAuthorityError, RuleLifecycleStatus
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
    CommandResultReference,
    IdempotencyDisposition,
)
from app.domain.rule_registry_types import EvidenceRevisionDraft
from app.repositories.rule_evidence_repository import RuleEvidenceRepository


class RuleEvidenceService:
    """Create immutable draft evidence revisions without granting authority."""

    def __init__(self, unit_of_work: GovernedUnitOfWork):
        self._unit_of_work = unit_of_work
        self._repository = RuleEvidenceRepository(unit_of_work.session)
        self._idempotency = GovernedIdempotencyService(unit_of_work)
        self._audit = GovernedAuditService(unit_of_work)

    def create_draft_revision(
        self,
        *,
        engineering_rule_revision_id: int,
        draft: EvidenceRevisionDraft,
        receipt_id: str,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
    ) -> CommandResultReference:
        """Create one correction, or replay its durable result reference."""
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
                raise RuntimeError("completed evidence replay has no durable result")
            return decision.result_reference
        if decision.disposition is IdempotencyDisposition.CONFLICT:
            raise ValueError("idempotency conflict for evidence revision command")
        if decision.disposition is IdempotencyDisposition.IN_PROGRESS:
            raise RuntimeError("evidence revision command is already in progress")
        if draft.lifecycle_status is not RuleLifecycleStatus.DRAFT:
            raise RegistryAuthorityError(
                "RuleEvidenceService creates DRAFT evidence revisions only"
            )
        if draft.evidence_class is EvidenceClass.SOURCE_BACKED:
            raise RegistryAuthorityError(
                "RuleEvidenceService cannot create SOURCE_BACKED evidence"
            )

        reference = self._repository.create_revision(
            engineering_rule_revision_id=engineering_rule_revision_id,
            draft=draft,
        )
        result = CommandResultReference(
            result_type="evidence_reference",
            result_id=str(reference.id),
            result_revision=str(reference.revision_number),
        )
        self._audit.record_event(
            event_id=audit.event_id,
            entity_type="evidence_reference",
            entity_id=draft.evidence_id,
            entity_revision=str(draft.revision_number),
            action="CREATE_DRAFT_EVIDENCE_REVISION",
            actor_id=audit.actor_id,
            actor_type=audit.actor_type,
            reason=audit.reason,
            correlation_id=audit.correlation_id,
            schema_version=audit.schema_version,
            software_version=audit.software_version,
            canonicalization_version=audit.canonicalization_version,
            hash_algorithm=audit.hash_algorithm,
            created_at=audit.created_at,
            actor_user_id=audit.actor_user_id,
            actor_role=audit.actor_role,
            authority_scope=audit.authority_scope,
            idempotency_key=command_identity.idempotency_key,
            prior_content_hash=(
                self._prior_content_hash(draft.supersedes_evidence_reference_id)
            ),
            new_content_hash=draft.content_hash,
            detail={
                "command": "CREATE_DRAFT_EVIDENCE_REVISION",
                "engineering_rule_revision_id": engineering_rule_revision_id,
                "evidence_id": draft.evidence_id,
                "revision_number": draft.revision_number,
                "supersedes_evidence_reference_id": (
                    draft.supersedes_evidence_reference_id
                ),
                "availability": draft.availability.value,
                "evidence_class": draft.evidence_class.value,
                "lifecycle_status": draft.lifecycle_status.value,
            },
        )
        completed = self._idempotency.complete(
            identity=command_identity,
            request_hash=request_hash,
            result_reference=result,
            completed_at=completed_at,
        )
        if completed.disposition not in {
            IdempotencyDisposition.COMPLETED,
            IdempotencyDisposition.REPLAY,
        }:
            raise RuntimeError("evidence command idempotency completion failed")
        return result

    def _prior_content_hash(self, prior_id: int | None) -> str | None:
        if prior_id is None:
            return None
        prior = self._repository.get(prior_id)
        return prior.content_hash if prior is not None else None
