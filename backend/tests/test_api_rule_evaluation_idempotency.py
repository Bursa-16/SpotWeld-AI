from __future__ import annotations

from app.application.governed_idempotency_service import GovernedIdempotencyService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.db.session import SessionLocal
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
    IdempotencyDisposition,
)
from app.domain.rule_evaluation import Observation, compare_rule
from app.schemas.governed_api import RuleEvaluationPersistenceRequest
from fastapi.testclient import TestClient
from test_api_rule_evaluation import (
    _governed_counts,
    _payload,
    _post,
    _requirement,
    _seed_rule_revision,
    _selected_resolution,
    _token,
    _unit_context,
    _user,
)


def _identity(*, evaluation_id: str, key: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace="registry.rule.evaluation",
        command_scope=evaluation_id,
        idempotency_key=key,
    )


def _request_hash(payload: RuleEvaluationPersistenceRequest, *, actor_user_id: int) -> CanonicalRequestHash:
    request = payload.model_dump(mode="json")
    request["actor_user_id"] = actor_user_id
    import hashlib
    import json

    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
    return CanonicalRequestHash(
        value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="governed-api-v1",
    )


def test_same_idempotency_key_same_body_replays_and_preserves_counts(client: TestClient) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_REPLAY"
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    email = "replay-eval@example.com"
    with SessionLocal() as session:
        _user(session, email=email, full_name="Replay Eval", role="Process Engineer")
        session.commit()

    payload = _payload(
        evaluation_id="API-EVAL-IDEMPOTENT",
        revision_number=1,
        comparison=compare_rule(
            _requirement(rule_id=rule_id),
            Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            applicability_result=_selected_resolution(rule_id=rule_id),
            unit_context=_unit_context(),
        ),
        observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
        unit_context=_unit_context(),
        decision_reason="idempotent evaluation",
    )

    first = _post(
        client,
        payload,
        token=_token(email),
        key="api-eval-idempotent-key",
    )
    assert first.status_code == 200

    with SessionLocal() as session:
        after_first = _governed_counts(session)

    second = _post(
        client,
        payload,
        token=_token(email),
        key="api-eval-idempotent-key",
    )
    assert second.status_code == 200
    assert second.json() == first.json()

    with SessionLocal() as session:
        after_second = _governed_counts(session)

    assert after_second == after_first


def test_same_idempotency_key_different_body_conflicts(client: TestClient) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_CONFLICT"
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    email = "conflict-eval@example.com"
    with SessionLocal() as session:
        _user(session, email=email, full_name="Conflict Eval", role="Process Engineer")
        session.commit()

    first_payload = _payload(
        evaluation_id="API-EVAL-CONFLICT",
        revision_number=1,
        comparison=compare_rule(
            _requirement(rule_id=rule_id),
            Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            applicability_result=_selected_resolution(rule_id=rule_id),
            unit_context=_unit_context(),
        ),
        observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
        unit_context=_unit_context(),
        decision_reason="idempotent conflict base",
    )
    first = _post(
        client,
        first_payload,
        token=_token(email),
        key="api-eval-conflict-key",
    )
    assert first.status_code == 200

    second_payload = _payload(
        evaluation_id="API-EVAL-CONFLICT",
        revision_number=1,
        comparison=compare_rule(
            _requirement(rule_id=rule_id),
            Observation("synthetic_parameter", 13.0, "synthetic_unit"),
            applicability_result=_selected_resolution(rule_id=rule_id),
            unit_context=_unit_context(),
        ),
        observation=Observation("synthetic_parameter", 13.0, "synthetic_unit"),
        unit_context=_unit_context(),
        decision_reason="idempotent conflict different body",
    )
    second = _post(
        client,
        second_payload,
        token=_token(email),
        key="api-eval-conflict-key",
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error_code"] == "IDEMPOTENCY_CONFLICT"
    assert body["command_namespace"] == "registry.rule.evaluation"
    assert body["command_scope"] == "API-EVAL-CONFLICT"


def test_in_progress_returns_structured_error(client: TestClient) -> None:
    with SessionLocal() as session:
        rule_id = "API_PERSISTED_EVALUATION_RULE_IN_PROGRESS"
        _seed_rule_revision(session, rule_id=rule_id)
        session.commit()

    email = "in-progress-eval@example.com"
    with SessionLocal() as session:
        actor = _user(session, email=email, full_name="In Progress Eval", role="Process Engineer")
        session.commit()
        actor_id = actor.id

    payload = _payload(
        evaluation_id="API-EVAL-IN-PROGRESS",
        revision_number=1,
        comparison=compare_rule(
            _requirement(rule_id=rule_id),
            Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            applicability_result=_selected_resolution(rule_id=rule_id),
            unit_context=_unit_context(),
        ),
        observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
        unit_context=_unit_context(),
        decision_reason="in-progress evaluation",
    )

    with SessionLocal() as session, GovernedUnitOfWork(session) as unit_of_work:
        decision = GovernedIdempotencyService(unit_of_work).reserve_or_inspect(
            receipt_id="api-eval-in-progress-receipt",
            identity=_identity(
                evaluation_id=payload.evaluation_id,
                key="api-eval-in-progress-key",
            ),
            request_hash=_request_hash(payload, actor_user_id=actor_id),
            correlation_id=f"rule-evaluation:{payload.evaluation_id}",
            schema_version="api-test-v1",
            software_version="test-build",
            created_at=payload.comparison.applicability_result.decision_time,
        )
        assert decision.disposition is IdempotencyDisposition.NEW
        unit_of_work.commit()

    response = _post(
        client,
        payload,
        token=_token(email),
        key="api-eval-in-progress-key",
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "IDEMPOTENCY_IN_PROGRESS"
    assert body["command_namespace"] == "registry.rule.evaluation"
    assert body["command_scope"] == "API-EVAL-IN-PROGRESS"
