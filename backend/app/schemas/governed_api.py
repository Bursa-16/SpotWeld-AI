from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.governance_types import ContentVersionMetadata, EvidenceClass
from app.domain.readiness import (
    CheckCondition,
    GovernedMachineReadinessCheck,
    GovernedRuleEvaluationSnapshot,
    MachineReadinessCheckTrace,
    MachineReadinessResult,
    ReadinessState,
)
from app.domain.rule_applicability import (
    ApplicabilityOutcome,
    ApplicabilityResolutionOutcome,
    ApplicabilityResult,
    GovernedApplicabilityCandidateResult,
    GovernedApplicabilityContext,
    GovernedApplicabilityResolution,
)
from app.domain.rule_evaluation import (
    ConversionProvenance,
    Observation,
    RuleComparison,
    RuleComparisonOutcome,
)
from app.domain.rule_registry_types import RuleOperator
from app.domain.unit_policy import ConversionEntry, UnitPolicyCatalog, UnitPolicyContext
from app.domain.verification_types import VerificationScopeSnapshot
from app.models.digital_weld_passport import DigitalWeldPassportLifecycleState


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


class DigitalWeldPassportRuleEvaluationReferenceSnapshot(BaseModel):
    evaluation_id: str = Field(min_length=1, max_length=120)
    revision_number: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class DigitalWeldPassportProvenanceSnapshot(BaseModel):
    rule_evaluations: list[DigitalWeldPassportRuleEvaluationReferenceSnapshot] = Field(
        default_factory=list
    )

    model_config = ConfigDict(extra="forbid")


class DigitalWeldPassportContextSnapshot(BaseModel):
    passport_id: str = Field(min_length=1, max_length=120)
    weld_identity: dict[str, Any] = Field(default_factory=dict)
    scope_snapshot: GovernedScopeSnapshot

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class DigitalWeldPassportMrcSnapshot(BaseModel):
    assessment_id: str = Field(min_length=1, max_length=120)
    revision_number: int = Field(gt=0)
    decision_time: datetime
    state: ReadinessState
    context_snapshot: dict[str, Any]
    prerequisites_snapshot: dict[str, Any]
    result_snapshot: dict[str, Any]
    authority_snapshot: dict[str, Any]
    validated_applicable_basis_count: int = Field(ge=0)
    supersedes_assessment_revision_id: int | None = None
    created_by_user_id: int | None = None
    created_by_actor_id: str = Field(min_length=1, max_length=200)
    schema_version: str = Field(min_length=1, max_length=120)
    canonicalization_version: str = Field(min_length=1, max_length=120)
    hash_algorithm: str = Field(min_length=1, max_length=40)
    content_hash: str = Field(min_length=1, max_length=256)
    software_version: str = Field(min_length=1, max_length=120)
    correlation_id: str = Field(min_length=1, max_length=120)

    model_config = ConfigDict(extra="forbid")


class DigitalWeldPassportDraftRequest(BaseModel):
    passport_id: str = Field(min_length=1, max_length=120)
    revision_number: int = Field(gt=0)
    context_snapshot: DigitalWeldPassportContextSnapshot
    provenance_snapshot: DigitalWeldPassportProvenanceSnapshot = Field(
        default_factory=DigitalWeldPassportProvenanceSnapshot
    )
    authority_scope: GovernedScopeSnapshot
    mrc_snapshot: DigitalWeldPassportMrcSnapshot
    supersedes_revision_id: int | None = None
    decision_reason: str = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_context(self):
        if self.context_snapshot.passport_id != self.passport_id:
            raise ValueError("context_snapshot passport_id must match passport_id")
        return self


class DigitalWeldPassportLifecycleRequest(BaseModel):
    passport_id: str = Field(min_length=1, max_length=120)
    revision_number: int = Field(gt=0)
    authority_scope: GovernedScopeSnapshot
    decision_reason: str = Field(min_length=1, max_length=5000)
    mrc_snapshot: DigitalWeldPassportMrcSnapshot | None = None
    supersedes_lifecycle_event_id: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class DigitalWeldPassportResponse(BaseModel):
    decision_outcome: Literal[
        "DRAFT",
        "ENGINEERING_DEFINED",
        "VALIDATION_PENDING",
        "VALIDATED",
        "APPROVED",
        "PRODUCTION_ACTIVE",
        "DENIED",
    ]
    result_type: str
    result_id: str
    result_revision: str
    passport_id: str
    revision_number: int
    state: DigitalWeldPassportLifecycleState
    context_snapshot: dict[str, Any]
    provenance_snapshot: dict[str, Any]
    authority_snapshot: dict[str, Any]
    mrc_snapshot: dict[str, Any] | None = None
    supersedes_revision_id: int | None = None
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


class RuleEvaluationContentVersionMetadata(GovernedContentVersionMetadata):
    pass


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


class RuleEvaluationConversionEntrySnapshot(BaseModel):
    from_unit: str = Field(min_length=1, max_length=80)
    to_unit: str = Field(min_length=1, max_length=80)
    factor: float

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> ConversionEntry:
        return ConversionEntry(
            from_unit=self.from_unit,
            to_unit=self.to_unit,
            factor=self.factor,
        )


class RuleEvaluationUnitPolicyContextSnapshot(BaseModel):
    expected_unit: str = Field(min_length=1, max_length=80)
    conversion_factors: list[RuleEvaluationConversionEntrySnapshot] = Field(
        default_factory=list
    )
    policy_version: GovernedContentVersionMetadata | None = None
    rounding_policy: str | None = None

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> UnitPolicyContext:
        return UnitPolicyContext(
            expected_unit=self.expected_unit,
            conversion_factors={
                (entry.from_unit, entry.to_unit): entry.factor
                for entry in self.conversion_factors
            },
            policy_version=(
                self.policy_version.as_domain()
                if self.policy_version is not None
                else None
            ),
            rounding_policy=self.rounding_policy,
        )


class RuleEvaluationUnitPolicyCatalogSnapshot(BaseModel):
    version: GovernedContentVersionMetadata
    rounding_policy: str = Field(min_length=1, max_length=120)
    conversions: list[RuleEvaluationConversionEntrySnapshot] = Field(
        default_factory=list
    )

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> UnitPolicyCatalog:
        return UnitPolicyCatalog(
            version=self.version.as_domain(),
            rounding_policy=self.rounding_policy,
            conversions=[entry.as_domain() for entry in self.conversions],
        )


class RuleEvaluationObservationSnapshot(BaseModel):
    parameter: str = Field(min_length=1, max_length=120)
    value: float
    unit: str = Field(min_length=1, max_length=80)

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> Observation:
        return Observation(
            parameter=self.parameter,
            value=self.value,
            unit=self.unit,
        )


class RuleEvaluationApplicabilityResultSnapshot(BaseModel):
    outcome: ApplicabilityOutcome
    reason: str = Field(min_length=1, max_length=5000)
    matched_keys: list[str] = Field(default_factory=list)
    unsatisfied_keys: list[str] = Field(default_factory=list)
    missing_keys: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> ApplicabilityResult:
        return ApplicabilityResult(
            outcome=self.outcome,
            reason=self.reason,
            matched_keys=tuple(self.matched_keys),
            unsatisfied_keys=tuple(self.unsatisfied_keys),
            missing_keys=tuple(self.missing_keys),
        )


class RuleEvaluationApplicabilityCandidateSnapshot(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=120)
    rule_id: str = Field(min_length=1, max_length=120)
    revision: str = Field(min_length=1, max_length=120)
    evidence_class: EvidenceClass
    enabled: bool
    active: bool
    suspended: bool = False
    revoked: bool = False
    superseded: bool = False
    basis_valid: bool = True
    effective_from: datetime
    expires_at: datetime | None = None
    specificity: int = Field(ge=0)
    scope_snapshot: dict[str, list[str] | None] = Field(default_factory=dict)
    scope_result: RuleEvaluationApplicabilityResultSnapshot | None = None
    eligible: bool
    eligibility_reasons: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RuleEvaluationApplicabilityResolutionSnapshot(BaseModel):
    outcome: ApplicabilityResolutionOutcome
    reason: str = Field(min_length=1, max_length=5000)
    decision_time: datetime
    context: GovernedScopeSnapshot
    candidates: list[RuleEvaluationApplicabilityCandidateSnapshot] = Field(
        default_factory=list
    )
    selected_candidate_id: str | None = None
    selected_rule_id: str | None = None
    selected_revision: str | None = None
    selected_specificity: int | None = Field(default=None, ge=0)
    conflict_candidate_ids: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> GovernedApplicabilityResolution:
        return GovernedApplicabilityResolution(
            outcome=self.outcome,
            reason=self.reason,
            decision_time=self.decision_time,
            context=GovernedApplicabilityContext(
                customer=self.context.customer,
                project=self.context.project,
                site=self.context.site,
                machine=self.context.machine,
            ),
            candidates=tuple(
                GovernedApplicabilityCandidateResult(
                    candidate_id=candidate.candidate_id,
                    rule_id=candidate.rule_id,
                    revision=candidate.revision,
                    evidence_class=candidate.evidence_class,
                    enabled=candidate.enabled,
                    active=candidate.active,
                    suspended=candidate.suspended,
                    revoked=candidate.revoked,
                    superseded=candidate.superseded,
                    basis_valid=candidate.basis_valid,
                    effective_from=candidate.effective_from,
                    expires_at=candidate.expires_at,
                    specificity=candidate.specificity,
                    scope_snapshot=tuple(
                        (key, tuple(values) if values is not None else ())
                        for key, values in sorted(candidate.scope_snapshot.items())
                    ),
                    scope_result=(
                        None
                        if candidate.scope_result is None
                        else candidate.scope_result.as_domain()
                    ),
                    eligible=candidate.eligible,
                    eligibility_reasons=tuple(candidate.eligibility_reasons),
                )
                for candidate in self.candidates
            ),
            selected_candidate_id=self.selected_candidate_id,
            selected_rule_id=self.selected_rule_id,
            selected_revision=self.selected_revision,
            selected_specificity=self.selected_specificity,
            conflict_candidate_ids=tuple(self.conflict_candidate_ids),
        )


class RuleEvaluationConversionProvenanceSnapshot(BaseModel):
    conversion_occurred: bool
    original_value: float | None = None
    original_unit: str | None = None
    comparison_value: float | None = None
    target_unit: str = Field(min_length=1, max_length=80)
    factor: float | None = None
    policy_version: RuleEvaluationContentVersionMetadata | None = None
    rounding_policy: str | None = None

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> ConversionProvenance:
        return ConversionProvenance(
            conversion_occurred=self.conversion_occurred,
            original_value=self.original_value,
            original_unit=self.original_unit,
            comparison_value=self.comparison_value,
            target_unit=self.target_unit,
            factor=self.factor,
            policy_version=(
                self.policy_version.as_domain()
                if self.policy_version is not None
                else None
            ),
            rounding_policy=self.rounding_policy,
        )


class RuleEvaluationComparisonSnapshot(BaseModel):
    rule_id: str = Field(min_length=1, max_length=120)
    revision: str = Field(min_length=1, max_length=120)
    parameter: str = Field(min_length=1, max_length=120)
    operator: RuleOperator
    outcome: RuleComparisonOutcome
    reason: str = Field(min_length=1, max_length=5000)
    observed_value: float | None = None
    observed_unit: str | None = None
    compared_value: float | None = None
    applicability_result: RuleEvaluationApplicabilityResolutionSnapshot
    conversion_provenance: RuleEvaluationConversionProvenanceSnapshot

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> RuleComparison:
        return RuleComparison(
            rule_id=self.rule_id,
            revision=self.revision,
            parameter=self.parameter,
            operator=self.operator,
            outcome=self.outcome,
            reason=self.reason,
            observed_value=self.observed_value,
            observed_unit=self.observed_unit,
            compared_value=self.compared_value,
            applicability_result=self.applicability_result.as_domain(),
            conversion_provenance=self.conversion_provenance.as_domain(),
        )


class RuleEvaluationPersistenceRequest(BaseModel):
    evaluation_id: str = Field(min_length=1, max_length=120)
    revision_number: int = Field(gt=0)
    comparison: RuleEvaluationComparisonSnapshot
    observation: RuleEvaluationObservationSnapshot | None = None
    unit_context: RuleEvaluationUnitPolicyContextSnapshot | None = None
    unit_catalog: RuleEvaluationUnitPolicyCatalogSnapshot | None = None
    supersedes_evaluation_id: int | None = None
    decision_reason: str = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_unit_inputs(self):
        if self.unit_context is None and self.unit_catalog is None:
            raise ValueError(
                "rule evaluation persistence requires a governed unit-policy snapshot"
            )
        if self.unit_context is not None and self.unit_catalog is not None:
            raise ValueError("pass either unit_context or unit_catalog, not both")
        return self

    def as_domain(self):
        return {
            "evaluation_id": self.evaluation_id,
            "revision_number": self.revision_number,
            "comparison": self.comparison.as_domain(),
            "applicability_result": self.comparison.applicability_result.as_domain(),
            "observation": (
                self.observation.as_domain() if self.observation is not None else None
            ),
            "unit_context": (
                self.unit_context.as_domain() if self.unit_context is not None else None
            ),
            "unit_catalog": (
                self.unit_catalog.as_domain() if self.unit_catalog is not None else None
            ),
            "supersedes_evaluation_id": self.supersedes_evaluation_id,
        }


class RuleEvaluationPersistenceResponse(BaseModel):
    decision_outcome: Literal[
        "SATISFIED",
        "NOT_SATISFIED",
        "NOT_APPLICABLE",
        "UNIT_MISMATCH",
        "UNRESOLVED",
        "DENIED",
    ]
    result_type: str
    result_id: str
    result_revision: str
    evaluation_id: str
    revision_number: int
    rule_id: str
    rule_revision: str
    parameter: str
    operator: RuleOperator
    idempotency_key: str
    command_namespace: str
    command_scope: str
    correlation_id: str

    model_config = ConfigDict(extra="forbid")


class MachineReadinessEvaluationSnapshot(BaseModel):
    evaluation_id: str = Field(min_length=1, max_length=120)
    revision_number: int = Field(gt=0)
    comparison: RuleEvaluationComparisonSnapshot

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> GovernedRuleEvaluationSnapshot:
        return GovernedRuleEvaluationSnapshot(
            evaluation_id=self.evaluation_id,
            revision_number=self.revision_number,
            comparison=self.comparison.as_domain(),
        )


class MachineReadinessCheckDefinitionSnapshot(BaseModel):
    check_id: str = Field(min_length=1, max_length=120)
    required: bool
    description: str | None = None
    evaluations: list[MachineReadinessEvaluationSnapshot] = Field(
        default_factory=list
    )

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> GovernedMachineReadinessCheck:
        return GovernedMachineReadinessCheck(
            check_id=self.check_id,
            required=self.required,
            description=self.description,
            evaluations=tuple(evaluation.as_domain() for evaluation in self.evaluations),
        )


class MachineReadinessCheckTraceSnapshot(MachineReadinessCheckDefinitionSnapshot):
    condition: CheckCondition
    reason: str = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> MachineReadinessCheckTrace:
        return MachineReadinessCheckTrace(
            check_id=self.check_id,
            required=self.required,
            evaluations=tuple(evaluation.as_domain() for evaluation in self.evaluations),
            condition=self.condition,
            reason=self.reason,
        )


class MachineReadinessPrerequisiteSnapshot(BaseModel):
    label: str = Field(min_length=1, max_length=5000)
    satisfied: bool

    model_config = ConfigDict(extra="forbid")


class MachineReadinessResultSnapshot(BaseModel):
    state: ReadinessState
    reasons: list[str] = Field(default_factory=list)
    prerequisites: list[MachineReadinessPrerequisiteSnapshot] = Field(
        default_factory=list
    )
    context: GovernedScopeSnapshot
    decision_time: datetime
    validated_applicable_basis_count: int = Field(ge=0)
    checks: list[MachineReadinessCheckTraceSnapshot] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def as_domain(self) -> MachineReadinessResult:
        return MachineReadinessResult(
            state=self.state,
            reasons=tuple(self.reasons),
            prerequisites=tuple(
                (prerequisite.label, prerequisite.satisfied)
                for prerequisite in self.prerequisites
            ),
            context=GovernedApplicabilityContext(
                customer=self.context.customer,
                project=self.context.project,
                site=self.context.site,
                machine=self.context.machine,
            ),
            decision_time=self.decision_time,
            checks=tuple(check.as_domain() for check in self.checks),
            validated_applicable_basis_count=self.validated_applicable_basis_count,
        )


class MachineReadinessPersistenceRequest(BaseModel):
    assessment_id: str = Field(min_length=1, max_length=120)
    revision_number: int = Field(gt=0)
    result: MachineReadinessResultSnapshot
    checks: list[MachineReadinessCheckDefinitionSnapshot] = Field(default_factory=list)
    supersedes_assessment_revision_id: int | None = None
    decision_reason: str = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")


class MachineReadinessPersistenceResponse(BaseModel):
    decision_outcome: Literal[
        "READY",
        "NOT_READY",
        "ENGINEERING_REVIEW_REQUIRED",
        "MANUAL_REVIEW_REQUIRED",
        "NOT_EVALUATED",
        "DENIED",
    ]
    result_type: str
    result_id: str
    result_revision: str
    assessment_id: str
    revision_number: int
    supersedes_assessment_revision_id: int | None = None
    result: MachineReadinessResultSnapshot
    checks: list[MachineReadinessCheckDefinitionSnapshot] = Field(default_factory=list)
    idempotency_key: str
    command_namespace: str
    command_scope: str
    correlation_id: str

    model_config = ConfigDict(extra="forbid")
