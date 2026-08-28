"""Persistence adapter for immutable governed rule evaluations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.rule_evaluation import RuleComparisonOutcome
from app.domain.rule_registry_types import RuleOperator
from app.models.rule_evaluation import RuleEvaluation
from app.models.rule_registry import EngineeringRule, EngineeringRuleRevision


class RuleEvaluationRepository:
    """Append-only rule-evaluation persistence under a caller-owned transaction."""

    def __init__(self, session: Session):
        self.session = session

    def list_history(self, evaluation_id: str) -> list[RuleEvaluation]:
        statement = (
            select(RuleEvaluation)
            .where(RuleEvaluation.evaluation_id == evaluation_id)
            .order_by(RuleEvaluation.revision_number, RuleEvaluation.id)
        )
        return list(self.session.scalars(statement))

    def get_latest(self, evaluation_id: str) -> RuleEvaluation | None:
        statement = (
            select(RuleEvaluation)
            .where(RuleEvaluation.evaluation_id == evaluation_id)
            .order_by(RuleEvaluation.revision_number.desc(), RuleEvaluation.id.desc())
        )
        return self.session.scalar(statement)

    def create_evaluation(
        self,
        *,
        engineering_rule: EngineeringRule,
        engineering_rule_revision: EngineeringRuleRevision,
        evaluation_id: str,
        revision_number: int,
        rule_id: str,
        rule_revision: str,
        parameter: str,
        operator: RuleOperator,
        outcome: RuleComparisonOutcome,
        reason: str,
        decision_time: datetime,
        observed_value: float | None,
        observed_unit: str | None,
        compared_value: float | None,
        applicability_snapshot: dict[str, object],
        observation_snapshot: dict[str, object],
        unit_policy_snapshot: dict[str, object],
        result_snapshot: dict[str, object],
        authority_snapshot: dict[str, object],
        created_by_actor_id: str,
        created_by_user_id: int | None,
        schema_version: str,
        canonicalization_version: str,
        hash_algorithm: str,
        content_hash: str,
        software_version: str,
        correlation_id: str,
        supersedes_evaluation_id: int | None = None,
    ) -> RuleEvaluation:
        if engineering_rule not in self.session:
            raise ValueError("engineering rule must belong to this repository session")
        if engineering_rule_revision not in self.session:
            raise ValueError(
                "engineering rule revision must belong to this repository session"
            )
        if engineering_rule_revision.engineering_rule_id != engineering_rule.id:
            raise ValueError("evaluation revision must belong to the same rule")
        if engineering_rule.rule_id != rule_id:
            raise ValueError("evaluation rule_id must match the persisted rule identity")
        if engineering_rule_revision.revision != rule_revision:
            raise ValueError(
                "evaluation rule_revision must match the persisted rule revision"
            )
        if revision_number <= 0:
            raise ValueError("evaluation revision_number must be positive")

        history = self.list_history(evaluation_id)
        if supersedes_evaluation_id is None:
            if history:
                raise ValueError(
                    "existing evaluation identity requires an explicit prior revision"
                )
            if revision_number != 1:
                raise ValueError("first evaluation revision_number must be 1")
        else:
            prior = self.session.get(RuleEvaluation, supersedes_evaluation_id)
            if prior is None:
                raise ValueError("superseded evaluation does not exist")
            if prior.evaluation_id != evaluation_id:
                raise ValueError("evaluation correction cannot cross evaluation identities")
            if prior.engineering_rule_id != engineering_rule.id:
                raise ValueError("evaluation correction must remain within the same rule")
            if revision_number != prior.revision_number + 1:
                raise ValueError("evaluation correction must use the next revision_number")
            if any(item.supersedes_evaluation_id == prior.id for item in history):
                raise ValueError("evaluation already has a successor")

        evaluation = RuleEvaluation(
            evaluation_id=evaluation_id,
            revision_number=revision_number,
            engineering_rule_id=engineering_rule.id,
            engineering_rule_revision_id=engineering_rule_revision.id,
            rule_id=rule_id,
            rule_revision=rule_revision,
            parameter=parameter,
            operator=operator,
            outcome=outcome,
            reason=reason,
            decision_time=decision_time,
            observed_value=observed_value,
            observed_unit=observed_unit,
            compared_value=compared_value,
            applicability_snapshot=applicability_snapshot,
            observation_snapshot=observation_snapshot,
            unit_policy_snapshot=unit_policy_snapshot,
            result_snapshot=result_snapshot,
            authority_snapshot=authority_snapshot,
            supersedes_evaluation_id=supersedes_evaluation_id,
            created_by_user_id=created_by_user_id,
            created_by_actor_id=created_by_actor_id,
            schema_version=schema_version,
            canonicalization_version=canonicalization_version,
            hash_algorithm=hash_algorithm,
            content_hash=content_hash,
            software_version=software_version,
            correlation_id=correlation_id,
        )
        self.session.add(evaluation)
        self.session.flush()
        self.session.refresh(evaluation)
        self.session.expunge(evaluation)
        return evaluation
