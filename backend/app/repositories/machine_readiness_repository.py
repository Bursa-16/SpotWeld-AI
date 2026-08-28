"""Persistence adapter for immutable governed machine-readiness assessments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.readiness import CheckCondition, ReadinessState
from app.models.machine_readiness import (
    MachineReadinessAssessment,
    MachineReadinessAssessmentRevision,
    MachineReadinessCheckResult,
)


class MachineReadinessRepository:
    """Append-only MRC persistence under a caller-owned transaction."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_assessment_id(self, assessment_id: str) -> MachineReadinessAssessment | None:
        return self.session.scalar(
            select(MachineReadinessAssessment).where(
                MachineReadinessAssessment.assessment_id == assessment_id
            )
        )

    def create_assessment(
        self,
        *,
        assessment_id: str,
        created_by_actor_id: str,
        created_by_user_id: int | None = None,
    ) -> MachineReadinessAssessment:
        assessment = MachineReadinessAssessment(
            assessment_id=assessment_id,
            created_by_user_id=created_by_user_id,
            created_by_actor_id=created_by_actor_id,
        )
        self.session.add(assessment)
        self.session.flush()
        self.session.refresh(assessment)
        self.session.expunge(assessment)
        return assessment

    def list_history(self, assessment_id: str) -> list[MachineReadinessAssessmentRevision]:
        statement = (
            select(MachineReadinessAssessmentRevision)
            .where(MachineReadinessAssessmentRevision.assessment_id == assessment_id)
            .order_by(
                MachineReadinessAssessmentRevision.revision_number,
                MachineReadinessAssessmentRevision.id,
            )
        )
        return list(self.session.scalars(statement))

    def get_latest_revision(
        self,
        assessment_id: str,
    ) -> MachineReadinessAssessmentRevision | None:
        statement = (
            select(MachineReadinessAssessmentRevision)
            .where(MachineReadinessAssessmentRevision.assessment_id == assessment_id)
            .order_by(
                MachineReadinessAssessmentRevision.revision_number.desc(),
                MachineReadinessAssessmentRevision.id.desc(),
            )
        )
        return self.session.scalar(statement)

    def create_revision(
        self,
        *,
        assessment: MachineReadinessAssessment,
        revision_number: int,
        state: ReadinessState,
        decision_time: datetime,
        context_snapshot: dict[str, object],
        prerequisites_snapshot: list[dict[str, object]],
        result_snapshot: dict[str, object],
        validated_applicable_basis_count: int,
        created_by_actor_id: str,
        created_by_user_id: int | None,
        schema_version: str,
        canonicalization_version: str,
        hash_algorithm: str,
        content_hash: str,
        authority_snapshot: dict[str, object],
        software_version: str,
        correlation_id: str,
        supersedes_assessment_revision_id: int | None = None,
    ) -> MachineReadinessAssessmentRevision:
        if not assessment.assessment_id.strip():
            raise ValueError("machine readiness assessment must have an identity")
        if revision_number <= 0:
            raise ValueError("assessment revision_number must be positive")

        history = self.list_history(assessment.assessment_id)
        if supersedes_assessment_revision_id is None:
            if history:
                raise ValueError(
                    "existing assessment identity requires an explicit prior revision"
                )
            if revision_number != 1:
                raise ValueError("first assessment revision_number must be 1")
        else:
            prior = self.session.get(
                MachineReadinessAssessmentRevision, supersedes_assessment_revision_id
            )
            if prior is None:
                raise ValueError("superseded assessment revision does not exist")
            if prior.assessment_id != assessment.assessment_id:
                raise ValueError(
                    "assessment correction cannot cross assessment identities"
                )
            if revision_number != prior.revision_number + 1:
                raise ValueError(
                    "assessment correction must use the next revision_number"
                )
            if any(item.supersedes_assessment_revision_id == prior.id for item in history):
                raise ValueError("assessment revision already has a successor")

        revision = MachineReadinessAssessmentRevision(
            assessment_id=assessment.assessment_id,
            revision_number=revision_number,
            decision_time=decision_time,
            state=state,
            context_snapshot=context_snapshot,
            prerequisites_snapshot=prerequisites_snapshot,
            result_snapshot=result_snapshot,
            validated_applicable_basis_count=validated_applicable_basis_count,
            supersedes_assessment_revision_id=supersedes_assessment_revision_id,
            created_by_user_id=created_by_user_id,
            created_by_actor_id=created_by_actor_id,
            schema_version=schema_version,
            canonicalization_version=canonicalization_version,
            hash_algorithm=hash_algorithm,
            content_hash=content_hash,
            authority_snapshot=authority_snapshot,
            software_version=software_version,
            correlation_id=correlation_id,
        )
        self.session.add(revision)
        self.session.flush()
        self.session.refresh(revision)
        self.session.expunge(revision)
        if assessment in self.session:
            self.session.expire(assessment, ["revisions"])
        return revision

    def create_check_result(
        self,
        *,
        assessment_revision: MachineReadinessAssessmentRevision,
        check_id: str,
        required: bool,
        description: str | None,
        condition: CheckCondition,
        reason: str,
        check_snapshot: dict[str, object],
    ) -> MachineReadinessCheckResult:
        if assessment_revision.id is None:
            raise ValueError("assessment revision must have a database identity")
        check_result = MachineReadinessCheckResult(
            assessment_revision_id=assessment_revision.id,
            check_id=check_id,
            required=required,
            description=description,
            condition=condition,
            reason=reason,
            check_snapshot=check_snapshot,
        )
        self.session.add(check_result)
        self.session.flush()
        self.session.refresh(check_result)
        self.session.expunge(check_result)
        return check_result
