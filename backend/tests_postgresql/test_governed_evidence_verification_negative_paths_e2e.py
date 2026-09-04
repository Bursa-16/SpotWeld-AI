"""Real-PostgreSQL evidence-verification negative-path regression tests.

Asserts the fail-closed contracts from SDS-115 Sections 4-14 and
EvidenceVerificationService._deny. The deterministic inverse of the
Phase 6A2 happy-path E2E. Covers:

  - MISSING_EVIDENCE_REFERENCE
  - MISSING_DURABLE_HUMAN_VERIFIER
  - MISSING_SUBMITTER_IDENTITY
  - SEPARATION_OF_DUTIES_VIOLATION (submitter == verifier)
  - NO_MATCHING_DELEGATION
  - DELEGATION_REVOKED
  - DELEGATION_EXPIRED
  - DELEGATION_NOT_YET_EFFECTIVE
  - SCOPE_MISMATCH
  - REVOCATION_METADATA_INCOMPLETE
  - Idempotency CONFLICT (same key + different request_hash)

INVALID_CAPABILITY is intentionally not covered: the repository's
create_delegation_revision invariant rejects non-EVIDENCE_VERIFICATION
capability at insert time, so the production path cannot reach the
deny branch.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.evidence_verification_service import EvidenceVerificationService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import GovernedAuditMetadata
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.domain.rule_registry_types import (
    EvidenceReferenceDraft,
    MissingHandling,
    RuleCategory,
    SafeDefault,
)
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
)
from app.domain.verification_types import (
    EvidenceVerificationCommand,
    EvidenceVerificationDelegationDraft,
    VerificationCapability,
    VerificationDelegationStatus,
    VerificationScopeSnapshot,
)
from app.models.entities import User
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.rule_registry import EvidenceReference
from app.models.verification import EvidenceVerificationDelegation
from app.repositories.evidence_verification_repository import (
    EvidenceVerificationRepository,
)


RULE_ID = "PHASE_6A4_GOVERNED_EVIDENCE_NEGATIVE"
RULE_REVISION = "1.0"
PROJECT = "phase-6a4-project"
LIFECYCLE_SCOPE = VerificationScopeSnapshot(project=PROJECT).as_dict()
BASE_TIME = datetime(2037, 3, 1, 12, 0, tzinfo=timezone.utc)


ACTORS = {
    "submitter": {
        "email": "phase6a4-submitter@example.com",
        "name": "Phase 6A4 Submitter",
        "role": "Engineer",
    },
    "verifier": {
        "email": "phase6a4-verifier@example.com",
        "name": "Phase 6A4 Verifier",
        "role": "Verifier",
    },
    "grantor": {
        "email": "phase6a4-grantor@example.com",
        "name": "Phase 6A4 Grantor",
        "role": "SecurityOwner",
    },
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _request_hash(label: str) -> CanonicalRequestHash:
    return CanonicalRequestHash(
        value=_digest({"phase": "6A4", "command": label}),
        hash_algorithm="sha256",
        canonicalization_version="phase-6a4-canonical-v1",
    )


def _identity(namespace: str, scope: str, key: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace=namespace,
        command_scope=scope,
        idempotency_key=key,
    )


def _audit(
    event_id: str,
    *,
    actor: dict[str, object],
    actor_user_id: int,
    idempotency_key: str,
    reason: str,
) -> GovernedAuditMetadata:
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id=str(actor["email"]),
        actor_type="user",
        actor_user_id=actor_user_id,
        actor_role=str(actor["role"]),
        authority_scope=LIFECYCLE_SCOPE,
        reason=reason,
        correlation_id=f"phase-6a4:{event_id}",
        idempotency_key=idempotency_key,
        schema_version="phase-6a4-v1",
        software_version="phase-6a4-test",
        canonicalization_version="phase-6a4-canonical-v1",
        hash_algorithm="sha256",
        detail={"phase": "6A4", "path": "governed-evidence-negative-path"},
        created_at=BASE_TIME,
    )


def _seed_users(session: Session) -> dict[str, int]:
    users = {
        key: User(
            email=str(actor["email"]),
            full_name=str(actor["name"]),
            password_hash=f"hash-{key}",
            role=str(actor["role"]),
        )
        for key, actor in ACTORS.items()
    }
    session.add_all(users.values())
    session.flush()
    return {key: user.id for key, user in users.items()}


def _version_metadata() -> ContentVersionMetadata:
    return ContentVersionMetadata(
        schema_version="phase-6a4-registry-v1",
        canonicalization_version="phase-6a4-canonical-v1",
        hash_algorithm="sha256",
        content_hash=_digest({"rule_id": RULE_ID, "revision": RULE_REVISION}),
        software_version="phase-6a4-test",
    )


def _make_registry_service(session: Session):
    from app.application.governed_audit_service import GovernedAuditService
    from app.application.governed_idempotency_service import GovernedIdempotencyService
    from app.application.rule_registry_service import RuleRegistryService
    from app.repositories.rule_registry_repository import RuleRegistryRepository

    class _Uow:
        def __init__(self, s: Session) -> None:
            self.session = s

        def ensure_open(self) -> None:
            return None

    uow = _Uow(session)  # type: ignore[assignment]
    service = RuleRegistryService.__new__(RuleRegistryService)
    service._unit_of_work = uow  # type: ignore[attr-defined]
    service._repository = RuleRegistryRepository(session)  # type: ignore[attr-defined]
    service._idempotency = GovernedIdempotencyService(uow)  # type: ignore[attr-defined]
    service._audit = GovernedAuditService(uow)  # type: ignore[attr-defined]
    return service


def _seed_draft_with_evidence(
    session: Session,
    *,
    submitter_user_id: int,
    verifier_user_id: int,
    rule_id: str,
    name: str,
    parameter: str,
    evidence_id: str,
) -> EvidenceReference:
    """Create a rule identity + draft carrying one evidence reference, and
    return the persisted EvidenceReference row.
    """
    service = _make_registry_service(session)
    service.create_identity(
        rule_id=rule_id,
        audit=_audit(
            f"{rule_id}-identity",
            actor=ACTORS["submitter"],
            actor_user_id=submitter_user_id,
            idempotency_key=f"{rule_id}-identity",
            reason=f"Seed identity for {rule_id}",
        ),
    )
    evidence_draft = EvidenceReferenceDraft(
        evidence_id=evidence_id,
        evidence_revision="1.0",
        source_document_id="SDS-115",
        source_document_revision="0.1",
        source_location="section-7",
        availability="AVAILABLE",
        verified_by_user_id=verifier_user_id,
        verified_at=BASE_TIME - timedelta(days=2),
    )
    draft = service.create_draft_revision(
        rule_id=rule_id,
        revision=RULE_REVISION,
        name=name,
        evidence_class=EvidenceClass.SOURCE_BACKED,
        category=RuleCategory.OTHER,
        parameter=parameter,
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.MANUAL_REVIEW,
        reason_for_change=f"Seed DRAFT for {rule_id}",
        version_metadata=_version_metadata(),
        audit=_audit(
            f"{rule_id}-draft",
            actor=ACTORS["submitter"],
            actor_user_id=submitter_user_id,
            idempotency_key=f"{rule_id}-draft",
            reason=f"Seed DRAFT for {rule_id}",
        ),
        evidence_references=(evidence_draft,),
    )
    return draft.evidence_references[0]


def _seed_active_delegation(
    session: Session,
    *,
    verifier_user_id: int,
    grantor_user_id: int,
    delegation_id: str,
    scope: VerificationScopeSnapshot,
    effective_from: datetime,
    expires_at: datetime,
) -> EvidenceVerificationDelegation:
    repository = EvidenceVerificationRepository(session)
    return repository.create_delegation_revision(
        draft=EvidenceVerificationDelegationDraft(
            delegation_id=delegation_id,
            revision_number=1,
            verifier_user_id=verifier_user_id,
            granted_by_user_id=grantor_user_id,
            scope_snapshot=scope,
            effective_from=effective_from,
            expires_at=expires_at,
            status=VerificationDelegationStatus.ACTIVE,
            capability=VerificationCapability.EVIDENCE_VERIFICATION,
            created_by_user_id=grantor_user_id,
            created_by_actor_id=str(ACTORS["grantor"]["email"]),
            schema_version="phase-6a4-verification-v1",
            canonicalization_version="phase-6a4-canonical-v1",
            hash_algorithm="sha256",
            content_hash=_digest(
                {"delegation_id": delegation_id, "scope": scope.as_dict()}
            ),
            software_version="phase-6a4-test",
        )
    )


def _assert_denial_audit(
    session: Session,
    *,
    evidence_reference_id: int,
    denial_code: str,
) -> GovernedAuditEvent:
    event = session.scalar(
        select(GovernedAuditEvent)
        .where(
            GovernedAuditEvent.entity_id
            == f"evidence_reference:{evidence_reference_id}",
            GovernedAuditEvent.action
            == "AUTHORIZE_EVIDENCE_VERIFICATION_DENIED",
        )
        .order_by(GovernedAuditEvent.id.desc())
    )
    assert event is not None, (
        f"expected evidence-verification denial audit for "
        f"evidence_reference:{evidence_reference_id}"
    )
    assert event.entity_type == "evidence_verification_denial"
    assert event.detail is not None
    assert event.detail.get("denial_code") == denial_code, (
        f"expected denial_code={denial_code!r}, "
        f"got {event.detail.get('denial_code')!r}"
    )
    return event


# ---------------------------------------------------------------------------
# Evidence-verification negative paths
# ---------------------------------------------------------------------------


def test_verification_denies_when_evidence_reference_missing(
    postgresql_engine,
) -> None:
    """A verification command that references no existing evidence
    reference must fail closed with denial code
    MISSING_EVIDENCE_REFERENCE (evidence_verification_service.py line 93).
    """
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    verifier_id = user_ids["verifier"]
    missing_evidence_id = 999_999_999
    command = EvidenceVerificationCommand(
        evidence_reference_id=missing_evidence_id,
        verifier_user_id=verifier_id,
        requested_scope=VerificationScopeSnapshot(project=PROJECT),
        decision_reason="Sentinel: no evidence reference exists",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{missing_evidence_id}",
        "phase-6a4-missing-evidence",
    )
    request_hash = _request_hash("phase-6a4-missing-evidence")
    audit = _audit(
        "phase-6a4-missing-evidence-audit",
        actor=ACTORS["verifier"],
        actor_user_id=verifier_id,
        idempotency_key="phase-6a4-missing-evidence",
        reason="Assert missing evidence reference denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-missing-evidence-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                verification_id="phase-6a4-missing-evidence-verification",
                completed_at=BASE_TIME,
            )
            assert result.result_type == "evidence_verification_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            evidence_reference_id=missing_evidence_id,
            denial_code="MISSING_EVIDENCE_REFERENCE",
        )


def test_verification_denies_when_verifier_user_does_not_exist(
    postgresql_engine,
) -> None:
    """A verification command whose verifier_user_id does not resolve to
    a durable human User must fail closed with denial code
    MISSING_DURABLE_HUMAN_VERIFIER (line 107).
    """
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    rule_id = f"{RULE_ID}_MISSING_VERIFIER"
    with Session(postgresql_engine) as session:
        evidence_ref = _seed_draft_with_evidence(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_id="phase-6a4-missing-verifier-evidence",
        )
        session.commit()
    sentinel_verifier_id = 999_999_999
    command = EvidenceVerificationCommand(
        evidence_reference_id=evidence_ref.id,
        verifier_user_id=sentinel_verifier_id,
        requested_scope=VerificationScopeSnapshot(project=PROJECT),
        decision_reason="Sentinel: verifier user does not exist",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{evidence_ref.id}",
        "phase-6a4-missing-verifier",
    )
    request_hash = _request_hash("phase-6a4-missing-verifier")
    audit = _audit(
        "phase-6a4-missing-verifier-audit",
        actor=ACTORS["verifier"],
        actor_user_id=verifier_id,
        idempotency_key="phase-6a4-missing-verifier",
        reason="Assert missing durable human verifier denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-missing-verifier-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                verification_id="phase-6a4-missing-verifier-verification",
                completed_at=BASE_TIME,
            )
            assert result.result_type == "evidence_verification_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            evidence_reference_id=evidence_ref.id,
            denial_code="MISSING_DURABLE_HUMAN_VERIFIER",
        )


def test_verification_denies_when_evidence_reference_lacks_submitter(
    postgresql_engine,
) -> None:
    """An evidence reference whose created_by_user_id is NULL must be
    denied with code MISSING_SUBMITTER_IDENTITY (line 120).

    Unreachable through production create_draft_revision (which always
    sets created_by_user_id). Cleared here to exercise the defensive
    branch, a state that can arise from data migrations or legacy imports.
    """
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    rule_id = f"{RULE_ID}_MISSING_SUBMITTER"
    with Session(postgresql_engine) as session:
        evidence_ref = _seed_draft_with_evidence(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_id="phase-6a4-missing-submitter-evidence",
        )
        evidence_ref.created_by_user_id = None
        session.commit()
    command = EvidenceVerificationCommand(
        evidence_reference_id=evidence_ref.id,
        verifier_user_id=verifier_id,
        requested_scope=VerificationScopeSnapshot(project=PROJECT),
        decision_reason="Sentinel: evidence reference lacks submitter",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{evidence_ref.id}",
        "phase-6a4-missing-submitter",
    )
    request_hash = _request_hash("phase-6a4-missing-submitter")
    audit = _audit(
        "phase-6a4-missing-submitter-audit",
        actor=ACTORS["verifier"],
        actor_user_id=verifier_id,
        idempotency_key="phase-6a4-missing-submitter",
        reason="Assert missing submitter identity denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-missing-submitter-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                verification_id="phase-6a4-missing-submitter-verification",
                completed_at=BASE_TIME,
            )
            assert result.result_type == "evidence_verification_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            evidence_reference_id=evidence_ref.id,
            denial_code="MISSING_SUBMITTER_IDENTITY",
        )


def test_verification_denies_when_separation_of_duties_violated(
    postgresql_engine,
) -> None:
    """verifier == submitter => SEPARATION_OF_DUTIES_VIOLATION (line 133)."""
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    grantor_id = user_ids["grantor"]
    rule_id = f"{RULE_ID}_SOD"
    with Session(postgresql_engine) as session:
        evidence_ref = _seed_draft_with_evidence(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_id="phase-6a4-sod-evidence",
        )
        # Seed an active delegation so the request reaches the SoD branch
        # (otherwise NO_MATCHING_DELEGATION triggers first).
        _seed_active_delegation(
            session,
            verifier_user_id=submitter_id,
            grantor_user_id=grantor_id,
            delegation_id="phase-6a4-sod-delegation",
            scope=VerificationScopeSnapshot(project=PROJECT),
            effective_from=BASE_TIME - timedelta(days=1),
            expires_at=BASE_TIME + timedelta(days=10),
        )
        session.commit()
    command = EvidenceVerificationCommand(
        evidence_reference_id=evidence_ref.id,
        verifier_user_id=submitter_id,  # == submitter
        requested_scope=VerificationScopeSnapshot(project=PROJECT),
        decision_reason="Sentinel: submitter is also the verifier",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{evidence_ref.id}",
        "phase-6a4-sod-violation",
    )
    request_hash = _request_hash("phase-6a4-sod-violation")
    audit = _audit(
        "phase-6a4-sod-violation-audit",
        actor=ACTORS["submitter"],
        actor_user_id=submitter_id,
        idempotency_key="phase-6a4-sod-violation",
        reason="Assert separation-of-duties denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-sod-violation-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                verification_id="phase-6a4-sod-violation-verification",
                completed_at=BASE_TIME,
            )
            assert result.result_type == "evidence_verification_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            evidence_reference_id=evidence_ref.id,
            denial_code="SEPARATION_OF_DUTIES_VIOLATION",
        )


def test_verification_denies_when_no_matching_delegation(
    postgresql_engine,
) -> None:
    """find_matching_delegation returns None => NO_MATCHING_DELEGATION (line 151)."""
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    rule_id = f"{RULE_ID}_NO_DELEGATION"
    with Session(postgresql_engine) as session:
        evidence_ref = _seed_draft_with_evidence(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_id="phase-6a4-no-delegation-evidence",
        )
        session.commit()
    command = EvidenceVerificationCommand(
        evidence_reference_id=evidence_ref.id,
        verifier_user_id=verifier_id,
        requested_scope=VerificationScopeSnapshot(project=PROJECT),
        decision_reason="Sentinel: no matching delegation",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{evidence_ref.id}",
        "phase-6a4-no-delegation",
    )
    request_hash = _request_hash("phase-6a4-no-delegation")
    audit = _audit(
        "phase-6a4-no-delegation-audit",
        actor=ACTORS["verifier"],
        actor_user_id=verifier_id,
        idempotency_key="phase-6a4-no-delegation",
        reason="Assert no matching delegation denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-no-delegation-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                verification_id="phase-6a4-no-delegation-verification",
                completed_at=BASE_TIME,
            )
            assert result.result_type == "evidence_verification_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            evidence_reference_id=evidence_ref.id,
            denial_code="NO_MATCHING_DELEGATION",
        )


def test_verification_denies_when_delegation_revoked(
    postgresql_engine,
) -> None:
    """delegation.status is REVOKED => DELEGATION_REVOKED (line 179)."""
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    grantor_id = user_ids["grantor"]
    rule_id = f"{RULE_ID}_REVOKED"
    with Session(postgresql_engine) as session:
        evidence_ref = _seed_draft_with_evidence(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_id="phase-6a4-revoked-evidence",
        )
        # Seed an ACTIVE delegation then supersede it with a REVOKED one.
        active = _seed_active_delegation(
            session,
            verifier_user_id=verifier_id,
            grantor_user_id=grantor_id,
            delegation_id="phase-6a4-revoked-delegation",
            scope=VerificationScopeSnapshot(project=PROJECT),
            effective_from=BASE_TIME - timedelta(days=10),
            expires_at=BASE_TIME + timedelta(days=10),
        )
        repository = EvidenceVerificationRepository(session)
        repository.create_delegation_revision(
            draft=EvidenceVerificationDelegationDraft(
                delegation_id="phase-6a4-revoked-delegation",
                revision_number=2,
                verifier_user_id=verifier_id,
                granted_by_user_id=grantor_id,
                scope_snapshot=VerificationScopeSnapshot(project=PROJECT),
                effective_from=BASE_TIME - timedelta(days=10),
                expires_at=BASE_TIME + timedelta(days=10),
                revoked_by_user_id=grantor_id,
                revoked_at=BASE_TIME - timedelta(days=1),
                revoked_reason="Revoked for negative-path coverage",
                status=VerificationDelegationStatus.REVOKED,
                capability=VerificationCapability.EVIDENCE_VERIFICATION,
                supersedes_delegation_id=active.id,
                created_by_user_id=grantor_id,
                created_by_actor_id=str(ACTORS["grantor"]["email"]),
                schema_version="phase-6a4-verification-v1",
                canonicalization_version="phase-6a4-canonical-v1",
                hash_algorithm="sha256",
                content_hash=_digest(
                    {"delegation_id": "phase-6a4-revoked-delegation",
                     "revision": 2}
                ),
                software_version="phase-6a4-test",
            )
        )
        session.commit()
    command = EvidenceVerificationCommand(
        evidence_reference_id=evidence_ref.id,
        verifier_user_id=verifier_id,
        requested_scope=VerificationScopeSnapshot(project=PROJECT),
        decision_reason="Sentinel: delegation has been revoked",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{evidence_ref.id}",
        "phase-6a4-revoked-delegation",
    )
    request_hash = _request_hash("phase-6a4-revoked-delegation")
    audit = _audit(
        "phase-6a4-revoked-audit",
        actor=ACTORS["verifier"],
        actor_user_id=verifier_id,
        idempotency_key="phase-6a4-revoked-delegation",
        reason="Assert revoked delegation denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-revoked-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                verification_id="phase-6a4-revoked-verification",
                completed_at=BASE_TIME,
            )
            assert result.result_type == "evidence_verification_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            evidence_reference_id=evidence_ref.id,
            denial_code="DELEGATION_REVOKED",
        )


def test_verification_denies_when_delegation_expired(
    postgresql_engine,
) -> None:
    """delegation.expires_at <= completed_at => DELEGATION_EXPIRED (line 196)."""
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    grantor_id = user_ids["grantor"]
    rule_id = f"{RULE_ID}_EXPIRED"
    with Session(postgresql_engine) as session:
        evidence_ref = _seed_draft_with_evidence(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_id="phase-6a4-expired-evidence",
        )
        _seed_active_delegation(
            session,
            verifier_user_id=verifier_id,
            grantor_user_id=grantor_id,
            delegation_id="phase-6a4-expired-delegation",
            scope=VerificationScopeSnapshot(project=PROJECT),
            effective_from=BASE_TIME - timedelta(days=30),
            expires_at=BASE_TIME - timedelta(days=1),
        )
        session.commit()
    command = EvidenceVerificationCommand(
        evidence_reference_id=evidence_ref.id,
        verifier_user_id=verifier_id,
        requested_scope=VerificationScopeSnapshot(project=PROJECT),
        decision_reason="Sentinel: delegation has expired",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{evidence_ref.id}",
        "phase-6a4-expired-delegation",
    )
    request_hash = _request_hash("phase-6a4-expired-delegation")
    audit = _audit(
        "phase-6a4-expired-audit",
        actor=ACTORS["verifier"],
        actor_user_id=verifier_id,
        idempotency_key="phase-6a4-expired-delegation",
        reason="Assert expired delegation denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-expired-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                verification_id="phase-6a4-expired-verification",
                completed_at=BASE_TIME,
            )
            assert result.result_type == "evidence_verification_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            evidence_reference_id=evidence_ref.id,
            denial_code="DELEGATION_EXPIRED",
        )


def test_verification_denies_when_delegation_not_yet_effective(
    postgresql_engine,
) -> None:
    """completed_at < delegation.effective_from => DELEGATION_NOT_YET_EFFECTIVE (line 210)."""
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    grantor_id = user_ids["grantor"]
    rule_id = f"{RULE_ID}_NOT_YET_EFFECTIVE"
    with Session(postgresql_engine) as session:
        evidence_ref = _seed_draft_with_evidence(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_id="phase-6a4-not-yet-effective-evidence",
        )
        _seed_active_delegation(
            session,
            verifier_user_id=verifier_id,
            grantor_user_id=grantor_id,
            delegation_id="phase-6a4-not-yet-effective-delegation",
            scope=VerificationScopeSnapshot(project=PROJECT),
            effective_from=BASE_TIME + timedelta(days=1),  # future
            expires_at=BASE_TIME + timedelta(days=10),
        )
        session.commit()
    command = EvidenceVerificationCommand(
        evidence_reference_id=evidence_ref.id,
        verifier_user_id=verifier_id,
        requested_scope=VerificationScopeSnapshot(project=PROJECT),
        decision_reason="Sentinel: delegation is not yet effective",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{evidence_ref.id}",
        "phase-6a4-not-yet-effective",
    )
    request_hash = _request_hash("phase-6a4-not-yet-effective")
    audit = _audit(
        "phase-6a4-not-yet-effective-audit",
        actor=ACTORS["verifier"],
        actor_user_id=verifier_id,
        idempotency_key="phase-6a4-not-yet-effective",
        reason="Assert not-yet-effective delegation denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-not-yet-effective-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                verification_id="phase-6a4-not-yet-effective-verification",
                completed_at=BASE_TIME,
            )
            assert result.result_type == "evidence_verification_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            evidence_reference_id=evidence_ref.id,
            denial_code="DELEGATION_NOT_YET_EFFECTIVE",
        )


def test_verification_denies_when_requested_scope_mismatches_delegation(
    postgresql_engine,
) -> None:
    """requested scope != delegation scope => SCOPE_MISMATCH (line 224)."""
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    grantor_id = user_ids["grantor"]
    rule_id = f"{RULE_ID}_SCOPE_MISMATCH"
    with Session(postgresql_engine) as session:
        evidence_ref = _seed_draft_with_evidence(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_id="phase-6a4-scope-mismatch-evidence",
        )
        _seed_active_delegation(
            session,
            verifier_user_id=verifier_id,
            grantor_user_id=grantor_id,
            delegation_id="phase-6a4-scope-mismatch-delegation",
            scope=VerificationScopeSnapshot(project=PROJECT),
            effective_from=BASE_TIME - timedelta(days=1),
            expires_at=BASE_TIME + timedelta(days=10),
        )
        session.commit()
    command = EvidenceVerificationCommand(
        evidence_reference_id=evidence_ref.id,
        verifier_user_id=verifier_id,
        requested_scope=VerificationScopeSnapshot(project="other-project"),
        decision_reason="Sentinel: requested scope does not match delegation",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{evidence_ref.id}",
        "phase-6a4-scope-mismatch",
    )
    request_hash = _request_hash("phase-6a4-scope-mismatch")
    audit = _audit(
        "phase-6a4-scope-mismatch-audit",
        actor=ACTORS["verifier"],
        actor_user_id=verifier_id,
        idempotency_key="phase-6a4-scope-mismatch",
        reason="Assert scope mismatch denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-scope-mismatch-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                verification_id="phase-6a4-scope-mismatch-verification",
                completed_at=BASE_TIME,
            )
            assert result.result_type == "evidence_verification_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            evidence_reference_id=evidence_ref.id,
            denial_code="SCOPE_MISMATCH",
        )


def test_verification_denies_when_revocation_metadata_incomplete(
    postgresql_engine,
) -> None:
    """revoked_by_user_id set but revoked_at is None => REVOCATION_METADATA_INCOMPLETE (line 238).

    Unreachable through the production repository invariant (it requires
    revoked_at to be set whenever revoked_by_user_id is set). The defensive
    branch is exercised by inserting a complete revocation then mutating
    status back to ACTIVE and clearing revoked_at.
    """
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    grantor_id = user_ids["grantor"]
    rule_id = f"{RULE_ID}_REVOCATION_INCOMPLETE"
    with Session(postgresql_engine) as session:
        evidence_ref = _seed_draft_with_evidence(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_id="phase-6a4-revocation-incomplete-evidence",
        )
        # Seed an ACTIVE delegation then supersede with REVOKED (so the
        # superseded row's revoked_by_user_id is set), then mutate the row
        # to expose the defensive state: status=ACTIVE + revoked_at=None
        # + revoked_by_user_id set.
        active = _seed_active_delegation(
            session,
            verifier_user_id=verifier_id,
            grantor_user_id=grantor_id,
            delegation_id="phase-6a4-revocation-incomplete-delegation",
            scope=VerificationScopeSnapshot(project=PROJECT),
            effective_from=BASE_TIME - timedelta(days=10),
            expires_at=BASE_TIME + timedelta(days=10),
        )
        repository = EvidenceVerificationRepository(session)
        repository.create_delegation_revision(
            draft=EvidenceVerificationDelegationDraft(
                delegation_id="phase-6a4-revocation-incomplete-delegation",
                revision_number=2,
                verifier_user_id=verifier_id,
                granted_by_user_id=grantor_id,
                scope_snapshot=VerificationScopeSnapshot(project=PROJECT),
                effective_from=BASE_TIME - timedelta(days=10),
                expires_at=BASE_TIME + timedelta(days=10),
                revoked_by_user_id=grantor_id,
                revoked_at=BASE_TIME - timedelta(days=1),
                revoked_reason="Seeded for defensive-branch coverage",
                status=VerificationDelegationStatus.REVOKED,
                capability=VerificationCapability.EVIDENCE_VERIFICATION,
                supersedes_delegation_id=active.id,
                created_by_user_id=grantor_id,
                created_by_actor_id=str(ACTORS["grantor"]["email"]),
                schema_version="phase-6a4-verification-v1",
                canonicalization_version="phase-6a4-canonical-v1",
                hash_algorithm="sha256",
                content_hash=_digest(
                    {
                        "delegation_id": "phase-6a4-revocation-incomplete-delegation",
                        "revision": 2,
                    }
                ),
                software_version="phase-6a4-test",
            )
        )
        session.commit()
        # The application checks REVOKED first (line 178). We must flip the
        # status back to ACTIVE to expose the partial-revocation state.
        revoked = session.scalar(
            select(EvidenceVerificationDelegation)
            .where(
                EvidenceVerificationDelegation.delegation_id
                == "phase-6a4-revocation-incomplete-delegation"
            )
            .order_by(EvidenceVerificationDelegation.revision_number.desc())
        )
        assert revoked is not None
        revoked.status = VerificationDelegationStatus.ACTIVE
        revoked.revoked_at = None
        session.commit()
    command = EvidenceVerificationCommand(
        evidence_reference_id=evidence_ref.id,
        verifier_user_id=verifier_id,
        requested_scope=VerificationScopeSnapshot(project=PROJECT),
        decision_reason="Sentinel: revocation metadata is incomplete",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{evidence_ref.id}",
        "phase-6a4-revocation-incomplete",
    )
    request_hash = _request_hash("phase-6a4-revocation-incomplete")
    audit = _audit(
        "phase-6a4-revocation-incomplete-audit",
        actor=ACTORS["verifier"],
        actor_user_id=verifier_id,
        idempotency_key="phase-6a4-revocation-incomplete",
        reason="Assert revocation-metadata-incomplete denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-revocation-incomplete-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                verification_id="phase-6a4-revocation-incomplete-verification",
                completed_at=BASE_TIME,
            )
            assert result.result_type == "evidence_verification_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            evidence_reference_id=evidence_ref.id,
            denial_code="REVOCATION_METADATA_INCOMPLETE",
        )


# ---------------------------------------------------------------------------
# Idempotency negative path: same key + different request hash
# ---------------------------------------------------------------------------


def test_verification_idempotency_conflict_raises_on_changed_payload(
    postgresql_engine,
) -> None:
    """Same idempotency_key + different request_hash must fail closed
    by raising ValueError (evidence_verification_service.py line 79).

    A successful verification decision with one payload, followed by a
    second command with the same idempotency key but a different
    canonical request hash, must NOT silently re-evaluate. The governed
    service must raise ValueError so the caller knows the conflict
    occurred.
    """
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    verifier_id = user_ids["verifier"]
    missing_evidence_id = 999_999_999
    command = EvidenceVerificationCommand(
        evidence_reference_id=missing_evidence_id,
        verifier_user_id=verifier_id,
        requested_scope=VerificationScopeSnapshot(project=PROJECT),
        decision_reason="Sentinel: original payload",
    )
    identity = _identity(
        EvidenceVerificationService.COMMAND_NAMESPACE,
        f"evidence:{missing_evidence_id}",
        "phase-6a4-idempotency-conflict",
    )
    request_hash_first = _request_hash("phase-6a4-idempotency-conflict-first")
    request_hash_second = _request_hash("phase-6a4-idempotency-conflict-second")
    audit = _audit(
        "phase-6a4-idempotency-conflict-audit",
        actor=ACTORS["verifier"],
        actor_user_id=verifier_id,
        idempotency_key="phase-6a4-idempotency-conflict",
        reason="Assert idempotency conflict on changed payload",
    )
    # First call: denial with the first request hash. Persists receipt.
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            first_result = service.verify_evidence(
                command=command,
                receipt_id="phase-6a4-idempotency-conflict-receipt",
                command_identity=identity,
                request_hash=request_hash_first,
                audit=audit,
                verification_id="phase-6a4-idempotency-conflict-verification",
                completed_at=BASE_TIME,
            )
            assert first_result.result_type == "evidence_verification_denial"
            unit_of_work.commit()

    # Second call: same idempotency key + DIFFERENT request hash.
    # Must raise ValueError, not return a new result.
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            import pytest as _pytest
            with _pytest.raises(ValueError, match="idempotency conflict"):
                service.verify_evidence(
                    command=command,
                    receipt_id="phase-6a4-idempotency-conflict-receipt",
                    command_identity=identity,
                    request_hash=request_hash_second,
                    audit=audit,
                    verification_id="phase-6a4-idempotency-conflict-verification",
                    completed_at=BASE_TIME,
                )

    # Exactly one durable denial audit + one durable command receipt.
    with Session(postgresql_engine) as session:
        audit_count = session.scalar(
            select(__import__("sqlalchemy").func.count(GovernedAuditEvent.id)).where(
                GovernedAuditEvent.entity_id
                == f"evidence_reference:{missing_evidence_id}"
            )
        )
        receipt_count = session.scalar(
            select(__import__("sqlalchemy").func.count(GovernedCommandReceipt.id)).where(
                GovernedCommandReceipt.idempotency_key
                == "phase-6a4-idempotency-conflict"
            )
        )
        assert audit_count == 1, (
            f"idempotency conflict must not create a second audit event, "
            f"got {audit_count}"
        )
        assert receipt_count == 1, (
            f"idempotency conflict must not create a second command receipt, "
            f"got {receipt_count}"
        )
