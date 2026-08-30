from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from app.api.dependencies import get_governed_actor_user
from app.api.errors import governed_error_response
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_evaluation_service import (
    RuleEvaluationPersistenceDraft,
    RuleEvaluationService,
)
from app.application.rule_registry_service import GovernedAuditMetadata
from app.db.session import SessionLocal
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.models.entities import User, utc_now
from app.schemas.governed_api import (
    RuleEvaluationPersistenceRequest,
    RuleEvaluationPersistenceResponse,
)

router = APIRouter(prefix="/rule-evaluations", tags=["Governed Rule Evaluation"])


def _command_identity(*, evaluation_id: str, idempotency_key: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
        command_scope=evaluation_id,
        idempotency_key=idempotency_key,
    )


def _canonical_request_hash(
    *,
    payload: RuleEvaluationPersistenceRequest,
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
    payload: RuleEvaluationPersistenceRequest,
    actor: User,
    idempotency_key: str,
) -> GovernedAuditMetadata:
    timestamp = utc_now()
    authority_scope = payload.comparison.applicability_result.context.model_dump(
        mode="json"
    )
    return GovernedAuditMetadata(
        event_id=f"rule-evaluation:{payload.evaluation_id}:{idempotency_key}:audit",
        actor_id=f"user:{actor.id}",
        actor_type="user",
        actor_user_id=actor.id,
        actor_role=actor.role,
        authority_scope=authority_scope,
        reason=payload.decision_reason,
        correlation_id=f"rule-evaluation:{payload.evaluation_id}",
        idempotency_key=idempotency_key,
        schema_version="rule-evaluation-api-v1",
        software_version="backend-api-v1",
        canonicalization_version="governed-api-v1",
        hash_algorithm="sha256",
        detail={
            "evaluation_id": payload.evaluation_id,
            "revision_number": payload.revision_number,
            "rule_id": payload.comparison.rule_id,
            "rule_revision": payload.comparison.revision,
            "decision_reason": payload.decision_reason,
            "authority_scope": authority_scope,
        },
        created_at=timestamp,
    )


def _response(
    *,
    payload: RuleEvaluationPersistenceRequest,
    idempotency_key: str,
    result_type: str,
    result_id: str,
    result_revision: str,
) -> RuleEvaluationPersistenceResponse:
    return RuleEvaluationPersistenceResponse(
        decision_outcome=(
            "DENIED"
            if result_type.endswith("_denial")
            else payload.comparison.outcome.value
        ),
        result_type=result_type,
        result_id=result_id,
        result_revision=result_revision,
        evaluation_id=payload.evaluation_id,
        revision_number=payload.revision_number,
        rule_id=payload.comparison.rule_id,
        rule_revision=payload.comparison.revision,
        parameter=payload.comparison.parameter,
        operator=payload.comparison.operator,
        idempotency_key=idempotency_key,
        command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
        command_scope=payload.evaluation_id,
        correlation_id=f"rule-evaluation:{payload.evaluation_id}",
    )


def _command_error(
    *,
    status_code: int,
    error_code: str,
    message: str,
    idempotency_key: str,
    command_scope: str,
    correlation_id: str,
) -> JSONResponse:
    return governed_error_response(
        status_code=status_code,
        error_code=error_code,
        message=message,
        idempotency_key=idempotency_key,
        command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
        command_scope=command_scope,
        correlation_id=correlation_id,
    )


def _execute_rule_evaluation_command(
    *,
    payload: RuleEvaluationPersistenceRequest,
    actor: User,
    idempotency_key: str,
    result_executor: Callable[
        [RuleEvaluationService, GovernedAuditMetadata, CommandIdentity, CanonicalRequestHash, datetime],
        Any,
    ],
) -> RuleEvaluationPersistenceResponse | JSONResponse:
    command_identity = _command_identity(
        evaluation_id=payload.evaluation_id,
        idempotency_key=idempotency_key,
    )
    request_hash = _canonical_request_hash(payload=payload, actor_user_id=actor.id)
    audit = _audit_metadata(payload=payload, actor=actor, idempotency_key=idempotency_key)

    with SessionLocal() as governed_session, GovernedUnitOfWork(governed_session) as unit_of_work:
        try:
            service = RuleEvaluationService(unit_of_work)
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
                    correlation_id=f"rule-evaluation:{payload.evaluation_id}",
                )
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=message,
                idempotency_key=idempotency_key,
                command_scope=command_identity.command_scope,
                correlation_id=f"rule-evaluation:{payload.evaluation_id}",
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
                    correlation_id=f"rule-evaluation:{payload.evaluation_id}",
                )
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=message,
                idempotency_key=idempotency_key,
                command_scope=command_identity.command_scope,
                correlation_id=f"rule-evaluation:{payload.evaluation_id}",
            )
        except Exception as exc:  # noqa: BLE001 pragma: no cover - adapter safety net
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=str(exc),
                idempotency_key=idempotency_key,
                command_scope=command_identity.command_scope,
                correlation_id=f"rule-evaluation:{payload.evaluation_id}",
            )

    return _response(
        payload=payload,
        idempotency_key=idempotency_key,
        result_type=result.result_type,
        result_id=result.result_id,
        result_revision=result.result_revision,
    )


@router.post("", response_model=RuleEvaluationPersistenceResponse)
def persist_rule_evaluation(
    payload: RuleEvaluationPersistenceRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key or not idempotency_key.strip():
        return _command_error(
            status_code=400,
            error_code="MISSING_IDEMPOTENCY_KEY",
            message="Idempotency-Key header is required for rule evaluation persistence",
            idempotency_key=idempotency_key or "",
            command_scope=payload.evaluation_id,
            correlation_id=f"rule-evaluation:{payload.evaluation_id}",
        )

    return _execute_rule_evaluation_command(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        result_executor=lambda service, audit, command_identity, request_hash, completed_at: service.persist_evaluation(
            draft=RuleEvaluationPersistenceDraft(
                evaluation_id=payload.evaluation_id,
                revision_number=payload.revision_number,
                comparison=payload.comparison.as_domain(),
                applicability_result=payload.comparison.applicability_result.as_domain(),
                observation=(
                    payload.observation.as_domain()
                    if payload.observation is not None
                    else None
                ),
                unit_context=(
                    payload.unit_context.as_domain()
                    if payload.unit_context is not None
                    else None
                ),
                unit_catalog=(
                    payload.unit_catalog.as_domain()
                    if payload.unit_catalog is not None
                    else None
                ),
                supersedes_evaluation_id=payload.supersedes_evaluation_id,
            ),
            receipt_id=f"{payload.evaluation_id}:{idempotency_key}",
            command_identity=command_identity,
            request_hash=request_hash,
            audit=audit,
            completed_at=completed_at,
        ),
    )
