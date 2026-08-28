"""rule evaluation persistence

Revision ID: 0008_rule_evaluation_persistence
Revises: 0007_rule_lifecycle_events
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_rule_evaluation_persistence"
down_revision = "0007_rule_lifecycle_events"
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
        "rule_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evaluation_id", sa.String(120), nullable=False),
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
        sa.Column("rule_id", sa.String(120), nullable=False),
        sa.Column("rule_revision", sa.String(40), nullable=False),
        sa.Column("parameter", sa.String(120), nullable=False),
        sa.Column(
            "operator",
            _enum(
                "MIN",
                "MAX",
                "RANGE",
                "EQUALS",
                "DERIVED_MIN",
                "CUSTOM",
                name="ck_rule_evaluations_operator",
            ),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            _enum(
                "SATISFIED",
                "NOT_SATISFIED",
                "NOT_APPLICABLE",
                "UNIT_MISMATCH",
                "UNRESOLVED",
                name="ck_rule_evaluations_outcome",
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=True),
        sa.Column("observed_unit", sa.String(80), nullable=True),
        sa.Column("compared_value", sa.Float(), nullable=True),
        sa.Column("applicability_snapshot", sa.JSON(), nullable=False),
        sa.Column("observation_snapshot", sa.JSON(), nullable=False),
        sa.Column("unit_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("authority_snapshot", sa.JSON(), nullable=False),
        sa.Column("supersedes_evaluation_id", sa.Integer(), nullable=True),
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
            "evaluation_id",
            "revision_number",
            name="uq_rule_evaluations_logical_revision",
        ),
        sa.UniqueConstraint(
            "evaluation_id",
            "id",
            name="uq_rule_evaluations_context_internal_id",
        ),
        sa.UniqueConstraint(
            "supersedes_evaluation_id",
            name="uq_rule_evaluations_single_successor",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id", "supersedes_evaluation_id"],
            ["rule_evaluations.evaluation_id", "rule_evaluations.id"],
            name="fk_rule_evaluations_same_evaluation_supersession",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["engineering_rule_id", "engineering_rule_revision_id"],
            [
                "engineering_rule_revisions.engineering_rule_id",
                "engineering_rule_revisions.id",
            ],
            name="fk_rule_evaluations_exact_rule_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_rule_evaluations_positive_revision_number",
        ),
        sa.CheckConstraint(
            "supersedes_evaluation_id IS NULL OR supersedes_evaluation_id != id",
            name="ck_rule_evaluations_not_self_superseding",
        ),
    )
    op.create_index(
        "ix_rule_evaluations_engineering_rule_id",
        "rule_evaluations",
        ["engineering_rule_id"],
    )
    op.create_index(
        "ix_rule_evaluations_engineering_rule_revision_id",
        "rule_evaluations",
        ["engineering_rule_revision_id"],
    )
    op.create_index(
        "ix_rule_evaluations_outcome",
        "rule_evaluations",
        ["outcome"],
    )
    op.create_index(
        "ix_rule_evaluations_correlation_id",
        "rule_evaluations",
        ["correlation_id"],
    )


def downgrade():
    op.drop_index(
        "ix_rule_evaluations_correlation_id",
        table_name="rule_evaluations",
    )
    op.drop_index(
        "ix_rule_evaluations_outcome",
        table_name="rule_evaluations",
    )
    op.drop_index(
        "ix_rule_evaluations_engineering_rule_revision_id",
        table_name="rule_evaluations",
    )
    op.drop_index(
        "ix_rule_evaluations_engineering_rule_id",
        table_name="rule_evaluations",
    )
    op.drop_table("rule_evaluations")
