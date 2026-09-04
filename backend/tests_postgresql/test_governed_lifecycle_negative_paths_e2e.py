"""Real-PostgreSQL governed lifecycle negative-path regression tests.

Asserts the fail-closed contracts from SDS-115 Sections 4-13 and
RuleRegistryService._resolve_source_backed_basis. These tests are the
deterministic inverse of the Phase 6A2 happy-path E2E and protect
against future regressions in:

  - separation of duties (submitter must not enable/activate)
  - missing/empty authority_scope (omission must never grant authority)
  - authority_scope not equal to verified evidence resource_scope
  - missing verified evidence decision
  - source-backed basis resolution when no evidence reference exists
  - audit-on-deny persistence with exact denial codes
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import (
    GovernedAuditMetadata,
    RuleRegistryService,
)
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
)
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.domain.rule_registry_types import (
    EvidenceReferenceDraft,
    MissingHandling,
    RuleCategory,
    SafeDefault,
)
from app.domain.verification_types import (
    EvidenceVerificationAuthoritySnapshot,
    EvidenceVerificationDecisionDraft,
    EvidenceVerificationDelegationDraft,
    VerificationCapability,
    VerificationDelegationStatus,
    VerificationScopeSnapshot,
)
from app.models.entities import User
from app.models.governance import GovernedAuditEvent
from app.models.rule_registry import EngineeringRuleRevision
from app.repositories.evidence_verification_repository import (
    EvidenceVerificationRepository,
)


RULE_ID = "PHASE_6A3_GOVERNED_NEGATIVE_PATH"
RULE_REVISION = "1.0"
PROJECT = "phase-6a3-project"
LIFECYCLE_SCOPE = VerificationScopeSnapshot(project=PROJECT).as_dict()
ALT_SCOPE = VerificationScopeSnapshot(project="other-project").as_dict()
BASE_TIME = datetime(2037, 2, 1, 12, 0, tzinfo=timezone.utc)


ACTORS = {
    "submitter": {
        "email": "phase6a3-submitter@example.com",
        "name": "Phase 6A3 Submitter",
        "role": "Engineer",
    },
    "verifier": {
        "email": "phase6a3-verifier@example.com",
        "name": "Phase 6A3 Verifier",
        "role": "Verifier",
    },
    "grantor": {
        "email": "phase6a3-grantor@example.com",
        "name": "Phase 6A3 Grantor",
        "role": "SecurityOwner",
    },
    "enabler": {
        "email": "phase6a3-enabler@example.com",
        "name": "Phase 6A3 Enabler",
        "role": "Engineer",
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
        value=_digest({"phase": "6A3", "command": label}),
        hash_algorithm="sha256",
        canonicalization_version="phase-6a3-canonical-v1",
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
    authority_scope: dict[str, object] | None = LIFECYCLE_SCOPE,
) -> GovernedAuditMetadata:
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id=str(actor["email"]),
        actor_type="user",
        actor_user_id=actor_user_id,
        actor_role=str(actor["role"]),
        authority_scope=authority_scope,
        reason=reason,
        correlation_id=f"phase-6a3:{event_id}",
        idempotency_key=idempotency_key,
        schema_version="phase-6a3-v1",
        software_version="phase-6a3-test",
        canonicalization_version="phase-6a3-canonical-v1",
        hash_algorithm="sha256",
        detail={"phase": "6A3", "path": "governed-negative-path"},
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
        schema_version="phase-6a3-registry-v1",
        canonicalization_version="phase-6a3-canonical-v1",
        hash_algorithm="sha256",
        content_hash=_digest({"rule_id": RULE_ID, "revision": RULE_REVISION}),
        software_version="phase-6a3-test",
    )


def _make_service(session: Session) -> RuleRegistryService:
    from app.application.governed_audit_service import GovernedAuditService
    from app.application.governed_idempotency_service import GovernedIdempotencyService
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


def _seed_draft(
    session: Session,
    *,
    submitter_user_id: int,
    rule_id: str,
    name: str,
    parameter: str,
    evidence_references: tuple[EvidenceReferenceDraft, ...] = (),
) -> EngineeringRuleRevision:
    service = _make_service(session)
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
    return service.create_draft_revision(
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
        evidence_references=evidence_references,
    )


def _seed_delegation_and_verified_decision(
    session: Session,
    *,
    submitter_user_id: int,
    verifier_user_id: int,
    grantor_user_id: int,
    rule_id: str,
    delegation_id: str,
    scope: VerificationScopeSnapshot,
    evidence_id: str,
) -> None:
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
    draft = _seed_draft(
        session,
        submitter_user_id=submitter_user_id,
        rule_id=rule_id,
        name=f"{rule_id} draft",
        parameter=f"{rule_id}_input",
        evidence_references=(evidence_draft,),
    )
    repository = EvidenceVerificationRepository(session)
    delegation = repository.create_delegation_revision(
        draft=EvidenceVerificationDelegationDraft(
            delegation_id=delegation_id,
            revision_number=1,
            verifier_user_id=verifier_user_id,
            granted_by_user_id=grantor_user_id,
            scope_snapshot=scope,
            effective_from=BASE_TIME - timedelta(days=1),
            expires_at=BASE_TIME + timedelta(days=10),
            status=VerificationDelegationStatus.ACTIVE,
            capability=VerificationCapability.EVIDENCE_VERIFICATION,
            created_by_user_id=grantor_user_id,
            created_by_actor_id=str(ACTORS["grantor"]["email"]),
            schema_version="phase-6a3-verification-v1",
            canonicalization_version="phase-6a3-canonical-v1",
            hash_algorithm="sha256",
            content_hash=_digest(
                {"delegation_id": delegation_id, "scope": scope.as_dict()}
            ),
            software_version="phase-6a3-test",
        )
    )
    authority_without_hash = EvidenceVerificationAuthoritySnapshot(
        verifier_user_id=verifier_user_id,
        verifier_role_snapshot=str(ACTORS["verifier"]["role"]),
        capability=VerificationCapability.EVIDENCE_VERIFICATION,
        resource_scope=scope,
        delegation_id=delegation_id,
        delegation_revision_number=1,
        delegation_status=VerificationDelegationStatus.ACTIVE,
        delegation_effective_from=delegation.effective_from,
        delegation_expires_at=delegation.expires_at,
        delegation_revoked_at=delegation.revoked_at,
        policy_identifier="SDS-115",
        policy_version="0.1 Draft",
        decision_at=BASE_TIME,
        correlation_id=f"phase-6a3-{delegation_id}",
        schema_version="phase-6a3-verification-v1",
        canonicalization_version="phase-6a3-canonical-v1",
        hash_algorithm="sha256",
        content_hash="",
        software_version="phase-6a3-test",
    )
    authority = EvidenceVerificationAuthoritySnapshot(
        verifier_user_id=authority_without_hash.verifier_user_id,
        verifier_role_snapshot=authority_without_hash.verifier_role_snapshot,
        capability=authority_without_hash.capability,
        resource_scope=authority_without_hash.resource_scope,
        delegation_id=authority_without_hash.delegation_id,
        delegation_revision_number=authority_without_hash.delegation_revision_number,
        delegation_status=authority_without_hash.delegation_status,
        delegation_effective_from=authority_without_hash.delegation_effective_from,
        delegation_expires_at=authority_without_hash.delegation_expires_at,
        delegation_revoked_at=authority_without_hash.delegation_revoked_at,
        policy_identifier=authority_without_hash.policy_identifier,
        policy_version=authority_without_hash.policy_version,
        decision_at=authority_without_hash.decision_at,
        correlation_id=authority_without_hash.correlation_id,
        schema_version=authority_without_hash.schema_version,
        canonicalization_version=authority_without_hash.canonicalization_version,
        hash_algorithm=authority_without_hash.hash_algorithm,
        content_hash=_digest(authority_without_hash.as_dict()),
        software_version=authority_without_hash.software_version,
    )
    evidence_ref = draft.evidence_references[0]
    repository.create_verification_decision(
        draft=EvidenceVerificationDecisionDraft(
            verification_id=f"phase-6a3-{delegation_id}-verification",
            revision_number=1,
            evidence_reference_id=evidence_ref.id,
            evidence_verification_delegation_id=delegation.id,
            verifier_user_id=verifier_user_id,
            authority_snapshot=authority.as_dict(),
            decision_reason="Verified exact source-backed test evidence",
            decided_at=BASE_TIME,
            policy_identifier="SDS-115",
            policy_version="0.1 Draft",
            correlation_id=f"phase-6a3-{delegation_id}-verification",
            supersedes_verification_decision_id=None,
            created_by_user_id=verifier_user_id,
            created_by_actor_id=str(ACTORS["verifier"]["email"]),
            schema_version="phase-6a3-verification-v1",
            canonicalization_version="phase-6a3-canonical-v1",
            hash_algorithm="sha256",
            content_hash=_digest(
                {
                    "verification_id": f"phase-6a3-{delegation_id}-verification",
                    "evidence_reference_id": evidence_ref.id,
                    "delegation_id": delegation.id,
                    "authority_hash": authority.content_hash,
                }
            ),
            software_version="phase-6a3-test",
        )
    )


def _assert_denial_audit(
    session: Session,
    *,
    entity_id: str,
    denial_code: str,
) -> GovernedAuditEvent:
    event = session.scalar(
        select(GovernedAuditEvent)
        .where(
            GovernedAuditEvent.entity_id == entity_id,
            GovernedAuditEvent.action
            == "AUTHORIZE_SOURCE_BACKED_LIFECYCLE_DENIED",
        )
        .order_by(GovernedAuditEvent.id.desc())
    )
    assert event is not None, f"expected lifecycle denial audit for {entity_id}"
    assert event.entity_type == "engineering_rule_lifecycle_denial"
    assert event.detail is not None
    assert event.detail.get("denial_code") == denial_code, (
        f"expected denial_code={denial_code!r}, "
        f"got {event.detail.get('denial_code')!r}"
    )
    return event


# ---------------------------------------------------------------------------
# Negative paths: engineering-rule lifecycle
# ---------------------------------------------------------------------------


def test_lifecycle_enablement_denies_when_actor_is_submitter(
    postgresql_engine,
) -> None:
    """submitter == actor => SEPARATION_OF_DUTIES_VIOLATION.

    The lifecycle code (rule_registry_service.py line 741) must deny the
    enable/activate attempt whenever the actor's durable user id equals
    the source-revision submitter's durable user id.
    """
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    grantor_id = user_ids["grantor"]
    rule_id = f"{RULE_ID}_SOD"
    with Session(postgresql_engine) as session:
        _seed_delegation_and_verified_decision(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            grantor_user_id=grantor_id,
            rule_id=rule_id,
            delegation_id="phase-6a3-sod-enable",
            scope=VerificationScopeSnapshot(project=PROJECT),
            evidence_id="phase-6a3-sod-evidence",
        )
        session.commit()
    identity = _identity(
        RuleRegistryService.ENABLEMENT_COMMAND_NAMESPACE,
        rule_id,
        "phase-6a3-sod-enable",
    )
    request_hash = _request_hash("phase-6a3-sod-enable")
    audit = _audit(
        "phase-6a3-sod-enable-audit",
        actor=ACTORS["submitter"],
        actor_user_id=submitter_id,
        idempotency_key="phase-6a3-sod-enable",
        reason="Assert SoD enablement denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            result = service.enable_source_backed_revision(
                rule_id=rule_id,
                source_revision=RULE_REVISION,
                receipt_id="phase-6a3-sod-enable-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                completed_at=BASE_TIME,
            )
            assert result.result_type == "engineering_rule_lifecycle_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            entity_id=rule_id,
            denial_code="SEPARATION_OF_DUTIES_VIOLATION",
        )


def test_lifecycle_enablement_denies_when_authority_scope_is_none(
    postgresql_engine,
) -> None:
    """authority_scope is None => MISSING_SCOPE_SNAPSHOT.

    Omitting authority_scope must never grant authority. The lifecycle
    code (rule_registry_service.py line 754-766) must deny the
    enable/activate attempt with the exact denial code
    MISSING_SCOPE_SNAPSHOT and persist the audit event.
    """
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    grantor_id = user_ids["grantor"]
    enabler_id = user_ids["enabler"]
    rule_id = f"{RULE_ID}_MISSING_SCOPE"
    with Session(postgresql_engine) as session:
        _seed_delegation_and_verified_decision(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            grantor_user_id=grantor_id,
            rule_id=rule_id,
            delegation_id="phase-6a3-missing-scope",
            scope=VerificationScopeSnapshot(project=PROJECT),
            evidence_id="phase-6a3-missing-scope-evidence",
        )
        session.commit()
    identity = _identity(
        RuleRegistryService.ENABLEMENT_COMMAND_NAMESPACE,
        rule_id,
        "phase-6a3-missing-scope",
    )
    request_hash = _request_hash("phase-6a3-missing-scope")
    audit = _audit(
        "phase-6a3-missing-scope-audit",
        actor=ACTORS["enabler"],
        actor_user_id=enabler_id,
        idempotency_key="phase-6a3-missing-scope",
        reason="Assert missing-scope denial",
        authority_scope=None,
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            result = service.enable_source_backed_revision(
                rule_id=rule_id,
                source_revision=RULE_REVISION,
                receipt_id="phase-6a3-missing-scope-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                completed_at=BASE_TIME,
            )
            assert result.result_type == "engineering_rule_lifecycle_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            entity_id=rule_id,
            denial_code="MISSING_SCOPE_SNAPSHOT",
        )


def test_lifecycle_enablement_denies_when_authority_scope_does_not_match_evidence(
    postgresql_engine,
) -> None:
    """authority_scope != verified resource_scope => UNRESOLVED_BASIS.

    A structurally valid authority_scope whose values do not match the
    verified evidence decision's resource_scope must fail closed. The
    lifecycle code (rule_registry_service.py line 978-980) must deny the
    enable/activate attempt and propagate the UNRESOLVED_BASIS denial
    code to the durable audit event.
    """
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    grantor_id = user_ids["grantor"]
    enabler_id = user_ids["enabler"]
    rule_id = f"{RULE_ID}_SCOPE_MISMATCH"
    with Session(postgresql_engine) as session:
        _seed_delegation_and_verified_decision(
            session,
            submitter_user_id=submitter_id,
            verifier_user_id=verifier_id,
            grantor_user_id=grantor_id,
            rule_id=rule_id,
            delegation_id="phase-6a3-scope-mismatch-enable",
            scope=VerificationScopeSnapshot(project=PROJECT),
            evidence_id="phase-6a3-scope-mismatch-evidence",
        )
        session.commit()
    identity = _identity(
        RuleRegistryService.ENABLEMENT_COMMAND_NAMESPACE,
        rule_id,
        "phase-6a3-scope-mismatch-enable",
    )
    request_hash = _request_hash("phase-6a3-scope-mismatch-enable")
    audit = _audit(
        "phase-6a3-scope-mismatch-enable-audit",
        actor=ACTORS["enabler"],
        actor_user_id=enabler_id,
        idempotency_key="phase-6a3-scope-mismatch-enable",
        reason="Assert scope-mismatch enablement denial",
        authority_scope=ALT_SCOPE,
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            result = service.enable_source_backed_revision(
                rule_id=rule_id,
                source_revision=RULE_REVISION,
                receipt_id="phase-6a3-scope-mismatch-enable-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                completed_at=BASE_TIME,
            )
            assert result.result_type == "engineering_rule_lifecycle_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            entity_id=rule_id,
            denial_code="UNRESOLVED_BASIS",
        )


def test_lifecycle_enablement_denies_when_no_verified_evidence_decision(
    postgresql_engine,
) -> None:
    """A draft with an evidence reference but no VERIFIED decision => UNRESOLVED_BASIS.

    When the source-backed evidence reference exists but the
    _resolve_source_backed_basis query returns no verified decision
    (rule_registry_service.py line 972-973), the lifecycle must fail
    closed and persist the UNRESOLVED_BASIS denial.
    """
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    verifier_id = user_ids["verifier"]
    enabler_id = user_ids["enabler"]
    rule_id = f"{RULE_ID}_NO_VERIFIED"
    with Session(postgresql_engine) as session:
        evidence_draft = EvidenceReferenceDraft(
            evidence_id="phase-6a3-no-verified-evidence",
            evidence_revision="1.0",
            source_document_id="SDS-115",
            source_document_revision="0.1",
            source_location="section-7",
            availability="AVAILABLE",
            verified_by_user_id=verifier_id,
            verified_at=BASE_TIME - timedelta(days=2),
        )
        _seed_draft(
            session,
            submitter_user_id=submitter_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_references=(evidence_draft,),
        )
        session.commit()
    identity = _identity(
        RuleRegistryService.ENABLEMENT_COMMAND_NAMESPACE,
        rule_id,
        "phase-6a3-no-verified",
    )
    request_hash = _request_hash("phase-6a3-no-verified")
    audit = _audit(
        "phase-6a3-no-verified-audit",
        actor=ACTORS["enabler"],
        actor_user_id=enabler_id,
        idempotency_key="phase-6a3-no-verified",
        reason="Assert no-verified-decision denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            result = service.enable_source_backed_revision(
                rule_id=rule_id,
                source_revision=RULE_REVISION,
                receipt_id="phase-6a3-no-verified-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                completed_at=BASE_TIME,
            )
            assert result.result_type == "engineering_rule_lifecycle_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            entity_id=rule_id,
            denial_code="UNRESOLVED_BASIS",
        )


def test_lifecycle_enablement_denies_when_draft_has_no_evidence_references(
    postgresql_engine,
) -> None:
    """A draft with zero evidence_references => UNRESOLVED_BASIS.

    The lifecycle code (rule_registry_service.py line 958-960) must deny
    the enable/activate attempt when the source revision has no evidence
    references at all.
    """
    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
    submitter_id = user_ids["submitter"]
    enabler_id = user_ids["enabler"]
    rule_id = f"{RULE_ID}_NO_EVIDENCE"
    with Session(postgresql_engine) as session:
        _seed_draft(
            session,
            submitter_user_id=submitter_id,
            rule_id=rule_id,
            name=f"{rule_id} draft",
            parameter=f"{rule_id}_input",
            evidence_references=(),
        )
        session.commit()
    identity = _identity(
        RuleRegistryService.ENABLEMENT_COMMAND_NAMESPACE,
        rule_id,
        "phase-6a3-no-evidence",
    )
    request_hash = _request_hash("phase-6a3-no-evidence")
    audit = _audit(
        "phase-6a3-no-evidence-audit",
        actor=ACTORS["enabler"],
        actor_user_id=enabler_id,
        idempotency_key="phase-6a3-no-evidence",
        reason="Assert no-evidence-references denial",
    )
    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            result = service.enable_source_backed_revision(
                rule_id=rule_id,
                source_revision=RULE_REVISION,
                receipt_id="phase-6a3-no-evidence-receipt",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                completed_at=BASE_TIME,
            )
            assert result.result_type == "engineering_rule_lifecycle_denial"
            unit_of_work.commit()
    with Session(postgresql_engine) as session:
        _assert_denial_audit(
            session,
            entity_id=rule_id,
            denial_code="UNRESOLVED_BASIS",
        )
