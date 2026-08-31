from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_governed_actor_user
from app.api.errors import governed_error_response
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.machine_readiness_service import (
    MachineReadinessPersistenceDraft,
    MachineReadinessService,
)
from app.application.rule_registry_service import GovernedAuditMetadata
from app.db.session import SessionLocal
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.domain.readiness import CheckCondition
from app.models.entities import User, utc_now
from app.models.machine_readiness import (
    MachineReadinessAssessmentRevision,
    MachineReadinessCheckResult,
)
from app.schemas.governed_api import (
    MachineReadinessCheckDefinitionSnapshot,
    MachineReadinessCheckTraceSnapshot,
    MachineReadinessEvaluationSnapshot,
    MachineReadinessPersistenceRequest,
    MachineReadinessPersistenceResponse,
    MachineReadinessPrerequisiteSnapshot,
    MachineReadinessResultSnapshot,
    RuleEvaluationComparisonSnapshot,
)

router = APIRouter(
    prefix="/machine-readiness-assessments",
    tags=["Governed Machine Readiness"],
)


def _command_identity(
    *,
    assessment_id: str,
    idempotency_key: str,
) -> CommandIdentity:
    return CommandIdentity(
        command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
        command_scope=assessment_id,
        idempotency_key=idempotency_key,
    )


def _canonical_request_hash(
    *,
    payload: MachineReadinessPersistenceRequest,
    actor_user_id: int,
) -> CanonicalRequestHash:
    request_payload = payload.model_dump(mode="json")
    request_payload["actor_user_id"] = actor_user_id
    canonical = json.dumps(request_payload, sort_keys=True, separators=(",", ":"))
    return CanonicalRequestHash(
        value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="governed-api-v1",
    )


def _audit_metadata(
    *,
    payload: MachineReadinessPersistenceRequest,
    actor: User,
    idempotency_key: str,
) -> GovernedAuditMetadata:
    timestamp = utc_now()
    authority_scope = payload.result.context.model_dump(mode="json")
    return GovernedAuditMetadata(
        event_id=f"machine-readiness:{payload.assessment_id}:{payload.revision_number}:{idempotency_key}:audit",
        actor_id=f"user:{actor.id}",
        actor_type="user",
        actor_user_id=actor.id,
        actor_role=actor.role,
        authority_scope=authority_scope,
        reason=payload.decision_reason,
        correlation_id=f"machine-readiness:{payload.assessment_id}:{payload.revision_number}",
        idempotency_key=idempotency_key,
        schema_version="machine-readiness-api-v1",
        software_version="backend-api-v1",
        canonicalization_version="governed-api-v1",
        hash_algorithm="sha256",
        detail={
            "assessment_id": payload.assessment_id,
            "revision_number": payload.revision_number,
            "decision_reason": payload.decision_reason,
            "supersedes_assessment_revision_id": payload.supersedes_assessment_revision_id,
            "authority_scope": authority_scope,
        },
        created_at=timestamp,
    )


def _response(
    *,
    payload: MachineReadinessPersistenceRequest,
    idempotency_key: str,
    result_type: str,
    result_id: str,
    result_revision: str,
) -> MachineReadinessPersistenceResponse:
    return MachineReadinessPersistenceResponse(
        decision_outcome=(
            "DENIED" if result_type.endswith("_denial") else payload.result.state.value
        ),
        result_type=result_type,
        result_id=result_id,
        result_revision=result_revision,
        assessment_id=payload.assessment_id,
        revision_number=payload.revision_number,
        supersedes_assessment_revision_id=payload.supersedes_assessment_revision_id,
        result=payload.result,
        checks=payload.checks,
        idempotency_key=idempotency_key,
        command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
        command_scope=payload.assessment_id,
        correlation_id=f"machine-readiness:{payload.assessment_id}:{payload.revision_number}",
    )


def _command_error(
    *,
    status_code: int,
    error_code: str,
    message: str,
    idempotency_key: str | None,
    command_scope: str,
    correlation_id: str,
) -> JSONResponse:
    return governed_error_response(
        status_code=status_code,
        error_code=error_code,
        message=message,
        idempotency_key=idempotency_key,
        command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
        command_scope=command_scope,
        correlation_id=correlation_id,
    )


def _execute_machine_readiness_command(
    *,
    payload: MachineReadinessPersistenceRequest,
    actor: User,
    idempotency_key: str,
    result_executor: Callable[
        [MachineReadinessService, GovernedAuditMetadata, CommandIdentity, CanonicalRequestHash, datetime],
        Any,
    ],
) -> MachineReadinessPersistenceResponse | JSONResponse:
    command_identity = _command_identity(
        assessment_id=payload.assessment_id,
        idempotency_key=idempotency_key,
    )
    request_hash = _canonical_request_hash(payload=payload, actor_user_id=actor.id)
    audit = _audit_metadata(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
    )

    with SessionLocal() as governed_session, GovernedUnitOfWork(governed_session) as unit_of_work:
        try:
            service = MachineReadinessService(unit_of_work)
            result = result_executor(service, audit, command_identity, request_hash, utc_now())
            unit_of_work.commit()
        except ValueError as exc:
            message = str(exc)
            if "idempotency conflict" in message:
                return _command_error(
                    status_code=409,
                    error_code="IDEMPOTENCY_CONFLICT",
                    message=message,
                    idempotency_key=idempotency_key,
                    command_scope=command_identity.command_scope,
                    correlation_id=audit.correlation_id,
                )
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=message,
                idempotency_key=idempotency_key,
                command_scope=command_identity.command_scope,
                correlation_id=audit.correlation_id,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "already in progress" in message:
                return _command_error(
                    status_code=409,
                    error_code="IDEMPOTENCY_IN_PROGRESS",
                    message=message,
                    idempotency_key=idempotency_key,
                    command_scope=command_identity.command_scope,
                    correlation_id=audit.correlation_id,
                )
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=message,
                idempotency_key=idempotency_key,
                command_scope=command_identity.command_scope,
                correlation_id=audit.correlation_id,
            )
        except (AttributeError, SQLAlchemyError, TypeError) as exc:
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=str(exc),
                idempotency_key=idempotency_key,
                command_scope=command_identity.command_scope,
                correlation_id=audit.correlation_id,
            )

    return _response(
        payload=payload,
        idempotency_key=idempotency_key,
        result_type=result.result_type,
        result_id=result.result_id,
        result_revision=result.result_revision,
    )


def _evaluation_snapshot_from_row_snapshot(
    snapshot: dict[str, Any],
) -> MachineReadinessEvaluationSnapshot:
    comparison = RuleEvaluationComparisonSnapshot.model_validate(
        _normalize_snapshot(snapshot["result_snapshot"])
    )
    return MachineReadinessEvaluationSnapshot(
        evaluation_id=str(snapshot["evaluation_id"]),
        revision_number=int(snapshot["revision_number"]),
        comparison=comparison,
    )


def _normalize_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_snapshot(subvalue) for key, subvalue in value.items()}
    if isinstance(value, tuple):
        if not value:
            return []
        if all(
            isinstance(item, dict)
            and "dimension" in item
            and "values" in item
            for item in value
        ):
            return {
                str(item["dimension"]): _normalize_snapshot(item["values"])
                for item in value
            }
        if all(
            isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)
            for item in value
        ):
            return {
                str(key): _normalize_snapshot(subvalue)
                for key, subvalue in value
            }
        return [_normalize_snapshot(item) for item in value]
    if isinstance(value, list):
        return [_normalize_snapshot(item) for item in value]
    return value


def _definition_from_check_snapshot(
    snapshot: dict[str, Any],
) -> MachineReadinessCheckDefinitionSnapshot:
    return MachineReadinessCheckDefinitionSnapshot(
        check_id=str(snapshot["check_id"]),
        required=bool(snapshot["required"]),
        description=snapshot.get("description"),
        evaluations=[
            _evaluation_snapshot_from_row_snapshot(evaluation)
            for evaluation in snapshot.get("evaluations", [])
        ],
    )


def _trace_from_check_snapshot(
    snapshot: dict[str, Any],
) -> MachineReadinessCheckTraceSnapshot:
    return MachineReadinessCheckTraceSnapshot(
        check_id=str(snapshot["check_id"]),
        required=bool(snapshot["required"]),
        description=snapshot.get("description"),
        evaluations=[
            _evaluation_snapshot_from_row_snapshot(evaluation)
            for evaluation in snapshot.get("evaluations", [])
        ],
        condition=CheckCondition(str(snapshot["condition"])),
        reason=str(snapshot["reason"]),
    )


def _result_from_revision(
    *,
    revision: MachineReadinessAssessmentRevision,
    check_rows: Sequence[MachineReadinessCheckResult],
) -> MachineReadinessResultSnapshot:
    snapshot = revision.result_snapshot
    return MachineReadinessResultSnapshot(
        state=revision.state,
        reasons=list(snapshot.get("reasons", [])),
        prerequisites=[
            MachineReadinessPrerequisiteSnapshot(label=str(label), satisfied=bool(satisfied))
            for label, satisfied in snapshot.get("prerequisites", [])
        ],
        context={
            "customer": snapshot["context"].get("customer"),
            "project": snapshot["context"].get("project"),
            "site": snapshot["context"].get("site"),
            "machine": snapshot["context"].get("machine"),
        },
        decision_time=revision.decision_time,
        validated_applicable_basis_count=revision.validated_applicable_basis_count,
        checks=[
            _trace_from_check_snapshot(
                row.check_snapshot if row.check_snapshot is not None else {}
            )
            for row in check_rows
        ],
    )


def _load_revision_response(
    *,
    session,
    assessment_id: str,
    revision_number: int,
) -> MachineReadinessPersistenceResponse | None:
    revision = session.scalar(
        select(MachineReadinessAssessmentRevision).where(
            MachineReadinessAssessmentRevision.assessment_id == assessment_id,
            MachineReadinessAssessmentRevision.revision_number == revision_number,
        )
    )
    if revision is None:
        return None

    check_rows = list(
        session.scalars(
            select(MachineReadinessCheckResult)
            .where(
                MachineReadinessCheckResult.assessment_revision_id == revision.id
            )
            .order_by(MachineReadinessCheckResult.check_id, MachineReadinessCheckResult.id)
        )
    )
    checks = [
        _definition_from_check_snapshot(row.check_snapshot)
        for row in check_rows
    ]
    result = _result_from_revision(revision=revision, check_rows=check_rows)
    return MachineReadinessPersistenceResponse(
        decision_outcome=result.state.value,
        result_type="machine_readiness",
        result_id=assessment_id,
        result_revision=str(revision_number),
        assessment_id=assessment_id,
        revision_number=revision_number,
        supersedes_assessment_revision_id=revision.supersedes_assessment_revision_id,
        result=result,
        checks=checks,
        idempotency_key=revision.authority_snapshot["idempotency_key"],
        command_namespace=revision.authority_snapshot["policy_identifier"],
        command_scope=assessment_id,
        correlation_id=revision.correlation_id,
    )


@router.post("", response_model=MachineReadinessPersistenceResponse)
def persist_machine_readiness(
    payload: MachineReadinessPersistenceRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key or not idempotency_key.strip():
        return _command_error(
            status_code=400,
            error_code="MISSING_IDEMPOTENCY_KEY",
            message="Idempotency-Key header is required for machine readiness commands",
            idempotency_key=idempotency_key,
            command_scope=payload.assessment_id,
            correlation_id=f"machine-readiness:{payload.assessment_id}:{payload.revision_number}",
        )

    return _execute_machine_readiness_command(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        result_executor=lambda service, audit, command_identity, request_hash, completed_at: service.persist_assessment(
            draft=MachineReadinessPersistenceDraft(
                assessment_id=payload.assessment_id,
                revision_number=payload.revision_number,
                result=payload.result.as_domain(),
                checks=tuple(check.as_domain() for check in payload.checks),
                supersedes_assessment_revision_id=payload.supersedes_assessment_revision_id,
            ),
            receipt_id=f"{payload.assessment_id}:{payload.revision_number}:{idempotency_key}",
            command_identity=command_identity,
            request_hash=request_hash,
            audit=audit,
            completed_at=completed_at,
        ),
    )


@router.get(
    "/{assessment_id}/revisions/{revision_number}",
    response_model=MachineReadinessPersistenceResponse,
)
def get_machine_readiness_revision(
    assessment_id: str,
    revision_number: int,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
):
    _ = actor
    with SessionLocal() as session:
        response = _load_revision_response(
            session=session,
            assessment_id=assessment_id,
            revision_number=revision_number,
        )
    if response is None:
        return _command_error(
            status_code=404,
            error_code="MACHINE_READINESS_REVISION_NOT_FOUND",
            message="machine readiness revision not found",
            idempotency_key=None,
            command_scope=assessment_id,
            correlation_id=f"machine-readiness:{assessment_id}:{revision_number}",
        )
    return response
