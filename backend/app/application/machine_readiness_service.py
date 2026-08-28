"""Governed persistence for immutable pure machine-readiness results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from app.application.governed_audit_service import GovernedAuditService
from app.application.governed_idempotency_service import GovernedIdempotencyService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import GovernedAuditMetadata
from app.domain.governance_types import ContentVersionMetadata
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
    CommandResultReference,
    IdempotencyDisposition,
)
from app.domain.readiness import (
    GovernedMachineReadinessCheck,
    GovernedRuleEvaluationSnapshot,
    MachineReadinessCheckTrace,
    MachineReadinessResult,
    ReadinessState,
)
from app.domain.rule_applicability import (
    ApplicabilityResolutionOutcome,
    GovernedApplicabilityCandidateResult,
    GovernedApplicabilityResolution,
)
from app.domain.rule_evaluation import Observation, RuleComparison
from app.models.governance import freeze_json
from app.models.rule_evaluation import RuleEvaluation
from app.repositories.machine_readiness_repository import MachineReadinessRepository

__all__ = [
    "MachineReadinessPersistenceDraft",
    "MachineReadinessService",
]


@dataclass(frozen=True, slots=True)
class MachineReadinessPersistenceDraft:
    """Caller-pinned MRC assessment revision and its check definitions."""

    assessment_id: str
    revision_number: int
    result: MachineReadinessResult
    checks: tuple[GovernedMachineReadinessCheck, ...] | Sequence[
        GovernedMachineReadinessCheck
    ] = ()
    supersedes_assessment_revision_id: int | None = None

    def __post_init__(self) -> None:
        if not self.assessment_id.strip():
            raise ValueError("assessment_id must be a non-empty string")
        if self.revision_number <= 0:
            raise ValueError("revision_number must be positive")
        if not isinstance(self.result, MachineReadinessResult):
            raise TypeError("result must be a MachineReadinessResult")
        if self.supersedes_assessment_revision_id is not None and (
            self.supersedes_assessment_revision_id <= 0
        ):
            raise ValueError("supersedes_assessment_revision_id must be positive")
        checks = self.checks if isinstance(self.checks, tuple) else tuple(self.checks)
        for check in checks:
            if not isinstance(check, GovernedMachineReadinessCheck):
                raise TypeError(
                    "checks must contain GovernedMachineReadinessCheck values"
                )
        object.__setattr__(self, "checks", checks)


class MachineReadinessService:
    """Persist already-computed governed MRC results without recomputation."""

    COMMAND_NAMESPACE = "registry.machine.readiness"

    def __init__(self, unit_of_work: GovernedUnitOfWork):
        self._unit_of_work = unit_of_work
        self._repository = MachineReadinessRepository(unit_of_work.session)
        self._idempotency = GovernedIdempotencyService(unit_of_work)
        self._audit = GovernedAuditService(unit_of_work)

    def persist_assessment(
        self,
        *,
        draft: MachineReadinessPersistenceDraft,
        receipt_id: str,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
    ) -> CommandResultReference:
        self._unit_of_work.ensure_open()
        if command_identity.command_namespace != self.COMMAND_NAMESPACE:
            raise ValueError("machine readiness command namespace mismatch")
        if command_identity.command_scope != draft.assessment_id:
            raise ValueError("machine readiness command scope must match assessment_id")
        if draft.result.decision_time.tzinfo is None or (
            draft.result.decision_time.utcoffset() is None
        ):
            raise ValueError("machine readiness decision_time must be timezone-aware")
        if draft.result.validated_applicable_basis_count < 0:
            raise ValueError("validated_applicable_basis_count must be non-negative")

        decision = self._idempotency.reserve_or_inspect(
            receipt_id=receipt_id,
            identity=command_identity,
            request_hash=request_hash,
            correlation_id=audit.correlation_id,
            schema_version=audit.schema_version,
            software_version=audit.software_version,
            created_at=audit.created_at,
        )
        if decision.disposition is IdempotencyDisposition.REPLAY:
            if decision.result_reference is None:
                raise RuntimeError("completed machine readiness replay has no durable result")
            return decision.result_reference
        if decision.disposition is IdempotencyDisposition.CONFLICT:
            raise ValueError("idempotency conflict for machine readiness command")
        if decision.disposition is IdempotencyDisposition.IN_PROGRESS:
            raise RuntimeError("machine readiness command is already in progress")

        canonical_checks = self._canonicalize_checks(draft.checks)
        result_checks = self._canonicalize_traces(draft.result.checks)
        if len(canonical_checks) != len(result_checks):
            return self._deny_machine_readiness(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="CHECK_COUNT_MISMATCH",
                denial_reason=(
                    "persistence requires the supplied check definitions to match "
                    "the pure result"
                ),
            )
        for definition, trace in zip(canonical_checks, result_checks, strict=True):
            if definition.check_id != trace.check_id:
                return self._deny_machine_readiness(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="CHECK_ID_MISMATCH",
                    denial_reason=(
                        "persistence requires the supplied check definitions to match "
                        "the pure result"
                    ),
                )
            if definition.required != trace.required:
                return self._deny_machine_readiness(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="REQUIRED_FLAG_MISMATCH",
                    denial_reason=(
                        "persistence requires the supplied check definitions to match "
                        "the pure result"
                    ),
                )
            if self._canonicalize_evaluations(definition.evaluations) != self._canonicalize_evaluations(
                trace.evaluations
            ):
                return self._deny_machine_readiness(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="EVALUATION_PIN_MISMATCH",
                    denial_reason=(
                        "persistence requires the supplied check definitions to match "
                        "the pure result"
                    ),
                )

        if self._canonicalize_traces(draft.result.checks) != result_checks:
            return self._deny_machine_readiness(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="PURE_RESULT_CONSISTENCY_MISMATCH",
                denial_reason=(
                    "persistence requires the supplied pure result to remain "
                    "internally consistent"
                ),
            )

        if draft.result.state is ReadinessState.READY and (
            draft.result.validated_applicable_basis_count <= 0
        ):
            return self._deny_machine_readiness(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="READY_WITHOUT_VALIDATED_BASIS",
                denial_reason="READY assessments require at least one validated basis",
            )

        evaluation_records: list[list[dict[str, object]]] = []
        for trace in result_checks:
            pinned_rows: list[dict[str, object]] = []
            for snapshot in self._canonicalize_evaluations(trace.evaluations):
                row = self._load_rule_evaluation(snapshot)
                if row is None:
                    return self._deny_machine_readiness(
                        draft=draft,
                        audit=audit,
                        completed_at=completed_at,
                        command_identity=command_identity,
                        request_hash=request_hash,
                        denial_code="MISSING_RULE_EVALUATION",
                        denial_reason=(
                            "persistence requires every pinned rule-evaluation "
                            "revision to exist"
                        ),
                    )
                if not self._rule_evaluation_matches(
                    row=row,
                    snapshot=snapshot,
                    decision_time=draft.result.decision_time,
                ):
                    return self._deny_machine_readiness(
                        draft=draft,
                        audit=audit,
                        completed_at=completed_at,
                        command_identity=command_identity,
                        request_hash=request_hash,
                        denial_code="RULE_EVALUATION_PIN_MISMATCH",
                        denial_reason=(
                            "persistence requires every pinned rule-evaluation "
                            "revision to match the pure result"
                        ),
                    )
                pinned_rows.append(self._rule_evaluation_row_snapshot(row))
            evaluation_records.append(pinned_rows)

        history = self._repository.list_history(draft.assessment_id)
        if not history:
            if draft.supersedes_assessment_revision_id is not None or draft.revision_number != 1:
                return self._deny_machine_readiness(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="REVISION_SEQUENCE_INVALID",
                    denial_reason="first machine readiness assessment revision_number must be 1",
                )
        else:
            latest = history[-1]
            if (
                draft.supersedes_assessment_revision_id is None
                or draft.supersedes_assessment_revision_id != latest.id
            ):
                return self._deny_machine_readiness(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="BRANCHING_REVISION_REJECTED",
                    denial_reason=(
                        "corrections must supersede the current latest machine "
                        "readiness revision"
                    ),
                )
            if draft.revision_number != latest.revision_number + 1:
                return self._deny_machine_readiness(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="REVISION_SEQUENCE_INVALID",
                    denial_reason="corrections must use the next revision_number",
                )

        assessment = self._repository.get_by_assessment_id(draft.assessment_id)
        if assessment is None:
            assessment = self._repository.create_assessment(
                assessment_id=draft.assessment_id,
                created_by_actor_id=audit.actor_id,
                created_by_user_id=audit.actor_user_id,
            )

        context_snapshot = self._context_snapshot(draft.result.context)
        prerequisites_snapshot = self._prerequisites_snapshot(draft.result.prerequisites)
        check_snapshots = [
            self._check_snapshot(definition=definition, trace=trace, evaluations=evaluations)
            for definition, trace, evaluations in zip(
                canonical_checks, result_checks, evaluation_records, strict=True
            )
        ]
        result_snapshot = self._result_snapshot(
            draft=draft,
            checks_snapshot=tuple(check_snapshots),
        )
        authority_snapshot = self._authority_snapshot(audit, draft)
        content_hash = self._hash(
            {
                "assessment_id": draft.assessment_id,
                "revision_number": draft.revision_number,
                "state": draft.result.state.value,
                "decision_time": draft.result.decision_time.isoformat(),
                "context_snapshot": context_snapshot,
                "prerequisites_snapshot": prerequisites_snapshot,
                "validated_applicable_basis_count": draft.result.validated_applicable_basis_count,
                "result_snapshot": result_snapshot,
                "authority_snapshot": authority_snapshot,
                "supersedes_assessment_revision_id": draft.supersedes_assessment_revision_id,
            }
        )
        revision = self._repository.create_revision(
            assessment=assessment,
            revision_number=draft.revision_number,
            state=draft.result.state,
            decision_time=draft.result.decision_time,
            context_snapshot=context_snapshot,
            prerequisites_snapshot=prerequisites_snapshot,
            result_snapshot=result_snapshot,
            validated_applicable_basis_count=draft.result.validated_applicable_basis_count,
            created_by_actor_id=audit.actor_id,
            created_by_user_id=audit.actor_user_id,
            schema_version=audit.schema_version,
            canonicalization_version=audit.canonicalization_version,
            hash_algorithm=audit.hash_algorithm,
            content_hash=content_hash,
            authority_snapshot=authority_snapshot,
            software_version=audit.software_version,
            correlation_id=audit.correlation_id,
            supersedes_assessment_revision_id=draft.supersedes_assessment_revision_id,
        )
        for definition, trace, _pinned_rows, snapshot in zip(
            canonical_checks, result_checks, evaluation_records, check_snapshots, strict=True
        ):
            self._repository.create_check_result(
                assessment_revision=revision,
                check_id=definition.check_id,
                required=definition.required,
                description=definition.description,
                condition=trace.condition,
                reason=trace.reason,
                check_snapshot=snapshot,
            )

        action = (
            "CORRECT_MACHINE_READINESS_ASSESSMENT"
            if draft.supersedes_assessment_revision_id is not None
            else "PERSIST_MACHINE_READINESS_ASSESSMENT"
        )
        self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type="machine_readiness_assessment",
            entity_id=draft.assessment_id,
            entity_revision=str(draft.revision_number),
            action=action,
            prior_content_hash=None
            if draft.supersedes_assessment_revision_id is None
            else history[-1].content_hash,
            new_content_hash=content_hash,
            detail=self._audit_detail(
                audit,
                command=action,
                assessment_id=draft.assessment_id,
                revision_number=draft.revision_number,
                state=draft.result.state.value,
                validated_applicable_basis_count=draft.result.validated_applicable_basis_count,
                supersedes_assessment_revision_id=draft.supersedes_assessment_revision_id,
                check_ids=[trace.check_id for trace in result_checks],
                context_snapshot=context_snapshot,
            ),
        )

        result = CommandResultReference(
            result_type="machine_readiness",
            result_id=draft.assessment_id,
            result_revision=str(draft.revision_number),
        )
        completed = self._idempotency.complete(
            identity=command_identity,
            request_hash=request_hash,
            result_reference=result,
            completed_at=completed_at,
        )
        if completed.result_reference != result:
            raise RuntimeError("machine readiness idempotency completion failed")
        return result

    def _load_rule_evaluation(
        self,
        snapshot: GovernedRuleEvaluationSnapshot,
    ) -> RuleEvaluation | None:
        statement = select(RuleEvaluation).where(
            RuleEvaluation.evaluation_id == snapshot.evaluation_id,
            RuleEvaluation.revision_number == snapshot.revision_number,
        )
        return self._repository.session.scalar(statement)

    def _rule_evaluation_matches(
        self,
        *,
        row: RuleEvaluation,
        snapshot: GovernedRuleEvaluationSnapshot,
        decision_time: datetime,
    ) -> bool:
        comparison = snapshot.comparison
        applicability_result = comparison.applicability_result
        if applicability_result is None:
            return False
        if applicability_result.outcome is not ApplicabilityResolutionOutcome.SELECTED:
            return False
        if (
            applicability_result.selected_rule_id is None
            or applicability_result.selected_revision is None
        ):
            return False
        if (
            applicability_result.selected_rule_id.strip() != comparison.rule_id.strip()
            or applicability_result.selected_revision.strip() != comparison.revision.strip()
        ):
            return False
        if self._normalize_datetime(applicability_result.decision_time) != self._normalize_datetime(
            decision_time
        ):
            return False
        if row.evaluation_id != snapshot.evaluation_id:
            return False
        if row.revision_number != snapshot.revision_number:
            return False
        if row.rule_id != comparison.rule_id or row.rule_revision != comparison.revision:
            return False
        if row.parameter != comparison.parameter:
            return False
        if row.operator != comparison.operator:
            return False
        if row.outcome != comparison.outcome:
            return False
        if row.reason != comparison.reason:
            return False
        if self._normalize_datetime(row.decision_time) != self._normalize_datetime(
            decision_time
        ):
            return False
        if row.observed_value != comparison.observed_value:
            return False
        if row.observed_unit != comparison.observed_unit:
            return False
        if row.compared_value != comparison.compared_value:
            return False
        if freeze_json(row.applicability_snapshot) != freeze_json(
            self._applicability_snapshot(applicability_result)
        ):
            return False
        if freeze_json(row.observation_snapshot) != freeze_json(
            self._observation_snapshot(self._comparison_observation(comparison))
        ):
            return False
        return freeze_json(row.result_snapshot) == freeze_json(
            self._comparison_snapshot(
                comparison=comparison,
                applicability_result=applicability_result,
            )
        )

    @staticmethod
    def _comparison_observation(comparison: RuleComparison) -> Observation | None:
        if comparison.observed_value is None or comparison.observed_unit is None:
            return None
        return Observation(
            parameter=comparison.parameter,
            value=comparison.observed_value,
            unit=comparison.observed_unit,
        )

    def _canonicalize_checks(
        self,
        checks: Sequence[GovernedMachineReadinessCheck],
    ) -> tuple[GovernedMachineReadinessCheck, ...]:
        merged: dict[str, GovernedMachineReadinessCheck] = {}
        for check in checks:
            existing = merged.get(check.check_id)
            if existing is None:
                merged[check.check_id] = check
                continue
            if existing.required != check.required:
                raise ValueError(
                    f"conflicting required flag supplied for check_id {check.check_id}"
                )
            if (
                existing.description is not None
                and check.description is not None
                and existing.description != check.description
            ):
                raise ValueError(
                    f"conflicting description supplied for check_id {check.check_id}"
                )
            merged[check.check_id] = GovernedMachineReadinessCheck(
                check_id=existing.check_id,
                required=existing.required,
                evaluations=existing.evaluations + check.evaluations,
                description=existing.description or check.description,
            )
        return tuple(sorted(merged.values(), key=lambda item: item.check_id))

    def _canonicalize_traces(
        self,
        traces: Sequence[MachineReadinessCheckTrace],
    ) -> tuple[MachineReadinessCheckTrace, ...]:
        merged: dict[str, MachineReadinessCheckTrace] = {}
        for trace in traces:
            existing = merged.get(trace.check_id)
            if existing is None:
                merged[trace.check_id] = trace
                continue
            if existing.required != trace.required:
                raise ValueError(
                    f"conflicting required flag supplied for check_id {trace.check_id}"
                )
            if existing.condition != trace.condition or existing.reason != trace.reason:
                raise ValueError(
                    f"conflicting trace supplied for check_id {trace.check_id}"
                )
            merged[trace.check_id] = MachineReadinessCheckTrace(
                check_id=existing.check_id,
                required=existing.required,
                evaluations=existing.evaluations + trace.evaluations,
                condition=existing.condition,
                reason=existing.reason,
            )
        return tuple(sorted(merged.values(), key=lambda item: item.check_id))

    def _canonicalize_evaluations(
        self,
        evaluations: Sequence[GovernedRuleEvaluationSnapshot],
    ) -> tuple[GovernedRuleEvaluationSnapshot, ...]:
        unique: dict[tuple[str, int], GovernedRuleEvaluationSnapshot] = {}
        for evaluation in evaluations:
            key = (evaluation.evaluation_id, evaluation.revision_number)
            existing = unique.get(key)
            if existing is not None and existing != evaluation:
                raise ValueError(
                    "conflicting governed rule-evaluation snapshots supplied for the "
                    "same evaluation_id/revision_number"
                )
            unique[key] = evaluation
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.evaluation_id,
                    item.revision_number,
                    item.comparison.rule_id,
                    item.comparison.revision,
                    item.comparison.outcome.value,
                ),
            )
        )

    def _check_snapshot(
        self,
        *,
        definition: GovernedMachineReadinessCheck,
        trace: MachineReadinessCheckTrace,
        evaluations: Sequence[dict[str, object]],
    ) -> dict[str, object]:
        return freeze_json(
            {
                "check_id": definition.check_id,
                "required": definition.required,
                "description": definition.description,
                "condition": trace.condition.value,
                "reason": trace.reason,
                "evaluations": list(evaluations),
            }
        )

    @staticmethod
    def _result_snapshot(
        *,
        draft: MachineReadinessPersistenceDraft,
        checks_snapshot: Sequence[dict[str, object]],
    ) -> dict[str, object]:
        return freeze_json(
            {
                "state": draft.result.state.value,
                "reasons": list(draft.result.reasons),
                "prerequisites": list(draft.result.prerequisites),
                "context": MachineReadinessService._context_snapshot(draft.result.context),
                "decision_time": draft.result.decision_time.isoformat(),
                "validated_applicable_basis_count": draft.result.validated_applicable_basis_count,
                "checks": list(checks_snapshot),
            }
        )

    @staticmethod
    def _applicability_snapshot(
        applicability_result: GovernedApplicabilityResolution,
    ) -> dict[str, object]:
        return freeze_json(
            {
                "outcome": applicability_result.outcome.value,
                "reason": applicability_result.reason,
                "decision_time": applicability_result.decision_time.isoformat(),
                "context": applicability_result.context.as_mapping(),
                "selected_candidate_id": applicability_result.selected_candidate_id,
                "selected_rule_id": applicability_result.selected_rule_id,
                "selected_revision": applicability_result.selected_revision,
                "selected_specificity": applicability_result.selected_specificity,
                "conflict_candidate_ids": list(applicability_result.conflict_candidate_ids),
                "candidates": [
                    MachineReadinessService._candidate_snapshot(candidate)
                    for candidate in applicability_result.candidates
                ],
            }
        )

    @staticmethod
    def _candidate_snapshot(
        candidate: GovernedApplicabilityCandidateResult,
    ) -> dict[str, object]:
        return freeze_json(
            {
                "candidate_id": candidate.candidate_id,
                "rule_id": candidate.rule_id,
                "revision": candidate.revision,
                "evidence_class": candidate.evidence_class.value,
                "enabled": candidate.enabled,
                "active": candidate.active,
                "suspended": candidate.suspended,
                "revoked": candidate.revoked,
                "superseded": candidate.superseded,
                "basis_valid": candidate.basis_valid,
                "effective_from": candidate.effective_from.isoformat(),
                "expires_at": (
                    candidate.expires_at.isoformat()
                    if candidate.expires_at is not None
                    else None
                ),
                "specificity": candidate.specificity,
                "scope_snapshot": [
                    {"dimension": key, "values": list(values)}
                    for key, values in candidate.scope_snapshot
                ],
                "scope_result": (
                    None
                    if candidate.scope_result is None
                    else {
                        "outcome": candidate.scope_result.outcome.value,
                        "reason": candidate.scope_result.reason,
                        "matched_keys": list(candidate.scope_result.matched_keys),
                        "unsatisfied_keys": list(candidate.scope_result.unsatisfied_keys),
                        "missing_keys": list(candidate.scope_result.missing_keys),
                    }
                ),
                "eligible": candidate.eligible,
                "eligibility_reasons": list(candidate.eligibility_reasons),
            }
        )

    @staticmethod
    def _comparison_snapshot(
        *,
        comparison: RuleComparison,
        applicability_result: GovernedApplicabilityResolution,
    ) -> dict[str, object]:
        return freeze_json(
            {
                "rule_id": comparison.rule_id,
                "revision": comparison.revision,
                "parameter": comparison.parameter,
                "operator": comparison.operator.value,
                "outcome": comparison.outcome.value,
                "reason": comparison.reason,
                "observed_value": comparison.observed_value,
                "observed_unit": comparison.observed_unit,
                "compared_value": comparison.compared_value,
                "applicability_result": MachineReadinessService._applicability_snapshot(
                    applicability_result
                ),
                "conversion_provenance": MachineReadinessService._conversion_provenance_snapshot(
                    comparison.conversion_provenance
                ),
            }
        )

    @staticmethod
    def _rule_evaluation_row_snapshot(row: RuleEvaluation) -> dict[str, object]:
        return freeze_json(
            {
                "evaluation_id": row.evaluation_id,
                "revision_number": row.revision_number,
                "rule_id": row.rule_id,
                "rule_revision": row.rule_revision,
                "parameter": row.parameter,
                "operator": row.operator.value,
                "outcome": row.outcome.value,
                "reason": row.reason,
                "decision_time": row.decision_time.isoformat(),
                "observed_value": row.observed_value,
                "observed_unit": row.observed_unit,
                "compared_value": row.compared_value,
                "applicability_snapshot": row.applicability_snapshot,
                "observation_snapshot": row.observation_snapshot,
                "unit_policy_snapshot": row.unit_policy_snapshot,
                "result_snapshot": row.result_snapshot,
                "authority_snapshot": row.authority_snapshot,
            }
        )

    @staticmethod
    def _observation_snapshot(observation: Observation | None) -> dict[str, object | None]:
        if observation is None:
            return freeze_json({"parameter": None, "value": None, "unit": None})
        return freeze_json(
            {
                "parameter": observation.parameter,
                "value": observation.value,
                "unit": observation.unit,
            }
        )

    @staticmethod
    def _context_snapshot(context) -> dict[str, object]:
        return freeze_json(context.as_mapping())

    @staticmethod
    def _prerequisites_snapshot(
        prerequisites: Sequence[tuple[str, bool]],
    ) -> tuple[tuple[str, bool], ...]:
        return tuple((label, bool(satisfied)) for label, satisfied in prerequisites)

    @staticmethod
    def _conversion_provenance_snapshot(provenance) -> dict[str, object | None]:
        return freeze_json(
            {
                "conversion_occurred": provenance.conversion_occurred,
                "original_value": provenance.original_value,
                "original_unit": provenance.original_unit,
                "comparison_value": provenance.comparison_value,
                "target_unit": provenance.target_unit,
                "factor": provenance.factor,
                "policy_version": MachineReadinessService._content_version(
                    provenance.policy_version
                ),
                "rounding_policy": provenance.rounding_policy,
            }
        )

    @staticmethod
    def _authority_snapshot(
        audit: GovernedAuditMetadata,
        draft: MachineReadinessPersistenceDraft,
    ) -> dict[str, object]:
        return freeze_json(
            {
                "actor_id": audit.actor_id,
                "actor_user_id": audit.actor_user_id,
                "actor_role": audit.actor_role,
                "actor_type": audit.actor_type,
                "authority_scope": (
                    dict(audit.authority_scope)
                    if audit.authority_scope is not None
                    else None
                ),
                "reason": audit.reason,
                "correlation_id": audit.correlation_id,
                "idempotency_key": audit.idempotency_key,
                "assessment_id": draft.assessment_id,
                "revision_number": draft.revision_number,
                "decision_time": draft.result.decision_time.isoformat(),
                "policy_identifier": MachineReadinessService.COMMAND_NAMESPACE,
                "schema_version": audit.schema_version,
                "canonicalization_version": audit.canonicalization_version,
                "hash_algorithm": audit.hash_algorithm,
                "software_version": audit.software_version,
            }
        )

    def _deny_machine_readiness(
        self,
        *,
        draft: MachineReadinessPersistenceDraft,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        denial_code: str,
        denial_reason: str,
    ) -> CommandResultReference:
        denial_event = self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type="machine_readiness_denial",
            entity_id=draft.assessment_id,
            entity_revision=str(draft.revision_number),
            action="PERSIST_MACHINE_READINESS_ASSESSMENT_DENIED",
            prior_content_hash=None,
            new_content_hash=None,
            detail=self._audit_detail(
                audit,
                command="PERSIST_MACHINE_READINESS_ASSESSMENT_DENIED",
                assessment_id=draft.assessment_id,
                revision_number=draft.revision_number,
                denial_code=denial_code,
                denial_reason=denial_reason,
            ),
        )
        result = CommandResultReference(
            result_type="machine_readiness_denial",
            result_id=str(denial_event.id),
            result_revision="denied",
        )
        completed = self._idempotency.complete(
            identity=command_identity,
            request_hash=request_hash,
            result_reference=result,
            completed_at=completed_at,
        )
        if completed.result_reference != result:
            raise RuntimeError("machine readiness denial idempotency completion failed")
        return result

    @staticmethod
    def _common_audit_fields(audit: GovernedAuditMetadata) -> dict[str, object]:
        return {
            "event_id": audit.event_id,
            "actor_id": audit.actor_id,
            "actor_type": audit.actor_type,
            "reason": audit.reason,
            "correlation_id": audit.correlation_id,
            "schema_version": audit.schema_version,
            "software_version": audit.software_version,
            "canonicalization_version": audit.canonicalization_version,
            "hash_algorithm": audit.hash_algorithm,
            "created_at": audit.created_at,
            "actor_user_id": audit.actor_user_id,
            "actor_role": audit.actor_role,
            "authority_scope": audit.authority_scope,
            "idempotency_key": audit.idempotency_key,
        }

    @staticmethod
    def _audit_detail(
        audit: GovernedAuditMetadata,
        **command_detail: object,
    ) -> dict[str, object]:
        detail = dict(audit.detail) if audit.detail is not None else {}
        detail.update(command_detail)
        return freeze_json(detail)

    @staticmethod
    def _content_version(version: ContentVersionMetadata | None) -> dict[str, object] | None:
        return None if version is None else asdict(version)

    @staticmethod
    def _hash(value: object) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
