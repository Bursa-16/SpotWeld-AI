from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_governed_actor_user
from app.api.errors import governed_error_response
from app.application.digital_weld_passport_service import (
    DigitalWeldPassportLifecycleTransitionDraft,
    DigitalWeldPassportRevisionDraft,
    DigitalWeldPassportService,
)
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import GovernedAuditMetadata
from app.db.session import SessionLocal
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.models.digital_weld_passport import (
    DigitalWeldPassportLifecycleEvent,
    DigitalWeldPassportLifecycleState,
    DigitalWeldPassportRevision,
)
from app.models.entities import User, utc_now
from app.schemas.governed_api import (
    DigitalWeldPassportDraftRequest,
    DigitalWeldPassportLifecycleRequest,
    DigitalWeldPassportResponse,
)

router = APIRouter(
    prefix="/digital-weld-passports",
    tags=["Governed Digital Weld Passport"],
)


def _command_identity(*, passport_id: str, idempotency_key: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace=DigitalWeldPassportService.COMMAND_NAMESPACE,
        command_scope=passport_id,
        idempotency_key=idempotency_key,
    )


def _canonical_request_hash(
    *,
    payload: Any,
    actor_user_id: int,
) -> CanonicalRequestHash:
    if hasattr(payload, "model_dump"):
        request_payload = payload.model_dump(mode="json")
    else:
        request_payload = payload
    request_payload["actor_user_id"] = actor_user_id
    canonical = json.dumps(request_payload, sort_keys=True, separators=(",", ":"))
    return CanonicalRequestHash(
        value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="governed-api-v1",
    )


def _audit_metadata(
    *,
    payload: Any,
    actor: User,
    idempotency_key: str,
    detail: dict[str, Any],
) -> GovernedAuditMetadata:
    timestamp = utc_now()
    authority_scope = payload.authority_scope.model_dump(mode="json")
    return GovernedAuditMetadata(
        event_id=f"dwp:{payload.passport_id}:{payload.revision_number}:{idempotency_key}:audit",
        actor_id=f"user:{actor.id}",
        actor_type="user",
        actor_user_id=actor.id,
        actor_role=actor.role,
        authority_scope=authority_scope,
        reason=payload.decision_reason,
        correlation_id=f"dwp:{payload.passport_id}:{payload.revision_number}",
        idempotency_key=idempotency_key,
        schema_version="dwp-api-v1",
        software_version="backend-api-v1",
        canonicalization_version="governed-api-v1",
        hash_algorithm="sha256",
        detail={
            "authority_scope": authority_scope,
            **detail,
        },
        created_at=timestamp,
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
        command_namespace=DigitalWeldPassportService.COMMAND_NAMESPACE,
        command_scope=command_scope,
        correlation_id=correlation_id,
    )


def _normalize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_json(subvalue) for key, subvalue in value.items()}
    if isinstance(value, tuple):
        return [_normalize_json(item) for item in value]
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    return value


def _response_from_payload(
    *,
    payload: DigitalWeldPassportDraftRequest,
    idempotency_key: str,
    result_type: str,
    result_id: str,
    result_revision: str,
    state: DigitalWeldPassportLifecycleState,
) -> DigitalWeldPassportResponse:
    return DigitalWeldPassportResponse(
        decision_outcome="DENIED" if result_type.endswith("_denial") else state.value,
        result_type=result_type,
        result_id=result_id,
        result_revision=result_revision,
        passport_id=payload.passport_id,
        revision_number=payload.revision_number,
        state=state,
        context_snapshot=payload.context_snapshot.model_dump(mode="json"),
        provenance_snapshot=payload.provenance_snapshot.model_dump(mode="json"),
        authority_snapshot={
            "scope_snapshot": payload.authority_scope.model_dump(mode="json"),
        },
        mrc_snapshot=payload.mrc_snapshot.model_dump(mode="json"),
        supersedes_revision_id=payload.supersedes_revision_id,
        idempotency_key=idempotency_key,
        command_namespace=DigitalWeldPassportService.COMMAND_NAMESPACE,
        command_scope=payload.passport_id,
        correlation_id=f"dwp:{payload.passport_id}:{payload.revision_number}",
    )


def _response_from_revision(
    *,
    revision: DigitalWeldPassportRevision,
    current_state: DigitalWeldPassportLifecycleState,
    current_result_type: str,
    idempotency_key: str,
    decision_outcome: str | None = None,
    result_id: str | None = None,
    result_revision: str | None = None,
) -> DigitalWeldPassportResponse:
    return DigitalWeldPassportResponse(
        decision_outcome=decision_outcome or current_state.value,
        result_type=current_result_type,
        result_id=result_id or revision.passport_id,
        result_revision=result_revision or str(revision.revision_number),
        passport_id=revision.passport_id,
        revision_number=revision.revision_number,
        state=current_state,
        context_snapshot=_normalize_json(revision.context_snapshot),
        provenance_snapshot=_normalize_json(revision.provenance_snapshot),
        authority_snapshot=_normalize_json(revision.authority_snapshot),
        mrc_snapshot=(
            None if revision.mrc_snapshot is None else _normalize_json(revision.mrc_snapshot)
        ),
        supersedes_revision_id=revision.supersedes_revision_id,
        idempotency_key=idempotency_key,
        command_namespace=DigitalWeldPassportService.COMMAND_NAMESPACE,
        command_scope=revision.passport_id,
        correlation_id=revision.correlation_id,
    )


def _load_exact_revision_response(
    *,
    session,
    passport_id: str,
    revision_number: int,
    idempotency_key: str,
) -> DigitalWeldPassportResponse | None:
    loaded = _load_exact_revision(
        session=session,
        passport_id=passport_id,
        revision_number=revision_number,
    )
    if loaded is None:
        return None
    revision, current = loaded
    return _response_from_revision(
        revision=revision,
        current_state=current.state,
        current_result_type="digital_weld_passport",
        idempotency_key=idempotency_key,
    )


def _load_exact_revision(
    *,
    session,
    passport_id: str,
    revision_number: int,
) -> tuple[DigitalWeldPassportRevision, DigitalWeldPassportLifecycleEvent] | None:
    revision = session.scalar(
        select(DigitalWeldPassportRevision).where(
            DigitalWeldPassportRevision.passport_id == passport_id,
            DigitalWeldPassportRevision.revision_number == revision_number,
        )
    )
    if revision is None:
        return None

    current = session.scalar(
        select(DigitalWeldPassportLifecycleEvent)
        .where(DigitalWeldPassportLifecycleEvent.passport_revision_id == revision.id)
        .order_by(DigitalWeldPassportLifecycleEvent.revision_number.desc())
    )
    if current is None:
        return None
    return revision, current


def _execute_dwp_command(
    *,
    payload: DigitalWeldPassportDraftRequest,
    actor: User,
    idempotency_key: str,
    result_executor: Callable[
        [
            DigitalWeldPassportService,
            GovernedAuditMetadata,
            CommandIdentity,
            CanonicalRequestHash,
            datetime,
        ],
        Any,
    ],
) -> DigitalWeldPassportResponse | JSONResponse:
    command_identity = _command_identity(
        passport_id=payload.passport_id,
        idempotency_key=idempotency_key,
    )
    request_hash = _canonical_request_hash(payload=payload, actor_user_id=actor.id)
    audit = _audit_metadata(payload=payload, actor=actor, idempotency_key=idempotency_key, detail={})

    with SessionLocal() as governed_session, GovernedUnitOfWork(governed_session) as unit_of_work:
        try:
            service = DigitalWeldPassportService(unit_of_work)
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
        except (AttributeError, SQLAlchemyError, TypeError, Exception) as exc:  # noqa: BLE001
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=str(exc),
                idempotency_key=idempotency_key,
                command_scope=command_identity.command_scope,
                correlation_id=audit.correlation_id,
            )

    if result.result_type.endswith("_denial"):
        return _response_from_payload(
            payload=payload,
            idempotency_key=idempotency_key,
            result_type=result.result_type,
            result_id=result.result_id,
            result_revision=result.result_revision,
            state=DigitalWeldPassportLifecycleState.DRAFT,
        )

    with SessionLocal() as session:
        response = _load_exact_revision_response(
            session=session,
            passport_id=payload.passport_id,
            revision_number=payload.revision_number,
            idempotency_key=idempotency_key,
        )
    if response is None:
        return _command_error(
            status_code=500,
            error_code="GOVERNED_TRANSACTION_FAILED",
            message="digital weld passport revision was not persisted",
            idempotency_key=idempotency_key,
            command_scope=command_identity.command_scope,
            correlation_id=audit.correlation_id,
        )
    return response


@router.post("", response_model=DigitalWeldPassportResponse)
def create_digital_weld_passport_revision(
    payload: DigitalWeldPassportDraftRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key or not idempotency_key.strip():
        return governed_error_response(
            status_code=400,
            error_code="MISSING_IDEMPOTENCY_KEY",
            message="Idempotency-Key header is required for digital weld passport drafts",
            correlation_id=payload.passport_id,
        )

    def _submit_draft_revision(
        service: DigitalWeldPassportService,
        audit: GovernedAuditMetadata,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        completed_at: datetime,
    ):
        return service.create_draft_revision(
            draft=DigitalWeldPassportRevisionDraft(
                passport_id=payload.passport_id,
                revision_number=payload.revision_number,
                context_snapshot=payload.context_snapshot.as_domain(),
                provenance_snapshot=payload.provenance_snapshot.model_dump(mode="json"),
                authority_snapshot={
                    "scope_snapshot": payload.authority_scope.model_dump(mode="json")
                },
                mrc_snapshot=payload.mrc_snapshot.model_dump(mode="json"),
                supersedes_revision_id=payload.supersedes_revision_id,
            ),
            receipt_id=f"dwp:{payload.passport_id}:{payload.revision_number}:{idempotency_key}",
            command_identity=command_identity,
            request_hash=request_hash,
            audit=audit,
            completed_at=completed_at,
        )

    return _execute_dwp_command(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        result_executor=_submit_draft_revision,
    )


def _execute_dwp_lifecycle_command(
    *,
    payload: DigitalWeldPassportLifecycleRequest,
    actor: User,
    idempotency_key: str,
    target_state: DigitalWeldPassportLifecycleState,
    result_executor: Callable[
        [
            DigitalWeldPassportService,
            GovernedAuditMetadata,
            CommandIdentity,
            CanonicalRequestHash,
            datetime,
        ],
        Any,
    ],
) -> DigitalWeldPassportResponse | JSONResponse:
    command_identity = _command_identity(
        passport_id=payload.passport_id,
        idempotency_key=idempotency_key,
    )
    request_payload = {
        "passport_id": payload.passport_id,
        "revision_number": payload.revision_number,
        "state": target_state.value,
        "authority_scope": payload.authority_scope.model_dump(mode="json"),
        "decision_reason": payload.decision_reason,
        "mrc_snapshot": (
            None
            if payload.mrc_snapshot is None
            else payload.mrc_snapshot.model_dump(mode="json")
        ),
        "supersedes_lifecycle_event_id": payload.supersedes_lifecycle_event_id,
    }
    request_hash = _canonical_request_hash(payload=request_payload, actor_user_id=actor.id)
    audit = _audit_metadata(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        detail={
            "passport_id": payload.passport_id,
            "revision_number": payload.revision_number,
            "target_state": target_state.value,
            "supersedes_lifecycle_event_id": payload.supersedes_lifecycle_event_id,
            "mrc_snapshot": request_payload["mrc_snapshot"],
        },
    )

    with SessionLocal() as governed_session, GovernedUnitOfWork(governed_session) as unit_of_work:
        try:
            service = DigitalWeldPassportService(unit_of_work)
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
        except (AttributeError, SQLAlchemyError, TypeError, Exception) as exc:  # noqa: BLE001
            return _command_error(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=str(exc),
                idempotency_key=idempotency_key,
                command_scope=command_identity.command_scope,
                correlation_id=audit.correlation_id,
            )

    with SessionLocal() as session:
        loaded = _load_exact_revision(
            session=session,
            passport_id=payload.passport_id,
            revision_number=payload.revision_number,
        )
    if loaded is None:
        return _command_error(
            status_code=500,
            error_code="GOVERNED_TRANSACTION_FAILED",
            message="digital weld passport revision was not persisted",
            idempotency_key=idempotency_key,
            command_scope=command_identity.command_scope,
            correlation_id=audit.correlation_id,
        )
    revision, current = loaded
    if result.result_type.endswith("_denial"):
        return _response_from_revision(
            revision=revision,
            current_state=current.state,
            current_result_type=result.result_type,
            idempotency_key=idempotency_key,
            decision_outcome="DENIED",
            result_id=result.result_id,
            result_revision=result.result_revision,
        )
    return _response_from_revision(
        revision=revision,
        current_state=current.state,
        current_result_type="digital_weld_passport",
        idempotency_key=idempotency_key,
    )


def _lifecycle_route(
    *,
    payload: DigitalWeldPassportLifecycleRequest,
    actor: User,
    idempotency_key: str | None,
    target_state: DigitalWeldPassportLifecycleState,
) -> DigitalWeldPassportResponse | JSONResponse:
    if not idempotency_key or not idempotency_key.strip():
        return governed_error_response(
            status_code=400,
            error_code="MISSING_IDEMPOTENCY_KEY",
            message="Idempotency-Key header is required for digital weld passport lifecycle commands",
            correlation_id=f"dwp:{payload.passport_id}:{payload.revision_number}:{target_state.value}",
        )

    return _execute_dwp_lifecycle_command(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        target_state=target_state,
        result_executor=lambda service, audit, command_identity, request_hash, completed_at: service.transition_revision(
            transition=DigitalWeldPassportLifecycleTransitionDraft(
                passport_id=payload.passport_id,
                revision_number=payload.revision_number,
                state=target_state,
                reason=payload.decision_reason,
                mrc_snapshot=(
                    None
                    if payload.mrc_snapshot is None
                    else payload.mrc_snapshot.model_dump(mode="json")
                ),
                supersedes_lifecycle_event_id=payload.supersedes_lifecycle_event_id,
            ),
            receipt_id=(
                f"{payload.passport_id}:{payload.revision_number}:{target_state.value}:{idempotency_key}"
            ),
            command_identity=command_identity,
            request_hash=request_hash,
            audit=audit,
            completed_at=completed_at,
        ),
    )


@router.post("/engineering-defined", response_model=DigitalWeldPassportResponse)
def transition_to_engineering_defined(
    payload: DigitalWeldPassportLifecycleRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return _lifecycle_route(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        target_state=DigitalWeldPassportLifecycleState.ENGINEERING_DEFINED,
    )


@router.post("/validation-pending", response_model=DigitalWeldPassportResponse)
def transition_to_validation_pending(
    payload: DigitalWeldPassportLifecycleRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return _lifecycle_route(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        target_state=DigitalWeldPassportLifecycleState.VALIDATION_PENDING,
    )


@router.post("/validated", response_model=DigitalWeldPassportResponse)
def transition_to_validated(
    payload: DigitalWeldPassportLifecycleRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return _lifecycle_route(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        target_state=DigitalWeldPassportLifecycleState.VALIDATED,
    )


@router.post("/approved", response_model=DigitalWeldPassportResponse)
def transition_to_approved(
    payload: DigitalWeldPassportLifecycleRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return _lifecycle_route(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        target_state=DigitalWeldPassportLifecycleState.APPROVED,
    )


@router.post("/production-active", response_model=DigitalWeldPassportResponse)
def transition_to_production_active(
    payload: DigitalWeldPassportLifecycleRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return _lifecycle_route(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        target_state=DigitalWeldPassportLifecycleState.PRODUCTION_ACTIVE,
    )


@router.get(
    "/{passport_id}/revisions/{revision_number}",
    response_model=DigitalWeldPassportResponse,
)
def get_digital_weld_passport_revision(
    passport_id: str,
    revision_number: int,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
):
    del actor
    with SessionLocal() as session:
        response = _load_exact_revision_response(
            session=session,
            passport_id=passport_id,
            revision_number=revision_number,
            idempotency_key=f"read:{passport_id}:{revision_number}",
        )
    if response is None:
        return governed_error_response(
            status_code=404,
            error_code="DWP_REVISION_NOT_FOUND",
            message="digital weld passport revision does not exist",
            command_namespace=DigitalWeldPassportService.COMMAND_NAMESPACE,
            command_scope=passport_id,
            correlation_id=f"dwp:{passport_id}:{revision_number}",
        )
    return response
