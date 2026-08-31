from __future__ import annotations

import pytest
from app.application.machine_readiness_service import MachineReadinessService
from app.core.security import create_access_token, hash_password
from app.db.session import Base, SessionLocal
from app.domain.governance_types import ContentVersionMetadata
from app.domain.readiness import CheckCondition, ReadinessState
from app.models.entities import User
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.machine_readiness import (
    MachineReadinessAssessment,
    MachineReadinessAssessmentRevision,
    MachineReadinessCheckResult,
)
from app.schemas.governed_api import (
    MachineReadinessCheckDefinitionSnapshot,
    MachineReadinessCheckTraceSnapshot,
    MachineReadinessEvaluationSnapshot,
    MachineReadinessPersistenceRequest,
    MachineReadinessResultSnapshot,
    RuleEvaluationApplicabilityCandidateSnapshot,
    RuleEvaluationApplicabilityResolutionSnapshot,
    RuleEvaluationApplicabilityResultSnapshot,
    RuleEvaluationComparisonSnapshot,
    RuleEvaluationContentVersionMetadata,
    RuleEvaluationConversionProvenanceSnapshot,
)
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from test_machine_readiness_persistence import (
    _engineering_review_case,
    _manual_review_case,
    _not_evaluated_case,
    _not_ready_case,
    _ready_case,
)


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


def _reset_database() -> None:
    with SessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(delete(table))
        session.commit()
        if not session.scalar(
            select(User).where(User.email == "admin@spotwelding.example")
        ):
            session.add(
                User(
                    email="admin@spotwelding.example",
                    full_name="System Administrator",
                    password_hash=hash_password("ChangeMe123!"),
                    role="System Admin",
                    is_active=True,
                )
            )
            session.commit()


def _scope() -> dict[str, str]:
    return {
        "customer": "customer-a",
        "project": "project-a",
        "site": "site-a",
        "machine": "machine-a",
    }


def _result_snapshot(result) -> MachineReadinessResultSnapshot:
    return MachineReadinessResultSnapshot(
        state=result.state,
        reasons=list(result.reasons),
        prerequisites=[
            {"label": label, "satisfied": satisfied}
            for label, satisfied in result.prerequisites
        ],
        context=result.context.as_mapping(),
        decision_time=result.decision_time,
        validated_applicable_basis_count=result.validated_applicable_basis_count,
        checks=[_check_trace_snapshot(check) for check in result.checks],
    )


def _check_snapshot(check) -> MachineReadinessCheckDefinitionSnapshot:
    return MachineReadinessCheckDefinitionSnapshot(
        check_id=check.check_id,
        required=check.required,
        description=check.description,
        evaluations=[_evaluation_snapshot(evaluation) for evaluation in check.evaluations],
    )


def _content_version(version: ContentVersionMetadata | None):
    if version is None:
        return None
    return RuleEvaluationContentVersionMetadata(
        schema_version=version.schema_version,
        canonicalization_version=version.canonicalization_version,
        hash_algorithm=version.hash_algorithm,
        content_hash=version.content_hash,
        software_version=version.software_version,
    )


def _applicability_result_snapshot(result):
    return RuleEvaluationApplicabilityResultSnapshot(
        outcome=result.outcome,
        reason=result.reason,
        matched_keys=list(result.matched_keys),
        unsatisfied_keys=list(result.unsatisfied_keys),
        missing_keys=list(result.missing_keys),
    )


def _applicability_resolution_snapshot(resolution):
    return RuleEvaluationApplicabilityResolutionSnapshot(
        outcome=resolution.outcome,
        reason=resolution.reason,
        decision_time=resolution.decision_time,
        context=resolution.context.as_mapping(),
        candidates=[
            RuleEvaluationApplicabilityCandidateSnapshot(
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
            for candidate in resolution.candidates
        ],
        selected_candidate_id=resolution.selected_candidate_id,
        selected_rule_id=resolution.selected_rule_id,
        selected_revision=resolution.selected_revision,
        selected_specificity=resolution.selected_specificity,
        conflict_candidate_ids=list(resolution.conflict_candidate_ids),
    )


def _conversion_provenance_snapshot(provenance):
    return RuleEvaluationConversionProvenanceSnapshot(
        conversion_occurred=provenance.conversion_occurred,
        original_value=provenance.original_value,
        original_unit=provenance.original_unit,
        comparison_value=provenance.comparison_value,
        target_unit=provenance.target_unit,
        factor=provenance.factor,
        policy_version=_content_version(provenance.policy_version),
        rounding_policy=provenance.rounding_policy,
    )


def _evaluation_snapshot(evaluation) -> MachineReadinessEvaluationSnapshot:
    comparison = evaluation.comparison
    return MachineReadinessEvaluationSnapshot(
        evaluation_id=evaluation.evaluation_id,
        revision_number=evaluation.revision_number,
        comparison=RuleEvaluationComparisonSnapshot(
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
        ),
    )


def _check_trace_snapshot(check) -> MachineReadinessCheckTraceSnapshot:
    return MachineReadinessCheckTraceSnapshot(
        check_id=check.check_id,
        required=check.required,
        description=None,
        evaluations=[_evaluation_snapshot(evaluation) for evaluation in check.evaluations],
        condition=CheckCondition(check.condition),
        reason=check.reason,
    )


def _payload(
    *,
    assessment_id: str,
    revision_number: int,
    result,
    checks,
    supersedes_assessment_revision_id: int | None = None,
    decision_reason: str = "governed machine-readiness persistence",
) -> MachineReadinessPersistenceRequest:
    return MachineReadinessPersistenceRequest(
        assessment_id=assessment_id,
        revision_number=revision_number,
        result=_result_snapshot(result),
        checks=[_check_snapshot(check) for check in checks],
        supersedes_assessment_revision_id=supersedes_assessment_revision_id,
        decision_reason=decision_reason,
    )


def _post(
    client: TestClient,
    payload: MachineReadinessPersistenceRequest,
    *,
    token: str,
    key: str,
):
    return client.post(
        "/api/v1/machine-readiness-assessments",
        json=payload.model_dump(mode="json"),
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": key,
        },
    )


def _counts(session: Session) -> tuple[int, int, int, int, int]:
    return (
        session.scalar(select(func.count(MachineReadinessAssessment.assessment_id))) or 0,
        session.scalar(select(func.count(MachineReadinessAssessmentRevision.id))) or 0,
        session.scalar(select(func.count(MachineReadinessCheckResult.id))) or 0,
        session.scalar(select(func.count(GovernedAuditEvent.id))) or 0,
        session.scalar(select(func.count(GovernedCommandReceipt.id))) or 0,
    )


@pytest.mark.parametrize(
    "builder, expected_state",
    [
        (_ready_case, ReadinessState.READY),
        (_not_ready_case, ReadinessState.NOT_READY),
        (_engineering_review_case, ReadinessState.ENGINEERING_REVIEW_REQUIRED),
        (_manual_review_case, ReadinessState.MANUAL_REVIEW_REQUIRED),
        (_not_evaluated_case, ReadinessState.NOT_EVALUATED),
    ],
)
def test_machine_readiness_post_returns_explicit_state_and_exact_pins(
    client: TestClient,
    builder,
    expected_state: ReadinessState,
) -> None:
    _reset_database()
    with SessionLocal() as session:
        actor = _user(
            session,
            email=f"mrc-{expected_state.value.lower()}@example.com",
            full_name="Machine Readiness Actor",
            role="Process Engineer",
        )
        actor_email = actor.email
        session.commit()
        result, checks = builder(session)

    payload = _payload(
        assessment_id=f"assessment-{expected_state.value.lower()}",
        revision_number=1,
        result=result,
        checks=checks,
        decision_reason=f"{expected_state.value.lower()} assessment",
    )

    with SessionLocal() as session:
        before = _counts(session)

    response = _post(
        client,
        payload,
        token=_token(actor_email),
        key=f"mrc-{expected_state.value.lower()}-key",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_outcome"] == expected_state.value
    assert body["result_type"] == "machine_readiness"
    assert body["result_id"] == payload.assessment_id
    assert body["result_revision"] == "1"
    assert body["assessment_id"] == payload.assessment_id
    assert body["revision_number"] == 1
    assert body["command_namespace"] == MachineReadinessService.COMMAND_NAMESPACE
    assert body["command_scope"] == payload.assessment_id
    assert body["result"]["state"] == expected_state.value
    assert body["result"]["validated_applicable_basis_count"] == result.validated_applicable_basis_count
    assert body["result"]["context"] == _scope()
    assert len(body["result"]["checks"]) == len(checks)
    assert len(body["checks"]) == len(checks)

    with SessionLocal() as session:
        after = _counts(session)
        revision = session.scalar(
            select(MachineReadinessAssessmentRevision).where(
                MachineReadinessAssessmentRevision.assessment_id == payload.assessment_id,
                MachineReadinessAssessmentRevision.revision_number == 1,
            )
        )
        assert revision is not None
        assert revision.state is expected_state
    assert after == (before[0] + 1, before[1] + 1, before[2] + len(checks), before[3] + 1, before[4] + 1)


def test_get_machine_readiness_revision_returns_exact_revision_and_does_not_recompute(
    client: TestClient,
    monkeypatch,
) -> None:
    _reset_database()
    with SessionLocal() as session:
        actor = _user(
            session,
            email="mrc-get@example.com",
            full_name="Machine Readiness Actor",
            role="Process Engineer",
        )
        actor_email = actor.email
        session.commit()
        result, checks = _ready_case(session)

    payload = _payload(
        assessment_id="assessment-get",
        revision_number=1,
        result=result,
        checks=checks,
        decision_reason="get exact revision",
    )
    post = _post(
        client,
        payload,
        token=_token(actor_email),
        key="mrc-get-key",
    )
    assert post.status_code == 200

    import app.domain.readiness as readiness_module

    monkeypatch.setattr(
        readiness_module,
        "evaluate_machine_readiness",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("readiness evaluation must not run during GET")
        ),
    )

    response = client.get(
        "/api/v1/machine-readiness-assessments/assessment-get/revisions/1",
        headers={"Authorization": f"Bearer {_token(actor_email)}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assessment_id"] == "assessment-get"
    assert body["revision_number"] == 1
    assert body["decision_outcome"] == "READY"
    assert body["result_type"] == "machine_readiness"
    assert body["result"]["state"] == "READY"
    assert body["result"]["checks"][0]["condition"] in {
        "PASSED",
        "NOT_APPLICABLE",
        "NOT_APPLICABLE_VERSION",
    }
    assert body["checks"][0]["check_id"] in {check.check_id for check in checks}


def test_machine_readiness_denial_is_explicit_and_audited(
    client: TestClient,
) -> None:
    _reset_database()
    with SessionLocal() as session:
        actor = _user(
            session,
            email="mrc-denial@example.com",
            full_name="Machine Readiness Actor",
            role="Process Engineer",
        )
        actor_email = actor.email
        session.commit()
        result, checks = _ready_case(session)

    payload = _payload(
        assessment_id="assessment-denial",
        revision_number=1,
        result=result,
        checks=checks[:-1],
        decision_reason="denial body",
    )
    with SessionLocal() as session:
        before = _counts(session)

    response = _post(
        client,
        payload,
        token=_token(actor_email),
        key="mrc-denial-key",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_outcome"] == "DENIED"
    assert body["result_type"] == "machine_readiness_denial"

    with SessionLocal() as session:
        after = _counts(session)
    assert after[0] == before[0]
    assert after[1] == before[1]
    assert after[2] == before[2]
    assert after[3] == before[3] + 1
    assert after[4] == before[4] + 1


def test_unauthenticated_inactive_and_actor_spoofing_are_rejected(
    client: TestClient,
) -> None:
    _reset_database()
    with SessionLocal() as session:
        actor = _user(
            session,
            email="mrc-auth@example.com",
            full_name="Machine Readiness Actor",
            role="Process Engineer",
        )
        inactive = _user(
            session,
            email="mrc-inactive@example.com",
            full_name="Inactive Actor",
            role="Process Engineer",
            is_active=False,
        )
        actor_email = actor.email
        actor_id = actor.id
        inactive_email = inactive.email
        session.commit()
        result, checks = _ready_case(session)

    payload = _payload(
        assessment_id="assessment-auth",
        revision_number=1,
        result=result,
        checks=checks,
    )

    unauthenticated = client.post(
        "/api/v1/machine-readiness-assessments",
        json=payload.model_dump(mode="json"),
        headers={"Idempotency-Key": "mrc-auth-key"},
    )
    assert unauthenticated.status_code == 401

    inactive_response = _post(
        client,
        payload,
        token=_token(inactive_email),
        key="mrc-inactive-key",
    )
    assert inactive_response.status_code == 401

    spoofed = client.post(
        "/api/v1/machine-readiness-assessments",
        json={
            **payload.model_dump(mode="json"),
            "actor_user_id": actor_id,
        },
        headers={
            "Authorization": f"Bearer {_token(actor_email)}",
            "Idempotency-Key": "mrc-spoof-key",
        },
    )
    assert spoofed.status_code == 422
