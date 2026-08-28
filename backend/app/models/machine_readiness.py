from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.domain.readiness import CheckCondition, ReadinessState
from app.models.entities import utc_now
from app.models.governance import (
    ImmutableJSON,
    freeze_json_attribute,
    portable_enum,
    protect_immutable_model,
)

__all__ = [
    "MachineReadinessAssessment",
    "MachineReadinessAssessmentRevision",
    "MachineReadinessCheckResult",
]


class MachineReadinessAssessment(Base):
    __tablename__ = "machine_readiness_assessments"

    assessment_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_actor_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    revisions: Mapped[list[MachineReadinessAssessmentRevision]] = relationship(
        order_by="MachineReadinessAssessmentRevision.revision_number",
        viewonly=True,
    )


class MachineReadinessAssessmentRevision(Base):
    __tablename__ = "machine_readiness_assessment_revisions"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id",
            "revision_number",
            name="uq_machine_readiness_assessment_revisions_logical_revision",
        ),
        UniqueConstraint(
            "assessment_id",
            "id",
            name="uq_machine_readiness_assessment_revisions_context_internal_id",
        ),
        UniqueConstraint(
            "supersedes_assessment_revision_id",
            name="uq_machine_readiness_assessment_revisions_single_successor",
        ),
        ForeignKeyConstraint(
            ["assessment_id", "supersedes_assessment_revision_id"],
            [
                "machine_readiness_assessment_revisions.assessment_id",
                "machine_readiness_assessment_revisions.id",
            ],
            name="fk_machine_readiness_assessment_revisions_same_assessment_supersession",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_machine_readiness_assessment_revisions_positive_revision_number",
        ),
        CheckConstraint(
            "supersedes_assessment_revision_id IS NULL "
            "OR supersedes_assessment_revision_id != id",
            name="ck_machine_readiness_assessment_revisions_not_self_superseding",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("machine_readiness_assessments.assessment_id", ondelete="RESTRICT"),
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[ReadinessState] = mapped_column(
        portable_enum(
            ReadinessState,
            "ck_machine_readiness_assessment_revisions_state",
        )
    )
    context_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    prerequisites_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    result_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    authority_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    validated_applicable_basis_count: Mapped[int] = mapped_column(Integer)
    supersedes_assessment_revision_id: Mapped[int | None] = mapped_column(
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
    correlation_id: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    assessment: Mapped[MachineReadinessAssessment] = relationship(
        foreign_keys=[assessment_id]
    )
    check_results: Mapped[list[MachineReadinessCheckResult]] = relationship(
        order_by="MachineReadinessCheckResult.id",
        viewonly=True,
    )


class MachineReadinessCheckResult(Base):
    __tablename__ = "machine_readiness_check_results"
    __table_args__ = (
        UniqueConstraint(
            "assessment_revision_id",
            "check_id",
            name="uq_machine_readiness_check_results_revision_check",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_revision_id: Mapped[int] = mapped_column(
        ForeignKey("machine_readiness_assessment_revisions.id", ondelete="RESTRICT"),
        index=True,
    )
    check_id: Mapped[str] = mapped_column(String(120))
    required: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition: Mapped[CheckCondition] = mapped_column(
        portable_enum(
            CheckCondition,
            "ck_machine_readiness_check_results_condition",
        )
    )
    reason: Mapped[str] = mapped_column(Text)
    check_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    assessment_revision: Mapped[MachineReadinessAssessmentRevision] = relationship(
        foreign_keys=[assessment_revision_id]
    )


protect_immutable_model(MachineReadinessAssessment)
protect_immutable_model(MachineReadinessAssessmentRevision)
protect_immutable_model(MachineReadinessCheckResult)
for _attribute in (
    MachineReadinessAssessmentRevision.context_snapshot,
    MachineReadinessAssessmentRevision.prerequisites_snapshot,
    MachineReadinessAssessmentRevision.result_snapshot,
    MachineReadinessAssessmentRevision.authority_snapshot,
    MachineReadinessCheckResult.check_snapshot,
):
    freeze_json_attribute(_attribute)
