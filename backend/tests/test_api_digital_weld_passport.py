from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.application import audit_service as legacy_audit_service
from app.application.governed_audit_service import GovernedAuditService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.domain.readiness import ReadinessState
from app.models.digital_weld_passport import (
    DigitalWeldPassport,
    DigitalWeldPassportLifecycleEvent,
    DigitalWeldPassportRevision,
)
from app.models.entities import User
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.machine_readiness import (
    MachineReadinessAssessment,
    MachineReadinessAssessmentRevision,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

PAST = datetime(2036, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
COMMAND_NAMESPACE = "dwp.passport"


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


def _mrc_snapshot(
    *,
    assessment_id: str,
    revision_number: int = 1,
    passport_id: str = "passport-1",
    scope_snapshot: dict[str, str] | None = None,
    state: ReadinessState = ReadinessState.NOT_READY,
) -> dict[str, object]:
    resolved_scope_snapshot = scope_snapshot or _scope()
    return {
        "assessment_id": assessment_id,
        "revision_number": revision_number,
        "decision_time": datetime(2036, 1, 2, 3, 4, 6, tzinfo=timezone.utc)
        .replace(tzinfo=None)
        .isoformat(),
        "state": state.value,
        "context_snapshot": {
            "passport_id": passport_id,
            "scope_snapshot": resolved_scope_snapshot,
        },
        "prerequisites_snapshot": {"validated_applicable_basis_count": 1},
        "result_snapshot": {"state": state.value},
        "authority_snapshot": {"scope_snapshot": resolved_scope_snapshot},
        "validated_applicable_basis_count": 1,
        "supersedes_assessment_revision_id": None,
        "created_by_user_id": None,
        "created_by_actor_id": "synthetic-mrc-actor",
        "schema_version": "mrc-test-v1",
        "canonicalization_version": "mrc-canonical-v1",
        "hash_algorithm": "sha256",
        "content_hash": f"{assessment_id}:{revision_number}",
        "software_version": "test-build",
        "correlation_id": f"{assessment_id}-correlation",
    }


def _seed_mrc(
    session: Session,
    *,
    assessment_id: str,
    revision_number: int = 1,
    passport_id: str = "passport-1",
    scope_snapshot: dict[str, str] | None = None,
    state: ReadinessState = ReadinessState.NOT_READY,
) -> dict[str, object]:
    resolved_scope_snapshot = scope_snapshot or _scope()
    assessment = MachineReadinessAssessment(
        assessment_id=assessment_id,
        created_by_user_id=None,
        created_by_actor_id="synthetic-mrc-actor",
    )
    session.add(assessment)
    session.flush()
    revision = MachineReadinessAssessmentRevision(
        assessment_id=assessment.assessment_id,
        revision_number=revision_number,
        decision_time=datetime(2036, 1, 2, 3, 4, 6, tzinfo=timezone.utc).replace(
            tzinfo=None
        ),
        state=state,
        context_snapshot={
            "passport_id": passport_id,
            "scope_snapshot": resolved_scope_snapshot,
        },
        prerequisites_snapshot={"validated_applicable_basis_count": 1},
        result_snapshot={"state": state.value},
        authority_snapshot={"scope_snapshot": resolved_scope_snapshot},
        validated_applicable_basis_count=1,
        created_by_user_id=None,
        created_by_actor_id="synthetic-mrc-actor",
        schema_version="mrc-test-v1",
        canonicalization_version="mrc-canonical-v1",
        hash_algorithm="sha256",
        content_hash=f"{assessment_id}:{revision_number}",
        software_version="test-build",
        correlation_id=f"{assessment_id}-correlation",
        supersedes_assessment_revision_id=None,
    )
    session.add(revision)
    session.flush()
    return _mrc_snapshot(
        assessment_id=assessment_id,
        revision_number=revision_number,
        passport_id=passport_id,
        scope_snapshot=resolved_scope_snapshot,
        state=state,
    )


def _passport_payload(
    *,
    passport_id: str,
    revision_number: int,
    mrc_snapshot: dict[str, object],
    scope: dict[str, str],
    decision_reason: str = "passport draft",
) -> dict[str, object]:
    return {
        "passport_id": passport_id,
        "revision_number": revision_number,
        "context_snapshot": {
            "passport_id": passport_id,
            "weld_identity": {"project": "P1", "site": "S1", "machine": "M1"},
            "scope_snapshot": scope,
        },
        "provenance_snapshot": {"rule_evaluations": []},
        "authority_scope": scope,
        "mrc_snapshot": mrc_snapshot,
        "supersedes_revision_id": None if revision_number == 1 else 1,
        "decision_reason": decision_reason,
    }


def _governed_counts(session: Session, passport_id: str) -> tuple[int, int, int, int, int]:
    return (
        session.scalar(
            select(func.count(DigitalWeldPassport.id)).where(
                DigitalWeldPassport.passport_id == passport_id
            )
        )
        or 0,
        session.scalar(
            select(func.count(DigitalWeldPassportRevision.id)).where(
                DigitalWeldPassportRevision.passport_id == passport_id
            )
        )
        or 0,
        session.scalar(
            select(func.count(DigitalWeldPassportLifecycleEvent.id))
            .join(
                DigitalWeldPassportRevision,
                DigitalWeldPassportRevision.id
                == DigitalWeldPassportLifecycleEvent.passport_revision_id,
            )
            .where(DigitalWeldPassportRevision.passport_id == passport_id)
        )
        or 0,
        session.scalar(
            select(func.count(GovernedAuditEvent.id)).where(
                GovernedAuditEvent.correlation_id.like(f"dwp:{passport_id}%")
            )
        )
        or 0,
        session.scalar(
            select(func.count(GovernedCommandReceipt.id)).where(
                GovernedCommandReceipt.correlation_id.like(f"dwp:{passport_id}%")
            )
        )
        or 0,
    )


def _post(
    client: TestClient,
    payload: dict[str, object],
    *,
    token: str | None,
    key: str,
) -> object:
    headers = {"Idempotency-Key": key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/api/v1/digital-weld-passports", json=payload, headers=headers)


def test_create_draft_revision_and_get_exact_revision(client: TestClient) -> None:
    with SessionLocal() as session:
        actor = _user(
            session,
            email="dwp-author@example.com",
            full_name="DWP Author",
            role="Process Engineer",
        )
        scope = _scope()
        mrc_snapshot = _seed_mrc(
            session,
            assessment_id="assessment-dwp-1",
            passport_id="passport-dwp-1",
            scope_snapshot=scope,
            state=ReadinessState.NOT_READY,
        )
        session.commit()
        actor_email = actor.email

    first_payload = _passport_payload(
        passport_id="passport-dwp-1",
        revision_number=1,
        mrc_snapshot=mrc_snapshot,
        scope=scope,
        decision_reason="draft revision 1",
    )
    first_response = _post(
        client,
        first_payload,
        token=_token(actor_email),
        key="dwp-draft-1",
    )
    assert first_response.status_code == 200
    first_body = first_response.json()
    assert first_body["decision_outcome"] == "DRAFT"
    assert first_body["state"] == "DRAFT"
    assert first_body["passport_id"] == "passport-dwp-1"
    assert first_body["revision_number"] == 1
    assert first_body["mrc_snapshot"]["state"] == "NOT_READY"

    with SessionLocal() as session:
        revision = session.scalar(
            select(DigitalWeldPassportRevision).where(
                DigitalWeldPassportRevision.passport_id == "passport-dwp-1",
                DigitalWeldPassportRevision.revision_number == 1,
            )
        )
        assert revision is not None
        first_revision_id = revision.id

    second_payload = _passport_payload(
        passport_id="passport-dwp-1",
        revision_number=2,
        mrc_snapshot=mrc_snapshot,
        scope=scope,
        decision_reason="draft revision 2",
    )
    second_payload["supersedes_revision_id"] = first_revision_id
    second_response = _post(
        client,
        second_payload,
        token=_token(actor_email),
        key="dwp-draft-2",
    )
    assert second_response.status_code == 200
    second_body = second_response.json()
    assert second_body["decision_outcome"] == "DRAFT"
    assert second_body["revision_number"] == 2

    get_first = client.get(
        "/api/v1/digital-weld-passports/passport-dwp-1/revisions/1",
        headers={"Authorization": f"Bearer {_token(actor_email)}"},
    )
    assert get_first.status_code == 200
    assert get_first.json()["revision_number"] == 1
    assert get_first.json()["state"] == "DRAFT"

    get_second = client.get(
        "/api/v1/digital-weld-passports/passport-dwp-1/revisions/2",
        headers={"Authorization": f"Bearer {_token(actor_email)}"},
    )
    assert get_second.status_code == 200
    assert get_second.json()["revision_number"] == 2
    assert get_second.json()["state"] == "DRAFT"


def test_unauthenticated_and_inactive_users_are_rejected(client: TestClient) -> None:
    unauthenticated = _post(
        client,
        _passport_payload(
            passport_id="passport-dwp-401",
            revision_number=1,
            mrc_snapshot=_mrc_snapshot(
                assessment_id="assessment-dwp-401",
                passport_id="passport-dwp-401",
                scope_snapshot=_scope(),
            ),
            scope=_scope(),
        ),
        token=None,
        key="dwp-401-key",
    )
    assert unauthenticated.status_code == 401

    with SessionLocal() as session:
        inactive = _user(
            session,
            email="inactive-dwp@example.com",
            full_name="Inactive DWP User",
            role="Process Engineer",
            is_active=False,
        )
        session.commit()

    inactive_response = _post(
        client,
        _passport_payload(
            passport_id="passport-dwp-402",
            revision_number=1,
            mrc_snapshot=_mrc_snapshot(
                assessment_id="assessment-dwp-402",
                passport_id="passport-dwp-402",
                scope_snapshot=_scope(),
            ),
            scope=_scope(),
        ),
        token=_token(inactive.email),
        key="dwp-402-key",
    )
    assert inactive_response.status_code == 401


def test_body_actor_spoofing_is_rejected(client: TestClient) -> None:
    with SessionLocal() as session:
        actor = _user(
            session,
            email="spoof-dwp@example.com",
            full_name="Spoof DWP User",
            role="Process Engineer",
        )
        session.commit()

    response = client.post(
        "/api/v1/digital-weld-passports",
        json={
            **_passport_payload(
                passport_id="passport-dwp-spoof",
                revision_number=1,
                mrc_snapshot=_mrc_snapshot(
                    assessment_id="assessment-dwp-spoof",
                    passport_id="passport-dwp-spoof",
                    scope_snapshot=_scope(),
                ),
                scope=_scope(),
            ),
            "actor_user_id": 999,
        },
        headers={
            "Authorization": f"Bearer {_token(actor.email)}",
            "Idempotency-Key": "dwp-spoof-key",
        },
    )
    assert response.status_code == 422


def test_system_admin_wildcard_alone_does_not_authorize_governed_draft_creation(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        admin = _user(
            session,
            email="admin-dwp@example.com",
            full_name="System Administrator",
            role="System Admin",
        )
        session.commit()

    response = _post(
        client,
        _passport_payload(
            passport_id="passport-dwp-admin",
            revision_number=1,
            mrc_snapshot=_mrc_snapshot(
                assessment_id="assessment-dwp-admin",
                passport_id="passport-dwp-admin",
                scope_snapshot=_scope(project="governed-project"),
            ),
            scope=_scope(project="other-project"),
        ),
        token=_token(admin.email),
        key="dwp-admin-key",
    )
    assert response.status_code == 200
    assert response.json()["decision_outcome"] == "DENIED"


def test_same_idempotency_key_same_body_replays_and_preserves_counts(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        actor = _user(
            session,
            email="dwp-idem@example.com",
            full_name="DWP Idempotency",
            role="Process Engineer",
        )
        scope = _scope()
        mrc_snapshot = _seed_mrc(
            session,
            assessment_id="assessment-dwp-idem",
            passport_id="passport-dwp-idem",
            scope_snapshot=scope,
        )
        session.commit()

    payload = _passport_payload(
        passport_id="passport-dwp-idem",
        revision_number=1,
        mrc_snapshot=mrc_snapshot,
        scope=scope,
        decision_reason="idempotent draft",
    )
    first = _post(client, payload, token=_token(actor.email), key="dwp-idem-key")
    assert first.status_code == 200
    before_counts = None
    with SessionLocal() as session:
        before_counts = _governed_counts(session, "passport-dwp-idem")

    replay = _post(client, payload, token=_token(actor.email), key="dwp-idem-key")
    assert replay.status_code == 200
    assert replay.json() == first.json()

    with SessionLocal() as session:
        after_counts = _governed_counts(session, "passport-dwp-idem")
    assert after_counts == before_counts


def test_same_idempotency_key_different_body_conflicts(client: TestClient) -> None:
    with SessionLocal() as session:
        actor = _user(
            session,
            email="dwp-conflict@example.com",
            full_name="DWP Conflict",
            role="Process Engineer",
        )
        scope = _scope()
        mrc_snapshot = _seed_mrc(
            session,
            assessment_id="assessment-dwp-conflict",
            passport_id="passport-dwp-conflict",
            scope_snapshot=scope,
        )
        session.commit()

    payload = _passport_payload(
        passport_id="passport-dwp-conflict",
        revision_number=1,
        mrc_snapshot=mrc_snapshot,
        scope=scope,
        decision_reason="conflict one",
    )
    first = _post(client, payload, token=_token(actor.email), key="dwp-conflict-key")
    assert first.status_code == 200

    conflict = _post(
        client,
        {**payload, "decision_reason": "conflict two"},
        token=_token(actor.email),
        key="dwp-conflict-key",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_CONFLICT"


def test_in_progress_returns_structured_error(client: TestClient) -> None:
    with SessionLocal() as session:
        actor = _user(
            session,
            email="dwp-progress@example.com",
            full_name="DWP In Progress",
            role="Process Engineer",
        )
        scope = _scope()
        mrc_snapshot = _seed_mrc(
            session,
            assessment_id="assessment-dwp-progress",
            passport_id="passport-dwp-progress",
            scope_snapshot=scope,
        )
        request_hash = CanonicalRequestHash(
            value=hashlib.sha256(
                json.dumps(
                    {
                        **_passport_payload(
                            passport_id="passport-dwp-progress",
                            revision_number=1,
                            mrc_snapshot=mrc_snapshot,
                            scope=scope,
                        ),
                        "actor_user_id": actor.id,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            hash_algorithm="sha256",
            canonicalization_version="governed-api-v1",
        )
        identity = CommandIdentity(
            command_namespace=COMMAND_NAMESPACE,
            command_scope="passport-dwp-progress",
            idempotency_key="dwp-progress-key",
        )
        session.commit()
        with GovernedUnitOfWork(session) as unit_of_work:
            unit_of_work.idempotency_repository.add_reserved(
                receipt_id="reserved-dwp-progress",
                identity=identity,
                request_hash=request_hash,
                correlation_id="reserved-dwp-progress-correlation",
                schema_version="dwp-api-v1",
                software_version="backend-api-v1",
                created_at=datetime.now(timezone.utc),
            )
            unit_of_work.commit()

    response = _post(
        client,
        _passport_payload(
            passport_id="passport-dwp-progress",
            revision_number=1,
            mrc_snapshot=mrc_snapshot,
            scope=scope,
        ),
        token=_token(actor.email),
        key="dwp-progress-key",
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "IDEMPOTENCY_IN_PROGRESS"


def test_atomic_rollback_on_injected_audit_failure(client: TestClient, monkeypatch) -> None:
    with SessionLocal() as session:
        actor = _user(
            session,
            email="dwp-atomic@example.com",
            full_name="DWP Atomic",
            role="Process Engineer",
        )
        scope = _scope()
        mrc_snapshot = _seed_mrc(
            session,
            assessment_id="assessment-dwp-atomic",
            passport_id="passport-dwp-atomic",
            scope_snapshot=scope,
        )
        session.commit()

    monkeypatch.setattr(
        GovernedAuditService,
        "record_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )

    response = _post(
        client,
        _passport_payload(
            passport_id="passport-dwp-atomic",
            revision_number=1,
            mrc_snapshot=mrc_snapshot,
            scope=scope,
            decision_reason="atomic rollback",
        ),
        token=_token(actor.email),
        key="dwp-atomic-key",
    )
    assert response.status_code == 500
    assert response.json()["error_code"] == "GOVERNED_TRANSACTION_FAILED"

    with SessionLocal() as session:
        counts = _governed_counts(session, "passport-dwp-atomic")
        assert counts == (0, 0, 0, 0, 0)


def test_legacy_write_audit_is_not_used(client: TestClient, monkeypatch) -> None:
    with SessionLocal() as session:
        actor = _user(
            session,
            email="dwp-legacy-audit@example.com",
            full_name="DWP Legacy Audit",
            role="Process Engineer",
        )
        scope = _scope()
        mrc_snapshot = _seed_mrc(
            session,
            assessment_id="assessment-dwp-legacy",
            passport_id="passport-dwp-legacy",
            scope_snapshot=scope,
        )
        session.commit()

    monkeypatch.setattr(
        legacy_audit_service,
        "write_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy audit must not be used")
        ),
    )

    response = _post(
        client,
        _passport_payload(
            passport_id="passport-dwp-legacy",
            revision_number=1,
            mrc_snapshot=mrc_snapshot,
            scope=scope,
            decision_reason="legacy audit guard",
        ),
        token=_token(actor.email),
        key="dwp-legacy-key",
    )
    assert response.status_code == 200
    assert response.json()["decision_outcome"] == "DRAFT"
