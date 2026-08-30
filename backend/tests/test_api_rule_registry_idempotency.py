from __future__ import annotations

from app.application import audit_service as legacy_audit_service
from app.application.governed_audit_service import GovernedAuditService
from app.application.governed_idempotency_service import GovernedIdempotencyService
from app.db.session import SessionLocal
from app.repositories.rule_registry_repository import RuleRegistryRepository
from fastapi.testclient import TestClient
from test_api_rule_registry import (
    _governed_counts,
    _promotion_payload,
    _setup_promotable_rule,
    _token,
)


def test_same_idempotency_key_same_body_replays_and_preserves_counts(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-IDEMPOTENCY-1",
            source_revision_name="draft-1",
            target_revision_name="source-backed-1",
        )

    before_counts = _governed_counts()
    payload = _promotion_payload(
        rule_id=seed["rule_id"],
        source_revision_name=seed["source_revision_name"],
        target_revision_name=seed["target_revision_name"],
        authority_scope=seed["authority_scope"],
        version_metadata=seed["version_metadata"],
    )
    first = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=payload,
        headers={
            "Authorization": f"Bearer {_token(seed['promoter_email'])}",
            "Idempotency-Key": "rule-registry-idempotency-1",
        },
    )
    assert first.status_code == 200
    first_body = first.json()

    second = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=payload,
        headers={
            "Authorization": f"Bearer {_token(seed['promoter_email'])}",
            "Idempotency-Key": "rule-registry-idempotency-1",
        },
    )
    assert second.status_code == 200
    assert second.json() == first_body
    assert _governed_counts() == (before_counts[0] + 1, before_counts[1] + 1)


def test_same_idempotency_key_different_body_conflicts(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-IDEMPOTENCY-2",
            source_revision_name="draft-1",
            target_revision_name="source-backed-2",
        )

    first = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=_promotion_payload(
            rule_id=seed["rule_id"],
            source_revision_name=seed["source_revision_name"],
            target_revision_name=seed["target_revision_name"],
            authority_scope=seed["authority_scope"],
            version_metadata=seed["version_metadata"],
        ),
        headers={
            "Authorization": f"Bearer {_token(seed['promoter_email'])}",
            "Idempotency-Key": "rule-registry-idempotency-2",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=_promotion_payload(
            rule_id=seed["rule_id"],
            source_revision_name=seed["source_revision_name"],
            target_revision_name=seed["target_revision_name"],
            authority_scope={"project": "different-project"},
            version_metadata=seed["version_metadata"],
        ),
        headers={
            "Authorization": f"Bearer {_token(seed['promoter_email'])}",
            "Idempotency-Key": "rule-registry-idempotency-2",
        },
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error_code"] == "IDEMPOTENCY_CONFLICT"


def test_in_progress_returns_structured_error(client: TestClient, monkeypatch) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-IDEMPOTENCY-3",
            source_revision_name="draft-1",
            target_revision_name="source-backed-3",
        )

    def _raise_in_progress(*args, **kwargs):
        raise RuntimeError("source-backed promotion command is already in progress")

    monkeypatch.setattr(GovernedIdempotencyService, "reserve_or_inspect", _raise_in_progress)

    response = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=_promotion_payload(
            rule_id=seed["rule_id"],
            source_revision_name=seed["source_revision_name"],
            target_revision_name=seed["target_revision_name"],
            authority_scope=seed["authority_scope"],
            version_metadata=seed["version_metadata"],
        ),
        headers={
            "Authorization": f"Bearer {_token(seed['promoter_email'])}",
            "Idempotency-Key": "rule-registry-idempotency-3",
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "IDEMPOTENCY_IN_PROGRESS"


def test_atomic_rollback_on_injected_audit_failure(client: TestClient, monkeypatch) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-IDEMPOTENCY-4",
            source_revision_name="draft-1",
            target_revision_name="source-backed-4",
        )

    before_counts = _governed_counts()
    monkeypatch.setattr(
        GovernedAuditService,
        "record_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )

    response = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=_promotion_payload(
            rule_id=seed["rule_id"],
            source_revision_name=seed["source_revision_name"],
            target_revision_name=seed["target_revision_name"],
            authority_scope=seed["authority_scope"],
            version_metadata=seed["version_metadata"],
        ),
        headers={
            "Authorization": f"Bearer {_token(seed['promoter_email'])}",
            "Idempotency-Key": "rule-registry-idempotency-4",
        },
    )
    assert response.status_code == 500
    assert response.json()["error_code"] == "GOVERNED_TRANSACTION_FAILED"
    assert _governed_counts() == before_counts

    with SessionLocal() as session:
        repository = RuleRegistryRepository(session)
        assert repository.get_revision(seed["rule_id"], seed["target_revision_name"]) is None


def test_legacy_write_audit_is_not_used(client: TestClient, monkeypatch) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-IDEMPOTENCY-5",
            source_revision_name="draft-1",
            target_revision_name="source-backed-5",
        )

    monkeypatch.setattr(
        legacy_audit_service,
        "write_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy audit must not be used")),
    )

    response = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=_promotion_payload(
            rule_id=seed["rule_id"],
            source_revision_name=seed["source_revision_name"],
            target_revision_name=seed["target_revision_name"],
            authority_scope=seed["authority_scope"],
            version_metadata=seed["version_metadata"],
        ),
        headers={
            "Authorization": f"Bearer {_token(seed['promoter_email'])}",
            "Idempotency-Key": "rule-registry-idempotency-5",
        },
    )
    assert response.status_code == 200
    assert response.json()["decision_outcome"] == "SOURCE_BACKED"