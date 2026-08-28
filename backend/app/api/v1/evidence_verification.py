from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header

from app.api.dependencies import get_governed_actor_user
from app.api.errors import governed_error_response
from app.application.evidence_verification_service import EvidenceVerificationService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import GovernedAuditMetadata
from app.db.session import SessionLocal
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.domain.verification_types import EvidenceVerificationCommand
from app.models.entities import User, utc_now
from app.schemas.governed_api import (
    EvidenceVerificationCreateRequest,
    EvidenceVerificationResponse,
)

router = APIRouter(prefix="/evidence-verifications", tags=["Governed Evidence Verification"])


def _canonical_request_hash(
    *, payload: EvidenceVerificationCreateRequest, actor_user_id: int
) -> CanonicalRequestHash:
    canonical = json.dumps(
        {
            "verification_id": payload.verification_id,
            "evidence_reference_id": payload.evidence_reference_id,
            "requested_scope": payload.requested_scope.model_dump(mode="json"),
            "decision_reason": payload.decision_reason,
            "actor_user_id": actor_user_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return CanonicalRequestHash(
        value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="governed-api-v1",
    )


def _command_identity(
    *, payload: EvidenceVerificationCreateRequest, actor_user_id: int, idempotency_key: str
) -> CommandIdentity:
    return CommandIdentity(
        command_namespace=EvidenceVerificationService.COMMAND_NAMESPACE,
        command_scope=f"verification_id={payload.verification_id};verifier_user_id={actor_user_id}",
        idempotency_key=idempotency_key,
    )


def _audit_metadata(
    *, payload: EvidenceVerificationCreateRequest, actor: User, idempotency_key: str
) -> GovernedAuditMetadata:
    timestamp = utc_now()
    return GovernedAuditMetadata(
        event_id=f"{payload.verification_id}:{idempotency_key}:audit",
        actor_id=f"user:{actor.id}",
        actor_type="user",
        reason=payload.decision_reason,
        correlation_id=payload.verification_id,
        schema_version="evidence-verification-api-v1",
        software_version="backend-api-v1",
        canonicalization_version="governed-api-v1",
        hash_algorithm="sha256",
        created_at=timestamp,
        actor_user_id=actor.id,
        actor_role=actor.role,
        authority_scope=payload.requested_scope.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        detail={
            "verification_id": payload.verification_id,
            "evidence_reference_id": payload.evidence_reference_id,
        },
    )


def _response(
    *,
    payload: EvidenceVerificationCreateRequest,
    actor: User,
    idempotency_key: str,
    result_type: str,
    result_id: str,
    result_revision: str,
) -> EvidenceVerificationResponse:
    return EvidenceVerificationResponse(
        decision_outcome=(
            "VERIFIED" if result_type == "evidence_verification_decision" else "DENIED"
        ),
        result_type=result_type,
        result_id=result_id,
        result_revision=result_revision,
        verification_id=payload.verification_id,
        evidence_reference_id=payload.evidence_reference_id,
        verifier_user_id=actor.id,
        requested_scope=payload.requested_scope,
        idempotency_key=idempotency_key,
        command_namespace=EvidenceVerificationService.COMMAND_NAMESPACE,
        command_scope=f"verification_id={payload.verification_id};verifier_user_id={actor.id}",
        correlation_id=payload.verification_id,
    )


@router.post("", response_model=EvidenceVerificationResponse)
def create_evidence_verification(
    payload: EvidenceVerificationCreateRequest,
    actor: User = Depends(get_governed_actor_user),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key or not idempotency_key.strip():
        return governed_error_response(
            status_code=400,
            error_code="MISSING_IDEMPOTENCY_KEY",
            message="Idempotency-Key header is required for evidence verification",
            correlation_id=payload.verification_id,
        )

    command_identity = _command_identity(
        payload=payload,
        actor_user_id=actor.id,
        idempotency_key=idempotency_key,
    )
    request_hash = _canonical_request_hash(payload=payload, actor_user_id=actor.id)
    audit = _audit_metadata(payload=payload, actor=actor, idempotency_key=idempotency_key)
    command = EvidenceVerificationCommand(
        evidence_reference_id=payload.evidence_reference_id,
        verifier_user_id=actor.id,
        requested_scope=payload.requested_scope.as_domain(),
        decision_reason=payload.decision_reason,
    )
    with SessionLocal() as governed_session, GovernedUnitOfWork(governed_session) as unit_of_work:
        try:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id=f"{payload.verification_id}:{actor.id}:{idempotency_key}",
                command_identity=command_identity,
                request_hash=request_hash,
                audit=audit,
                verification_id=payload.verification_id,
                completed_at=datetime.now(timezone.utc),
            )
            unit_of_work.commit()
        except ValueError as exc:
            message = str(exc)
            if "idempotency conflict" in message:
                return governed_error_response(
                    status_code=409,
                    error_code="IDEMPOTENCY_CONFLICT",
                    message=message,
                    idempotency_key=idempotency_key,
                    command_namespace=EvidenceVerificationService.COMMAND_NAMESPACE,
                    command_scope=command_identity.command_scope,
                    correlation_id=payload.verification_id,
                )
            return governed_error_response(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=message,
                idempotency_key=idempotency_key,
                command_namespace=EvidenceVerificationService.COMMAND_NAMESPACE,
                command_scope=command_identity.command_scope,
                correlation_id=payload.verification_id,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "already in progress" in message:
                return governed_error_response(
                    status_code=409,
                    error_code="IDEMPOTENCY_IN_PROGRESS",
                    message=message,
                    idempotency_key=idempotency_key,
                    command_namespace=EvidenceVerificationService.COMMAND_NAMESPACE,
                    command_scope=command_identity.command_scope,
                    correlation_id=payload.verification_id,
                )
            return governed_error_response(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=message,
                idempotency_key=idempotency_key,
                command_namespace=EvidenceVerificationService.COMMAND_NAMESPACE,
                command_scope=command_identity.command_scope,
                correlation_id=payload.verification_id,
            )
        except Exception as exc:  # pragma: no cover - adapter safety net  # noqa: BLE001
            return governed_error_response(
                status_code=500,
                error_code="GOVERNED_TRANSACTION_FAILED",
                message=str(exc),
                idempotency_key=idempotency_key,
                command_namespace=EvidenceVerificationService.COMMAND_NAMESPACE,
                command_scope=command_identity.command_scope,
                correlation_id=payload.verification_id,
            )

    return _response(
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        result_type=result.result_type,
        result_id=result.result_id,
        result_revision=result.result_revision,
    )
