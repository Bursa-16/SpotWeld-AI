from __future__ import annotations

from app.application import audit_service as legacy_audit_service
from app.application.governed_audit_service import GovernedAuditService
from app.db.session import SessionLocal
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.machine_readiness import MachineReadinessAssessment
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_api_machine_readiness import (
    _payload,
    _post,
    _ready_case,
    _reset_database,
    _token,
    _user,
)


def test_atomic_rollback_on_injected_audit_failure(
    client: TestClient,
    monkeypatch,
) -> None:
    _reset_database()
    with SessionLocal() as session:
        actor = _user(
            session,
            email="mrc-atomic@example.com",
            full_name="Machine Readiness Actor",
            role="Process Engineer",
        )
        actor_email = actor.email
        session.commit()
        result, checks = _ready_case(session)

    payload = _payload(
        assessment_id="assessment-atomic",
        revision_number=1,
        result=result,
        checks=checks,
        decision_reason="atomic rollback",
    )

    monkeypatch.setattr(
        GovernedAuditService,
        "record_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )

    response = _post(
        client,
        payload,
        token=_token(actor_email),
        key="mrc-atomic-key",
    )
    assert response.status_code == 500
    assert response.json()["error_code"] == "GOVERNED_TRANSACTION_FAILED"

    with SessionLocal() as session:
        assert (
            session.scalar(
                select(func.count(MachineReadinessAssessment.assessment_id)).where(
                    MachineReadinessAssessment.assessment_id == "assessment-atomic"
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(GovernedAuditEvent.id)).where(
                    GovernedAuditEvent.correlation_id
                    == "machine-readiness:assessment-atomic:1"
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(GovernedCommandReceipt.id)).where(
                    GovernedCommandReceipt.correlation_id
                    == "machine-readiness:assessment-atomic:1"
                )
            )
            == 0
        )


def test_legacy_write_audit_is_not_used(
    client: TestClient,
    monkeypatch,
) -> None:
    _reset_database()
    with SessionLocal() as session:
        actor = _user(
            session,
            email="mrc-legacy-audit@example.com",
            full_name="Machine Readiness Actor",
            role="Process Engineer",
        )
        actor_email = actor.email
        session.commit()
        result, checks = _ready_case(session)

    payload = _payload(
        assessment_id="assessment-legacy-audit",
        revision_number=1,
        result=result,
        checks=checks,
    )

    monkeypatch.setattr(
        legacy_audit_service,
        "write_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy audit must not be used")
        ),
    )

    response = _post(
        client,
        payload,
        token=_token(actor_email),
        key="mrc-legacy-audit-key",
    )
    assert response.status_code == 200
    assert response.json()["decision_outcome"] == "READY"
