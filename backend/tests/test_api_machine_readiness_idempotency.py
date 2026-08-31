from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.machine_readiness_service import MachineReadinessService
from app.db.session import SessionLocal
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from fastapi.testclient import TestClient
from test_api_machine_readiness import (
    _payload,
    _post,
    _ready_case,
    _reset_database,
    _token,
    _user,
)


def _request_hash(*, payload, actor_user_id: int) -> CanonicalRequestHash:
    canonical = json.dumps(
        {**payload.model_dump(mode="json"), "actor_user_id": actor_user_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    return CanonicalRequestHash(
        value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="governed-api-v1",
    )


def test_machine_readiness_idempotency_replay_conflict_and_in_progress(
    client: TestClient,
) -> None:
    _reset_database()
    with SessionLocal() as session:
        actor = _user(
            session,
            email="mrc-idempotency@example.com",
            full_name="Machine Readiness Actor",
            role="Process Engineer",
        )
        actor_id = actor.id
        actor_email = actor.email
        session.commit()
        result, checks = _ready_case(session)

    payload = _payload(
        assessment_id="assessment-idempotency",
        revision_number=1,
        result=result,
        checks=checks,
        decision_reason="idempotency body",
    )
    first = _post(
        client,
        payload,
        token=_token(actor_email),
        key="mrc-idempotency-key",
    )
    assert first.status_code == 200

    replay = _post(
        client,
        payload,
        token=_token(actor_email),
        key="mrc-idempotency-key",
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()

    conflict = _post(
        client,
        payload.model_copy(update={"decision_reason": "changed body"}),
        token=_token(actor_email),
        key="mrc-idempotency-key",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_CONFLICT"

    conflict_payload = _payload(
        assessment_id="assessment-in-progress",
        revision_number=1,
        result=result,
        checks=checks,
        decision_reason="in progress body",
    )
    identity = CommandIdentity(
        command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
        command_scope="assessment-in-progress",
        idempotency_key="mrc-in-progress-key",
    )
    request_hash = _request_hash(
        payload=conflict_payload,
        actor_user_id=actor_id,
    )
    with SessionLocal() as session, GovernedUnitOfWork(session) as unit_of_work:
        unit_of_work.idempotency_repository.add_reserved(
            receipt_id="reserved-mrc-receipt",
            identity=identity,
            request_hash=request_hash,
            correlation_id="reserved-mrc-correlation",
            schema_version="machine-readiness-api-v1",
            software_version="backend-api-v1",
            created_at=datetime.now(timezone.utc),
        )
        unit_of_work.commit()

    in_progress = _post(
        client,
        conflict_payload,
        token=_token(actor_email),
        key="mrc-in-progress-key",
    )
    assert in_progress.status_code == 409
    assert in_progress.json()["error_code"] == "IDEMPOTENCY_IN_PROGRESS"
