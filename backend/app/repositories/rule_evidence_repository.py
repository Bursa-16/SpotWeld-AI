"""Persistence adapter for append-only non-authoritative evidence revisions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.governance_types import (
    EvidenceClass,
    RegistryAuthorityError,
    RuleLifecycleStatus,
)
from app.domain.rule_registry_types import EvidenceRevisionDraft
from app.models.rule_registry import EngineeringRuleRevision, EvidenceReference


class RuleEvidenceRepository:
    """Persist and read evidence history in a caller-owned transaction."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, evidence_reference_id: int) -> EvidenceReference | None:
        return self.session.get(EvidenceReference, evidence_reference_id)

    def list_history(
        self,
        *,
        engineering_rule_revision_id: int,
        evidence_id: str,
    ) -> list[EvidenceReference]:
        statement = (
            select(EvidenceReference)
            .where(
                EvidenceReference.engineering_rule_revision_id
                == engineering_rule_revision_id,
                EvidenceReference.evidence_id == evidence_id,
            )
            .order_by(EvidenceReference.revision_number, EvidenceReference.id)
        )
        return list(self.session.scalars(statement))

    def create_revision(
        self,
        *,
        engineering_rule_revision_id: int,
        draft: EvidenceRevisionDraft,
    ) -> EvidenceReference:
        if draft.evidence_class == EvidenceClass.SOURCE_BACKED:
            raise RegistryAuthorityError(
                "R2 draft evidence cannot claim SOURCE_BACKED authority"
            )
        if draft.lifecycle_status not in {
            RuleLifecycleStatus.DRAFT,
            RuleLifecycleStatus.REVIEW,
        }:
            raise RegistryAuthorityError(
                "R2 evidence must remain in a non-authoritative draft lifecycle"
            )
        if draft.revision_number <= 0:
            raise ValueError("evidence revision_number must be positive")
        parent = self.session.get(
            EngineeringRuleRevision,
            engineering_rule_revision_id,
        )
        if parent is None:
            raise ValueError("engineering rule revision does not exist")

        history = self.list_history(
            engineering_rule_revision_id=engineering_rule_revision_id,
            evidence_id=draft.evidence_id,
        )
        prior: EvidenceReference | None = None
        if draft.supersedes_evidence_reference_id is None:
            if history:
                raise ValueError(
                    "existing evidence identity requires an explicit prior revision"
                )
            if draft.revision_number != 1:
                raise ValueError("first evidence revision_number must be 1")
        else:
            prior = self.get(draft.supersedes_evidence_reference_id)
            if prior is None:
                raise ValueError("superseded evidence revision does not exist")
            if prior.engineering_rule_revision_id != engineering_rule_revision_id:
                raise ValueError("evidence supersession cannot cross rule revisions")
            if prior.evidence_id != draft.evidence_id:
                raise ValueError("evidence supersession cannot cross evidence identities")
            if draft.revision_number != prior.revision_number + 1:
                raise ValueError("evidence correction must use the next revision_number")
            if any(
                item.supersedes_evidence_reference_id == prior.id for item in history
            ):
                raise ValueError("evidence revision already has a successor")

        reference = EvidenceReference(
            engineering_rule_revision_id=engineering_rule_revision_id,
            evidence_id=draft.evidence_id,
            evidence_revision=draft.evidence_revision,
            revision_number=draft.revision_number,
            supersedes_evidence_reference_id=(
                draft.supersedes_evidence_reference_id
            ),
            availability=draft.availability,
            source_type=draft.source_type,
            source_name=draft.source_name,
            source_document=draft.source_document,
            edition=draft.edition,
            section_reference=draft.section_reference,
            page_reference=draft.page_reference,
            table_reference=draft.table_reference,
            evidence_class=draft.evidence_class,
            lifecycle_status=draft.lifecycle_status,
            reference_uri=draft.reference_uri,
            reference_metadata=draft.reference_metadata,
            schema_version=draft.schema_version,
            hash_algorithm=draft.hash_algorithm,
            content_hash=draft.content_hash,
            verified_by_user_id=None,
            verified_by_actor_id=None,
            verified_at=None,
            approved_by_user_id=None,
            approved_by_actor_id=None,
            approved_at=None,
            created_by_user_id=draft.created_by_user_id,
            created_by_actor_id=draft.created_by_actor_id,
        )
        reference._r2_evidence_revision = True
        self.session.add(reference)
        self.session.flush()
        return reference
