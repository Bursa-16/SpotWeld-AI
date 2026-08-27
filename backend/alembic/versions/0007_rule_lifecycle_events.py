"""rule lifecycle events

Revision ID: 0007_rule_lifecycle_events
Revises: 0006_evidence_verification_authority_foundation
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_rule_lifecycle_events"
down_revision = "0006_evidence_verification_authority_foundation"
branch_labels = None
depends_on = None


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
    )


def upgrade():
    op.create_table(
        "rule_lifecycle_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lifecycle_event_id", sa.String(120), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "engineering_rule_id",
            sa.Integer(),
            sa.ForeignKey("engineering_rules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "engineering_rule_revision_id",
            sa.Integer(),
            sa.ForeignKey("engineering_rule_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            _enum(
                "ENABLE",
                "ACTIVATE",
                "SUSPEND",
                "REVOKE",
                "DEPRECATE",
                "SUPERSEDE",
                "EXPIRE",
                "CORRECT",
                name="ck_rule_lifecycle_events_event_type",
            ),
            nullable=False,
        ),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False),
        sa.Column("basis_snapshot", sa.JSON(), nullable=False),
        sa.Column("authority_snapshot", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_rule_lifecycle_event_id", sa.Integer(), nullable=True),
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
            "lifecycle_event_id",
            "revision_number",
            name="uq_rule_lifecycle_events_logical_revision",
        ),
        sa.UniqueConstraint(
            "lifecycle_event_id",
            "id",
            name="uq_rule_lifecycle_events_context_internal_id",
        ),
        sa.UniqueConstraint(
            "supersedes_rule_lifecycle_event_id",
            name="uq_rule_lifecycle_events_single_successor",
        ),
        sa.ForeignKeyConstraint(
            ["lifecycle_event_id", "supersedes_rule_lifecycle_event_id"],
            [
                "rule_lifecycle_events.lifecycle_event_id",
                "rule_lifecycle_events.id",
            ],
            name="fk_rule_lifecycle_events_same_event_supersession",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["engineering_rule_id", "engineering_rule_revision_id"],
            [
                "engineering_rule_revisions.engineering_rule_id",
                "engineering_rule_revisions.id",
            ],
            name="fk_rule_lifecycle_events_exact_rule_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_rule_lifecycle_events_positive_revision_number",
        ),
        sa.CheckConstraint(
            "supersedes_rule_lifecycle_event_id IS NULL "
            "OR supersedes_rule_lifecycle_event_id != id",
            name="ck_rule_lifecycle_events_not_self_superseding",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_from",
            name="ck_rule_lifecycle_events_effective_window",
        ),
    )
    op.create_index(
        "ix_rule_lifecycle_events_engineering_rule_id",
        "rule_lifecycle_events",
        ["engineering_rule_id"],
    )
    op.create_index(
        "ix_rule_lifecycle_events_engineering_rule_revision_id",
        "rule_lifecycle_events",
        ["engineering_rule_revision_id"],
    )
    op.create_index(
        "ix_rule_lifecycle_events_event_type",
        "rule_lifecycle_events",
        ["event_type"],
    )
    op.create_index(
        "ix_rule_lifecycle_events_correlation_id",
        "rule_lifecycle_events",
        ["correlation_id"],
    )


def downgrade():
    op.drop_index(
        "ix_rule_lifecycle_events_correlation_id",
        table_name="rule_lifecycle_events",
    )
    op.drop_index(
        "ix_rule_lifecycle_events_event_type",
        table_name="rule_lifecycle_events",
    )
    op.drop_index(
        "ix_rule_lifecycle_events_engineering_rule_revision_id",
        table_name="rule_lifecycle_events",
    )
    op.drop_index(
        "ix_rule_lifecycle_events_engineering_rule_id",
        table_name="rule_lifecycle_events",
    )
    op.drop_table("rule_lifecycle_events")
