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
from app.application.rule_registry_service import (
    GovernedAuditMetadata,
    RuleRegistryService,
)
from app.db.session import SessionLocal
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.models.entities import User, utc_now
from app.schemas.governed_api import (
    RuleRegistryLifecycleRequest,
    RuleRegistryLifecycleResponse,
    RuleRegistrySourceBackedPromotionRequest,
)

router = APIRouter(prefix="/rule-registry", tags=["Governed Rule Registry"])


def _command_identity(*, namespace: str, rule_id: str, idempotency_key: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace=namespace,
        command_scope=rule_id,
        idempotency_key=idempotency_key,
    )


def _canonical_request_hash(payload: dict[str, Any]) -> CanonicalRequestHash:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return CanonicalRequestHash(
        value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="governed-api-v1",
    )


def _audit_metadata(
    *,
    event_id: str,
    actor: User,
    authority_scope: dict[str, object],
    idempotency_key: str,
    decision_reason: str,
    correlation_id: str,
) -> GovernedAuditMetadata:
    timestamp = utc_now()
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id=f"user:{actor.id}",
        actor_type="user",
        actor_user_id=actor.id,
        actor_role=actor.role,
        authority_scope=authority_scope,
        reason=decision_reason,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        schema_version="rule-registry-api-v1",
        software_version="backend-api-v1",
        canonicalization_version="governed-api-v1",
        hash_algorithm="sha256",
        detail={
            "decision_reason": decision_reason,
            "authority_scope": authority_scope,
        },
        created_at=timestamp,
    )


def _response(
    *,
    decision_outcome: str,
    result_type: str,
    result_id: str,
    result_revision: str,
    rule_id: str,
    source_revision: str,
    authority_scope: dict[str, object],
    idempotency_key: str,
    command_namespace: str,
    command_scope: str,
    correlation_id: str,
) -> RuleRegistryLifecycleResponse:
    return RuleRegistryLifecycleResponse(
        decision_outcome=decision_outcome,
        result_type=result_type,
        result_id=result_id,
        result_revision=result_revision,
        rule_id=rule_id,
        source_revision=source_revision,
        authority_scope=authority_scope,
        idempotency_key=idempotency_key,
        command_namespace=command_namespace,
        command_scope=command_scope,
        correlation_id=correlation_id,
    )


def _command_error(
    *,
    status_code: int,
    error_code: str,
    message: str,
    idempotency_key: str,
    command_namespace: str,
    command_scope: str,
    correlation_id: str,
) -> JSONResponse:
    return governed_error_response(
        status_code=status_code,
        error_code=error_code,
        message=message,
        idempotency_key=idempotency_key,
        command_namespace=command_namespace,
        command_scope=command_scope,
        correlation_id=correlation_id,
    )


def _command_result_outcome(result_type: str, command_outcome: str) -> str:
    if result_type.endswith("_denial"):
        return "DENIED"
    return command_outcome


def _execute_rule_registry_command(
    *,
    payload: RuleRegistrySourceBackedPromotionRequest | RuleRegistryLifecycleRequest,
    actor: User,
    idempotency_key: str,
    command_namespace: str,
    command_outcome: str,
    command_name: str,
    result_executor: Callable[[RuleRegistryService, GovernedAuditMetadata, CommandIdentity, CanonicalRequestHash, datetime], Any],
) -> RuleRegistryLifecycleResponse | JSONResponse:
    command_identity = _command_identity(
        namespace=command_namespace,
        rule_id=payload.rule_id,
        idempotency_key=idempotency_key,
    )
    authority_scope = payload.authority_scope.model_dump(mode="json")
    correlation_id = f"{command_name}:{payload.rule_id}:{payload.source_revision}"
    if isinstance(payload, RuleRegistrySourceBackedPromotionRequest):
        correlation_id = f"{correlation_id}:{payload.revision}"

    request_payload: dict[str, Any] = {
        "command": command_name,
        "rule_id": payload.rule_id,
        "source_revision": payload.source_revision,
        "authority_scope": authority_scope,
        "decision_reason": payload.decision_reason,
        "actor_user_id": actor.id,
    }
    if isinstance(payload, RuleRegistrySourceBackedPromotionRequest):
        request_payload.update(
            {
                "revision": payload.revision,
                "version_metadata": payload.version_metadata.model_dump(mode="json"),
            }
        )
    else:
        request_payload.update(
            {
                "effective_from": payload.effective_from.isoformat(),
                "expires_at": payload.expires_at.isoformat()
                if payload.expires_at is not None
                else None,
            }
        )
    request_hash = _canonical_request_hash(request_payload)
    audit = _audit_metadata(
        event_id=f"{correlation_id}:{idempotency_key}:audit",
        actor=actor,
        authority_scope=authority_scope,
        idempotency_key=idempotency_key,
        decision_reason=payload.decision_reason,
        correlation_id=correlation_id,
    )

    with SessionLocal() as governed_session, GovernedUnitOfWork(governed_session) as unit_of_work:
        try:
            service = RuleRegistryService(unit_of_work)
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
                    command_namespace=command_namespace,
                    command_scope=command_identity.command_scope,
                    correlation_id=correlation_id,
                )
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=message,
                idempotency_key=idempotency_key,
                command_namespace=command_namespace,
                command_scope=command_identity.command_scope,
                correlation_id=correlation_id,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "already in progress" in message:
                return _command_error(
                    status_code=409,
                    error_code="IDEMPOTENCY_IN_PROGRESS",
                    message=message,
                    idempotency_key=idempotency_key,
                    command_namespace=command_namespace,
                    command_scope=command_identity.command_scope,
                    correlation_id=correlation_id,
                )
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=message,
                idempotency_key=idempotency_key,
                command_namespace=command_namespace,
                command_scope=command_identity.command_scope,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # pragma: no cover - adapter safety net  # noqa: BLE001
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=str(exc),
                idempotency_key=idempotency_key,
                command_namespace=command_namespace,
                command_scope=command_identity.command_scope,
                correlation_id=correlation_id,
            )

    return _response(
        decision_outcome=_command_result_outcome(result.result_type, command_outcome),
        result_type=result.result_type,
        result_id=result.result_id,
        result_revision=result.result_revision,
        rule_id=payload.rule_id,
        source_revision=payload.source_revision,
        authority_scope=authority_scope,
        idempotency_key=idempotency_key,
        command_namespace=command_namespace,
        command_scope=command_identity.command_scope,
        correlation_id=correlation_id,
    )


@router.post("/source-backed-promotion", response_model=RuleRegistryLifecycleResponse)
def source_backed_promotion(
    payload: RuleRegistrySourceBackedPromotionRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key or not idempotency_key.strip():
        return _command_error(
            status_code=400,
            error_code="MISSING_IDEMPOTENCY_KEY",
            message="Idempotency-Key header is required for rule registry commands",
            idempotency_key=idempotency_key,
            command_namespace=RuleRegistryService.COMMAND_NAMESPACE,
            command_scope=payload.rule_id,
            correlation_id=f"source-backed-promotion:{payload.rule_id}:{payload.source_revision}:{payload.revision}",
        )

    return _execute_rule_registry_command(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        command_namespace=RuleRegistryService.COMMAND_NAMESPACE,
        command_outcome="SOURCE_BACKED",
        command_name="source-backed-promotion",
        result_executor=lambda service, audit, command_identity, request_hash, completed_at: service.promote_source_backed(
            rule_id=payload.rule_id,
            source_revision=payload.source_revision,
            revision=payload.revision,
            version_metadata=payload.version_metadata.as_domain(),
            receipt_id=f"{payload.rule_id}:{payload.source_revision}:{payload.revision}:{idempotency_key}",
            command_identity=command_identity,
            request_hash=request_hash,
            audit=audit,
            completed_at=completed_at,
        ),
    )


@router.post("/source-backed-enablement", response_model=RuleRegistryLifecycleResponse)
def source_backed_enablement(
    payload: RuleRegistryLifecycleRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key or not idempotency_key.strip():
        return _command_error(
            status_code=400,
            error_code="MISSING_IDEMPOTENCY_KEY",
            message="Idempotency-Key header is required for rule registry commands",
            idempotency_key=idempotency_key,
            command_namespace=RuleRegistryService.ENABLEMENT_COMMAND_NAMESPACE,
            command_scope=payload.rule_id,
            correlation_id=f"source-backed-enablement:{payload.rule_id}:{payload.source_revision}",
        )

    return _execute_rule_registry_command(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        command_namespace=RuleRegistryService.ENABLEMENT_COMMAND_NAMESPACE,
        command_outcome="ENABLED",
        command_name="source-backed-enablement",
        result_executor=lambda service, audit, command_identity, request_hash, completed_at: service.enable_source_backed(
            rule_id=payload.rule_id,
            source_revision=payload.source_revision,
            receipt_id=f"{payload.rule_id}:{payload.source_revision}:{idempotency_key}",
            command_identity=command_identity,
            request_hash=request_hash,
            audit=audit,
            effective_from=payload.effective_from,
            expires_at=payload.expires_at,
            completed_at=completed_at,
        ),
    )


@router.post("/source-backed-activation", response_model=RuleRegistryLifecycleResponse)
def source_backed_activation(
    payload: RuleRegistryLifecycleRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key or not idempotency_key.strip():
        return _command_error(
            status_code=400,
            error_code="MISSING_IDEMPOTENCY_KEY",
            message="Idempotency-Key header is required for rule registry commands",
            idempotency_key=idempotency_key,
            command_namespace=RuleRegistryService.ACTIVATION_COMMAND_NAMESPACE,
            command_scope=payload.rule_id,
            correlation_id=f"source-backed-activation:{payload.rule_id}:{payload.source_revision}",
        )

    return _execute_rule_registry_command(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        command_namespace=RuleRegistryService.ACTIVATION_COMMAND_NAMESPACE,
        command_outcome="ACTIVE",
        command_name="source-backed-activation",
        result_executor=lambda service, audit, command_identity, request_hash, completed_at: service.activate_source_backed(
            rule_id=payload.rule_id,
            source_revision=payload.source_revision,
            receipt_id=f"{payload.rule_id}:{payload.source_revision}:{idempotency_key}",
            command_identity=command_identity,
            request_hash=request_hash,
            audit=audit,
            effective_from=payload.effective_from,
            expires_at=payload.expires_at,
            completed_at=completed_at,
        ),
    )
