from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
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
from app.models.entities import utc_now
from app.models.governance import (
    ImmutableJSON,
    freeze_json_attribute,
    portable_enum,
    protect_immutable_model,
)

__all__ = [
    "DigitalWeldPassport",
    "DigitalWeldPassportLifecycleEvent",
    "DigitalWeldPassportLifecycleState",
    "DigitalWeldPassportRevision",
]


class DigitalWeldPassportLifecycleState(StrEnum):
    CREATED = "CREATED"
    DRAFT = "DRAFT"
    ENGINEERING_DEFINED = "ENGINEERING_DEFINED"
    VALIDATION_PENDING = "VALIDATION_PENDING"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    PRODUCTION_ACTIVE = "PRODUCTION_ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"
    ARCHIVED = "ARCHIVED"


class DigitalWeldPassport(Base):
    __tablename__ = "digital_weld_passports"
    __table_args__ = (
        UniqueConstraint("passport_id", name="uq_digital_weld_passports_passport_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    passport_id: Mapped[str] = mapped_column(String(120))
    current_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_actor_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    revisions: Mapped[list[DigitalWeldPassportRevision]] = relationship(
        order_by="DigitalWeldPassportRevision.revision_number",
        viewonly=True,
    )


class DigitalWeldPassportRevision(Base):
    __tablename__ = "digital_weld_passport_revisions"
    __table_args__ = (
        UniqueConstraint(
            "passport_id",
            "revision_number",
            name="uq_digital_weld_passport_revisions_logical_revision",
        ),
        UniqueConstraint(
            "passport_id",
            "id",
            name="uq_digital_weld_passport_revisions_context_internal_id",
        ),
        UniqueConstraint(
            "supersedes_revision_id",
            name="uq_digital_weld_passport_revisions_single_successor",
        ),
        ForeignKeyConstraint(
            ["passport_id", "supersedes_revision_id"],
            [
                "digital_weld_passport_revisions.passport_id",
                "digital_weld_passport_revisions.id",
            ],
            name="fk_digital_weld_passport_revisions_same_passport_supersession",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_digital_weld_passport_revisions_positive_revision_number",
        ),
        CheckConstraint(
            "supersedes_revision_id IS NULL OR supersedes_revision_id != id",
            name="ck_digital_weld_passport_revisions_not_self_superseding",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    passport_id: Mapped[str] = mapped_column(
        ForeignKey("digital_weld_passports.passport_id", ondelete="RESTRICT"),
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    context_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    mrc_snapshot: Mapped[dict | None] = mapped_column(ImmutableJSON, nullable=True)
    provenance_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    authority_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    supersedes_revision_id: Mapped[int | None] = mapped_column(
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

    passport: Mapped[DigitalWeldPassport] = relationship(
        foreign_keys=[passport_id]
    )
    lifecycle_events: Mapped[list[DigitalWeldPassportLifecycleEvent]] = relationship(
        order_by="DigitalWeldPassportLifecycleEvent.revision_number",
        viewonly=True,
    )


class DigitalWeldPassportLifecycleEvent(Base):
    __tablename__ = "digital_weld_passport_lifecycle_events"
    __table_args__ = (
        UniqueConstraint(
            "passport_revision_id",
            "revision_number",
            name="uq_digital_weld_passport_lifecycle_events_logical_revision",
        ),
        UniqueConstraint(
            "passport_revision_id",
            "id",
            name="uq_digital_weld_passport_lifecycle_events_context_internal_id",
        ),
        UniqueConstraint(
            "supersedes_lifecycle_event_id",
            name="uq_digital_weld_passport_lifecycle_events_single_successor",
        ),
        ForeignKeyConstraint(
            ["passport_revision_id", "supersedes_lifecycle_event_id"],
            [
                "digital_weld_passport_lifecycle_events.passport_revision_id",
                "digital_weld_passport_lifecycle_events.id",
            ],
            name="fk_digital_weld_passport_lifecycle_same_revision_supersession",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_digital_weld_passport_lifecycle_positive_revision_number",
        ),
        CheckConstraint(
            "supersedes_lifecycle_event_id IS NULL "
            "OR supersedes_lifecycle_event_id != id",
            name="ck_digital_weld_passport_lifecycle_events_not_self_superseding",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    passport_revision_id: Mapped[int] = mapped_column(
        ForeignKey("digital_weld_passport_revisions.id", ondelete="RESTRICT"),
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[DigitalWeldPassportLifecycleState] = mapped_column(
        portable_enum(
            DigitalWeldPassportLifecycleState,
            "ck_digital_weld_passport_lifecycle_events_state",
        ),
        index=True,
    )
    authority_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    reason: Mapped[str] = mapped_column(Text)
    prior_content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    new_content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    supersedes_lifecycle_event_id: Mapped[int | None] = mapped_column(
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

    passport_revision: Mapped[DigitalWeldPassportRevision] = relationship(
        foreign_keys=[passport_revision_id]
    )


protect_immutable_model(DigitalWeldPassportRevision)
protect_immutable_model(DigitalWeldPassportLifecycleEvent)
for _attribute in (
    DigitalWeldPassportRevision.context_snapshot,
    DigitalWeldPassportRevision.mrc_snapshot,
    DigitalWeldPassportRevision.provenance_snapshot,
    DigitalWeldPassportRevision.authority_snapshot,
    DigitalWeldPassportLifecycleEvent.authority_snapshot,
):
    freeze_json_attribute(_attribute)
