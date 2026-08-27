"""Non-authoritative Registry identity and draft-revision orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.application.governed_audit_service import GovernedAuditService
from app.application.governed_idempotency_service import GovernedIdempotencyService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    RuleLifecycleStatus,
)
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
    CommandResultReference,
    IdempotencyDisposition,
)
from app.domain.rule_registry_types import (
    EvidenceReferenceDraft,
    MissingHandling,
    RuleCategory,
    SafeDefault,
)
from app.domain.verification_types import VerificationDecisionOutcome
from app.models.rule_registry import EngineeringRule, EngineeringRuleRevision
from app.models.verification import EvidenceVerificationDecision
from app.repositories.rule_registry_repository import RuleRegistryRepository


@dataclass(frozen=True, slots=True)
class GovernedAuditMetadata:
    """Caller-supplied metadata supported by the existing audit schema.

    ``idempotency_key`` is trace metadata only.  The current schema does not
    provide authoritative idempotency uniqueness or command deduplication.
    """

    event_id: str
    actor_id: str
    actor_type: str
    reason: str
    correlation_id: str
    schema_version: str
    software_version: str
    canonicalization_version: str
    hash_algorithm: str
    created_at: datetime
    actor_user_id: int | None = None
    actor_role: str | None = None
    authority_scope: Mapping[str, object] | None = None
    idempotency_key: str | None = None
    detail: Mapping[str, object] | None = None


class RuleRegistryService:
    """Coordinate non-authoritative Registry drafts and governed audit."""

    COMMAND_NAMESPACE = "registry.rule.source_backed_promotion"

    def __init__(self, unit_of_work: GovernedUnitOfWork):
        self._unit_of_work = unit_of_work
        self._repository = RuleRegistryRepository(unit_of_work.session)
        self._idempotency = GovernedIdempotencyService(unit_of_work)
        self._audit = GovernedAuditService(unit_of_work)

    def create_identity(
        self,
        *,
        rule_id: str,
        audit: GovernedAuditMetadata,
    ) -> EngineeringRule:
        """Create a stable Registry identity without engineering authority."""
        self._unit_of_work.ensure_open()
        rule = self._repository.create_rule(
            rule_id=rule_id,
            created_by_actor_id=audit.actor_id,
            created_by_user_id=audit.actor_user_id,
        )
        self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type="engineering_rule",
            entity_id=rule_id,
            entity_revision="identity",
            action="CREATE_RULE_IDENTITY",
            prior_content_hash=None,
            new_content_hash=None,
            detail=self._audit_detail(
                audit,
                command="CREATE_RULE_IDENTITY",
                rule_id=rule_id,
            ),
        )
        return rule

    def create_draft_revision(
        self,
        *,
        rule_id: str,
        revision: str,
        name: str,
        evidence_class: EvidenceClass,
        category: RuleCategory,
        parameter: str,
        safe_default: SafeDefault,
        missing_handling: MissingHandling,
        reason_for_change: str,
        version_metadata: ContentVersionMetadata,
        audit: GovernedAuditMetadata,
        evidence_references: Sequence[EvidenceReferenceDraft] = (),
        applicability_metadata: dict | None = None,
        applicability_schema_version: str | None = None,
        description: str | None = None,
        note: str | None = None,
        enabled: bool = False,
    ) -> EngineeringRuleRevision:
        """Create a DRAFT revision; repository authority guards remain final."""
        self._unit_of_work.ensure_open()
        rule = self._repository.get_by_rule_id(rule_id)
        if rule is None:
            raise ValueError(f"engineering rule identity does not exist: {rule_id}")

        rule_revision = self._repository.create_revision(
            engineering_rule=rule,
            revision=revision,
            name=name,
            status=RuleLifecycleStatus.DRAFT,
            evidence_class=evidence_class,
            category=category,
            parameter=parameter,
            safe_default=safe_default,
            missing_handling=missing_handling,
            enabled=enabled,
            reason_for_change=reason_for_change,
            version_metadata=version_metadata,
            created_by_actor_id=audit.actor_id,
            created_by_user_id=audit.actor_user_id,
            evidence_references=evidence_references,
            applicability_metadata=applicability_metadata,
            applicability_schema_version=applicability_schema_version,
            description=description,
            note=note,
        )
        self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type="engineering_rule_revision",
            entity_id=rule_id,
            entity_revision=revision,
            action="CREATE_DRAFT_RULE_REVISION",
            prior_content_hash=None,
            new_content_hash=version_metadata.content_hash,
            detail=self._audit_detail(
                audit,
                command="CREATE_DRAFT_RULE_REVISION",
                rule_id=rule_id,
                revision=revision,
                lifecycle_status=RuleLifecycleStatus.DRAFT.value,
                evidence_class=evidence_class.value,
                enabled=enabled,
            ),
        )
        return rule_revision

    def promote_source_backed(
        self,
        *,
        rule_id: str,
        source_revision: str,
        revision: str,
        version_metadata: ContentVersionMetadata,
        receipt_id: str,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
    ) -> CommandResultReference:
        """Promote one draft revision to SOURCE_BACKED with durable idempotency."""
        self._unit_of_work.ensure_open()
        if command_identity.command_namespace != self.COMMAND_NAMESPACE:
            raise ValueError("source-backed promotion command namespace mismatch")
        if command_identity.command_scope != rule_id:
            raise ValueError("source-backed promotion command scope must match rule_id")
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
                raise RuntimeError("completed source-backed replay has no durable result")
            return decision.result_reference
        if decision.disposition is IdempotencyDisposition.CONFLICT:
            raise ValueError("idempotency conflict for source-backed promotion command")
        if decision.disposition is IdempotencyDisposition.IN_PROGRESS:
            raise RuntimeError("source-backed promotion command is already in progress")
        if audit.actor_type != "user" or audit.actor_user_id is None:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="NON_HUMAN_PROMOTER",
                denial_reason="source-backed promotion requires a human user",
            )

        rule = self._repository.get_by_rule_id(rule_id)
        if rule is None:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="MISSING_RULE_IDENTITY",
                denial_reason="engineering rule identity does not exist",
            )

        source = self._repository.get_revision(rule_id, source_revision)
        if source is None:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="MISSING_SOURCE_REVISION",
                denial_reason="source draft revision does not exist",
            )
        if source.status is not RuleLifecycleStatus.DRAFT:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="SOURCE_REVISION_NOT_DRAFT",
                denial_reason="only a DRAFT revision can be promoted to SOURCE_BACKED",
            )
        if source.evidence_class is EvidenceClass.SOURCE_BACKED:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="SOURCE_ALREADY_BACKED",
                denial_reason="source revision is already SOURCE_BACKED",
            )
        if source.created_by_user_id is None:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="MISSING_SOURCE_SUBMITTER",
                denial_reason="source revision lacks durable human submitter identity",
            )
        if source.created_by_user_id == audit.actor_user_id:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="SEPARATION_OF_DUTIES_VIOLATION",
                denial_reason="source submitter must not execute the promotion",
            )
        if source.revision == revision:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="SOURCE_AND_TARGET_REVISION_MATCH",
                denial_reason="promoted revision must differ from the source revision",
            )

        source_evidence_references = list(source.evidence_references)
        if not source_evidence_references:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="MISSING_EVIDENCE_REFERENCES",
                denial_reason="source-backed promotion requires verified evidence references",
            )

        verified_decisions: list[
            tuple[EvidenceReferenceDraft, EvidenceVerificationDecision]
        ] = []
        source_scope = dict(audit.authority_scope) if audit.authority_scope is not None else None
        if source_scope is None:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="MISSING_AUTHORITY_SCOPE",
                denial_reason="source-backed promotion requires an explicit authority scope",
            )

        for evidence_reference in source_evidence_references:
            verified_decision = self._repository.get_latest_verified_evidence_decision(
                evidence_reference_id=evidence_reference.id
            )
            if verified_decision is None:
                return self._deny_source_backed_promotion(
                    rule_id=rule_id,
                    source_revision=source_revision,
                    revision=revision,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="UNVERIFIED_EVIDENCE_REFERENCE",
                    denial_reason="each source evidence reference must have a VERIFIED decision",
                )
            if verified_decision.decision_outcome is not VerificationDecisionOutcome.VERIFIED:
                return self._deny_source_backed_promotion(
                    rule_id=rule_id,
                    source_revision=source_revision,
                    revision=revision,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="INVALID_VERIFICATION_OUTCOME",
                    denial_reason="each source evidence reference must have a VERIFIED decision",
                )
            if verified_decision.verifier_user_id == audit.actor_user_id:
                return self._deny_source_backed_promotion(
                    rule_id=rule_id,
                    source_revision=source_revision,
                    revision=revision,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="VERIFIER_EXECUTED_PROMOTION",
                    denial_reason="promotion executor must not be the evidence verifier",
                )
            verified_scope = verified_decision.authority_snapshot.get("resource_scope")
            if verified_scope != source_scope:
                return self._deny_source_backed_promotion(
                    rule_id=rule_id,
                    source_revision=source_revision,
                    revision=revision,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="AUTHORITY_SCOPE_MISMATCH",
                    denial_reason="verified evidence scope must match the promotion scope",
                )
            verified_decisions.append((evidence_reference, verified_decision))

        expected_content_hash = self._hash(
            {
                "rule_id": rule_id,
                "source_revision": source.revision,
                "source_revision_id": source.id,
                "target_revision": revision,
                "source_content_hash": source.content_hash,
                "authority_scope": source_scope,
                "evidence_pins": [
                    {
                        "evidence_reference_id": evidence_reference.id,
                        "evidence_id": evidence_reference.evidence_id,
                        "evidence_revision": evidence_reference.evidence_revision,
                        "verification_decision_id": verified_decision.id,
                        "verification_revision_number": verified_decision.revision_number,
                        "verifier_user_id": verified_decision.verifier_user_id,
                    }
                    for evidence_reference, verified_decision in verified_decisions
                ],
            }
        )
        if version_metadata.content_hash != expected_content_hash:
            return self._deny_source_backed_promotion(
                rule_id=rule_id,
                source_revision=source_revision,
                revision=revision,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="CONTENT_HASH_MISMATCH",
                denial_reason="source-backed revision hash must pin the exact evidence revision set",
            )

        promoted_revision = self._repository.create_revision(
            engineering_rule=rule,
            revision=revision,
            name=source.name,
            status=RuleLifecycleStatus.DRAFT,
            evidence_class=EvidenceClass.SOURCE_BACKED,
            category=source.category,
            parameter=source.parameter,
            operator=source.operator,
            min_value=source.min_value,
            max_value=source.max_value,
            unit=source.unit,
            applicability_metadata=source.applicability_metadata,
            applicability_schema_version=source.applicability_schema_version,
            effective_date=source.effective_date,
            expiry_date=source.expiry_date,
            supersedes_revision_id=source.id,
            source_type=source.source_type,
            source_name=source.source_name,
            source_document=source.source_document,
            source_url=source.source_url,
            safe_default=source.safe_default,
            missing_handling=source.missing_handling,
            conflict_handling=source.conflict_handling,
            unit_mismatch_handling=source.unit_mismatch_handling,
            description=source.description,
            note=source.note,
            enabled=False,
            reason_for_change=audit.reason,
            version_metadata=version_metadata,
            created_by_actor_id=audit.actor_id,
            created_by_user_id=audit.actor_user_id,
            evidence_references=tuple(
                EvidenceReferenceDraft(
                    evidence_id=evidence_reference.evidence_id,
                    evidence_revision=evidence_reference.evidence_revision,
                    evidence_class=evidence_reference.evidence_class,
                    lifecycle_status=evidence_reference.lifecycle_status,
                    created_by_actor_id=evidence_reference.created_by_actor_id,
                    created_by_user_id=evidence_reference.created_by_user_id,
                    source_type=evidence_reference.source_type,
                    source_name=evidence_reference.source_name,
                    source_document=evidence_reference.source_document,
                    edition=evidence_reference.edition,
                    section_reference=evidence_reference.section_reference,
                    page_reference=evidence_reference.page_reference,
                    table_reference=evidence_reference.table_reference,
                    reference_uri=evidence_reference.reference_uri,
                    reference_metadata=evidence_reference.reference_metadata,
                    schema_version=evidence_reference.schema_version,
                    hash_algorithm=evidence_reference.hash_algorithm,
                    content_hash=evidence_reference.content_hash,
                )
                for evidence_reference, _verified_decision in verified_decisions
            ),
            allow_source_backed=True,
        )
        self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type="engineering_rule_revision",
            entity_id=rule_id,
            entity_revision=revision,
            action="PROMOTE_SOURCE_BACKED_RULE_REVISION",
            prior_content_hash=source.content_hash,
            new_content_hash=version_metadata.content_hash,
            detail=self._audit_detail(
                audit,
                command="PROMOTE_SOURCE_BACKED_RULE_REVISION",
                rule_id=rule_id,
                source_revision=source.revision,
                source_revision_id=source.id,
                source_revision_content_hash=source.content_hash,
                target_revision=revision,
                evidence_reference_ids=[
                    evidence_reference.id for evidence_reference, _ in verified_decisions
                ],
                verification_decision_ids=[
                    verified_decision.id for _evidence_reference, verified_decision in verified_decisions
                ],
                authority_scope=source_scope,
                promoted_content_hash=version_metadata.content_hash,
            ),
        )
        result = CommandResultReference(
            result_type="engineering_rule_revision",
            result_id=str(promoted_revision.id),
            result_revision=promoted_revision.revision,
        )
        completed = self._idempotency.complete(
            identity=command_identity,
            request_hash=request_hash,
            result_reference=result,
            completed_at=completed_at,
        )
        if completed.result_reference != result:
            raise RuntimeError("source-backed promotion idempotency completion failed")
        return result

    @staticmethod
    def _common_audit_fields(audit: GovernedAuditMetadata) -> dict[str, object]:
        return {
            "event_id": audit.event_id,
            "actor_id": audit.actor_id,
            "actor_type": audit.actor_type,
            "reason": audit.reason,
            "correlation_id": audit.correlation_id,
            "schema_version": audit.schema_version,
            "software_version": audit.software_version,
            "canonicalization_version": audit.canonicalization_version,
            "hash_algorithm": audit.hash_algorithm,
            "created_at": audit.created_at,
            "actor_user_id": audit.actor_user_id,
            "actor_role": audit.actor_role,
            "authority_scope": audit.authority_scope,
            "idempotency_key": audit.idempotency_key,
        }

    @staticmethod
    def _audit_detail(
        audit: GovernedAuditMetadata,
        **command_detail: object,
    ) -> dict[str, object]:
        detail = dict(audit.detail) if audit.detail is not None else {}
        detail.update(command_detail)
        return detail

    @staticmethod
    def _hash(value: object) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _deny_source_backed_promotion(
        self,
        *,
        rule_id: str,
        source_revision: str,
        revision: str,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        denial_code: str,
        denial_reason: str,
    ) -> CommandResultReference:
        denial_event = self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type="engineering_rule_promotion_denial",
            entity_id=rule_id,
            entity_revision=revision,
            action="AUTHORIZE_SOURCE_BACKED_PROMOTION_DENIED",
            prior_content_hash=None,
            new_content_hash=None,
            detail=self._audit_detail(
                audit,
                command="AUTHORIZE_SOURCE_BACKED_PROMOTION_DENIED",
                rule_id=rule_id,
                source_revision=source_revision,
                target_revision=revision,
                denial_code=denial_code,
                denial_reason=denial_reason,
            ),
        )
        result = CommandResultReference(
            result_type="engineering_rule_promotion_denial",
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
            raise RuntimeError("source-backed promotion denial idempotency completion failed")
        return result
