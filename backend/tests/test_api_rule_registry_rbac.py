from __future__ import annotations

from dataclasses import asdict

from app.db.session import SessionLocal
from fastapi.testclient import TestClient
from test_api_rule_registry import _setup_promotable_rule, _token, _user


def _promotion_payload(seed: dict[str, object]) -> dict[str, object]:
    return {
        "rule_id": seed["rule_id"],
        "source_revision": seed["source_revision_name"],
        "revision": seed["target_revision_name"],
        "authority_scope": seed["authority_scope"],
        "version_metadata": asdict(seed["version_metadata"]),
        "decision_reason": "API governed source-backed promotion",
    }


def test_unauthenticated_and_inactive_users_are_rejected(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-RBAC-1",
            source_revision_name="draft-1",
            target_revision_name="source-backed-1",
        )
        _user(
            session,
            email="inactive-api@example.com",
            full_name="Inactive API User",
            role="Approver",
            is_active=False,
        )
        session.commit()

    unauthenticated = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=_promotion_payload(seed),
        headers={"Idempotency-Key": "rule-registry-rbac-1"},
    )
    assert unauthenticated.status_code == 401

    inactive = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=_promotion_payload(seed),
        headers={
            "Authorization": f"Bearer {_token('inactive-api@example.com')}",
            "Idempotency-Key": "rule-registry-rbac-2",
        },
    )
    assert inactive.status_code == 401


def test_body_actor_spoofing_is_rejected(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-RBAC-2",
            source_revision_name="draft-1",
            target_revision_name="source-backed-2",
        )

    response = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json={
            **_promotion_payload(seed),
            "actor_user_id": 999999,
        },
        headers={
            "Authorization": f"Bearer {_token(seed['promoter_email'])}",
            "Idempotency-Key": "rule-registry-rbac-3",
        },
    )
    assert response.status_code == 422


def test_system_admin_wildcard_does_not_bypass_governed_lifecycle(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-RBAC-3",
            source_revision_name="draft-1",
            target_revision_name="source-backed-3",
        )

    response = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json={
            **_promotion_payload(seed),
            "authority_scope": {"project": "other-project"},
        },
        headers={
            "Authorization": f"Bearer {_token('admin@spotwelding.example')}",
            "Idempotency-Key": "rule-registry-rbac-4",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_outcome"] == "DENIED"
    assert body["result_type"] == "engineering_rule_promotion_denial"


def test_submitter_cannot_promote_source_backed_revision(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-RBAC-4",
            source_revision_name="draft-1",
            target_revision_name="source-backed-4",
        )

    response = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=_promotion_payload(seed),
        headers={
            "Authorization": f"Bearer {_token(seed['submitter_email'])}",
            "Idempotency-Key": "rule-registry-rbac-5",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_outcome"] == "DENIED"
    assert body["result_type"] == "engineering_rule_promotion_denial"


def test_verifier_cannot_promote_source_backed_revision(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-RBAC-5",
            source_revision_name="draft-1",
            target_revision_name="source-backed-5",
        )

    response = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=_promotion_payload(seed),
        headers={
            "Authorization": f"Bearer {_token(seed['verifier_email'])}",
            "Idempotency-Key": "rule-registry-rbac-6",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_outcome"] == "DENIED"
    assert body["result_type"] == "engineering_rule_promotion_denial"