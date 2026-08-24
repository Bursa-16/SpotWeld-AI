"""Non-authoritative Registry identity and draft-revision orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.application.governed_audit_service import GovernedAuditService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    RuleLifecycleStatus,
)
from app.domain.rule_registry_types import (
    EvidenceReferenceDraft,
    MissingHandling,
    RuleCategory,
    SafeDefault,
)
from app.models.rule_registry import EngineeringRule, EngineeringRuleRevision
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

    def __init__(self, unit_of_work: GovernedUnitOfWork):
        self._unit_of_work = unit_of_work
        self._repository = RuleRegistryRepository(unit_of_work.session)
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
