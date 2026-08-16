"""empty engineering Registry revision persistence foundation

Revision ID: 0003_registry_foundation
Revises: 0002_auth_audit
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_registry_foundation"
down_revision = "0002_auth_audit"
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
        "engineering_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.String(120), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_by_actor_id", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("rule_id", name="uq_engineering_rules_rule_id"),
    )

    op.create_table(
        "engineering_rule_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "engineering_rule_id",
            sa.Integer(),
            sa.ForeignKey("engineering_rules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "status",
            _enum(
                "DRAFT",
                "REVIEW",
                "ACTIVE",
                "SUPERSEDED",
                "DEPRECATED",
                "EXPIRED",
                name="ck_engineering_rule_revisions_lifecycle_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "evidence_class",
            _enum(
                "SOURCE_BACKED",
                "PROPOSED",
                "UNRESOLVED",
                name="ck_engineering_rule_revisions_evidence_class",
            ),
            nullable=False,
        ),
        sa.Column(
            "category",
            _enum(
                "EQUIPMENT",
                "MATERIAL",
                "PARAMETER",
                "ELECTRODE",
                "MACHINE",
                "COOLING",
                "OTHER",
                name="ck_engineering_rule_revisions_category",
            ),
            nullable=False,
        ),
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
                name="ck_engineering_rule_revisions_operator",
            ),
            nullable=True,
        ),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(80), nullable=True),
        sa.Column("applicability_metadata", sa.JSON(), nullable=True),
        sa.Column("applicability_schema_version", sa.String(40), nullable=True),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_revision_id", sa.Integer(), nullable=True),
        sa.Column(
            "source_type",
            _enum(
                "OEM",
                "ISO",
                "AWS",
                "SEP",
                "COMPANY_STANDARD",
                "FIELD_MODEL",
                "LITERATURE",
                "DERIVED",
                name="ck_engineering_rule_revisions_source_type",
            ),
            nullable=True,
        ),
        sa.Column("source_name", sa.String(255), nullable=True),
        sa.Column("source_document", sa.String(255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "safe_default",
            _enum(
                "UNRESOLVED",
                "MANUAL_REVIEW",
                name="ck_engineering_rule_revisions_safe_default",
            ),
            nullable=False,
        ),
        sa.Column(
            "missing_handling",
            _enum(
                "DATA_INSUFFICIENT",
                "SKIP_OPTIONAL",
                name="ck_engineering_rule_revisions_missing_handling",
            ),
            nullable=False,
        ),
        sa.Column("conflict_handling", sa.String(120), nullable=True),
        sa.Column("unit_mismatch_handling", sa.String(120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason_for_change", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("canonicalization_version", sa.String(40), nullable=False),
        sa.Column("hash_algorithm", sa.String(40), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("software_version", sa.String(80), nullable=False),
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
            "revision",
            name="uq_engineering_rule_revisions_rule_revision",
        ),
        sa.UniqueConstraint(
            "engineering_rule_id",
            "id",
            name="uq_engineering_rule_revisions_rule_internal_id",
        ),
        sa.ForeignKeyConstraint(
            ["engineering_rule_id", "supersedes_revision_id"],
            [
                "engineering_rule_revisions.engineering_rule_id",
                "engineering_rule_revisions.id",
            ],
            name="fk_engineering_rule_revisions_same_rule_supersession",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "supersedes_revision_id IS NULL OR supersedes_revision_id != id",
            name="ck_engineering_rule_revisions_not_self_superseding",
        ),
        sa.CheckConstraint(
            "expiry_date IS NULL OR effective_date IS NULL OR expiry_date > effective_date",
            name="ck_engineering_rule_revisions_effective_window",
        ),
    )
    op.create_index(
        "ix_engineering_rule_revisions_engineering_rule_id",
        "engineering_rule_revisions",
        ["engineering_rule_id"],
    )

    op.create_table(
        "evidence_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "engineering_rule_revision_id",
            sa.Integer(),
            sa.ForeignKey("engineering_rule_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("evidence_id", sa.String(120), nullable=False),
        sa.Column("evidence_revision", sa.String(80), nullable=False),
        sa.Column(
            "source_type",
            _enum(
                "OEM",
                "ISO",
                "AWS",
                "SEP",
                "COMPANY_STANDARD",
                "FIELD_MODEL",
                "LITERATURE",
                "DERIVED",
                name="ck_evidence_references_source_type",
            ),
            nullable=True,
        ),
        sa.Column("source_name", sa.String(255), nullable=True),
        sa.Column("source_document", sa.String(255), nullable=True),
        sa.Column("edition", sa.String(100), nullable=True),
        sa.Column("section_reference", sa.String(120), nullable=True),
        sa.Column("page_reference", sa.String(120), nullable=True),
        sa.Column("table_reference", sa.String(120), nullable=True),
        sa.Column(
            "evidence_class",
            _enum(
                "SOURCE_BACKED",
                "PROPOSED",
                "UNRESOLVED",
                name="ck_evidence_references_evidence_class",
            ),
            nullable=False,
        ),
        sa.Column(
            "lifecycle_status",
            _enum(
                "DRAFT",
                "REVIEW",
                "ACTIVE",
                "SUPERSEDED",
                "DEPRECATED",
                "EXPIRED",
                name="ck_evidence_references_lifecycle_status",
            ),
            nullable=False,
        ),
        sa.Column("reference_uri", sa.Text(), nullable=True),
        sa.Column("reference_metadata", sa.JSON(), nullable=True),
        sa.Column("schema_version", sa.String(40), nullable=True),
        sa.Column("hash_algorithm", sa.String(40), nullable=True),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column(
            "verified_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("verified_by_actor_id", sa.String(200), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "approved_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("approved_by_actor_id", sa.String(200), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_by_actor_id", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "engineering_rule_revision_id",
            "evidence_id",
            "evidence_revision",
            name="uq_evidence_references_revision_identity",
        ),
    )
    op.create_index(
        "ix_evidence_references_engineering_rule_revision_id",
        "evidence_references",
        ["engineering_rule_revision_id"],
    )

    op.create_table(
        "governed_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(120), nullable=False, unique=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(120), nullable=False),
        sa.Column("entity_revision", sa.String(80), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("actor_type", sa.String(40), nullable=False),
        sa.Column("actor_role", sa.String(100), nullable=True),
        sa.Column("authority_scope", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("software_version", sa.String(80), nullable=False),
        sa.Column("canonicalization_version", sa.String(40), nullable=False),
        sa.Column("hash_algorithm", sa.String(40), nullable=False),
        sa.Column("prior_content_hash", sa.String(128), nullable=True),
        sa.Column("new_content_hash", sa.String(128), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column(
            "correction_of_event_id",
            sa.Integer(),
            sa.ForeignKey("governed_audit_events.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_governed_audit_events_entity_type",
        "governed_audit_events",
        ["entity_type"],
    )
    op.create_index(
        "ix_governed_audit_events_entity_id",
        "governed_audit_events",
        ["entity_id"],
    )
    op.create_index(
        "ix_governed_audit_events_correlation_id",
        "governed_audit_events",
        ["correlation_id"],
    )


def downgrade():
    op.drop_index(
        "ix_governed_audit_events_correlation_id",
        table_name="governed_audit_events",
    )
    op.drop_index(
        "ix_governed_audit_events_entity_id",
        table_name="governed_audit_events",
    )
    op.drop_index(
        "ix_governed_audit_events_entity_type",
        table_name="governed_audit_events",
    )
    op.drop_table("governed_audit_events")
    op.drop_index(
        "ix_evidence_references_engineering_rule_revision_id",
        table_name="evidence_references",
    )
    op.drop_table("evidence_references")
    op.drop_index(
        "ix_engineering_rule_revisions_engineering_rule_id",
        table_name="engineering_rule_revisions",
    )
    op.drop_table("engineering_rule_revisions")
    op.drop_table("engineering_rules")
