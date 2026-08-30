from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    RuleLifecycleStatus,
)
from app.domain.rule_applicability import (
    GovernedApplicabilityCandidate,
    GovernedApplicabilityContext,
    GovernedApplicabilityResolution,
    resolve_governed_applicability,
)
from app.domain.rule_evaluation import (
    Observation,
    RuleComparison,
    RuleComparisonOutcome,
    RuleRequirement,
    compare_rule,
)
from app.domain.rule_registry_types import (
    MissingHandling,
    RuleCategory,
    RuleOperator,
    SafeDefault,
)
from app.domain.unit_policy import ConversionEntry, UnitPolicyCatalog, UnitPolicyContext
from app.models.entities import User
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.rule_evaluation import RuleEvaluation
from app.models.rule_registry import EngineeringRule, EngineeringRuleRevision
from app.repositories.governance_repository import GovernanceRepository
from app.repositories.rule_registry_repository import RuleRegistryRepository
from app.schemas.governed_api import (
    GovernedScopeSnapshot,
    RuleEvaluationApplicabilityCandidateSnapshot,
    RuleEvaluationApplicabilityResolutionSnapshot,
    RuleEvaluationApplicabilityResultSnapshot,
    RuleEvaluationComparisonSnapshot,
    RuleEvaluationContentVersionMetadata,
    RuleEvaluationConversionEntrySnapshot,
    RuleEvaluationConversionProvenanceSnapshot,
    RuleEvaluationObservationSnapshot,
    RuleEvaluationPersistenceRequest,
    RuleEvaluationUnitPolicyCatalogSnapshot,
    RuleEvaluationUnitPolicyContextSnapshot,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

RULE_ID = "API_PERSISTED_EVALUATION_RULE"
RULE_REVISION = "1.0"
NEWER_RULE_REVISION = "2.0"
DECISION_TIME = datetime(2034, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
PAST = datetime(2034, 1, 1, 0, 0, tzinfo=timezone.utc)


def _token(email: str) -> str:
    return create_access_token(email)


def _user(
    session: Session,
    *,
    email: str,
    full_name: str,
    role: str,
    is_active: bool = True,
) -> User:
    user = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password("ChangeMe123!"),
        role=role,
        is_active=is_active,
    )
    session.add(user)
    session.flush()
    return user


def _scope(
    *,
    customer: str = "customer-a",
    project: str = "project-a",
    site: str = "site-a",
    machine: str = "machine-a",
) -> dict[str, str]:
    return {
        "customer": customer,
        "project": project,
        "site": site,
        "machine": machine,
    }


def _governed_counts(session: Session) -> tuple[int, int, int]:
    return (
        session.scalar(select(func.count(RuleEvaluation.id))) or 0,
        session.scalar(select(func.count(GovernedAuditEvent.id))) or 0,
        session.scalar(select(func.count(GovernedCommandReceipt.id))) or 0,
    )


def _seed_rule_revision(
    session: Session,
    *,
    rule_id: str = RULE_ID,
    revision: str = RULE_REVISION,
    operator: RuleOperator = RuleOperator.MIN,
    min_value: float | None = 10.0,
    max_value: float | None = None,
    unit: str = "synthetic_unit",
    evidence_class: EvidenceClass = EvidenceClass.SOURCE_BACKED,
) -> EngineeringRuleRevision:
    repository = RuleRegistryRepository(session)
    rule = session.scalar(select(EngineeringRule).where(EngineeringRule.rule_id == rule_id))
    if rule is None:
        rule = repository.create_rule(
            rule_id=rule_id,
            created_by_actor_id="seed-actor",
            created_by_user_id=None,
        )
    return repository.create_revision(
        engineering_rule=rule,
        revision=revision,
        name="API persisted evaluation rule",
        status=RuleLifecycleStatus.DRAFT,
        evidence_class=evidence_class,
        category=RuleCategory.OTHER,
        parameter="synthetic_parameter",
        operator=operator,
        min_value=min_value,
        max_value=max_value,
        unit=unit,
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.DATA_INSUFFICIENT,
        enabled=False,
        reason_for_change="API persisted evaluation seed",
        version_metadata=ContentVersionMetadata(
            schema_version="api-evaluation-v1",
            canonicalization_version="api-evaluation-canonical-v1",
            hash_algorithm="sha256",
            content_hash=hashlib.sha256(f"{rule_id}:{revision}".encode()).hexdigest(),
            software_version="test-build",
        ),
        created_by_actor_id="seed-actor",
        created_by_user_id=None,
        allow_source_backed=True,
    )


def _selected_resolution(
    *,
    rule_id: str = RULE_ID,
    revision: str = RULE_REVISION,
    scope: dict[str, str] | None = None,
    decision_time: datetime = DECISION_TIME,
) -> GovernedApplicabilityResolution:
    if scope is None:
        scope = _scope()
    candidate = GovernedApplicabilityCandidate(
        candidate_id=f"{rule_id}:{revision}",
        rule_id=rule_id,
        revision=revision,
        evidence_class=EvidenceClass.SOURCE_BACKED,
        enabled=True,
        active=True,
        scope_snapshot={"customer": [scope["customer"]]},
        effective_from=PAST,
    )
    return resolve_governed_applicability(
        GovernedApplicabilityContext(**scope),
        decision_time,
        [candidate],
    )


def _requirement(
    *,
    rule_id: str = RULE_ID,
    revision: str = RULE_REVISION,
    operator: RuleOperator = RuleOperator.MIN,
    min_value: float | None = 10.0,
    max_value: float | None = None,
    unit: str = "synthetic_unit",
    enabled: bool = True,
) -> RuleRequirement:
    return RuleRequirement(
        rule_id=rule_id,
        revision=revision,
        parameter="synthetic_parameter",
        operator=operator,
        unit=unit,
        min_value=min_value,
        max_value=max_value,
        enabled=enabled,
    )


def _unit_context(expected_unit: str = "synthetic_unit") -> UnitPolicyContext:
    return UnitPolicyContext(expected_unit=expected_unit)


def _unit_catalog() -> UnitPolicyCatalog:
    return UnitPolicyCatalog(
        version=ContentVersionMetadata(
            schema_version="unit-policy-v1",
            canonicalization_version="unit-policy-canonical-v1",
            hash_algorithm="sha256",
            content_hash=hashlib.sha256(b"unit-policy").hexdigest(),
            software_version="test-build",
        ),
        rounding_policy="nearest",
        conversions=(
            ConversionEntry(
                from_unit="secondary_unit",
                to_unit="synthetic_unit",
                factor=2.0,
            ),
        ),
    )


def _applicability_result_snapshot(
    result,
) -> RuleEvaluationApplicabilityResultSnapshot:
    return RuleEvaluationApplicabilityResultSnapshot(
        outcome=result.outcome,
        reason=result.reason,
        matched_keys=list(result.matched_keys),
        unsatisfied_keys=list(result.unsatisfied_keys),
        missing_keys=list(result.missing_keys),
    )


def _applicability_candidate_snapshot(candidate) -> RuleEvaluationApplicabilityCandidateSnapshot:
    return RuleEvaluationApplicabilityCandidateSnapshot(
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
        scope_snapshot={
            key: list(values) if values is not None else None
            for key, values in candidate.scope_snapshot
        },
        scope_result=(
            None
            if candidate.scope_result is None
            else _applicability_result_snapshot(candidate.scope_result)
        ),
        eligible=candidate.eligible,
        eligibility_reasons=list(candidate.eligibility_reasons),
    )


def _applicability_resolution_snapshot(
    resolution: GovernedApplicabilityResolution,
) -> RuleEvaluationApplicabilityResolutionSnapshot:
    return RuleEvaluationApplicabilityResolutionSnapshot(
        outcome=resolution.outcome,
        reason=resolution.reason,
        decision_time=resolution.decision_time,
        context=GovernedScopeSnapshot(
            customer=resolution.context.customer,
            project=resolution.context.project,
            site=resolution.context.site,
            machine=resolution.context.machine,
        ),
        candidates=[
            _applicability_candidate_snapshot(candidate)
            for candidate in resolution.candidates
        ],
        selected_candidate_id=resolution.selected_candidate_id,
        selected_rule_id=resolution.selected_rule_id,
        selected_revision=resolution.selected_revision,
        selected_specificity=resolution.selected_specificity,
        conflict_candidate_ids=list(resolution.conflict_candidate_ids),
    )


def _conversion_provenance_snapshot(
    provenance,
) -> RuleEvaluationConversionProvenanceSnapshot:
    return RuleEvaluationConversionProvenanceSnapshot(
        conversion_occurred=provenance.conversion_occurred,
        original_value=provenance.original_value,
        original_unit=provenance.original_unit,
        comparison_value=provenance.comparison_value,
        target_unit=provenance.target_unit,
        factor=provenance.factor,
        policy_version=(
            None
            if provenance.policy_version is None
            else RuleEvaluationContentVersionMetadata(
                schema_version=provenance.policy_version.schema_version,
                canonicalization_version=provenance.policy_version.canonicalization_version,
                hash_algorithm=provenance.policy_version.hash_algorithm,
                content_hash=provenance.policy_version.content_hash,
                software_version=provenance.policy_version.software_version,
            )
        ),
        rounding_policy=provenance.rounding_policy,
    )


def _comparison_snapshot(comparison: RuleComparison) -> RuleEvaluationComparisonSnapshot:
    return RuleEvaluationComparisonSnapshot(
        rule_id=comparison.rule_id,
        revision=comparison.revision,
        parameter=comparison.parameter,
        operator=comparison.operator,
        outcome=comparison.outcome,
        reason=comparison.reason,
        observed_value=comparison.observed_value,
        observed_unit=comparison.observed_unit,
        compared_value=comparison.compared_value,
        applicability_result=_applicability_resolution_snapshot(
            comparison.applicability_result
        ),
        conversion_provenance=_conversion_provenance_snapshot(
            comparison.conversion_provenance
        ),
    )


def _observation_snapshot(observation: Observation | None) -> RuleEvaluationObservationSnapshot | None:
    if observation is None:
        return None
    return RuleEvaluationObservationSnapshot(
        parameter=observation.parameter,
        value=observation.value,
        unit=observation.unit,
    )


def _unit_context_snapshot(
    unit_context: UnitPolicyContext | None,
) -> RuleEvaluationUnitPolicyContextSnapshot | None:
    if unit_context is None:
        return None
    return RuleEvaluationUnitPolicyContextSnapshot(
        expected_unit=unit_context.expected_unit,
        conversion_factors=[
            RuleEvaluationConversionEntrySnapshot(
                from_unit=from_unit,
                to_unit=to_unit,
                factor=factor,
            )
            for (from_unit, to_unit), factor in unit_context.conversion_factors.items()
        ],
        policy_version=(
            None
            if unit_context.policy_version is None
            else RuleEvaluationContentVersionMetadata(
                schema_version=unit_context.policy_version.schema_version,
                canonicalization_version=unit_context.policy_version.canonicalization_version,
                hash_algorithm=unit_context.policy_version.hash_algorithm,
                content_hash=unit_context.policy_version.content_hash,
                software_version=unit_context.policy_version.software_version,
            )
        ),
        rounding_policy=unit_context.rounding_policy,
    )


def _unit_catalog_snapshot(
    unit_catalog: UnitPolicyCatalog | None,
) -> RuleEvaluationUnitPolicyCatalogSnapshot | None:
    if unit_catalog is None:
        return None
    return RuleEvaluationUnitPolicyCatalogSnapshot(
        version=RuleEvaluationContentVersionMetadata(
            schema_version=unit_catalog.version.schema_version,
            canonicalization_version=unit_catalog.version.canonicalization_version,
            hash_algorithm=unit_catalog.version.hash_algorithm,
            content_hash=unit_catalog.version.content_hash,
            software_version=unit_catalog.version.software_version,
        ),
        rounding_policy=unit_catalog.rounding_policy,
        conversions=[
            RuleEvaluationConversionEntrySnapshot(
                from_unit=entry.from_unit,
                to_unit=entry.to_unit,
                factor=entry.factor,
            )
            for entry in unit_catalog.conversions
        ],
    )


def _payload(
    *,
    evaluation_id: str,
    revision_number: int,
    comparison: RuleComparison,
    observation: Observation | None,
    unit_context: UnitPolicyContext | None = None,
    unit_catalog: UnitPolicyCatalog | None = None,
    supersedes_evaluation_id: int | None = None,
    decision_reason: str = "governed evaluation persistence",
) -> RuleEvaluationPersistenceRequest:
    return RuleEvaluationPersistenceRequest(
        evaluation_id=evaluation_id,
        revision_number=revision_number,
        comparison=_comparison_snapshot(comparison),
        observation=_observation_snapshot(observation),
        unit_context=_unit_context_snapshot(unit_context),
        unit_catalog=_unit_catalog_snapshot(unit_catalog),
        supersedes_evaluation_id=supersedes_evaluation_id,
        decision_reason=decision_reason,
    )


def _post(
    client: TestClient,
    payload: RuleEvaluationPersistenceRequest,
    *,
    token: str,
    key: str,
):
    return client.post(
        "/api/v1/rule-evaluations",
        json=payload.model_dump(mode="json"),
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": key,
        },
    )


def _persisted_evaluation(
    session: Session,
    *,
    evaluation_id: str,
    revision_number: int,
) -> RuleEvaluation | None:
    return session.scalar(
        select(RuleEvaluation).where(
            RuleEvaluation.evaluation_id == evaluation_id,
            RuleEvaluation.revision_number == revision_number,
        )
    )


def test_unauthenticated_inactive_and_actor_spoofing_are_rejected(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_AUTH"
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    unauthenticated = client.post(
        "/api/v1/rule-evaluations",
        json=_payload(
            evaluation_id="API-EVAL-401",
            revision_number=1,
            comparison=compare_rule(
                _requirement(rule_id=rule_id),
                Observation("synthetic_parameter", 12.0, "synthetic_unit"),
                applicability_result=_selected_resolution(rule_id=rule_id),
                unit_context=_unit_context(),
            ),
            observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            unit_context=_unit_context(),
        ).model_dump(mode="json"),
        headers={"Idempotency-Key": "api-eval-401"},
    )
    assert unauthenticated.status_code == 401

    with SessionLocal() as session:
        _user(
            session,
            email="inactive-eval@example.com",
            full_name="Inactive Eval",
            role="Process Engineer",
            is_active=False,
        )
        session.commit()

    inactive = client.post(
        "/api/v1/rule-evaluations",
        json=_payload(
            evaluation_id="API-EVAL-402",
            revision_number=1,
            comparison=compare_rule(
                _requirement(rule_id=rule_id),
                Observation("synthetic_parameter", 12.0, "synthetic_unit"),
                applicability_result=_selected_resolution(rule_id=rule_id),
                unit_context=_unit_context(),
            ),
            observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            unit_context=_unit_context(),
        ).model_dump(mode="json"),
        headers={
            "Authorization": f"Bearer {_token('inactive-eval@example.com')}",
            "Idempotency-Key": "api-eval-402",
        },
    )
    assert inactive.status_code == 401

    spoofed = client.post(
        "/api/v1/rule-evaluations",
            json={
                **_payload(
                    evaluation_id="API-EVAL-403",
                    revision_number=1,
                    comparison=compare_rule(
                    _requirement(rule_id=rule_id),
                    Observation("synthetic_parameter", 12.0, "synthetic_unit"),
                    applicability_result=_selected_resolution(rule_id=rule_id),
                    unit_context=_unit_context(),
                ),
                observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
                unit_context=_unit_context(),
            ).model_dump(mode="json"),
            "actor_user_id": 999,
        },
        headers={
            "Authorization": f"Bearer {_token('admin@spotwelding.example')}",
            "Idempotency-Key": "api-eval-403",
        },
    )
    assert spoofed.status_code == 422


def test_persisted_evaluation_returns_explicit_outcome_and_exact_pins(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_SUCCESS"
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    actor_email = "engineer-eval@example.com"
    with SessionLocal() as session:
        actor = _user(
            session,
            email=actor_email,
            full_name="Evaluation Engineer",
            role="Process Engineer",
        )
        session.commit()
        actor_id = actor.id

    payload = _payload(
        evaluation_id="API-EVAL-410",
        revision_number=1,
        comparison=compare_rule(
            _requirement(rule_id=rule_id),
            Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            applicability_result=_selected_resolution(rule_id=rule_id),
            unit_context=_unit_context(),
        ),
        observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
        unit_context=_unit_context(),
        decision_reason="API success path",
    )

    with SessionLocal() as session:
        before_counts = _governed_counts(session)

    response = _post(
        client,
        payload,
        token=_token(actor_email),
        key="api-eval-410",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_outcome"] == "SATISFIED"
    assert body["result_type"] == "rule_evaluation"
    assert body["result_id"] == "API-EVAL-410"
    assert body["result_revision"] == "1"
    assert body["rule_id"] == rule_id
    assert body["rule_revision"] == RULE_REVISION
    assert body["evaluation_id"] == "API-EVAL-410"
    assert body["revision_number"] == 1
    assert body["command_namespace"] == "registry.rule.evaluation"
    assert body["command_scope"] == "API-EVAL-410"

    with SessionLocal() as session:
        persisted = _persisted_evaluation(session, evaluation_id="API-EVAL-410", revision_number=1)
        assert persisted is not None
        audit_event = GovernanceRepository(session).get_by_event_id(
            "rule-evaluation:API-EVAL-410:api-eval-410:audit"
        )
        assert audit_event is not None
        assert audit_event.actor_user_id == actor_id
        assert audit_event.actor_role == "Process Engineer"
        after_counts = _governed_counts(session)
    assert after_counts == (before_counts[0] + 1, before_counts[1] + 1, before_counts[2] + 1)


@pytest.mark.parametrize(
    (
        "rule_id",
        "evaluation_id",
        "comparison",
        "observation",
        "unit_context",
        "unit_catalog",
        "expected_outcome",
    ),
    [
        pytest.param(
            "API_PERSISTED_EVALUATION_RULE_NOT_SAT",
            "API-EVAL-411",
            compare_rule(
                _requirement(rule_id="API_PERSISTED_EVALUATION_RULE_NOT_SAT"),
                Observation("synthetic_parameter", 8.0, "synthetic_unit"),
                applicability_result=_selected_resolution(rule_id="API_PERSISTED_EVALUATION_RULE_NOT_SAT"),
                unit_context=_unit_context(),
            ),
            Observation("synthetic_parameter", 8.0, "synthetic_unit"),
            _unit_context(),
            None,
            "NOT_SATISFIED",
            id="not-satisfied",
        ),
        pytest.param(
            "API_PERSISTED_EVALUATION_RULE_NOT_APP",
            "API-EVAL-412",
            compare_rule(
                _requirement(
                    rule_id="API_PERSISTED_EVALUATION_RULE_NOT_APP",
                    enabled=False,
                ),
                None,
                applicability_result=_selected_resolution(
                    rule_id="API_PERSISTED_EVALUATION_RULE_NOT_APP"
                ),
                unit_context=_unit_context(),
            ),
            None,
            _unit_context(),
            None,
            "NOT_APPLICABLE",
            id="not-applicable",
        ),
        pytest.param(
            "API_PERSISTED_EVALUATION_RULE_UNIT",
            "API-EVAL-413",
            compare_rule(
                _requirement(rule_id="API_PERSISTED_EVALUATION_RULE_UNIT"),
                Observation("synthetic_parameter", 12.0, "other_unit"),
                applicability_result=_selected_resolution(
                    rule_id="API_PERSISTED_EVALUATION_RULE_UNIT"
                ),
                unit_context=_unit_context(),
            ),
            Observation("synthetic_parameter", 12.0, "other_unit"),
            _unit_context(),
            None,
            "UNIT_MISMATCH",
            id="unit-mismatch",
        ),
        pytest.param(
            "API_PERSISTED_EVALUATION_RULE_UNRES",
            "API-EVAL-414",
            compare_rule(
                _requirement(rule_id="API_PERSISTED_EVALUATION_RULE_UNRES"),
                None,
                applicability_result=_selected_resolution(
                    rule_id="API_PERSISTED_EVALUATION_RULE_UNRES"
                ),
                unit_context=_unit_context(),
            ),
            None,
            _unit_context(),
            None,
            "UNRESOLVED",
            id="unresolved",
        ),
    ],
)
def test_persisted_evaluation_returns_explicit_outcomes(
    client: TestClient,
    rule_id: str,
    evaluation_id: str,
    comparison: RuleComparison,
    observation: Observation | None,
    unit_context: UnitPolicyContext | None,
    unit_catalog: UnitPolicyCatalog | None,
    expected_outcome: str,
) -> None:
    with SessionLocal() as session:
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    payload = _payload(
        evaluation_id=evaluation_id,
        revision_number=1,
        comparison=comparison,
        observation=observation,
        unit_context=unit_context,
        unit_catalog=unit_catalog,
        decision_reason=f"{evaluation_id} decision",
    )

    response = _post(
        client,
        payload,
        token=_token("admin@spotwelding.example"),
        key=f"{evaluation_id}-key",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_outcome"] == expected_outcome
    assert body["result_type"] == "rule_evaluation"
    assert body["result_id"] == evaluation_id
    assert body["evaluation_id"] == evaluation_id
    assert body["rule_id"] == rule_id
    assert body["rule_revision"] == RULE_REVISION


def test_latest_rule_revision_is_not_authority_and_arbitrary_threshold_fields_are_rejected(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_LATEST"
        _seed_rule_revision(
            session,
            rule_id=rule_id,
            revision=RULE_REVISION,
            operator=RuleOperator.MIN,
        )
        _seed_rule_revision(
            session,
            rule_id=rule_id,
            revision=NEWER_RULE_REVISION,
            operator=RuleOperator.MAX,
        )
        session.commit()

    payload = _payload(
        evaluation_id="API-EVAL-415",
        revision_number=1,
        comparison=compare_rule(
            _requirement(rule_id=rule_id, revision=RULE_REVISION),
            Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            applicability_result=_selected_resolution(
                rule_id=rule_id, revision=RULE_REVISION
            ),
            unit_context=_unit_context(),
        ),
        observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
        unit_context=_unit_context(),
        decision_reason="older exact revision must remain valid",
    )

    response = _post(
        client,
        payload,
        token=_token("admin@spotwelding.example"),
        key="api-eval-415",
    )
    assert response.status_code == 200
    assert response.json()["rule_revision"] == RULE_REVISION

    rejected = client.post(
        "/api/v1/rule-evaluations",
        json={
            **payload.model_dump(mode="json"),
            "comparison": {
                **payload.comparison.model_dump(mode="json"),
                "min_value": 999.0,
            },
        },
        headers={
            "Authorization": f"Bearer {_token('admin@spotwelding.example')}",
            "Idempotency-Key": "api-eval-415b",
        },
    )
    assert rejected.status_code == 422


def test_governed_conversion_provenance_is_preserved(client: TestClient) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_CONVERSION"
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    requirement = _requirement(rule_id=rule_id)
    resolution = _selected_resolution(rule_id=rule_id)
    observation = Observation("synthetic_parameter", 5.0, "secondary_unit")
    comparison = compare_rule(
        requirement,
        observation,
        applicability_result=resolution,
        unit_catalog=_unit_catalog(),
    )
    payload = _payload(
        evaluation_id="API-EVAL-416",
        revision_number=1,
        comparison=comparison,
        observation=observation,
        unit_catalog=_unit_catalog(),
        decision_reason="governed conversion provenance",
    )

    response = _post(
        client,
        payload,
        token=_token("admin@spotwelding.example"),
        key="api-eval-416",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_outcome"] == "SATISFIED"

    with SessionLocal() as session:
        persisted = _persisted_evaluation(session, evaluation_id="API-EVAL-416", revision_number=1)
        assert persisted is not None
        assert persisted.outcome == RuleComparisonOutcome.SATISFIED
        assert persisted.unit_policy_snapshot["kind"] == "unit_catalog"
        assert persisted.unit_policy_snapshot["conversions"][0]["from_unit"] == "secondary_unit"
        assert persisted.unit_policy_snapshot["conversions"][0]["to_unit"] == "synthetic_unit"
        assert persisted.unit_policy_snapshot["conversions"][0]["factor"] == 2.0
        assert persisted.result_snapshot["conversion_provenance"]["conversion_occurred"] is True
        assert persisted.result_snapshot["conversion_provenance"]["factor"] == 2.0


def test_persistence_does_not_recompute_or_use_legacy_authority(
    client: TestClient,
    monkeypatch,
) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_NORECOMP"
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    payload = _payload(
        evaluation_id="API-EVAL-417",
        revision_number=1,
        comparison=compare_rule(
            _requirement(rule_id=rule_id),
            Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            applicability_result=_selected_resolution(rule_id=rule_id),
            unit_context=_unit_context(),
        ),
        observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
        unit_context=_unit_context(),
        decision_reason="no recomputation",
    )

    import app.domain.rule_applicability as rule_applicability_module
    import app.domain.rule_evaluation as rule_evaluation_module

    monkeypatch.setattr(
        rule_applicability_module,
        "resolve_governed_applicability",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("resolve_governed_applicability must not be called")
        ),
    )
    monkeypatch.setattr(
        rule_evaluation_module,
        "compare_rule",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("compare_rule must not be called")
        ),
    )

    response = _post(
        client,
        payload,
        token=_token("admin@spotwelding.example"),
        key="api-eval-417",
    )
    assert response.status_code == 200
    assert response.json()["decision_outcome"] == "SATISFIED"
