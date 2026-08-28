from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.application.evidence_verification_service import EvidenceVerificationService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    RuleLifecycleStatus,
)
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
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


def _scope(customer="customer-a", project="project-a", site="site-a", machine="machine-a") -> dict[str, str]:
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
) -> EvidenceVerificationDelegationDraft:
    return EvidenceVerificationDelegationDraft(
        delegation_id=delegation_id,
        revision_number=1,
        verifier_user_id=verifier.id,
        granted_by_user_id=grantor.id,
        revoked_by_user_id=None,
        scope_snapshot=VerificationScopeSnapshot(**scope),
        effective_from=PAST,
        expires_at=None,
        revoked_at=None,
        revoked_reason=None,
        status=VerificationDelegationStatus.ACTIVE,
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


def _request(
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


def _identity(*, verification_id: str, verifier_user_id: int, key: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace=EvidenceVerificationService.COMMAND_NAMESPACE,
        command_scope=f"verification_id={verification_id};verifier_user_id={verifier_user_id}",
        idempotency_key=key,
    )


def _request_hash(*, payload: dict[str, object], actor_user_id: int) -> CanonicalRequestHash:
    canonical = json.dumps(
        {**payload, "actor_user_id": actor_user_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    return CanonicalRequestHash(
        value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="governed-api-v1",
    )


def test_missing_idempotency_key_is_structured_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/evidence-verifications",
        json=_request(
            verification_id="EV-501",
            evidence_reference_id=1,
            scope=_scope(),
        ),
        headers={"Authorization": f"Bearer {_token('admin@spotwelding.example')}"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "MISSING_IDEMPOTENCY_KEY"


def test_same_idempotency_key_same_body_replays_and_preserves_counts(client: TestClient) -> None:
    with SessionLocal() as session:
        submitter = _user(session, email="submitter-3@example.com", full_name="Submitter 3", role="Submitter")
        verifier = _user(session, email="verifier-3@example.com", full_name="Verifier 3", role="Verifier")
        grantor = _user(session, email="grantor-3@example.com", full_name="Grantor 3", role="Security/Governance Owner")
        evidence = _evidence_reference(
            session,
            submitter=submitter,
            rule_id="EV-API-RULE-3",
            evidence_id="EV-API-EVIDENCE-3",
            evidence_revision="document-1",
        )
        EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-API-3",
                verifier=verifier,
                grantor=grantor,
                scope=_scope(),
            )
        )
        session.commit()

    before = None
    for attempt in range(2):
        response = client.post(
            "/api/v1/evidence-verifications",
            json=_request(
                verification_id="EV-502",
                evidence_reference_id=evidence.id,
                scope=_scope(),
            ),
            headers={
                "Authorization": f"Bearer {_token('verifier-3@example.com')}",
                "Idempotency-Key": "ev-502-key",
            },
        )
        assert response.status_code == 200
        if attempt == 0:
            first_body = response.json()
            with SessionLocal() as session:
                before = _governed_counts(session)
        else:
            second_body = response.json()
            assert second_body == first_body
            with SessionLocal() as session:
                after = _governed_counts(session)
            assert after == before


def test_same_idempotency_key_different_body_conflicts(client: TestClient) -> None:
    with SessionLocal() as session:
        submitter = _user(session, email="submitter-4@example.com", full_name="Submitter 4", role="Submitter")
        verifier = _user(session, email="verifier-4@example.com", full_name="Verifier 4", role="Verifier")
        grantor = _user(session, email="grantor-4@example.com", full_name="Grantor 4", role="Security/Governance Owner")
        evidence = _evidence_reference(
            session,
            submitter=submitter,
            rule_id="EV-API-RULE-4",
            evidence_id="EV-API-EVIDENCE-4",
            evidence_revision="document-1",
        )
        EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-API-4",
                verifier=verifier,
                grantor=grantor,
                scope=_scope(),
            )
        )
        session.commit()

    first = client.post(
        "/api/v1/evidence-verifications",
        json=_request(
            verification_id="EV-503",
            evidence_reference_id=evidence.id,
            scope=_scope(),
        ),
        headers={
            "Authorization": f"Bearer {_token('verifier-4@example.com')}",
            "Idempotency-Key": "ev-503-key",
        },
    )
    assert first.status_code == 200

    conflict = client.post(
        "/api/v1/evidence-verifications",
        json=_request(
            verification_id="EV-503",
            evidence_reference_id=evidence.id,
            scope=_scope(customer="customer-b"),
            decision_reason="changed body",
        ),
        headers={
            "Authorization": f"Bearer {_token('verifier-4@example.com')}",
            "Idempotency-Key": "ev-503-key",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_CONFLICT"


def test_in_progress_returns_structured_error(client: TestClient) -> None:
    with SessionLocal() as session:
        submitter = _user(session, email="submitter-5@example.com", full_name="Submitter 5", role="Submitter")
        verifier = _user(session, email="verifier-5@example.com", full_name="Verifier 5", role="Verifier")
        grantor = _user(session, email="grantor-5@example.com", full_name="Grantor 5", role="Security/Governance Owner")
        evidence = _evidence_reference(
            session,
            submitter=submitter,
            rule_id="EV-API-RULE-5",
            evidence_id="EV-API-EVIDENCE-5",
            evidence_revision="document-1",
        )
        EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-API-5",
                verifier=verifier,
                grantor=grantor,
                scope=_scope(),
            )
        )
        session.commit()

    payload = _request(
        verification_id="EV-504",
        evidence_reference_id=evidence.id,
        scope=_scope(),
    )
    identity = _identity(
        verification_id="EV-504",
        verifier_user_id=verifier.id,
        key="ev-504-key",
    )
    request_hash = _request_hash(payload=payload, actor_user_id=verifier.id)
    with SessionLocal() as session, GovernedUnitOfWork(session) as unit_of_work:
        unit_of_work.idempotency_repository.add_reserved(
            receipt_id="reserved-receipt",
            identity=identity,
            request_hash=request_hash,
            correlation_id="EV-504",
            schema_version="evidence-verification-api-v1",
            software_version="backend-api-v1",
            created_at=PAST,
        )
        unit_of_work.commit()

    in_progress = client.post(
        "/api/v1/evidence-verifications",
        json=payload,
        headers={
            "Authorization": f"Bearer {_token('verifier-5@example.com')}",
            "Idempotency-Key": "ev-504-key",
        },
    )
    assert in_progress.status_code == 409
    assert in_progress.json()["error_code"] == "IDEMPOTENCY_IN_PROGRESS"
