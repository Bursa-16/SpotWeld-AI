"""Persistence adapter for evidence verification authority foundation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.governance_types import RegistryAuthorityError
from app.domain.verification_types import (
    EvidenceVerificationDecisionDraft,
    EvidenceVerificationDelegationDraft,
    VerificationCapability,
    VerificationDecisionOutcome,
)
from app.models.rule_registry import EvidenceReference
from app.models.verification import (
    EvidenceVerificationDecision,
    EvidenceVerificationDelegation,
)


class EvidenceVerificationRepository:
    """Store and inspect verification authority records in one session."""

    def __init__(self, session: Session):
        self.session = session

    def get_evidence_reference(self, evidence_reference_id: int) -> EvidenceReference | None:
        return self.session.get(EvidenceReference, evidence_reference_id)

    def list_delegation_history(self, delegation_id: str) -> list[EvidenceVerificationDelegation]:
        statement = (
            select(EvidenceVerificationDelegation)
            .where(EvidenceVerificationDelegation.delegation_id == delegation_id)
            .order_by(
                EvidenceVerificationDelegation.revision_number,
                EvidenceVerificationDelegation.id,
            )
        )
        return list(self.session.scalars(statement))

    def find_matching_delegation(
        self,
        *,
        verifier_user_id: int,
        scope_snapshot: dict[str, object],
    ) -> EvidenceVerificationDelegation | None:
        statement = (
            select(EvidenceVerificationDelegation)
            .where(
                EvidenceVerificationDelegation.verifier_user_id == verifier_user_id,
                EvidenceVerificationDelegation.capability
                == VerificationCapability.EVIDENCE_VERIFICATION,
            )
            .order_by(
                EvidenceVerificationDelegation.revision_number.desc(),
                EvidenceVerificationDelegation.id.desc(),
            )
        )
        for delegation in self.session.scalars(statement):
            if delegation.scope_snapshot == scope_snapshot:
                return delegation
        return None

    def create_delegation_revision(
        self,
        *,
        draft: EvidenceVerificationDelegationDraft,
    ) -> EvidenceVerificationDelegation:
        if draft.capability is not VerificationCapability.EVIDENCE_VERIFICATION:
            raise RegistryAuthorityError(
                "verification delegations are evidence-verification only"
            )
        if draft.revision_number <= 0:
            raise ValueError("delegation revision_number must be positive")
        if draft.expires_at is not None and draft.expires_at <= draft.effective_from:
            raise ValueError("delegation expires_at must be after effective_from")

        prior: EvidenceVerificationDelegation | None = None
        if draft.supersedes_delegation_id is not None:
            prior = self.session.get(
                EvidenceVerificationDelegation, draft.supersedes_delegation_id
            )
            if prior is None:
                raise ValueError("superseded delegation revision does not exist")
            if prior.delegation_id != draft.delegation_id:
                raise ValueError(
                    "delegation supersession cannot cross delegation identities"
                )
            if draft.revision_number != prior.revision_number + 1:
                raise ValueError(
                    "delegation correction must use the next revision_number"
                )
            if any(
                item.supersedes_delegation_id == prior.id
                for item in self.list_delegation_history(draft.delegation_id)
            ):
                raise ValueError("delegation revision already has a successor")
        else:
            if self.list_delegation_history(draft.delegation_id):
                raise ValueError(
                    "existing delegation identity requires an explicit prior revision"
                )
            if draft.revision_number != 1:
                raise ValueError("first delegation revision_number must be 1")

        delegation = EvidenceVerificationDelegation(
            delegation_id=draft.delegation_id,
            revision_number=draft.revision_number,
            verifier_user_id=draft.verifier_user_id,
            granted_by_user_id=draft.granted_by_user_id,
            revoked_by_user_id=draft.revoked_by_user_id,
            capability=draft.capability,
            scope_snapshot=draft.scope_snapshot.as_dict(),
            effective_from=draft.effective_from,
            expires_at=draft.expires_at,
            revoked_at=draft.revoked_at,
            revoked_reason=draft.revoked_reason,
            status=draft.status,
            supersedes_delegation_id=draft.supersedes_delegation_id,
            created_by_user_id=draft.created_by_user_id,
            created_by_actor_id=draft.created_by_actor_id,
            schema_version=draft.schema_version,
            canonicalization_version=draft.canonicalization_version,
            hash_algorithm=draft.hash_algorithm,
            content_hash=draft.content_hash,
            software_version=draft.software_version,
        )
        self.session.add(delegation)
        self.session.flush()
        self.session.refresh(delegation)
        self.session.expunge(delegation)
        return delegation

    def list_verification_history(
        self, verification_id: str
    ) -> list[EvidenceVerificationDecision]:
        statement = (
            select(EvidenceVerificationDecision)
            .where(EvidenceVerificationDecision.verification_id == verification_id)
            .order_by(
                EvidenceVerificationDecision.revision_number,
                EvidenceVerificationDecision.id,
            )
        )
        return list(self.session.scalars(statement))

    def create_verification_decision(
        self,
        *,
        draft: EvidenceVerificationDecisionDraft,
    ) -> EvidenceVerificationDecision:
        if draft.revision_number <= 0:
            raise ValueError("verification revision_number must be positive")
        evidence_reference = self.get_evidence_reference(draft.evidence_reference_id)
        if evidence_reference is None:
            raise ValueError("evidence reference does not exist")
        delegation = self.session.get(
            EvidenceVerificationDelegation, draft.evidence_verification_delegation_id
        )
        if delegation is None:
            raise ValueError("verification delegation does not exist")
        if draft.decision_outcome is not VerificationDecisionOutcome.VERIFIED:
            raise RegistryAuthorityError(
                "VERIFIED is the only successful decision outcome"
            )

        prior: EvidenceVerificationDecision | None = None
        if draft.supersedes_verification_decision_id is not None:
            prior = self.session.get(
                EvidenceVerificationDecision,
                draft.supersedes_verification_decision_id,
            )
            if prior is None:
                raise ValueError("superseded verification decision does not exist")
            if prior.verification_id != draft.verification_id:
                raise ValueError(
                    "verification supersession cannot cross verification identities"
                )
            if draft.revision_number != prior.revision_number + 1:
                raise ValueError(
                    "verification correction must use the next revision_number"
                )
            if any(
                item.supersedes_verification_decision_id == prior.id
                for item in self.list_verification_history(draft.verification_id)
            ):
                raise ValueError("verification decision already has a successor")
        else:
            if self.list_verification_history(draft.verification_id):
                raise ValueError(
                    "existing verification identity requires an explicit prior decision"
                )
            if draft.revision_number != 1:
                raise ValueError("first verification revision_number must be 1")

        decision = EvidenceVerificationDecision(
            verification_id=draft.verification_id,
            revision_number=draft.revision_number,
            evidence_reference_id=evidence_reference.id,
            evidence_verification_delegation_id=delegation.id,
            verifier_user_id=draft.verifier_user_id,
            decision_outcome=draft.decision_outcome,
            decision_reason=draft.decision_reason,
            authority_snapshot=draft.authority_snapshot,
            authority_snapshot_schema_version=draft.schema_version,
            authority_snapshot_canonicalization_version=draft.canonicalization_version,
            authority_snapshot_hash_algorithm=draft.hash_algorithm,
            authority_snapshot_content_hash=draft.content_hash,
            policy_identifier=draft.policy_identifier,
            policy_version=draft.policy_version,
            correlation_id=draft.correlation_id,
            decided_at=draft.decided_at,
            supersedes_verification_decision_id=draft.supersedes_verification_decision_id,
            created_by_user_id=draft.created_by_user_id,
            created_by_actor_id=draft.created_by_actor_id,
            schema_version=draft.schema_version,
            canonicalization_version=draft.canonicalization_version,
            hash_algorithm=draft.hash_algorithm,
            content_hash=draft.content_hash,
            software_version=draft.software_version,
        )
        self.session.add(decision)
        self.session.flush()
        self.session.refresh(decision)
        self.session.expunge(decision)
        return decision
