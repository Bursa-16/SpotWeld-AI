from __future__ import annotations

from collections.abc import Mapping

from fastapi.responses import JSONResponse

from app.schemas.governed_api import GovernedAPIError


def governed_error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    detail: Mapping[str, object] | None = None,
    idempotency_key: str | None = None,
    command_namespace: str | None = None,
    command_scope: str | None = None,
    correlation_id: str | None = None,
) -> JSONResponse:
    payload = GovernedAPIError(
        error_code=error_code,
        message=message,
        detail=dict(detail) if detail is not None else None,
        idempotency_key=idempotency_key,
        command_namespace=command_namespace,
        command_scope=command_scope,
        correlation_id=correlation_id,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())
