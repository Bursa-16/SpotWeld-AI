from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship

from app.db.session import Base
from app.domain.governance_types import (
    EvidenceClass,
    RegistryAuthorityError,
    RuleLifecycleStatus,
)
from app.domain.rule_registry_types import (
    MissingHandling,
    RuleCategory,
    RuleOperator,
    RuleSourceType,
    SafeDefault,
)
from app.models.entities import utc_now
from app.models.governance import (
    ImmutableJSON,
    freeze_json_attribute,
    portable_enum,
    protect_immutable_model,
)


class EngineeringRule(Base):
    __tablename__ = "engineering_rules"
    __table_args__ = (
        UniqueConstraint("rule_id", name="uq_engineering_rules_rule_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(120))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_actor_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    revisions: Mapped[list["EngineeringRuleRevision"]] = relationship(
        order_by="EngineeringRuleRevision.id",
        viewonly=True,
    )


class EngineeringRuleRevision(Base):
    __tablename__ = "engineering_rule_revisions"
    __table_args__ = (
        UniqueConstraint(
            "engineering_rule_id",
            "revision",
            name="uq_engineering_rule_revisions_rule_revision",
        ),
        UniqueConstraint(
            "engineering_rule_id",
            "id",
            name="uq_engineering_rule_revisions_rule_internal_id",
        ),
        ForeignKeyConstraint(
            ["engineering_rule_id", "supersedes_revision_id"],
            [
                "engineering_rule_revisions.engineering_rule_id",
                "engineering_rule_revisions.id",
            ],
            name="fk_engineering_rule_revisions_same_rule_supersession",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "supersedes_revision_id IS NULL OR supersedes_revision_id != id",
            name="ck_engineering_rule_revisions_not_self_superseding",
        ),
        CheckConstraint(
            "expiry_date IS NULL OR effective_date IS NULL OR expiry_date > effective_date",
            name="ck_engineering_rule_revisions_effective_window",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engineering_rule_id: Mapped[int] = mapped_column(
        ForeignKey("engineering_rules.id", ondelete="RESTRICT"), index=True
    )
    revision: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[RuleLifecycleStatus] = mapped_column(
        portable_enum(
            RuleLifecycleStatus,
            "ck_engineering_rule_revisions_lifecycle_status",
        )
    )
    evidence_class: Mapped[EvidenceClass] = mapped_column(
        portable_enum(
            EvidenceClass,
            "ck_engineering_rule_revisions_evidence_class",
        )
    )
    category: Mapped[RuleCategory] = mapped_column(
        portable_enum(
            RuleCategory,
            "ck_engineering_rule_revisions_category",
        )
    )
    parameter: Mapped[str] = mapped_column(String(120))
    operator: Mapped[RuleOperator | None] = mapped_column(
        portable_enum(
            RuleOperator,
            "ck_engineering_rule_revisions_operator",
        ),
        nullable=True,
    )
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    applicability_metadata: Mapped[dict | None] = mapped_column(
        ImmutableJSON, nullable=True
    )
    applicability_schema_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[RuleSourceType | None] = mapped_column(
        portable_enum(
            RuleSourceType,
            "ck_engineering_rule_revisions_source_type",
        ),
        nullable=True,
    )
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_document: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    safe_default: Mapped[SafeDefault] = mapped_column(
        portable_enum(
            SafeDefault,
            "ck_engineering_rule_revisions_safe_default",
        )
    )
    missing_handling: Mapped[MissingHandling] = mapped_column(
        portable_enum(
            MissingHandling,
            "ck_engineering_rule_revisions_missing_handling",
        )
    )
    conflict_handling: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit_mismatch_handling: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    reason_for_change: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(String(40))
    canonicalization_version: Mapped[str] = mapped_column(String(40))
    hash_algorithm: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(128))
    software_version: Mapped[str] = mapped_column(String(80))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_actor_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    engineering_rule: Mapped[EngineeringRule] = relationship()
    evidence_references: Mapped[list["EvidenceReference"]] = relationship(
        order_by="EvidenceReference.id",
        viewonly=True,
    )


class EvidenceReference(Base):
    __tablename__ = "evidence_references"
    __table_args__ = (
        UniqueConstraint(
            "engineering_rule_revision_id",
            "evidence_id",
            "evidence_revision",
            name="uq_evidence_references_revision_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engineering_rule_revision_id: Mapped[int] = mapped_column(
        ForeignKey("engineering_rule_revisions.id", ondelete="RESTRICT"), index=True
    )
    evidence_id: Mapped[str] = mapped_column(String(120))
    evidence_revision: Mapped[str] = mapped_column(String(80))
    source_type: Mapped[RuleSourceType | None] = mapped_column(
        portable_enum(
            RuleSourceType,
            "ck_evidence_references_source_type",
        ),
        nullable=True,
    )
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_document: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edition: Mapped[str | None] = mapped_column(String(100), nullable=True)
    section_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    page_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    table_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    evidence_class: Mapped[EvidenceClass] = mapped_column(
        portable_enum(
            EvidenceClass,
            "ck_evidence_references_evidence_class",
        )
    )
    lifecycle_status: Mapped[RuleLifecycleStatus] = mapped_column(
        portable_enum(
            RuleLifecycleStatus,
            "ck_evidence_references_lifecycle_status",
        )
    )
    reference_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_metadata: Mapped[dict | None] = mapped_column(ImmutableJSON, nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hash_algorithm: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    verified_by_actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_by_actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_actor_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    engineering_rule_revision: Mapped[EngineeringRuleRevision] = relationship(
        foreign_keys=[engineering_rule_revision_id]
    )


def _reject_phase1_authority_revision(_mapper, _connection, target) -> None:
    if target.evidence_class == EvidenceClass.SOURCE_BACKED or target.enabled:
        raise RegistryAuthorityError(
            "Phase 1 cannot persist enabled or SOURCE_BACKED Registry revisions"
        )


def _guard_phase1_evidence_insert(_mapper, _connection, target) -> None:
    if target.evidence_class == EvidenceClass.SOURCE_BACKED:
        raise RegistryAuthorityError("Phase 1 cannot persist SOURCE_BACKED evidence")
    if target.lifecycle_status not in {
        RuleLifecycleStatus.DRAFT,
        RuleLifecycleStatus.REVIEW,
    }:
        raise RegistryAuthorityError("Phase 1 evidence must remain DRAFT or REVIEW")
    session = object_session(target)
    parent_revision = target.engineering_rule_revision
    if (
        session is None
        or parent_revision is None
        or parent_revision not in session.new
    ):
        raise RegistryAuthorityError(
            "evidence must be assembled with a new revision in the same flush"
        )


freeze_json_attribute(EngineeringRuleRevision.applicability_metadata)
freeze_json_attribute(EvidenceReference.reference_metadata)
event.listen(
    EngineeringRuleRevision,
    "before_insert",
    _reject_phase1_authority_revision,
)
event.listen(EvidenceReference, "before_insert", _guard_phase1_evidence_insert)
protect_immutable_model(EngineeringRule)
protect_immutable_model(EngineeringRuleRevision)
protect_immutable_model(EvidenceReference)
