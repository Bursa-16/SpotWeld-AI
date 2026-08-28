"""digital weld passport persistence

Revision ID: 0010_digital_weld_passport
Revises: 0009_machine_readiness_persistence
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_digital_weld_passport"
down_revision = "0009_machine_readiness_persistence"
branch_labels = None
depends_on = None


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    op.create_table(
        "digital_weld_passports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("passport_id", sa.String(120), nullable=False),
        sa.Column("current_revision_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_by_actor_id", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "passport_id",
            name="uq_digital_weld_passports_passport_id",
        ),
    )
    op.create_table(
        "digital_weld_passport_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("passport_id", sa.String(120), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("mrc_snapshot", sa.JSON(), nullable=True),
        sa.Column("provenance_snapshot", sa.JSON(), nullable=False),
        sa.Column("authority_snapshot", sa.JSON(), nullable=False),
        sa.Column("supersedes_revision_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_by_actor_id", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("canonicalization_version", sa.String(40), nullable=False),
        sa.Column("hash_algorithm", sa.String(40), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("software_version", sa.String(80), nullable=False),
        sa.Column("correlation_id", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "passport_id",
            "revision_number",
            name="uq_digital_weld_passport_revisions_logical_revision",
        ),
        sa.UniqueConstraint(
            "passport_id",
            "id",
            name="uq_digital_weld_passport_revisions_context_internal_id",
        ),
        sa.UniqueConstraint(
            "supersedes_revision_id",
            name="uq_digital_weld_passport_revisions_single_successor",
        ),
        sa.ForeignKeyConstraint(
            ["passport_id"],
            ["digital_weld_passports.passport_id"],
            name="fk_digital_weld_passport_revisions_passport_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["passport_id", "supersedes_revision_id"],
            [
                "digital_weld_passport_revisions.passport_id",
                "digital_weld_passport_revisions.id",
            ],
            name="fk_digital_weld_passport_revisions_same_passport_supersession",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_digital_weld_passport_revisions_positive_revision_number",
        ),
        sa.CheckConstraint(
            "supersedes_revision_id IS NULL OR supersedes_revision_id != id",
            name="ck_digital_weld_passport_revisions_not_self_superseding",
        ),
    )
    op.create_index(
        "ix_digital_weld_passport_revisions_passport_id",
        "digital_weld_passport_revisions",
        ["passport_id"],
    )
    op.create_index(
        "ix_digital_weld_passport_revisions_correlation_id",
        "digital_weld_passport_revisions",
        ["correlation_id"],
    )
    op.create_table(
        "digital_weld_passport_lifecycle_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("passport_revision_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            _enum(
                "CREATED",
                "DRAFT",
                "ENGINEERING_DEFINED",
                "VALIDATION_PENDING",
                "VALIDATED",
                "APPROVED",
                "PRODUCTION_ACTIVE",
                "SUPERSEDED",
                "RETIRED",
                "ARCHIVED",
                name="ck_digital_weld_passport_lifecycle_events_state",
            ),
            nullable=False,
        ),
        sa.Column("authority_snapshot", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("prior_content_hash", sa.String(128), nullable=True),
        sa.Column("new_content_hash", sa.String(128), nullable=True),
        sa.Column("supersedes_lifecycle_event_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_by_actor_id", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("canonicalization_version", sa.String(40), nullable=False),
        sa.Column("hash_algorithm", sa.String(40), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("software_version", sa.String(80), nullable=False),
        sa.Column("correlation_id", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "passport_revision_id",
            "revision_number",
            name="uq_digital_weld_passport_lifecycle_events_logical_revision",
        ),
        sa.UniqueConstraint(
            "passport_revision_id",
            "id",
            name="uq_digital_weld_passport_lifecycle_events_context_internal_id",
        ),
        sa.UniqueConstraint(
            "supersedes_lifecycle_event_id",
            name="uq_digital_weld_passport_lifecycle_events_single_successor",
        ),
        sa.ForeignKeyConstraint(
            ["passport_revision_id"],
            ["digital_weld_passport_revisions.id"],
            name="fk_digital_weld_passport_lifecycle_events_passport_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["passport_revision_id", "supersedes_lifecycle_event_id"],
            [
                "digital_weld_passport_lifecycle_events.passport_revision_id",
                "digital_weld_passport_lifecycle_events.id",
            ],
            name="fk_digital_weld_passport_lifecycle_events_same_revision_supersession",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_digital_weld_passport_lifecycle_events_positive_revision_number",
        ),
        sa.CheckConstraint(
            "supersedes_lifecycle_event_id IS NULL "
            "OR supersedes_lifecycle_event_id != id",
            name="ck_digital_weld_passport_lifecycle_events_not_self_superseding",
        ),
    )
    op.create_index(
        "ix_digital_weld_passport_lifecycle_events_passport_revision_id",
        "digital_weld_passport_lifecycle_events",
        ["passport_revision_id"],
    )
    op.create_index(
        "ix_digital_weld_passport_lifecycle_events_state",
        "digital_weld_passport_lifecycle_events",
        ["state"],
    )
    op.create_index(
        "ix_digital_weld_passport_lifecycle_events_correlation_id",
        "digital_weld_passport_lifecycle_events",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_digital_weld_passport_lifecycle_events_correlation_id",
        table_name="digital_weld_passport_lifecycle_events",
    )
    op.drop_index(
        "ix_digital_weld_passport_lifecycle_events_state",
        table_name="digital_weld_passport_lifecycle_events",
    )
    op.drop_index(
        "ix_digital_weld_passport_lifecycle_events_passport_revision_id",
        table_name="digital_weld_passport_lifecycle_events",
    )
    op.drop_table("digital_weld_passport_lifecycle_events")
    op.drop_index(
        "ix_digital_weld_passport_revisions_correlation_id",
        table_name="digital_weld_passport_revisions",
    )
    op.drop_index(
        "ix_digital_weld_passport_revisions_passport_id",
        table_name="digital_weld_passport_revisions",
    )
    op.drop_table("digital_weld_passport_revisions")
    op.drop_table("digital_weld_passports")
