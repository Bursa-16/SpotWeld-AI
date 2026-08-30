from __future__ import annotations

from app.application import audit_service as legacy_audit_service
from app.application.governed_audit_service import GovernedAuditService
from app.db.session import SessionLocal
from app.domain.rule_evaluation import Observation, compare_rule
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.rule_evaluation import RuleEvaluation
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_api_rule_evaluation import (
    _payload,
    _post,
    _requirement,
    _seed_rule_revision,
    _selected_resolution,
    _token,
    _unit_context,
    _user,
)


def test_successful_evaluation_commits_evaluation_audit_and_receipt_atomically(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_ATOMIC_SUCCESS"
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    email = "atomic-success@example.com"
    with SessionLocal() as session:
        _user(session, email=email, full_name="Atomic Success", role="Process Engineer")
        session.commit()

    payload = _payload(
        evaluation_id="API-EVAL-ATOMIC-1",
        revision_number=1,
        comparison=compare_rule(
            _requirement(rule_id=rule_id),
            Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            applicability_result=_selected_resolution(rule_id=rule_id),
            unit_context=_unit_context(),
        ),
        observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
        unit_context=_unit_context(),
        decision_reason="atomic success",
    )

    response = _post(
        client,
        payload,
        token=_token(email),
        key="api-eval-atomic-success-key",
    )
    assert response.status_code == 200
    assert response.json()["decision_outcome"] == "SATISFIED"

    with SessionLocal() as session:
        persisted = session.scalar(
            select(func.count(RuleEvaluation.id)).where(
                RuleEvaluation.evaluation_id == "API-EVAL-ATOMIC-1"
            )
        )
        audit = session.scalar(
            select(func.count(GovernedAuditEvent.id)).where(
                GovernedAuditEvent.correlation_id == "rule-evaluation:API-EVAL-ATOMIC-1"
            )
        )
        receipt = session.scalar(
            select(func.count(GovernedCommandReceipt.id)).where(
                GovernedCommandReceipt.command_scope == "API-EVAL-ATOMIC-1"
            )
        )
    assert persisted == 1
    assert audit == 1
    assert receipt == 1


def test_atomic_rollback_on_injected_audit_failure(
    client: TestClient,
    monkeypatch,
) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_ATOMIC_FAILURE"
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    email = "atomic-failure@example.com"
    with SessionLocal() as session:
        _user(session, email=email, full_name="Atomic Failure", role="Process Engineer")
        session.commit()

    payload = _payload(
        evaluation_id="API-EVAL-ATOMIC-2",
        revision_number=1,
        comparison=compare_rule(
            _requirement(rule_id=rule_id),
            Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            applicability_result=_selected_resolution(rule_id=rule_id),
            unit_context=_unit_context(),
        ),
        observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
        unit_context=_unit_context(),
        decision_reason="atomic failure",
    )

    monkeypatch.setattr(
        GovernedAuditService,
        "record_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )

    response = _post(
        client,
        payload,
        token=_token(email),
        key="api-eval-atomic-failure-key",
    )
    assert response.status_code == 500
    assert response.json()["error_code"] == "GOVERNED_TRANSACTION_FAILED"

    with SessionLocal() as session:
        assert (
            session.scalar(
                select(func.count(RuleEvaluation.id)).where(
                    RuleEvaluation.evaluation_id == "API-EVAL-ATOMIC-2"
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(GovernedAuditEvent.id)).where(
                    GovernedAuditEvent.correlation_id == "rule-evaluation:API-EVAL-ATOMIC-2"
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(GovernedCommandReceipt.id)).where(
                    GovernedCommandReceipt.command_scope == "API-EVAL-ATOMIC-2"
                )
            )
            == 0
        )


def test_legacy_write_audit_is_not_used(
    client: TestClient,
    monkeypatch,
) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_ATOMIC_LEGACY"
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    email = "legacy-audit@example.com"
    with SessionLocal() as session:
        _user(session, email=email, full_name="Legacy Audit", role="Process Engineer")
        session.commit()

    payload = _payload(
        evaluation_id="API-EVAL-ATOMIC-3",
        revision_number=1,
        comparison=compare_rule(
            _requirement(rule_id=rule_id),
            Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            applicability_result=_selected_resolution(rule_id=rule_id),
            unit_context=_unit_context(),
        ),
        observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
        unit_context=_unit_context(),
        decision_reason="legacy audit not used",
    )

    monkeypatch.setattr(
        legacy_audit_service,
        "write_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy audit must not be used")),
    )

    response = _post(
        client,
        payload,
        token=_token(email),
        key="api-eval-atomic-legacy-key",
    )
    assert response.status_code == 200
    assert response.json()["decision_outcome"] == "SATISFIED"
