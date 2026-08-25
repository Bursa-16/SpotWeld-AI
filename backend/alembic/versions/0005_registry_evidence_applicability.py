"""registry evidence revision and applicability persistence

Revision ID: 0005_registry_evidence_applicability
Revises: 0004_persistent_idempotency
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_registry_evidence_applicability"
down_revision = "0004_persistent_idempotency"
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
    with op.batch_alter_table("evidence_references") as batch_op:
        batch_op.add_column(
            sa.Column(
                "revision_number",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("supersedes_evidence_reference_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "availability",
                _enum(
                    "UNKNOWN",
                    "AVAILABLE",
                    "UNAVAILABLE",
                    name="ck_evidence_references_availability",
                ),
                nullable=False,
                server_default="UNKNOWN",
            )
        )
    evidence_references = sa.table(
        "evidence_references",
        sa.column("id", sa.Integer()),
        sa.column("engineering_rule_revision_id", sa.Integer()),
        sa.column("evidence_id", sa.String()),
        sa.column("revision_number", sa.Integer()),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            evidence_references.c.id,
            evidence_references.c.engineering_rule_revision_id,
            evidence_references.c.evidence_id,
        ).order_by(
            evidence_references.c.engineering_rule_revision_id,
            evidence_references.c.evidence_id,
            evidence_references.c.id,
        )
    )
    prior_identity = None
    revision_number = 0
    for row in rows:
        identity = (row.engineering_rule_revision_id, row.evidence_id)
        if identity != prior_identity:
            prior_identity = identity
            revision_number = 1
        else:
            revision_number += 1
        connection.execute(
            evidence_references.update()
            .where(evidence_references.c.id == row.id)
            .values(revision_number=revision_number)
        )

    with op.batch_alter_table("evidence_references") as batch_op:
        batch_op.alter_column("revision_number", nullable=False)
        batch_op.alter_column("availability", server_default=None)
        batch_op.create_unique_constraint(
            "uq_evidence_references_logical_revision",
            ["engineering_rule_revision_id", "evidence_id", "revision_number"],
        )
        batch_op.create_unique_constraint(
            "uq_evidence_references_context_internal_id",
            ["engineering_rule_revision_id", "evidence_id", "id"],
        )
        batch_op.create_unique_constraint(
            "uq_evidence_references_single_successor",
            ["supersedes_evidence_reference_id"],
        )
        batch_op.create_foreign_key(
            "fk_evidence_references_same_context_supersession",
            "evidence_references",
            [
                "engineering_rule_revision_id",
                "evidence_id",
                "supersedes_evidence_reference_id",
            ],
            ["engineering_rule_revision_id", "evidence_id", "id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_evidence_references_positive_revision_number",
            "revision_number > 0",
        )
        batch_op.create_check_constraint(
            "ck_evidence_references_not_self_superseding",
            "supersedes_evidence_reference_id IS NULL "
            "OR supersedes_evidence_reference_id != id",
        )

    op.create_table(
        "rule_applicabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("engineering_rule_id", sa.Integer(), nullable=False),
        sa.Column("engineering_rule_revision_id", sa.Integer(), nullable=False),
        sa.Column("applicability_id", sa.String(120), nullable=False),
        sa.Column("applicability_revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_applicability_id", sa.Integer(), nullable=True),
        sa.Column(
            "dimension",
            _enum(
                "MACHINE",
                "WELD_GUN",
                "STATION_ROBOT_OPERATION",
                "MATERIAL_FAMILY",
                "SHEET_STACK",
                "ELECTRODE_TIP",
                "PROCESS_PARAMETER_SCHEDULE",
                "CUSTOMER_OEM_CONTEXT",
                "CATEGORY",
                "RULE_LIFECYCLE_EFFECTIVE_DATE",
                "EQUIPMENT_CONFIGURATION",
                name="ck_rule_applicabilities_dimension",
            ),
            nullable=False,
        ),
        sa.Column("allowed_values", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_by_actor_id", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "engineering_rule_id",
            "applicability_id",
            "applicability_revision",
            name="uq_rule_applicabilities_revision_identity",
        ),
        sa.UniqueConstraint(
            "engineering_rule_id",
            "applicability_id",
            "id",
            name="uq_rule_applicabilities_context_internal_id",
        ),
        sa.UniqueConstraint(
            "supersedes_applicability_id",
            name="uq_rule_applicabilities_single_successor",
        ),
        sa.ForeignKeyConstraint(
            ["engineering_rule_id", "engineering_rule_revision_id"],
            [
                "engineering_rule_revisions.engineering_rule_id",
                "engineering_rule_revisions.id",
            ],
            name="fk_rule_applicabilities_exact_rule_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "engineering_rule_id",
                "applicability_id",
                "supersedes_applicability_id",
            ],
            [
                "rule_applicabilities.engineering_rule_id",
                "rule_applicabilities.applicability_id",
                "rule_applicabilities.id",
            ],
            name="fk_rule_applicabilities_same_rule_supersession",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "applicability_revision > 0",
            name="ck_rule_applicabilities_positive_revision",
        ),
        sa.CheckConstraint(
            "supersedes_applicability_id IS NULL "
            "OR supersedes_applicability_id != id",
            name="ck_rule_applicabilities_not_self_superseding",
        ),
    )
    op.create_index(
        "ix_rule_applicabilities_engineering_rule_revision_id",
        "rule_applicabilities",
        ["engineering_rule_revision_id"],
    )


def downgrade():
    op.drop_index(
        "ix_rule_applicabilities_engineering_rule_revision_id",
        table_name="rule_applicabilities",
    )
    op.drop_table("rule_applicabilities")

    with op.batch_alter_table("evidence_references") as batch_op:
        batch_op.drop_constraint(
            "fk_evidence_references_same_context_supersession",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "uq_evidence_references_single_successor",
            type_="unique",
        )
        batch_op.drop_constraint(
            "uq_evidence_references_context_internal_id",
            type_="unique",
        )
        batch_op.drop_constraint(
            "uq_evidence_references_logical_revision",
            type_="unique",
        )
        batch_op.drop_constraint(
            "ck_evidence_references_not_self_superseding",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_evidence_references_positive_revision_number",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_evidence_references_availability",
            type_="check",
        )
        batch_op.drop_column("availability")
        batch_op.drop_column("supersedes_evidence_reference_id")
        batch_op.drop_column("revision_number")
