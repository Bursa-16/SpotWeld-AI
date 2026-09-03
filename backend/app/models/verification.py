from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.domain.verification_types import (
    VerificationCapability,
    VerificationDecisionOutcome,
    VerificationDelegationStatus,
)
from app.models.entities import utc_now
from app.models.governance import ImmutableJSON, portable_enum, protect_immutable_model


class EvidenceVerificationDelegation(Base):
    __tablename__ = "evidence_verification_delegations"
    __table_args__ = (
        UniqueConstraint(
            "delegation_id",
            "revision_number",
            name="uq_evidence_verification_delegations_logical_revision",
        ),
        UniqueConstraint(
            "delegation_id",
            "id",
            name="uq_evidence_verification_delegations_context_internal_id",
        ),
        UniqueConstraint(
            "supersedes_delegation_id",
            name="uq_evidence_verification_delegations_single_successor",
        ),
        ForeignKeyConstraint(
            ["delegation_id", "supersedes_delegation_id"],
            [
                "evidence_verification_delegations.delegation_id",
                "evidence_verification_delegations.id",
            ],
            name="fk_evidence_verification_delegations_delegation_supersession",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_evidence_verification_delegations_positive_revision_number",
        ),
        CheckConstraint(
            "supersedes_delegation_id IS NULL OR supersedes_delegation_id != id",
            name="ck_evidence_verification_delegations_not_self_superseding",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_from",
            name="ck_evidence_verification_delegations_effective_window",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delegation_id: Mapped[str] = mapped_column(String(120))
    revision_number: Mapped[int] = mapped_column(Integer)
    verifier_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    granted_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    capability: Mapped[VerificationCapability] = mapped_column(
        portable_enum(
            VerificationCapability,
            "ck_evidence_verification_delegations_capability",
        )
    )
    scope_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[VerificationDelegationStatus] = mapped_column(
        portable_enum(
            VerificationDelegationStatus,
            "ck_evidence_verification_delegations_status",
        )
    )
    supersedes_delegation_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_actor_id: Mapped[str] = mapped_column(String(200))
    schema_version: Mapped[str] = mapped_column(String(40))
    canonicalization_version: Mapped[str] = mapped_column(String(40))
    hash_algorithm: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(128))
    software_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EvidenceVerificationDecision(Base):
    __tablename__ = "evidence_verification_decisions"
    __table_args__ = (
        UniqueConstraint(
            "verification_id",
            "revision_number",
            name="uq_evidence_verification_decisions_logical_revision",
        ),
        UniqueConstraint(
            "verification_id",
            "id",
            name="uq_evidence_verification_decisions_context_internal_id",
        ),
        UniqueConstraint(
            "supersedes_verification_decision_id",
            name="uq_evidence_verification_decisions_single_successor",
        ),
        ForeignKeyConstraint(
            ["verification_id", "supersedes_verification_decision_id"],
            [
                "evidence_verification_decisions.verification_id",
                "evidence_verification_decisions.id",
            ],
            name="fk_evidence_verification_decisions_verification_supersession",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_evidence_verification_decisions_positive_revision_number",
        ),
        CheckConstraint(
            "supersedes_verification_decision_id IS NULL "
            "OR supersedes_verification_decision_id != id",
            name="ck_evidence_verification_decisions_not_self_superseding",
        ),
        Index(
            "ix_evidence_verification_decisions_delegation_id",
            "evidence_verification_delegation_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    verification_id: Mapped[str] = mapped_column(String(120))
    revision_number: Mapped[int] = mapped_column(Integer)
    evidence_reference_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_references.id", ondelete="RESTRICT"), index=True
    )
    evidence_verification_delegation_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_verification_delegations.id", ondelete="RESTRICT"),
    )
    verifier_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    decision_outcome: Mapped[VerificationDecisionOutcome] = mapped_column(
        portable_enum(
            VerificationDecisionOutcome,
            "ck_evidence_verification_decisions_outcome",
        )
    )
    decision_reason: Mapped[str] = mapped_column(Text)
    authority_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    authority_snapshot_schema_version: Mapped[str] = mapped_column(String(40))
    authority_snapshot_canonicalization_version: Mapped[str] = mapped_column(
        String(40)
    )
    authority_snapshot_hash_algorithm: Mapped[str] = mapped_column(String(40))
    authority_snapshot_content_hash: Mapped[str] = mapped_column(String(128))
    policy_identifier: Mapped[str] = mapped_column(String(80))
    policy_version: Mapped[str] = mapped_column(String(80))
    correlation_id: Mapped[str] = mapped_column(String(120), index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_verification_decision_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_actor_id: Mapped[str] = mapped_column(String(200))
    schema_version: Mapped[str] = mapped_column(String(40))
    canonicalization_version: Mapped[str] = mapped_column(String(40))
    hash_algorithm: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(128))
    software_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


protect_immutable_model(EvidenceVerificationDelegation)
protect_immutable_model(EvidenceVerificationDecision)
