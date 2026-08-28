from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    RuleLifecycleStatus,
)
from app.domain.rule_registry_types import (
    EvidenceReferenceDraft,
    MissingHandling,
    RuleCategory,
    SafeDefault,
)
from app.domain.verification_types import (
    EvidenceVerificationDelegationDraft,
    VerificationDelegationStatus,
    VerificationScopeSnapshot,
)
from app.models.entities import User
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.rule_registry import EvidenceReference
from app.models.verification import EvidenceVerificationDecision
from app.repositories.evidence_verification_repository import (
    EvidenceVerificationRepository,
)
from app.repositories.rule_registry_repository import RuleRegistryRepository
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

PAST = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


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
        session.scalar(select(func.count(EvidenceVerificationDecision.id))) or 0,
        session.scalar(select(func.count(GovernedAuditEvent.id))) or 0,
        session.scalar(select(func.count(GovernedCommandReceipt.id))) or 0,
    )


def _evidence_reference(
    session: Session,
    *,
    submitter: User,
    rule_id: str,
    evidence_id: str,
    evidence_revision: str,
) -> EvidenceReference:
    repository = RuleRegistryRepository(session)
    rule = repository.create_rule(
        rule_id=rule_id,
        created_by_actor_id="submitter-actor",
        created_by_user_id=submitter.id,
    )
    revision = repository.create_revision(
        engineering_rule=rule,
        revision="draft-1",
        name="Verification foundation rule",
        status=RuleLifecycleStatus.DRAFT,
        evidence_class=EvidenceClass.UNRESOLVED,
        category=RuleCategory.OTHER,
        parameter="verification_parameter",
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.DATA_INSUFFICIENT,
        enabled=False,
        reason_for_change="Verification foundation fixture",
        version_metadata=ContentVersionMetadata(
            schema_version="verification-test-v1",
            canonicalization_version="canonical-test-v1",
            hash_algorithm="sha256",
            content_hash=hashlib.sha256(f"{rule_id}:draft-1".encode()).hexdigest(),
            software_version="test-build",
        ),
        created_by_actor_id="submitter-actor",
        created_by_user_id=submitter.id,
        evidence_references=(
            EvidenceReferenceDraft(
                evidence_id=evidence_id,
                evidence_revision=evidence_revision,
                evidence_class=EvidenceClass.UNRESOLVED,
                lifecycle_status=RuleLifecycleStatus.DRAFT,
                created_by_actor_id="submitter-actor",
                created_by_user_id=submitter.id,
                source_document="Verification evidence",
                section_reference="section-1",
                schema_version="verification-evidence-v1",
                hash_algorithm="sha256",
                content_hash=hashlib.sha256(
                    f"{evidence_id}:{evidence_revision}".encode()
                ).hexdigest(),
            ),
        ),
    )
    session.flush()
    reference = revision.evidence_references[0]
    session.expunge(reference)
    return reference


def _delegation(
    *,
    delegation_id: str,
    verifier: User,
    grantor: User,
    scope: dict[str, str],
    effective_from: datetime = PAST,
    expires_at: datetime | None = None,
    revoked_by_user_id: int | None = None,
    revoked_at: datetime | None = None,
    revoked_reason: str | None = None,
    status: VerificationDelegationStatus = VerificationDelegationStatus.ACTIVE,
) -> EvidenceVerificationDelegationDraft:
    return EvidenceVerificationDelegationDraft(
        delegation_id=delegation_id,
        revision_number=1,
        verifier_user_id=verifier.id,
        granted_by_user_id=grantor.id,
        revoked_by_user_id=revoked_by_user_id,
        scope_snapshot=VerificationScopeSnapshot(**scope),
        effective_from=effective_from,
        expires_at=expires_at,
        revoked_at=revoked_at,
        revoked_reason=revoked_reason,
        status=status,
        supersedes_delegation_id=None,
        created_by_user_id=grantor.id,
        created_by_actor_id="grantor-actor",
        schema_version="verification-delegation-v1",
        canonicalization_version="canonical-test-v1",
        hash_algorithm="sha256",
        content_hash=hashlib.sha256(
            f"{delegation_id}:{verifier.id}:{grantor.id}:{scope}".encode()
        ).hexdigest(),
        software_version="test-build",
    )


def _create_delegation(
    session: Session,
    *,
    delegation_id: str,
    verifier: User,
    grantor: User,
    scope: dict[str, str],
    effective_from: datetime = PAST,
    expires_at: datetime | None = None,
    revoked_by_user_id: int | None = None,
    revoked_at: datetime | None = None,
    revoked_reason: str | None = None,
    status: VerificationDelegationStatus = VerificationDelegationStatus.ACTIVE,
) -> None:
    EvidenceVerificationRepository(session).create_delegation_revision(
        draft=_delegation(
            delegation_id=delegation_id,
            verifier=verifier,
            grantor=grantor,
            scope=scope,
            effective_from=effective_from,
            expires_at=expires_at,
            revoked_by_user_id=revoked_by_user_id,
            revoked_at=revoked_at,
            revoked_reason=revoked_reason,
            status=status,
        )
    )


def _payload(
    *,
    verification_id: str,
    evidence_reference_id: int,
    scope: dict[str, str],
    decision_reason: str = "verification passed",
) -> dict[str, object]:
    return {
        "verification_id": verification_id,
        "evidence_reference_id": evidence_reference_id,
        "requested_scope": scope,
        "decision_reason": decision_reason,
    }


def test_unauthenticated_and_inactive_users_are_rejected(client: TestClient) -> None:
    unauthenticated = client.post(
        "/api/v1/evidence-verifications",
        json=_payload(
            verification_id="EV-401",
            evidence_reference_id=1,
            scope=_scope(),
        ),
        headers={"Idempotency-Key": "ev-401-key"},
    )
    assert unauthenticated.status_code == 401

    with SessionLocal() as session:
        _user(
            session,
            email="inactive@example.com",
            full_name="Inactive User",
            role="Verifier",
            is_active=False,
        )
        session.commit()

    inactive = client.post(
        "/api/v1/evidence-verifications",
        json=_payload(
            verification_id="EV-402",
            evidence_reference_id=1,
            scope=_scope(),
        ),
        headers={
            "Authorization": f"Bearer {_token('inactive@example.com')}",
            "Idempotency-Key": "ev-402-key",
        },
    )
    assert inactive.status_code == 401


def test_client_cannot_impersonate_actor_and_system_admin_wildcard_alone_is_not_authority(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        submitter = _user(
            session,
            email="submitter@example.com",
            full_name="Submitter",
            role="Submitter",
        )
        evidence = _evidence_reference(
            session,
            submitter=submitter,
            rule_id="EV-API-RULE-1",
            evidence_id="EV-API-EVIDENCE-1",
            evidence_revision="document-1",
        )
        session.commit()

    impersonation = client.post(
        "/api/v1/evidence-verifications",
        json={
            **_payload(
                verification_id="EV-403",
                evidence_reference_id=evidence.id,
                scope=_scope(),
            ),
            "verifier_user_id": 999,
        },
        headers={
            "Authorization": f"Bearer {_token('admin@spotwelding.example')}",
            "Idempotency-Key": "ev-403-key",
        },
    )
    assert impersonation.status_code == 422

    admin = client.post(
        "/api/v1/evidence-verifications",
        json=_payload(
            verification_id="EV-404",
            evidence_reference_id=evidence.id,
            scope=_scope(),
        ),
        headers={
            "Authorization": f"Bearer {_token('admin@spotwelding.example')}",
            "Idempotency-Key": "ev-404-key",
        },
    )
    assert admin.status_code == 200
    body = admin.json()
    assert body["decision_outcome"] == "DENIED"
    assert body["result_type"] == "evidence_verification_denial"


def test_matching_delegation_verifies_and_scope_mismatch_denial_is_explicit_and_audited(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        submitter = _user(
            session,
            email="submitter-2@example.com",
            full_name="Submitter 2",
            role="Submitter",
        )
        verifier = _user(
            session,
            email="verifier-2@example.com",
            full_name="Verifier 2",
            role="Verifier",
        )
        grantor = _user(
            session,
            email="grantor-2@example.com",
            full_name="Grantor 2",
            role="Security/Governance Owner",
        )
        evidence = _evidence_reference(
            session,
            submitter=submitter,
            rule_id="EV-API-RULE-2",
            evidence_id="EV-API-EVIDENCE-2",
            evidence_revision="document-1",
        )
        _create_delegation(
            session,
            delegation_id="DELEGATION-API-1",
            verifier=verifier,
            grantor=grantor,
            scope=_scope(),
        )
        session.commit()

    with SessionLocal() as session:
        before = _governed_counts(session)
    verified = client.post(
        "/api/v1/evidence-verifications",
        json=_payload(
            verification_id="EV-405",
            evidence_reference_id=evidence.id,
            scope=_scope(),
        ),
        headers={
            "Authorization": f"Bearer {_token('verifier-2@example.com')}",
            "Idempotency-Key": "ev-405-key",
        },
    )
    assert verified.status_code == 200
    verified_body = verified.json()
    assert verified_body["decision_outcome"] == "VERIFIED"
    assert verified_body["result_type"] == "evidence_verification_decision"

    with SessionLocal() as session:
        after = _governed_counts(session)
    assert after[0] == before[0] + 1
    assert after[1] == before[1] + 1
    assert after[2] == before[2] + 1

    with SessionLocal() as session:
        before_denial = _governed_counts(session)
    denial = client.post(
        "/api/v1/evidence-verifications",
        json=_payload(
            verification_id="EV-406",
            evidence_reference_id=evidence.id,
            scope=_scope(customer="customer-b"),
        ),
        headers={
            "Authorization": f"Bearer {_token('verifier-2@example.com')}",
            "Idempotency-Key": "ev-406-key",
        },
    )
    assert denial.status_code == 200
    denial_body = denial.json()
    assert denial_body["decision_outcome"] == "DENIED"
    assert denial_body["result_type"] == "evidence_verification_denial"

    with SessionLocal() as session:
        after_denial = _governed_counts(session)
    assert after_denial[0] == before_denial[0]
    assert after_denial[1] == before_denial[1] + 1
    assert after_denial[2] == before_denial[2] + 1
