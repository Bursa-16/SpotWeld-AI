"""initial project and weld point schema"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_code", sa.String(80), nullable=False),
        sa.Column("project_name", sa.String(200), nullable=False),
        sa.Column("customer", sa.String(200), nullable=False, server_default=""),
        sa.Column("vehicle_platform", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="Aktif"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_code"),
    )
    op.create_table("weld_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("point_code", sa.String(100), nullable=False),
        sa.Column("part_no", sa.String(120), nullable=False, server_default=""),
        sa.Column("part_revision", sa.String(40), nullable=False, server_default=""),
        sa.Column("station", sa.String(100), nullable=False, server_default=""),
        sa.Column("robot", sa.String(100), nullable=False, server_default=""),
        sa.Column("gun", sa.String(100), nullable=False, server_default=""),
        sa.Column("operation_no", sa.String(100), nullable=False, server_default=""),
        sa.Column("criticality", sa.String(50), nullable=False, server_default="Standart"),
        sa.Column("approval_status", sa.String(50), nullable=False, server_default="Taslak"),
        sa.Column("analysis_input", sa.JSON(), nullable=False),
        sa.Column("analysis_result", sa.JSON(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "point_code", name="uq_project_point"),
    )
    op.create_table("weld_point_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("weld_point_id", sa.Integer(), sa.ForeignKey("weld_points.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("changed_by", sa.String(150), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("weld_point_id", "revision_no", name="uq_point_revision"),
    )
    op.create_table("approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("weld_point_id", sa.Integer(), sa.ForeignKey("weld_points.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approval_type", sa.String(80), nullable=False),
        sa.Column("approver", sa.String(150), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("approvals")
    op.drop_table("weld_point_revisions")
    op.drop_table("weld_points")
    op.drop_table("projects")
