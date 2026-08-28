from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.verification_types import VerificationScopeSnapshot


class GovernedScopeSnapshot(BaseModel):
    customer: str | None = None
    project: str | None = None
    site: str | None = None
    machine: str | None = None

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> VerificationScopeSnapshot:
        return VerificationScopeSnapshot(
            customer=self.customer,
            project=self.project,
            site=self.site,
            machine=self.machine,
        )


class EvidenceVerificationCreateRequest(BaseModel):
    verification_id: str = Field(min_length=1, max_length=120)
    evidence_reference_id: int = Field(gt=0)
    requested_scope: GovernedScopeSnapshot
    decision_reason: str = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")


class EvidenceVerificationResponse(BaseModel):
    decision_outcome: Literal["VERIFIED", "DENIED"]
    result_type: str
    result_id: str
    result_revision: str
    verification_id: str
    evidence_reference_id: int
    verifier_user_id: int
    requested_scope: GovernedScopeSnapshot
    idempotency_key: str
    command_namespace: str
    command_scope: str
    correlation_id: str

    model_config = ConfigDict(extra="forbid")


class GovernedAPIError(BaseModel):
    error_code: str
    message: str
    detail: dict[str, Any] | None = None
    idempotency_key: str | None = None
    command_namespace: str | None = None
    command_scope: str | None = None
    correlation_id: str | None = None

    model_config = ConfigDict(extra="forbid")
