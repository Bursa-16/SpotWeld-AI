from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.domain.rule_evaluation import RuleComparisonOutcome
from app.domain.rule_registry_types import RuleOperator
from app.models.entities import utc_now
from app.models.governance import (
    ImmutableJSON,
    freeze_json_attribute,
    portable_enum,
    protect_immutable_model,
)
from app.models.rule_registry import EngineeringRule, EngineeringRuleRevision


class RuleEvaluation(Base):
    __tablename__ = "rule_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id",
            "revision_number",
            name="uq_rule_evaluations_logical_revision",
        ),
        UniqueConstraint(
            "evaluation_id",
            "id",
            name="uq_rule_evaluations_context_internal_id",
        ),
        UniqueConstraint(
            "supersedes_evaluation_id",
            name="uq_rule_evaluations_single_successor",
        ),
        ForeignKeyConstraint(
            ["evaluation_id", "supersedes_evaluation_id"],
            ["rule_evaluations.evaluation_id", "rule_evaluations.id"],
            name="fk_rule_evaluations_same_evaluation_supersession",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["engineering_rule_id", "engineering_rule_revision_id"],
            [
                "engineering_rule_revisions.engineering_rule_id",
                "engineering_rule_revisions.id",
            ],
            name="fk_rule_evaluations_exact_rule_revision",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_rule_evaluations_positive_revision_number",
        ),
        CheckConstraint(
            "supersedes_evaluation_id IS NULL OR supersedes_evaluation_id != id",
            name="ck_rule_evaluations_not_self_superseding",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(String(120))
    revision_number: Mapped[int] = mapped_column(Integer)
    engineering_rule_id: Mapped[int] = mapped_column(
        ForeignKey("engineering_rules.id", ondelete="RESTRICT"), index=True
    )
    engineering_rule_revision_id: Mapped[int] = mapped_column(
        ForeignKey("engineering_rule_revisions.id", ondelete="RESTRICT"),
        index=True,
    )
    rule_id: Mapped[str] = mapped_column(String(120))
    rule_revision: Mapped[str] = mapped_column(String(40))
    parameter: Mapped[str] = mapped_column(String(120))
    operator: Mapped[RuleOperator] = mapped_column(
        portable_enum(
            RuleOperator,
            "ck_rule_evaluations_operator",
        )
    )
    outcome: Mapped[RuleComparisonOutcome] = mapped_column(
        portable_enum(
            RuleComparisonOutcome,
            "ck_rule_evaluations_outcome",
        ),
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    compared_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    applicability_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    observation_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    unit_policy_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    result_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    authority_snapshot: Mapped[dict] = mapped_column(ImmutableJSON)
    supersedes_evaluation_id: Mapped[int | None] = mapped_column(
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

    engineering_rule: Mapped[EngineeringRule] = relationship(
        foreign_keys=[engineering_rule_id]
    )
    engineering_rule_revision: Mapped[EngineeringRuleRevision] = relationship(
        foreign_keys=[engineering_rule_revision_id]
    )


protect_immutable_model(RuleEvaluation)
for _attribute in (
    RuleEvaluation.applicability_snapshot,
    RuleEvaluation.observation_snapshot,
    RuleEvaluation.unit_policy_snapshot,
    RuleEvaluation.result_snapshot,
    RuleEvaluation.authority_snapshot,
):
    freeze_json_attribute(_attribute)
