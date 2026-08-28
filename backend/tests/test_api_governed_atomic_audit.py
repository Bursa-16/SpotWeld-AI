from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.application import audit_service as legacy_audit_service
from app.application.governed_audit_service import GovernedAuditService
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


def _user(session: Session, *, email: str, full_name: str, role: str) -> User:
    user = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password("ChangeMe123!"),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def _scope() -> dict[str, str]:
    return {
        "customer": "customer-a",
        "project": "project-a",
        "site": "site-a",
        "machine": "machine-a",
    }


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
) -> EvidenceVerificationDelegationDraft:
    return EvidenceVerificationDelegationDraft(
        delegation_id=delegation_id,
        revision_number=1,
        verifier_user_id=verifier.id,
        granted_by_user_id=grantor.id,
        revoked_by_user_id=None,
        scope_snapshot=VerificationScopeSnapshot(**_scope()),
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
            f"{delegation_id}:{verifier.id}:{grantor.id}".encode()
        ).hexdigest(),
        software_version="test-build",
    )


def _payload(verification_id: str, evidence_reference_id: int, decision_reason: str = "verification passed") -> dict[str, object]:
    return {
        "verification_id": verification_id,
        "evidence_reference_id": evidence_reference_id,
        "requested_scope": _scope(),
        "decision_reason": decision_reason,
    }


def test_atomic_rollback_on_injected_audit_failure(client: TestClient, monkeypatch) -> None:
    with SessionLocal() as session:
        submitter = _user(session, email="submitter-6@example.com", full_name="Submitter 6", role="Submitter")
        verifier = _user(session, email="verifier-6@example.com", full_name="Verifier 6", role="Verifier")
        grantor = _user(session, email="grantor-6@example.com", full_name="Grantor 6", role="Security/Governance Owner")
        evidence = _evidence_reference(
            session,
            submitter=submitter,
            rule_id="EV-API-RULE-6",
            evidence_id="EV-API-EVIDENCE-6",
            evidence_revision="document-1",
        )
        EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-API-6",
                verifier=verifier,
                grantor=grantor,
            )
        )
        session.commit()

    monkeypatch.setattr(
        GovernedAuditService,
        "record_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )

    response = client.post(
        "/api/v1/evidence-verifications",
        json=_payload("EV-601", evidence.id),
        headers={
            "Authorization": f"Bearer {_token('verifier-6@example.com')}",
            "Idempotency-Key": "ev-601-key",
        },
    )
    assert response.status_code == 500
    assert response.json()["error_code"] == "GOVERNED_TRANSACTION_FAILED"

    with SessionLocal() as session:
        assert (
            session.scalar(
                select(func.count(EvidenceVerificationDecision.id)).where(
                    EvidenceVerificationDecision.verification_id == "EV-601"
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(GovernedAuditEvent.id)).where(
                    GovernedAuditEvent.correlation_id == "EV-601"
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(GovernedCommandReceipt.id)).where(
                    GovernedCommandReceipt.correlation_id == "EV-601"
                )
            )
            == 0
        )


def test_legacy_write_audit_is_not_used(client: TestClient, monkeypatch) -> None:
    with SessionLocal() as session:
        submitter = _user(session, email="submitter-7@example.com", full_name="Submitter 7", role="Submitter")
        verifier = _user(session, email="verifier-7@example.com", full_name="Verifier 7", role="Verifier")
        grantor = _user(session, email="grantor-7@example.com", full_name="Grantor 7", role="Security/Governance Owner")
        evidence = _evidence_reference(
            session,
            submitter=submitter,
            rule_id="EV-API-RULE-7",
            evidence_id="EV-API-EVIDENCE-7",
            evidence_revision="document-1",
        )
        EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-API-7",
                verifier=verifier,
                grantor=grantor,
            )
        )
        session.commit()

    monkeypatch.setattr(
        legacy_audit_service,
        "write_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy audit must not be used")),
    )

    response = client.post(
        "/api/v1/evidence-verifications",
        json=_payload("EV-602", evidence.id),
        headers={
            "Authorization": f"Bearer {_token('verifier-7@example.com')}",
            "Idempotency-Key": "ev-602-key",
        },
    )
    assert response.status_code == 200
    assert response.json()["decision_outcome"] == "VERIFIED"
