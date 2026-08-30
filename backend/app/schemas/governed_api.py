from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.governance_types import ContentVersionMetadata
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


class GovernedContentVersionMetadata(BaseModel):
    schema_version: str = Field(min_length=1, max_length=120)
    canonicalization_version: str = Field(min_length=1, max_length=120)
    hash_algorithm: str = Field(min_length=1, max_length=40)
    content_hash: str = Field(min_length=1, max_length=256)
    software_version: str = Field(min_length=1, max_length=120)

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> ContentVersionMetadata:
        return ContentVersionMetadata(
            schema_version=self.schema_version,
            canonicalization_version=self.canonicalization_version,
            hash_algorithm=self.hash_algorithm,
            content_hash=self.content_hash,
            software_version=self.software_version,
        )


class RuleRegistrySourceBackedPromotionRequest(BaseModel):
    rule_id: str = Field(min_length=1, max_length=120)
    source_revision: str = Field(min_length=1, max_length=120)
    revision: str = Field(min_length=1, max_length=120)
    authority_scope: GovernedScopeSnapshot
    version_metadata: GovernedContentVersionMetadata
    decision_reason: str = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")


class RuleRegistryLifecycleRequest(BaseModel):
    rule_id: str = Field(min_length=1, max_length=120)
    source_revision: str = Field(min_length=1, max_length=120)
    authority_scope: GovernedScopeSnapshot
    decision_reason: str = Field(min_length=1, max_length=5000)
    effective_from: datetime
    expires_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class RuleRegistryLifecycleResponse(BaseModel):
    decision_outcome: Literal["SOURCE_BACKED", "ENABLED", "ACTIVE", "DENIED"]
    result_type: str
    result_id: str
    result_revision: str
    rule_id: str
    source_revision: str
    authority_scope: GovernedScopeSnapshot
    idempotency_key: str
    command_namespace: str
    command_scope: str
    correlation_id: str

    model_config = ConfigDict(extra="forbid")
