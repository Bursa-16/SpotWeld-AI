"""Governed persistence for immutable pure rule-evaluation results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime

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
from app.domain.rule_applicability import (
    ApplicabilityResolutionOutcome,
    GovernedApplicabilityCandidateResult,
    GovernedApplicabilityResolution,
)
from app.domain.rule_evaluation import Observation, RuleComparison
from app.domain.unit_policy import UnitPolicyCatalog, UnitPolicyContext
from app.models.rule_registry import EngineeringRule, EngineeringRuleRevision
from app.repositories.rule_evaluation_repository import RuleEvaluationRepository


@dataclass(frozen=True, slots=True)
class RuleEvaluationPersistenceDraft:
    evaluation_id: str
    revision_number: int
    comparison: RuleComparison
    applicability_result: GovernedApplicabilityResolution
    observation: Observation | None
    unit_context: UnitPolicyContext | None = None
    unit_catalog: UnitPolicyCatalog | None = None
    supersedes_evaluation_id: int | None = None

    def __post_init__(self) -> None:
        if not self.evaluation_id.strip():
            raise ValueError("evaluation_id must be a non-empty string")
        if self.revision_number <= 0:
            raise ValueError("revision_number must be positive")
        if self.unit_context is not None and self.unit_catalog is not None:
            raise ValueError("pass either unit_context or unit_catalog, not both")
        if self.unit_context is None and self.unit_catalog is None:
            raise ValueError("rule evaluation persistence requires a unit policy snapshot")


class RuleEvaluationService:
    """Persist already-computed governed evaluations without recomputation."""

    COMMAND_NAMESPACE = "registry.rule.evaluation"

    def __init__(self, unit_of_work: GovernedUnitOfWork):
        self._unit_of_work = unit_of_work
        self._repository = RuleEvaluationRepository(unit_of_work.session)
        self._idempotency = GovernedIdempotencyService(unit_of_work)
        self._audit = GovernedAuditService(unit_of_work)

    def persist_evaluation(
        self,
        *,
        draft: RuleEvaluationPersistenceDraft,
        receipt_id: str,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
    ) -> CommandResultReference:
        self._unit_of_work.ensure_open()
        if command_identity.command_namespace != self.COMMAND_NAMESPACE:
            raise ValueError("rule evaluation command namespace mismatch")
        if command_identity.command_scope != draft.evaluation_id:
            raise ValueError("rule evaluation command scope must match evaluation_id")

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
                raise RuntimeError("completed rule evaluation replay has no durable result")
            return decision.result_reference
        if decision.disposition is IdempotencyDisposition.CONFLICT:
            raise ValueError("idempotency conflict for rule evaluation command")
        if decision.disposition is IdempotencyDisposition.IN_PROGRESS:
            raise RuntimeError("rule evaluation command is already in progress")

        comparison = draft.comparison
        if comparison.applicability_result is None:
            return self._deny_rule_evaluation(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="MISSING_APPLICABILITY_RESULT",
                denial_reason="persistence requires a SELECTED applicability result",
            )
        if (
            comparison.applicability_result.outcome
            is not ApplicabilityResolutionOutcome.SELECTED
        ):
            return self._deny_rule_evaluation(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="APPLICABILITY_NOT_SELECTED",
                denial_reason="persistence requires a SELECTED applicability result",
            )
        if comparison.applicability_result != draft.applicability_result:
            return self._deny_rule_evaluation(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="APPLICABILITY_PIN_MISMATCH",
                denial_reason="supplied applicability snapshot does not match the pure result",
            )
        if (
            comparison.applicability_result.selected_rule_id is None
            or comparison.applicability_result.selected_revision is None
        ):
            return self._deny_rule_evaluation(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="APPLICABILITY_IDENTITY_INCOMPLETE",
                denial_reason="selected applicability result is missing the governing identity",
            )
        if (
            comparison.applicability_result.selected_rule_id.strip() != comparison.rule_id.strip()
            or comparison.applicability_result.selected_revision.strip() != comparison.revision.strip()
        ):
            return self._deny_rule_evaluation(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="RULE_PIN_MISMATCH",
                denial_reason="selected applicability pin does not match the evaluated rule identity",
            )
        if draft.observation is None:
            if comparison.observed_value is not None or comparison.observed_unit is not None:
                return self._deny_rule_evaluation(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="OBSERVATION_PIN_MISMATCH",
                    denial_reason="supplied observation snapshot does not match the pure result",
                )
        else:
            if (
                draft.observation.parameter.strip() != comparison.parameter.strip()
                or draft.observation.value != comparison.observed_value
                or draft.observation.unit != comparison.observed_unit
            ):
                return self._deny_rule_evaluation(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="OBSERVATION_PIN_MISMATCH",
                    denial_reason="supplied observation snapshot does not match the pure result",
                )

        unit_policy_snapshot = self._unit_policy_snapshot(draft)
        if not self._unit_policy_snapshot_matches(
            comparison=comparison,
            draft=draft,
            unit_policy_snapshot=unit_policy_snapshot,
        ):
            return self._deny_rule_evaluation(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="UNIT_POLICY_PIN_MISMATCH",
                denial_reason="supplied unit-policy snapshot does not match the pure result",
            )

        history = self._repository.list_history(draft.evaluation_id)
        if not history:
            if draft.supersedes_evaluation_id is not None or draft.revision_number != 1:
                return self._deny_rule_evaluation(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="REVISION_SEQUENCE_INVALID",
                    denial_reason="first evaluation revision_number must be 1",
                )
        else:
            latest = history[-1]
            if (
                draft.supersedes_evaluation_id is None
                or draft.supersedes_evaluation_id != latest.id
            ):
                return self._deny_rule_evaluation(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="BRANCHING_REVISION_REJECTED",
                    denial_reason="corrections must supersede the current latest revision",
                )
            if draft.revision_number != latest.revision_number + 1:
                return self._deny_rule_evaluation(
                    draft=draft,
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="REVISION_SEQUENCE_INVALID",
                    denial_reason="corrections must use the next revision_number",
                )

        rule = self._repository.session.scalar(
            select(EngineeringRule).where(EngineeringRule.rule_id == comparison.rule_id)
        )
        if rule is None:
            return self._deny_rule_evaluation(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="MISSING_RULE_IDENTITY",
                denial_reason="the evaluated rule identity does not exist",
            )
        revision = self._repository.session.scalar(
            select(EngineeringRuleRevision).where(
                EngineeringRuleRevision.engineering_rule_id == rule.id,
                EngineeringRuleRevision.revision == comparison.revision,
            )
        )
        if revision is None:
            return self._deny_rule_evaluation(
                draft=draft,
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="MISSING_RULE_REVISION",
                denial_reason="the evaluated rule revision does not exist",
            )

        result_snapshot = self._result_snapshot(
            comparison=comparison,
            applicability_result=draft.applicability_result,
        )
        authority_snapshot = self._authority_snapshot(audit, draft)
        content_hash = self._hash(
            {
                "evaluation_id": draft.evaluation_id,
                "revision_number": draft.revision_number,
                "rule_id": comparison.rule_id,
                "revision": comparison.revision,
                "parameter": comparison.parameter,
                "operator": comparison.operator.value,
                "decision_time": draft.applicability_result.decision_time.isoformat(),
                "comparison": result_snapshot,
                "observation_snapshot": self._observation_snapshot(draft.observation),
                "unit_policy_snapshot": unit_policy_snapshot,
                "applicability_snapshot": self._applicability_snapshot(
                    draft.applicability_result
                ),
                "authority_snapshot": authority_snapshot,
                "supersedes_evaluation_id": draft.supersedes_evaluation_id,
            }
        )
        evaluation = self._repository.create_evaluation(
            engineering_rule=rule,
            engineering_rule_revision=revision,
            evaluation_id=draft.evaluation_id,
            revision_number=draft.revision_number,
            rule_id=comparison.rule_id,
            rule_revision=comparison.revision,
            parameter=comparison.parameter,
            operator=comparison.operator,
            outcome=comparison.outcome,
            reason=comparison.reason,
            decision_time=draft.applicability_result.decision_time,
            observed_value=comparison.observed_value,
            observed_unit=comparison.observed_unit,
            compared_value=comparison.compared_value,
            applicability_snapshot=self._applicability_snapshot(draft.applicability_result),
            observation_snapshot=self._observation_snapshot(draft.observation),
            unit_policy_snapshot=unit_policy_snapshot,
            result_snapshot=result_snapshot,
            authority_snapshot=authority_snapshot,
            created_by_actor_id=audit.actor_id,
            created_by_user_id=audit.actor_user_id,
            schema_version=audit.schema_version,
            canonicalization_version=audit.canonicalization_version,
            hash_algorithm=audit.hash_algorithm,
            content_hash=content_hash,
            software_version=audit.software_version,
            correlation_id=audit.correlation_id,
            supersedes_evaluation_id=draft.supersedes_evaluation_id,
        )
        self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type="rule_evaluation",
            entity_id=draft.evaluation_id,
            entity_revision=str(draft.revision_number),
            action=(
                "CORRECT_RULE_EVALUATION"
                if draft.supersedes_evaluation_id is not None
                else "PERSIST_RULE_EVALUATION"
            ),
            prior_content_hash=None
            if draft.supersedes_evaluation_id is None
            else history[-1].content_hash,
            new_content_hash=evaluation.content_hash,
            detail=self._audit_detail(
                audit,
                command=(
                    "CORRECT_RULE_EVALUATION"
                    if draft.supersedes_evaluation_id is not None
                    else "PERSIST_RULE_EVALUATION"
                ),
                evaluation_id=draft.evaluation_id,
                revision_number=draft.revision_number,
                rule_id=comparison.rule_id,
                rule_revision=comparison.revision,
                outcome=comparison.outcome.value,
                supersedes_evaluation_id=draft.supersedes_evaluation_id,
                applicability_result=self._applicability_snapshot(
                    draft.applicability_result
                ),
                observation_snapshot=self._observation_snapshot(draft.observation),
                unit_policy_snapshot=unit_policy_snapshot,
            ),
        )
        result = CommandResultReference(
            result_type="rule_evaluation",
            result_id=draft.evaluation_id,
            result_revision=str(draft.revision_number),
        )
        completed = self._idempotency.complete(
            identity=command_identity,
            request_hash=request_hash,
            result_reference=result,
            completed_at=completed_at,
        )
        if completed.result_reference != result:
            raise RuntimeError("rule evaluation idempotency completion failed")
        return result

    def _unit_policy_snapshot(
        self,
        draft: RuleEvaluationPersistenceDraft,
    ) -> dict[str, object]:
        if draft.unit_context is not None:
            return {
                "kind": "unit_context",
                "expected_unit": draft.unit_context.expected_unit,
                "conversion_factors": [
                    {
                        "from_unit": from_unit,
                        "to_unit": to_unit,
                        "factor": factor,
                    }
                    for (from_unit, to_unit), factor in sorted(
                        draft.unit_context.conversion_factors.items()
                    )
                ],
                "policy_version": self._content_version(draft.unit_context.policy_version),
                "rounding_policy": draft.unit_context.rounding_policy,
            }
        assert draft.unit_catalog is not None
        return {
            "kind": "unit_catalog",
            "version": self._content_version(draft.unit_catalog.version),
            "rounding_policy": draft.unit_catalog.rounding_policy,
            "conversions": [
                {
                    "from_unit": entry.from_unit,
                    "to_unit": entry.to_unit,
                    "factor": entry.factor,
                }
                for entry in draft.unit_catalog.conversions
            ],
        }

    def _unit_policy_snapshot_matches(
        self,
        *,
        comparison: RuleComparison,
        draft: RuleEvaluationPersistenceDraft,
        unit_policy_snapshot: dict[str, object],
    ) -> bool:
        provenance = comparison.conversion_provenance
        if unit_policy_snapshot["kind"] == "unit_context":
            if draft.unit_context is None:
                return False
            if unit_policy_snapshot["expected_unit"] != provenance.target_unit:
                return False
            snapshot_version = unit_policy_snapshot.get("policy_version")
            if (
                provenance.policy_version is not None
                and snapshot_version != self._content_version(provenance.policy_version)
            ):
                return False
            if provenance.conversion_occurred:
                source_unit = provenance.original_unit
                if source_unit is None or provenance.factor is None:
                    return False
                factor = draft.unit_context.conversion_factors.get(
                    (source_unit.strip(), provenance.target_unit.strip())
                )
                if factor != provenance.factor:
                    return False
            elif snapshot_version not in (None, self._content_version(provenance.policy_version)):
                return False
            return True

        if draft.unit_catalog is None:
            return False
        if unit_policy_snapshot["version"] != self._content_version(provenance.policy_version):
            return False
        if provenance.conversion_occurred and provenance.factor is not None:
            matching = [
                entry
                for entry in draft.unit_catalog.conversions
                if entry.from_unit == provenance.original_unit
                and entry.to_unit == provenance.target_unit
                and entry.factor == provenance.factor
            ]
            if not matching:
                return False
        return True

    @staticmethod
    def _observation_snapshot(observation: Observation | None) -> dict[str, object | None]:
        if observation is None:
            return {"parameter": None, "value": None, "unit": None}
        return {
            "parameter": observation.parameter,
            "value": observation.value,
            "unit": observation.unit,
        }

    @staticmethod
    def _applicability_snapshot(
        applicability_result: GovernedApplicabilityResolution,
    ) -> dict[str, object]:
        return {
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
                RuleEvaluationService._candidate_snapshot(candidate)
                for candidate in applicability_result.candidates
            ],
        }

    @staticmethod
    def _candidate_snapshot(
        candidate: GovernedApplicabilityCandidateResult,
    ) -> dict[str, object]:
        return {
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

    @staticmethod
    def _result_snapshot(
        *,
        comparison: RuleComparison,
        applicability_result: GovernedApplicabilityResolution,
    ) -> dict[str, object]:
        return {
            "rule_id": comparison.rule_id,
            "revision": comparison.revision,
            "parameter": comparison.parameter,
            "operator": comparison.operator.value,
            "outcome": comparison.outcome.value,
            "reason": comparison.reason,
            "observed_value": comparison.observed_value,
            "observed_unit": comparison.observed_unit,
            "compared_value": comparison.compared_value,
            "applicability_result": RuleEvaluationService._applicability_snapshot(
                applicability_result
            ),
            "conversion_provenance": RuleEvaluationService._conversion_provenance_snapshot(
                comparison.conversion_provenance
            ),
        }

    @staticmethod
    def _conversion_provenance_snapshot(
        provenance,
    ) -> dict[str, object | None]:
        return {
            "conversion_occurred": provenance.conversion_occurred,
            "original_value": provenance.original_value,
            "original_unit": provenance.original_unit,
            "comparison_value": provenance.comparison_value,
            "target_unit": provenance.target_unit,
            "factor": provenance.factor,
            "policy_version": RuleEvaluationService._content_version(
                provenance.policy_version
            ),
            "rounding_policy": provenance.rounding_policy,
        }

    @staticmethod
    def _authority_snapshot(
        audit: GovernedAuditMetadata,
        draft: RuleEvaluationPersistenceDraft,
    ) -> dict[str, object]:
        return {
            "actor_id": audit.actor_id,
            "actor_user_id": audit.actor_user_id,
            "actor_role": audit.actor_role,
            "actor_type": audit.actor_type,
            "authority_scope": (
                dict(audit.authority_scope) if audit.authority_scope is not None else None
            ),
            "reason": audit.reason,
            "correlation_id": audit.correlation_id,
            "idempotency_key": audit.idempotency_key,
            "evaluation_id": draft.evaluation_id,
            "revision_number": draft.revision_number,
            "decision_time": draft.applicability_result.decision_time.isoformat(),
            "policy_identifier": RuleEvaluationService.COMMAND_NAMESPACE,
            "schema_version": audit.schema_version,
            "canonicalization_version": audit.canonicalization_version,
            "hash_algorithm": audit.hash_algorithm,
            "software_version": audit.software_version,
        }

    def _deny_rule_evaluation(
        self,
        *,
        draft: RuleEvaluationPersistenceDraft,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        denial_code: str,
        denial_reason: str,
    ) -> CommandResultReference:
        denial_event = self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type="rule_evaluation_denial",
            entity_id=draft.evaluation_id,
            entity_revision=str(draft.revision_number),
            action="PERSIST_RULE_EVALUATION_DENIED",
            prior_content_hash=None,
            new_content_hash=None,
            detail=self._audit_detail(
                audit,
                command="PERSIST_RULE_EVALUATION_DENIED",
                evaluation_id=draft.evaluation_id,
                revision_number=draft.revision_number,
                denial_code=denial_code,
                denial_reason=denial_reason,
            ),
        )
        result = CommandResultReference(
            result_type="rule_evaluation_denial",
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
            raise RuntimeError("rule evaluation denial idempotency completion failed")
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
        return detail

    @staticmethod
    def _content_version(version: ContentVersionMetadata | None) -> dict[str, object] | None:
        return None if version is None else asdict(version)

    @staticmethod
    def _hash(value: object) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
