from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    RegistryAuthorityError,
    RuleLifecycleStatus,
)
from app.domain.rule_registry_types import (
    EvidenceReferenceDraft,
    MissingHandling,
    RuleCategory,
    RuleOperator,
    RuleSourceType,
    SafeDefault,
)
from app.domain.verification_types import VerificationDecisionOutcome
from app.models.rule_registry import (
    EngineeringRule,
    EngineeringRuleRevision,
    EvidenceReference,
)
from app.models.verification import EvidenceVerificationDecision


class RuleRegistryRepository:
    """Threshold-free Registry persistence under a caller-owned transaction."""

    def __init__(self, session: Session):
        self.session = session

    def create_rule(
        self,
        *,
        rule_id: str,
        created_by_actor_id: str,
        created_by_user_id: int | None = None,
    ) -> EngineeringRule:
        rule = EngineeringRule(
            rule_id=rule_id,
            created_by_user_id=created_by_user_id,
            created_by_actor_id=created_by_actor_id,
        )
        self.session.add(rule)
        self.session.flush()
        return rule

    def create_revision(
        self,
        *,
        engineering_rule: EngineeringRule,
        revision: str,
        name: str,
        status: RuleLifecycleStatus,
        evidence_class: EvidenceClass,
        category: RuleCategory,
        parameter: str,
        safe_default: SafeDefault,
        missing_handling: MissingHandling,
        enabled: bool,
        reason_for_change: str,
        version_metadata: ContentVersionMetadata,
        created_by_actor_id: str,
        created_by_user_id: int | None = None,
        evidence_references: Sequence[EvidenceReferenceDraft] = (),
        allow_source_backed: bool = False,
        operator: RuleOperator | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        unit: str | None = None,
        applicability_metadata: dict | None = None,
        applicability_schema_version: str | None = None,
        effective_date: datetime | None = None,
        expiry_date: datetime | None = None,
        supersedes_revision_id: int | None = None,
        source_type: RuleSourceType | None = None,
        source_name: str | None = None,
        source_document: str | None = None,
        source_url: str | None = None,
        conflict_handling: str | None = None,
        unit_mismatch_handling: str | None = None,
        description: str | None = None,
        note: str | None = None,
    ) -> EngineeringRuleRevision:
        if evidence_class == EvidenceClass.SOURCE_BACKED and not allow_source_backed:
            raise RegistryAuthorityError(
                "SOURCE_BACKED creation requires a later governed evidence workflow"
            )
        if enabled:
            raise RegistryAuthorityError(
                "enabled Registry revisions are unavailable in the Phase 1 foundation"
            )
        for evidence in evidence_references:
            if evidence.evidence_class == EvidenceClass.SOURCE_BACKED:
                raise RegistryAuthorityError(
                    "SOURCE_BACKED evidence requires a later governed verification workflow"
                )
            if evidence.lifecycle_status not in {
                RuleLifecycleStatus.DRAFT,
                RuleLifecycleStatus.REVIEW,
            }:
                raise RegistryAuthorityError(
                    "only unverified DRAFT or REVIEW evidence is accepted in Phase 1"
                )
        if engineering_rule not in self.session:
            raise ValueError("engineering rule must belong to this repository session")
        if engineering_rule.id is None:
            self.session.flush()

        if supersedes_revision_id is not None:
            superseded = self.session.get(EngineeringRuleRevision, supersedes_revision_id)
            if superseded is None:
                raise ValueError("superseded revision does not exist")
            if superseded.engineering_rule_id != engineering_rule.id:
                raise ValueError("a revision can supersede only a revision of the same rule")

        rule_revision = EngineeringRuleRevision(
            engineering_rule_id=engineering_rule.id,
            revision=revision,
            name=name,
            status=status,
            evidence_class=evidence_class,
            category=category,
            parameter=parameter,
            operator=operator,
            min_value=min_value,
            max_value=max_value,
            unit=unit,
            applicability_metadata=applicability_metadata,
            applicability_schema_version=applicability_schema_version,
            effective_date=effective_date,
            expiry_date=expiry_date,
            supersedes_revision_id=supersedes_revision_id,
            source_type=source_type,
            source_name=source_name,
            source_document=source_document,
            source_url=source_url,
            safe_default=safe_default,
            missing_handling=missing_handling,
            conflict_handling=conflict_handling,
            unit_mismatch_handling=unit_mismatch_handling,
            description=description,
            note=note,
            enabled=enabled,
            reason_for_change=reason_for_change,
            schema_version=version_metadata.schema_version,
            canonicalization_version=version_metadata.canonicalization_version,
            hash_algorithm=version_metadata.hash_algorithm,
            content_hash=version_metadata.content_hash,
            software_version=version_metadata.software_version,
            created_by_user_id=created_by_user_id,
            created_by_actor_id=created_by_actor_id,
        )
        if evidence_class == EvidenceClass.SOURCE_BACKED:
            rule_revision._allow_source_backed_revision = True
        self.session.add(rule_revision)

        for evidence in evidence_references:
            reference = EvidenceReference(
                engineering_rule_revision=rule_revision,
                evidence_id=evidence.evidence_id,
                evidence_revision=evidence.evidence_revision,
                source_type=evidence.source_type,
                source_name=evidence.source_name,
                source_document=evidence.source_document,
                edition=evidence.edition,
                section_reference=evidence.section_reference,
                page_reference=evidence.page_reference,
                table_reference=evidence.table_reference,
                evidence_class=evidence.evidence_class,
                lifecycle_status=evidence.lifecycle_status,
                reference_uri=evidence.reference_uri,
                reference_metadata=evidence.reference_metadata,
                schema_version=evidence.schema_version,
                hash_algorithm=evidence.hash_algorithm,
                content_hash=evidence.content_hash,
                verified_by_user_id=None,
                verified_by_actor_id=None,
                verified_at=None,
                approved_by_user_id=None,
                approved_by_actor_id=None,
                approved_at=None,
                created_by_user_id=evidence.created_by_user_id,
                created_by_actor_id=evidence.created_by_actor_id,
            )
            self.session.add(reference)
        self.session.flush()
        self.session.expire(engineering_rule, ["revisions"])
        return rule_revision

    def get_latest_verified_evidence_decision(
        self,
        *,
        evidence_reference_id: int,
    ) -> EvidenceVerificationDecision | None:
        statement = (
            select(EvidenceVerificationDecision)
            .where(
                EvidenceVerificationDecision.evidence_reference_id
                == evidence_reference_id,
                EvidenceVerificationDecision.decision_outcome
                == VerificationDecisionOutcome.VERIFIED,
            )
            .order_by(
                EvidenceVerificationDecision.revision_number.desc(),
                EvidenceVerificationDecision.id.desc(),
            )
        )
        return self.session.scalar(statement)

    def get_by_rule_id(self, rule_id: str) -> EngineeringRule | None:
        return self.session.scalar(
            select(EngineeringRule).where(EngineeringRule.rule_id == rule_id)
        )

    def get_revision(
        self,
        rule_id: str,
        revision: str,
    ) -> EngineeringRuleRevision | None:
        statement = (
            select(EngineeringRuleRevision)
            .join(EngineeringRule)
            .where(
                EngineeringRule.rule_id == rule_id,
                EngineeringRuleRevision.revision == revision,
            )
        )
        return self.session.scalar(statement)

    def list_revisions(self, rule_id: str) -> list[EngineeringRuleRevision]:
        statement = (
            select(EngineeringRuleRevision)
            .join(EngineeringRule)
            .where(EngineeringRule.rule_id == rule_id)
            .order_by(EngineeringRuleRevision.created_at, EngineeringRuleRevision.id)
        )
        return list(self.session.scalars(statement))
