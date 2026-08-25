"""persistent governed-command idempotency foundation

Revision ID: 0004_persistent_idempotency
Revises: 0003_registry_foundation
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_persistent_idempotency"
down_revision = "0003_registry_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "governed_command_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("receipt_id", sa.String(120), nullable=False, unique=True),
        sa.Column("command_namespace", sa.String(120), nullable=False),
        sa.Column("command_scope", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("request_hash", sa.String(128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "RESERVED",
                "COMPLETED",
                name="ck_governed_command_receipts_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("result_type", sa.String(100), nullable=True),
        sa.Column("result_id", sa.String(120), nullable=True),
        sa.Column("result_revision", sa.String(80), nullable=True),
        sa.Column("correlation_id", sa.String(120), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("software_version", sa.String(80), nullable=False),
        sa.Column("canonicalization_version", sa.String(40), nullable=False),
        sa.Column("hash_algorithm", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "command_namespace",
            "command_scope",
            "idempotency_key",
            name="uq_governed_command_receipts_command_identity",
        ),
        sa.CheckConstraint(
            "(status = 'RESERVED' AND completed_at IS NULL "
            "AND result_type IS NULL AND result_id IS NULL "
            "AND result_revision IS NULL) OR "
            "(status = 'COMPLETED' AND completed_at IS NOT NULL "
            "AND result_type IS NOT NULL AND result_id IS NOT NULL "
            "AND result_revision IS NOT NULL)",
            name="ck_governed_command_receipts_completion_shape",
        ),
    )
    op.create_index(
        "ix_governed_command_receipts_correlation_id",
        "governed_command_receipts",
        ["correlation_id"],
    )


def downgrade():
    op.drop_index(
        "ix_governed_command_receipts_correlation_id",
        table_name="governed_command_receipts",
    )
    op.drop_table("governed_command_receipts")
