"""machine readiness persistence

Revision ID: 0009_machine_readiness_persistence
Revises: 0008_rule_evaluation_persistence
"""

import sqlalchemy as sa

from alembic import op

revision = "0009_machine_readiness_persistence"
down_revision = "0008_rule_evaluation_persistence"
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
        "machine_readiness_assessments",
        sa.Column("assessment_id", sa.String(120), primary_key=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_by_actor_id", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "machine_readiness_assessment_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.String(120), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "state",
            _enum(
                "READY",
                "NOT_READY",
                "ENGINEERING_REVIEW_REQUIRED",
                "MANUAL_REVIEW_REQUIRED",
                "NOT_EVALUATED",
                name="ck_machine_readiness_assessment_revisions_state",
            ),
            nullable=False,
        ),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("prerequisites_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("authority_snapshot", sa.JSON(), nullable=False),
        sa.Column("validated_applicable_basis_count", sa.Integer(), nullable=False),
        sa.Column("supersedes_assessment_revision_id", sa.Integer(), nullable=True),
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
            "assessment_id",
            "revision_number",
            name="uq_machine_readiness_assessment_revisions_logical_revision",
        ),
        sa.UniqueConstraint(
            "assessment_id",
            "id",
            name="uq_machine_readiness_assessment_revisions_context_internal_id",
        ),
        sa.UniqueConstraint(
            "supersedes_assessment_revision_id",
            name="uq_machine_readiness_assessment_revisions_single_successor",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id", "supersedes_assessment_revision_id"],
            [
                "machine_readiness_assessment_revisions.assessment_id",
                "machine_readiness_assessment_revisions.id",
            ],
            name="fk_machine_readiness_assessment_rev_assessment_supersession",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["machine_readiness_assessments.assessment_id"],
            name="fk_machine_readiness_assessment_revisions_assessment_identity",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_machine_readiness_assessment_rev_positive_revision_number",
        ),
        sa.CheckConstraint(
            "supersedes_assessment_revision_id IS NULL "
            "OR supersedes_assessment_revision_id != id",
            name="ck_machine_readiness_assessment_revisions_not_self_superseding",
        ),
    )
    op.create_index(
        "ix_machine_readiness_assessment_revisions_assessment_id",
        "machine_readiness_assessment_revisions",
        ["assessment_id"],
    )
    op.create_index(
        "ix_machine_readiness_assessment_revisions_correlation_id",
        "machine_readiness_assessment_revisions",
        ["correlation_id"],
    )
    op.create_table(
        "machine_readiness_check_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_revision_id", sa.Integer(), nullable=False),
        sa.Column("check_id", sa.String(120), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "condition",
            _enum(
                "PASSED",
                "FAILED",
                "UNRESOLVED",
                "DATA_INSUFFICIENT",
                "CONTEXT_INSUFFICIENT",
                "RULE_CONFLICT",
                "NOT_APPLICABLE_VERSION",
                "EVIDENCE_UNAVAILABLE",
                "OBSERVATION_MISSING",
                "NOT_EVALUATED",
                name="ck_machine_readiness_check_results_condition",
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("check_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "assessment_revision_id",
            "check_id",
            name="uq_machine_readiness_check_results_revision_check",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_revision_id"],
            ["machine_readiness_assessment_revisions.id"],
            name="fk_machine_readiness_check_results_assessment_revision",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_machine_readiness_check_results_assessment_revision_id",
        "machine_readiness_check_results",
        ["assessment_revision_id"],
    )


def downgrade():
    op.drop_index(
        "ix_machine_readiness_check_results_assessment_revision_id",
        table_name="machine_readiness_check_results",
    )
    op.drop_table("machine_readiness_check_results")
    op.drop_index(
        "ix_machine_readiness_assessment_revisions_correlation_id",
        table_name="machine_readiness_assessment_revisions",
    )
    op.drop_index(
        "ix_machine_readiness_assessment_revisions_assessment_id",
        table_name="machine_readiness_assessment_revisions",
    )
    op.drop_table("machine_readiness_assessment_revisions")
    op.drop_table("machine_readiness_assessments")
