from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import RuleRegistryService
from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.domain.governance_types import EvidenceClass, RuleLifecycleStatus
from app.domain.rule_registry_types import EvidenceReferenceDraft
from app.domain.verification_types import VerificationScopeSnapshot
from app.models.entities import User
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.repositories.rule_registry_repository import RuleRegistryRepository
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_rule_registry_service import (
    _audit,
    _create_draft,
    _create_identity,
    _source_backed_version,
    _verified_decision_for_reference,
)

LIFECYCLE_TIME = datetime(2031, 2, 3, 4, 5, 8, tzinfo=timezone.utc)
LIFECYCLE_EXPIRES = datetime(2031, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def _token(email: str) -> str:
    return create_access_token(email)


def _user(
    session,
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


def _authority_scope() -> dict[str, object]:
    return VerificationScopeSnapshot(project="synthetic-project").as_dict()


def _seed_users(session, *, rule_id: str) -> dict[str, User]:
    return {
        "submitter": _user(
            session,
            email=f"{rule_id.lower()}-submitter@example.com",
            full_name="Submitter User",
            role="Engineer",
        ),
        "verifier": _user(
            session,
            email=f"{rule_id.lower()}-verifier@example.com",
            full_name="Verifier User",
            role="Verifier",
        ),
        "promoter": _user(
            session,
            email=f"{rule_id.lower()}-promoter@example.com",
            full_name="Promoter User",
            role="Approver",
        ),
        "lifecycle_actor": _user(
            session,
            email=f"{rule_id.lower()}-lifecycle@example.com",
            full_name="Lifecycle User",
            role="Approver",
        ),
        "grantor": _user(
            session,
            email=f"{rule_id.lower()}-grantor@example.com",
            full_name="Grantor User",
            role="Approver",
        ),
    }


def _setup_promotable_rule(
    session,
    *,
    rule_id: str,
    source_revision_name: str,
    target_revision_name: str,
) -> dict[str, object]:
    users = _seed_users(session, rule_id=rule_id)
    submitter = users["submitter"]
    verifier = users["verifier"]
    promoter = users["promoter"]
    grantor = users["grantor"]
    submitter_id = submitter.id
    submitter_email = submitter.email
    submitter_role = submitter.role
    authority_scope = _authority_scope()
    session.commit()
    with GovernedUnitOfWork(session) as unit_of_work:
        service = RuleRegistryService(unit_of_work)
        _create_identity(
            service,
            rule_id,
            f"{rule_id}-identity-event",
            audit=_audit(
                f"{rule_id}-identity-event",
                actor_id=submitter_email,
                actor_type="user",
                actor_user_id=submitter_id,
                actor_role=submitter_role,
                authority_scope=authority_scope,
                reason="API governance identity",
            ),
        )
        source_revision = _create_draft(
            service,
            rule_id,
            source_revision_name,
            f"{rule_id}-draft-event",
            audit=_audit(
                f"{rule_id}-draft-event",
                actor_id=submitter_email,
                actor_type="user",
                actor_user_id=submitter_id,
                actor_role=submitter_role,
                authority_scope=authority_scope,
                reason="API governance draft",
            ),
            evidence_references=(
                EvidenceReferenceDraft(
                    evidence_id=f"{rule_id}-evidence",
                    evidence_revision="1",
                    evidence_class=EvidenceClass.UNRESOLVED,
                    lifecycle_status=RuleLifecycleStatus.DRAFT,
                    created_by_actor_id=submitter_email,
                    created_by_user_id=submitter_id,
                    reference_uri=f"urn:{rule_id}:evidence",
                ),
            ),
        )
        verified_decision = _verified_decision_for_reference(
            session,
            evidence_reference=source_revision.evidence_references[0],
            verifier=verifier,
            grantor=grantor,
            verification_id=f"{rule_id}-verification",
        )
        evidence_pins = [
            {
                "evidence_reference_id": source_revision.evidence_references[0].id,
                "evidence_id": source_revision.evidence_references[0].evidence_id,
                "evidence_revision": source_revision.evidence_references[0].evidence_revision,
                "verification_decision_id": verified_decision.id,
                "verification_revision_number": verified_decision.revision_number,
                "verifier_user_id": verified_decision.verifier_user_id,
            }
        ]
        version_metadata = _source_backed_version(
            rule_id=rule_id,
            source_revision=source_revision,
            target_revision=target_revision_name,
            evidence_pins=evidence_pins,
            authority_scope=authority_scope,
        )
        unit_of_work.commit()
    return {
        "rule_id": rule_id,
        "source_revision_name": source_revision_name,
        "target_revision_name": target_revision_name,
        "authority_scope": authority_scope,
        "version_metadata": version_metadata,
        "submitter_email": submitter.email,
        "verifier_email": verifier.email,
        "promoter_email": promoter.email,
        "lifecycle_email": users["lifecycle_actor"].email,
        "grantor_email": grantor.email,
    }


def _setup_source_backed_rule(
    session,
    *,
    rule_id: str,
    source_revision_name: str,
) -> dict[str, object]:
    users = _seed_users(session, rule_id=rule_id)
    submitter = users["submitter"]
    verifier = users["verifier"]
    lifecycle_actor = users["lifecycle_actor"]
    grantor = users["grantor"]
    submitter_id = submitter.id
    submitter_email = submitter.email
    submitter_role = submitter.role
    authority_scope = _authority_scope()
    session.commit()
    with GovernedUnitOfWork(session) as unit_of_work:
        service = RuleRegistryService(unit_of_work)
        _create_identity(
            service,
            rule_id,
            f"{rule_id}-identity-event",
            audit=_audit(
                f"{rule_id}-identity-event",
                actor_id=submitter_email,
                actor_type="user",
                actor_user_id=submitter_id,
                actor_role=submitter_role,
                authority_scope=authority_scope,
                reason="API governance identity",
            ),
        )
        source_revision = _create_draft(
            service,
            rule_id,
            source_revision_name,
            f"{rule_id}-source-backed-draft-event",
            evidence_class=EvidenceClass.SOURCE_BACKED,
            allow_source_backed=True,
            audit=_audit(
                f"{rule_id}-source-backed-draft-event",
                actor_id=submitter_email,
                actor_type="user",
                actor_user_id=submitter_id,
                actor_role=submitter_role,
                authority_scope=authority_scope,
                reason="API source-backed draft",
            ),
            evidence_references=(
                EvidenceReferenceDraft(
                    evidence_id=f"{rule_id}-evidence",
                    evidence_revision="1",
                    evidence_class=EvidenceClass.UNRESOLVED,
                    lifecycle_status=RuleLifecycleStatus.DRAFT,
                    created_by_actor_id=submitter_email,
                    created_by_user_id=submitter_id,
                    reference_uri=f"urn:{rule_id}:evidence",
                ),
            ),
        )
        verified_decision = _verified_decision_for_reference(
            session,
            evidence_reference=source_revision.evidence_references[0],
            verifier=verifier,
            grantor=grantor,
            verification_id=f"{rule_id}-verification",
        )
        evidence_pins = [
            {
                "evidence_reference_id": source_revision.evidence_references[0].id,
                "evidence_id": source_revision.evidence_references[0].evidence_id,
                "evidence_revision": source_revision.evidence_references[0].evidence_revision,
                "verification_decision_id": verified_decision.id,
                "verification_revision_number": verified_decision.revision_number,
                "verifier_user_id": verified_decision.verifier_user_id,
            }
        ]
        version_metadata = _source_backed_version(
            rule_id=rule_id,
            source_revision=source_revision,
            target_revision=source_revision_name,
            evidence_pins=evidence_pins,
            authority_scope=authority_scope,
        )
        unit_of_work.commit()
    return {
        "rule_id": rule_id,
        "source_revision_name": source_revision_name,
        "authority_scope": authority_scope,
        "version_metadata": version_metadata,
        "submitter_email": submitter.email,
        "lifecycle_email": lifecycle_actor.email,
    }


def _promotion_payload(
    *,
    rule_id: str,
    source_revision_name: str,
    target_revision_name: str,
    authority_scope: dict[str, object],
    version_metadata,
) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "source_revision": source_revision_name,
        "revision": target_revision_name,
        "authority_scope": authority_scope,
        "version_metadata": asdict(version_metadata),
        "decision_reason": "API governed source-backed promotion",
    }


def _lifecycle_payload(
    *,
    rule_id: str,
    source_revision_name: str,
    authority_scope: dict[str, object],
    decision_reason: str = "API governed source-backed lifecycle",
) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "source_revision": source_revision_name,
        "authority_scope": authority_scope,
        "decision_reason": decision_reason,
        "effective_from": LIFECYCLE_TIME.isoformat(),
        "expires_at": LIFECYCLE_EXPIRES.isoformat(),
    }


def _governed_counts() -> tuple[int, int]:
    with SessionLocal() as session:
        return (
            session.scalar(select(func.count(GovernedAuditEvent.id))) or 0,
            session.scalar(select(func.count(GovernedCommandReceipt.id))) or 0,
        )


def test_source_backed_promotion_happy_path(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-REGISTRY-1",
            source_revision_name="draft-1",
            target_revision_name="source-backed-1",
        )

    promotion_response = client.post(
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
            "Idempotency-Key": "rule-registry-promotion-1",
        },
    )
    assert promotion_response.status_code == 200
    promotion_body = promotion_response.json()
    assert promotion_body["decision_outcome"] == "SOURCE_BACKED"
    assert promotion_body["result_type"] == "engineering_rule_revision"
    assert promotion_body["rule_id"] == seed["rule_id"]
    assert promotion_body["source_revision"] == seed["source_revision_name"]
    assert promotion_body["authority_scope"]["project"] == "synthetic-project"
    assert promotion_body["result_revision"] == seed["target_revision_name"]

    with SessionLocal() as session:
        repository = RuleRegistryRepository(session)
        promoted = repository.get_revision(seed["rule_id"], seed["target_revision_name"])
        assert promoted is not None
        assert promoted.evidence_class is EvidenceClass.SOURCE_BACKED


def test_source_backed_enablement_and_activation_happy_path(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_source_backed_rule(
            session,
            rule_id="API-RULE-REGISTRY-2",
            source_revision_name="source-backed-2",
        )

    enable_response = client.post(
        "/api/v1/rule-registry/source-backed-enablement",
        json=_lifecycle_payload(
            rule_id=seed["rule_id"],
            source_revision_name=seed["source_revision_name"],
            authority_scope=seed["authority_scope"],
            decision_reason="API governed source-backed enablement",
        ),
        headers={
            "Authorization": f"Bearer {_token(seed['lifecycle_email'])}",
            "Idempotency-Key": "rule-registry-enable-1",
        },
    )
    assert enable_response.status_code == 200
    enable_body = enable_response.json()
    assert enable_body["decision_outcome"] == "ENABLED"
    assert enable_body["result_type"] == "engineering_rule_lifecycle_event"
    assert enable_body["rule_id"] == seed["rule_id"]
    assert enable_body["source_revision"] == seed["source_revision_name"]

    activation_response = client.post(
        "/api/v1/rule-registry/source-backed-activation",
        json=_lifecycle_payload(
            rule_id=seed["rule_id"],
            source_revision_name=seed["source_revision_name"],
            authority_scope=seed["authority_scope"],
            decision_reason="API governed source-backed activation",
        ),
        headers={
            "Authorization": f"Bearer {_token(seed['lifecycle_email'])}",
            "Idempotency-Key": "rule-registry-activation-1",
        },
    )
    assert activation_response.status_code == 200
    activation_body = activation_response.json()
    assert activation_body["decision_outcome"] == "ACTIVE"
    assert activation_body["result_type"] == "engineering_rule_lifecycle_event"
    assert activation_body["rule_id"] == seed["rule_id"]
    assert activation_body["source_revision"] == seed["source_revision_name"]


def test_source_backed_enablement_requires_source_backed_revision(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-REGISTRY-3",
            source_revision_name="draft-1",
            target_revision_name="source-backed-3",
        )

    response = client.post(
        "/api/v1/rule-registry/source-backed-enablement",
        json=_lifecycle_payload(
            rule_id=seed["rule_id"],
            source_revision_name=seed["source_revision_name"],
            authority_scope=seed["authority_scope"],
        ),
        headers={
            "Authorization": f"Bearer {_token(seed['lifecycle_email'])}",
            "Idempotency-Key": "rule-registry-enable-2",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_outcome"] == "DENIED"
    assert body["result_type"] == "engineering_rule_lifecycle_denial"
    assert body["result_revision"] == "denied"


def test_direct_source_backed_to_active_is_blocked(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_source_backed_rule(
            session,
            rule_id="API-RULE-REGISTRY-4",
            source_revision_name="source-backed-4",
        )

    activation_response = client.post(
        "/api/v1/rule-registry/source-backed-activation",
        json=_lifecycle_payload(
            rule_id=seed["rule_id"],
            source_revision_name=seed["source_revision_name"],
            authority_scope=seed["authority_scope"],
            decision_reason="API governed direct activation attempt",
        ),
        headers={
            "Authorization": f"Bearer {_token(seed['lifecycle_email'])}",
            "Idempotency-Key": "rule-registry-activation-4",
        },
    )
    assert activation_response.status_code == 200
    body = activation_response.json()
    assert body["decision_outcome"] == "DENIED"
    assert body["result_type"] == "engineering_rule_lifecycle_denial"


def test_source_backed_promotion_records_denial_audit_atomically(client: TestClient) -> None:
    with SessionLocal() as session:
        seed = _setup_promotable_rule(
            session,
            rule_id="API-RULE-REGISTRY-5",
            source_revision_name="draft-1",
            target_revision_name="source-backed-5",
        )

    before_audit, before_receipt = _governed_counts()
    response = client.post(
        "/api/v1/rule-registry/source-backed-promotion",
        json=_promotion_payload(
            rule_id=seed["rule_id"],
            source_revision_name=seed["source_revision_name"],
            target_revision_name=seed["target_revision_name"],
            authority_scope={"project": "other-project"},
            version_metadata=seed["version_metadata"],
        ),
        headers={
            "Authorization": f"Bearer {_token(seed['promoter_email'])}",
            "Idempotency-Key": "rule-registry-promotion-5",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_outcome"] == "DENIED"
    assert body["result_type"] == "engineering_rule_promotion_denial"

    after_audit, after_receipt = _governed_counts()
    assert after_audit == before_audit + 1
    assert after_receipt == before_receipt + 1