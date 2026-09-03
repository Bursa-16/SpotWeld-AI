"""evidence verification authority foundation

Revision ID: 0006_evidence_verification_authority_foundation
Revises: 0005_registry_evidence_applicability
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_evidence_verification_authority_foundation"
down_revision = "0005_registry_evidence_applicability"
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
        "evidence_verification_delegations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delegation_id", sa.String(120), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "verifier_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "granted_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "revoked_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "capability",
            _enum(
                "EVIDENCE_VERIFICATION",
                name="ck_evidence_verification_delegations_capability",
            ),
            nullable=False,
        ),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _enum(
                "ACTIVE",
                "REVOKED",
                "EXPIRED",
                name="ck_evidence_verification_delegations_status",
            ),
            nullable=False,
        ),
        sa.Column("supersedes_delegation_id", sa.Integer(), nullable=True),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "delegation_id",
            "revision_number",
            name="uq_evidence_verification_delegations_logical_revision",
        ),
        sa.UniqueConstraint(
            "delegation_id",
            "id",
            name="uq_evidence_verification_delegations_context_internal_id",
        ),
        sa.UniqueConstraint(
            "supersedes_delegation_id",
            name="uq_evidence_verification_delegations_single_successor",
        ),
        sa.ForeignKeyConstraint(
            ["delegation_id", "supersedes_delegation_id"],
            [
                "evidence_verification_delegations.delegation_id",
                "evidence_verification_delegations.id",
            ],
            name="fk_evidence_verification_delegations_delegation_supersession",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_evidence_verification_delegations_positive_revision_number",
        ),
        sa.CheckConstraint(
            "supersedes_delegation_id IS NULL OR supersedes_delegation_id != id",
            name="ck_evidence_verification_delegations_not_self_superseding",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_from",
            name="ck_evidence_verification_delegations_effective_window",
        ),
    )
    op.create_index(
        "ix_evidence_verification_delegations_verifier_user_id",
        "evidence_verification_delegations",
        ["verifier_user_id"],
    )

    op.create_table(
        "evidence_verification_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("verification_id", sa.String(120), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "evidence_reference_id",
            sa.Integer(),
            sa.ForeignKey("evidence_references.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "evidence_verification_delegation_id",
            sa.Integer(),
            sa.ForeignKey("evidence_verification_delegations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "verifier_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "decision_outcome",
            _enum("VERIFIED", name="ck_evidence_verification_decisions_outcome"),
            nullable=False,
        ),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("authority_snapshot", sa.JSON(), nullable=False),
        sa.Column("authority_snapshot_schema_version", sa.String(40), nullable=False),
        sa.Column(
            "authority_snapshot_canonicalization_version",
            sa.String(40),
            nullable=False,
        ),
        sa.Column("authority_snapshot_hash_algorithm", sa.String(40), nullable=False),
        sa.Column("authority_snapshot_content_hash", sa.String(128), nullable=False),
        sa.Column("policy_identifier", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("correlation_id", sa.String(120), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_verification_decision_id", sa.Integer(), nullable=True),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "verification_id",
            "revision_number",
            name="uq_evidence_verification_decisions_logical_revision",
        ),
        sa.UniqueConstraint(
            "verification_id",
            "id",
            name="uq_evidence_verification_decisions_context_internal_id",
        ),
        sa.UniqueConstraint(
            "supersedes_verification_decision_id",
            name="uq_evidence_verification_decisions_single_successor",
        ),
        sa.ForeignKeyConstraint(
            ["verification_id", "supersedes_verification_decision_id"],
            [
                "evidence_verification_decisions.verification_id",
                "evidence_verification_decisions.id",
            ],
            name="fk_evidence_verification_decisions_verification_supersession",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_evidence_verification_decisions_positive_revision_number",
        ),
        sa.CheckConstraint(
            "supersedes_verification_decision_id IS NULL "
            "OR supersedes_verification_decision_id != id",
            name="ck_evidence_verification_decisions_not_self_superseding",
        ),
    )
    op.create_index(
        "ix_evidence_verification_decisions_evidence_reference_id",
        "evidence_verification_decisions",
        ["evidence_reference_id"],
    )
    op.create_index(
        "ix_evidence_verification_decisions_delegation_id",
        "evidence_verification_decisions",
        ["evidence_verification_delegation_id"],
    )
    op.create_index(
        "ix_evidence_verification_decisions_verifier_user_id",
        "evidence_verification_decisions",
        ["verifier_user_id"],
    )
    op.create_index(
        "ix_evidence_verification_decisions_correlation_id",
        "evidence_verification_decisions",
        ["correlation_id"],
    )


def downgrade():
    op.drop_index(
        "ix_evidence_verification_decisions_correlation_id",
        table_name="evidence_verification_decisions",
    )
    op.drop_index(
        "ix_evidence_verification_decisions_verifier_user_id",
        table_name="evidence_verification_decisions",
    )
    op.drop_index(
        "ix_evidence_verification_decisions_delegation_id",
        table_name="evidence_verification_decisions",
    )
    op.drop_index(
        "ix_evidence_verification_decisions_evidence_reference_id",
        table_name="evidence_verification_decisions",
    )
    op.drop_table("evidence_verification_decisions")

    op.drop_index(
        "ix_evidence_verification_delegations_verifier_user_id",
        table_name="evidence_verification_delegations",
    )
    op.drop_table("evidence_verification_delegations")
