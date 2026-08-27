"""Tests for non-authoritative Registry draft service orchestration."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import (
    GovernedAuditMetadata,
    RuleRegistryService,
)
from app.db.session import Base
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    RegistryAuthorityError,
    RuleLifecycleStatus,
)
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
)
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
from app.models.rule_registry import (
    EngineeringRule,
    EngineeringRuleRevision,
    EvidenceReference,
    RuleLifecycleEvent,
    RuleLifecycleEventType,
)
from app.models.verification import EvidenceVerificationDecision
from app.repositories.evidence_verification_repository import (
    EvidenceVerificationRepository,
)
from app.repositories.governance_repository import GovernanceRepository
from app.repositories.idempotency_repository import IdempotencyRepository
from app.repositories.rule_registry_repository import RuleRegistryRepository
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture()
def service_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(connection)
    engine.dispose()


def _audit(
    event_id: str,
    *,
    correlation_id: str | None = "synthetic-correlation",
    idempotency_key: str | None = "trace-key",
    actor_id: str = "synthetic-actor",
    actor_type: str = "service",
    actor_user_id: int | None = None,
    actor_role: str | None = "synthetic-role",
    authority_scope: dict[str, object] | None = None,
    reason: str = "Synthetic draft command",
    detail: dict[str, object] | None = None,
) -> GovernedAuditMetadata:
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id=actor_id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        authority_scope=authority_scope or {"project": "synthetic-project"},
        reason=reason,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        schema_version="audit-test-v1",
        software_version="test-build",
        canonicalization_version="audit-canonical-v1",
        hash_algorithm="sha256",
        detail=detail or {"caller_trace": "synthetic"},
        created_at=datetime(2031, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
    )


def _version(rule_id: str, revision: str) -> ContentVersionMetadata:
    payload = json.dumps(
        {"rule_id": rule_id, "revision": revision},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ContentVersionMetadata(
        schema_version="registry-test-v1",
        canonicalization_version="registry-canonical-v1",
        hash_algorithm="sha256",
        content_hash=hashlib.sha256(payload).hexdigest(),
        software_version="test-build",
    )


def _create_identity(
    service: RuleRegistryService,
    rule_id: str,
    event_id: str,
    *,
    audit: GovernedAuditMetadata | None = None,
) -> EngineeringRule:
    return service.create_identity(rule_id=rule_id, audit=audit or _audit(event_id))


def _create_draft(
    service: RuleRegistryService,
    rule_id: str,
    revision: str,
    event_id: str,
    *,
    evidence_class: EvidenceClass = EvidenceClass.UNRESOLVED,
    enabled: bool = False,
    allow_source_backed: bool = False,
    audit: GovernedAuditMetadata | None = None,
    evidence_references: tuple[EvidenceReferenceDraft, ...] = (),
) -> EngineeringRuleRevision:
    return service.create_draft_revision(
        rule_id=rule_id,
        revision=revision,
        name="Synthetic draft requirement",
        evidence_class=evidence_class,
        category=RuleCategory.OTHER,
        parameter="synthetic_parameter",
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.DATA_INSUFFICIENT,
        reason_for_change="Synthetic draft revision",
        version_metadata=_version(rule_id, revision),
        audit=audit or _audit(event_id),
        evidence_references=evidence_references,
        enabled=enabled,
        allow_source_backed=allow_source_backed,
    )


def _source_backed_version(
    *,
    rule_id: str,
    source_revision: EngineeringRuleRevision,
    target_revision: str,
    evidence_pins: list[dict[str, object]],
    authority_scope: dict[str, object],
) -> ContentVersionMetadata:
    payload = {
        "rule_id": rule_id,
        "source_revision": source_revision.revision,
        "source_revision_id": source_revision.id,
        "target_revision": target_revision,
        "source_content_hash": source_revision.content_hash,
        "authority_scope": authority_scope,
        "evidence_pins": evidence_pins,
    }
    return ContentVersionMetadata(
        schema_version="registry-test-v1",
        canonicalization_version="registry-canonical-v1",
        hash_algorithm="sha256",
        content_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        software_version="test-build",
    )


def _seed_promotion_users(session: Session) -> dict[str, User]:
    users = {
        "submitter": User(
            email="submitter@example.com",
            full_name="Submitter User",
            password_hash="hash-submit",
            role="Engineer",
        ),
        "verifier": User(
            email="verifier@example.com",
            full_name="Verifier User",
            password_hash="hash-verify",
            role="Verifier",
        ),
        "promoter": User(
            email="promoter@example.com",
            full_name="Promoter User",
            password_hash="hash-promote",
            role="Approver",
        ),
        "grantor": User(
            email="grantor@example.com",
            full_name="Grantor User",
            password_hash="hash-grant",
            role="Approver",
        ),
    }
    session.add_all(users.values())
    session.flush()
    return users


def _promotion_identity(rule_id: str, key: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace=RuleRegistryService.COMMAND_NAMESPACE,
        command_scope=rule_id,
        idempotency_key=key,
    )


def _promotion_request_hash(payload: dict[str, object]) -> CanonicalRequestHash:
    return CanonicalRequestHash(
        value=hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="registry-canonical-v1",
    )


def _lifecycle_identity(rule_id: str, namespace: str, key: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace=namespace,
        command_scope=rule_id,
        idempotency_key=key,
    )


def _lifecycle_request_hash(payload: dict[str, object]) -> CanonicalRequestHash:
    return CanonicalRequestHash(
        value=hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="registry-canonical-v1",
    )


def _enablement_basis(
    *,
    rule_id: str,
    source_revision: EngineeringRuleRevision,
    evidence_references: tuple[EvidenceReference, ...],
    verified_decisions: tuple[EvidenceVerificationDecision, ...],
    authority_scope: dict[str, object],
) -> dict[str, object]:
    payload = {
        "rule_id": rule_id,
        "source_revision_id": source_revision.id,
        "source_revision": source_revision.revision,
        "source_content_hash": source_revision.content_hash,
        "scope_snapshot": authority_scope,
        "evidence_pins": [
            {
                "evidence_reference_id": reference.id,
                "evidence_id": reference.evidence_id,
                "evidence_revision": reference.evidence_revision,
                "verification_decision_id": decision.id,
                "verification_revision_number": decision.revision_number,
                "verification_decision_content_hash": decision.content_hash,
                "verification_authority_snapshot_hash": decision.authority_snapshot_content_hash,
                "verifier_user_id": decision.verifier_user_id,
            }
            for reference, decision in zip(
                evidence_references,
                verified_decisions,
                strict=True,
            )
        ],
    }
    payload["content_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def _verified_decision_for_reference(
    session: Session,
    *,
    evidence_reference: EvidenceReference,
    verifier: User,
    grantor: User,
    verification_id: str,
    revision_number: int = 1,
    supersedes_verification_decision_id: int | None = None,
    decision_reason: str = "Synthetic VERIFIED decision",
) -> EvidenceVerificationDecision:
    repository = EvidenceVerificationRepository(session)
    scope_snapshot = VerificationScopeSnapshot(project="synthetic-project")
    delegation = repository.create_delegation_revision(
        draft=EvidenceVerificationDelegationDraft(
            delegation_id=f"{verification_id}-delegation",
            revision_number=1,
            verifier_user_id=verifier.id,
            granted_by_user_id=grantor.id,
            scope_snapshot=scope_snapshot,
            effective_from=datetime(2031, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
            expires_at=None,
            revoked_by_user_id=None,
            revoked_at=None,
            revoked_reason=None,
            status=VerificationDelegationStatus.ACTIVE,
            capability=VerificationCapability.EVIDENCE_VERIFICATION,
            created_by_user_id=grantor.id,
            created_by_actor_id="grantor-actor",
            schema_version="verification-test-v1",
            canonicalization_version="verification-canonical-v1",
            hash_algorithm="sha256",
            content_hash=hashlib.sha256(
                json.dumps(
                    {
                        "delegation_id": f"{verification_id}-delegation",
                        "verifier_user_id": verifier.id,
                        "scope_snapshot": scope_snapshot.as_dict(),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            software_version="test-build",
        )
    )
    authority_snapshot = EvidenceVerificationAuthoritySnapshot(
        verifier_user_id=verifier.id,
        verifier_role_snapshot=verifier.role,
        capability=VerificationCapability.EVIDENCE_VERIFICATION,
        resource_scope=scope_snapshot,
        delegation_id=delegation.delegation_id,
        delegation_revision_number=delegation.revision_number,
        delegation_status=delegation.status,
        delegation_effective_from=delegation.effective_from,
        delegation_expires_at=delegation.expires_at,
        delegation_revoked_at=delegation.revoked_at,
        policy_identifier="SDS-115",
        policy_version="0.1 Draft",
        decision_at=datetime(2031, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
        correlation_id=f"{verification_id}-correlation",
        schema_version="evidence-verification-authority-snapshot-v1",
        canonicalization_version="canonical-v1",
        hash_algorithm="sha256",
        content_hash="",
        software_version="test-build",
    )
    authority_hash = hashlib.sha256(
        json.dumps(
            authority_snapshot.as_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    authority_snapshot = EvidenceVerificationAuthoritySnapshot(
        verifier_user_id=verifier.id,
        verifier_role_snapshot=verifier.role,
        capability=VerificationCapability.EVIDENCE_VERIFICATION,
        resource_scope=scope_snapshot,
        delegation_id=delegation.delegation_id,
        delegation_revision_number=delegation.revision_number,
        delegation_status=delegation.status,
        delegation_effective_from=delegation.effective_from,
        delegation_expires_at=delegation.expires_at,
        delegation_revoked_at=delegation.revoked_at,
        policy_identifier="SDS-115",
        policy_version="0.1 Draft",
        decision_at=datetime(2031, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
        correlation_id=f"{verification_id}-correlation",
        schema_version="evidence-verification-authority-snapshot-v1",
        canonicalization_version="canonical-v1",
        hash_algorithm="sha256",
        content_hash=authority_hash,
        software_version="test-build",
    )
    return repository.create_verification_decision(
        draft=EvidenceVerificationDecisionDraft(
            verification_id=verification_id,
            revision_number=revision_number,
            evidence_reference_id=evidence_reference.id,
            evidence_verification_delegation_id=delegation.id,
            verifier_user_id=verifier.id,
            authority_snapshot=authority_snapshot.as_dict(),
            decision_reason=decision_reason,
            decided_at=datetime(2031, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
            policy_identifier="SDS-115",
            policy_version="0.1 Draft",
            correlation_id=f"{verification_id}-correlation",
            supersedes_verification_decision_id=supersedes_verification_decision_id,
            created_by_user_id=verifier.id,
            created_by_actor_id="verifier-actor",
            schema_version="verification-test-v1",
            canonicalization_version="verification-canonical-v1",
            hash_algorithm="sha256",
            content_hash=hashlib.sha256(
                json.dumps(
                    {
                        "verification_id": verification_id,
                        "evidence_reference_id": evidence_reference.id,
                        "delegation_id": delegation.id,
                        "verifier_user_id": verifier.id,
                        "authority_snapshot_hash": authority_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            software_version="test-build",
        )
    )


def test_create_registry_identity_within_uow(service_engine) -> None:
    with Session(service_engine) as session, GovernedUnitOfWork(
        session
    ) as unit_of_work:
            rule = _create_identity(
                RuleRegistryService(unit_of_work),
                "SERVICE_IDENTITY_RULE",
                "identity-event",
            )
            assert rule.rule_id == "SERVICE_IDENTITY_RULE"
            assert session.in_transaction()
            unit_of_work.commit()

    with Session(service_engine) as read_session:
        persisted = RuleRegistryRepository(read_session).get_by_rule_id(
            "SERVICE_IDENTITY_RULE"
        )
        assert persisted is not None


def test_create_non_authoritative_draft_revision_with_evidence(
    service_engine,
) -> None:
    evidence = EvidenceReferenceDraft(
        evidence_id="SYNTHETIC_EVIDENCE",
        evidence_revision="draft-1",
        evidence_class=EvidenceClass.UNRESOLVED,
        lifecycle_status=RuleLifecycleStatus.DRAFT,
        created_by_actor_id="synthetic-actor",
        reference_metadata={"state": "unverified"},
    )
    with Session(service_engine) as session, GovernedUnitOfWork(
        session
    ) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            _create_identity(service, "DRAFT_RULE", "draft-identity-event")
            revision = _create_draft(
                service,
                "DRAFT_RULE",
                "draft-1",
                "draft-revision-event",
                evidence_references=(evidence,),
            )
            assert revision.status is RuleLifecycleStatus.DRAFT
            assert revision.evidence_class is EvidenceClass.UNRESOLVED
            assert revision.enabled is False
            assert revision.operator is None
            assert revision.min_value is None
            assert revision.max_value is None
            assert revision.unit is None
            unit_of_work.commit()

    with Session(service_engine) as read_session:
        revision = RuleRegistryRepository(read_session).get_revision(
            "DRAFT_RULE", "draft-1"
        )
        assert revision is not None
        assert len(revision.evidence_references) == 1
        assert revision.evidence_references[0].verified_at is None
        assert revision.evidence_references[0].approved_at is None


def test_identity_and_audit_commit_atomically(service_engine) -> None:
    with Session(service_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            _create_identity(
                RuleRegistryService(unit_of_work),
                "ATOMIC_IDENTITY_RULE",
                "atomic-identity-event",
            )
            unit_of_work.commit()

    with Session(service_engine) as read_session:
        assert RuleRegistryRepository(read_session).get_by_rule_id(
            "ATOMIC_IDENTITY_RULE"
        ) is not None
        assert GovernanceRepository(read_session).get_by_event_id(
            "atomic-identity-event"
        ) is not None


def test_revision_and_audit_commit_atomically(service_engine) -> None:
    with Session(service_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            _create_identity(service, "ATOMIC_REVISION_RULE", "revision-root-event")
            _create_draft(
                service,
                "ATOMIC_REVISION_RULE",
                "draft-1",
                "atomic-revision-event",
            )
            unit_of_work.commit()

    with Session(service_engine) as read_session:
        assert RuleRegistryRepository(read_session).get_revision(
            "ATOMIC_REVISION_RULE", "draft-1"
        ) is not None
        assert GovernanceRepository(read_session).get_by_event_id(
            "atomic-revision-event"
        ) is not None


def test_audit_failure_rolls_back_identity_creation(service_engine) -> None:
    invalid_audit = _audit("invalid-identity-audit", correlation_id=None)
    with pytest.raises(IntegrityError):
        with Session(service_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                RuleRegistryService(unit_of_work).create_identity(
                    rule_id="AUDIT_FAILURE_IDENTITY",
                    audit=invalid_audit,
                )
                unit_of_work.commit()

    with Session(service_engine) as read_session:
        assert RuleRegistryRepository(read_session).get_by_rule_id(
            "AUDIT_FAILURE_IDENTITY"
        ) is None
        assert GovernanceRepository(read_session).get_by_event_id(
            "invalid-identity-audit"
        ) is None


def test_audit_failure_rolls_back_revision_creation(service_engine) -> None:
    with Session(service_engine) as setup_session:
        with GovernedUnitOfWork(setup_session) as setup_uow:
            _create_identity(
                RuleRegistryService(setup_uow),
                "AUDIT_FAILURE_REVISION_RULE",
                "setup-root-event",
            )
            setup_uow.commit()

    invalid_audit = _audit("invalid-revision-audit", correlation_id=None)
    with pytest.raises(IntegrityError):
        with Session(service_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                _create_draft(
                    RuleRegistryService(unit_of_work),
                    "AUDIT_FAILURE_REVISION_RULE",
                    "draft-1",
                    "unused-event-id",
                    audit=invalid_audit,
                )
                unit_of_work.commit()

    with Session(service_engine) as read_session:
        assert RuleRegistryRepository(read_session).get_revision(
            "AUDIT_FAILURE_REVISION_RULE", "draft-1"
        ) is None
        assert GovernanceRepository(read_session).get_by_event_id(
            "invalid-revision-audit"
        ) is None


def test_registry_failure_leaves_no_durable_audit(service_engine) -> None:
    with Session(service_engine) as setup_session:
        with GovernedUnitOfWork(setup_session) as setup_uow:
            _create_identity(
                RuleRegistryService(setup_uow),
                "DUPLICATE_SERVICE_RULE",
                "original-identity-event",
            )
            setup_uow.commit()

    with pytest.raises(IntegrityError):
        with Session(service_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                _create_identity(
                    RuleRegistryService(unit_of_work),
                    "DUPLICATE_SERVICE_RULE",
                    "duplicate-attempt-event",
                )
                unit_of_work.commit()

    with Session(service_engine) as read_session:
        assert GovernanceRepository(read_session).get_by_event_id(
            "duplicate-attempt-event"
        ) is None


def test_service_never_commits_or_rolls_back_internally(service_engine) -> None:
    with Session(service_engine) as session:
        commits: list[bool] = []
        rollbacks: list[bool] = []
        event.listen(session, "after_commit", lambda _session: commits.append(True))
        event.listen(
            session, "after_rollback", lambda _session: rollbacks.append(True)
        )
        unit_of_work = GovernedUnitOfWork(session)
        _create_identity(
            RuleRegistryService(unit_of_work),
            "NO_INTERNAL_FINALIZATION_RULE",
            "no-finalization-event",
        )
        assert commits == []
        assert rollbacks == []
        unit_of_work.rollback()


def test_source_backed_draft_creation_is_rejected(service_engine) -> None:
    with Session(service_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            _create_identity(service, "SOURCE_BACKED_REJECTED", "source-root-event")
            with pytest.raises(RegistryAuthorityError):
                _create_draft(
                    service,
                    "SOURCE_BACKED_REJECTED",
                    "draft-1",
                    "source-revision-event",
                    evidence_class=EvidenceClass.SOURCE_BACKED,
                )


def test_source_backed_promotion_creates_revision_and_replays_idempotently(
    service_engine,
) -> None:
    rule_id = "SOURCE_BACKED_PROMOTION_RULE"
    source_revision_name = "draft-1"
    promoted_revision_name = "source-backed-1"
    authority_scope = VerificationScopeSnapshot(
        project="synthetic-project"
    ).as_dict()

    with Session(service_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            users = _seed_promotion_users(session)
            submitter = users["submitter"]
            verifier = users["verifier"]
            promoter = users["promoter"]
            grantor = users["grantor"]
            source_audit = _audit(
                "source-draft-event",
                actor_id="submitter-actor",
                actor_type="user",
                actor_user_id=submitter.id,
                actor_role=submitter.role,
                authority_scope=authority_scope,
                reason="Synthetic source-backed draft",
            )
            draft_audit = _audit(
                "source-draft-revision-event",
                actor_id="submitter-actor",
                actor_type="user",
                actor_user_id=submitter.id,
                actor_role=submitter.role,
                authority_scope=authority_scope,
                reason="Synthetic source-backed draft",
            )
            service = RuleRegistryService(unit_of_work)
            _create_identity(
                service,
                rule_id,
                "source-root-event",
                audit=source_audit,
            )
            evidence_references = (
                EvidenceReferenceDraft(
                    evidence_id="SOURCE_BACKED_EVIDENCE_A",
                    evidence_revision="1",
                    evidence_class=EvidenceClass.UNRESOLVED,
                    lifecycle_status=RuleLifecycleStatus.DRAFT,
                    created_by_actor_id="submitter-actor",
                    created_by_user_id=submitter.id,
                    reference_uri="urn:source-backed:evidence-a",
                ),
                EvidenceReferenceDraft(
                    evidence_id="SOURCE_BACKED_EVIDENCE_B",
                    evidence_revision="7",
                    evidence_class=EvidenceClass.UNRESOLVED,
                    lifecycle_status=RuleLifecycleStatus.DRAFT,
                    created_by_actor_id="submitter-actor",
                    created_by_user_id=submitter.id,
                    reference_uri="urn:source-backed:evidence-b",
                ),
            )
            source_revision = _create_draft(
                service,
                rule_id,
                source_revision_name,
                "source-draft-revision-event",
                audit=draft_audit,
                evidence_references=evidence_references,
            )
            verified_decisions = [
                _verified_decision_for_reference(
                    session,
                    evidence_reference=reference,
                    verifier=verifier,
                    grantor=grantor,
                    verification_id=f"{reference.evidence_id}-verification",
                )
                for reference in source_revision.evidence_references
            ]
            evidence_pins = [
                {
                    "evidence_reference_id": reference.id,
                    "evidence_id": reference.evidence_id,
                    "evidence_revision": reference.evidence_revision,
                    "verification_decision_id": decision.id,
                    "verification_revision_number": decision.revision_number,
                    "verifier_user_id": decision.verifier_user_id,
                }
                for reference, decision in zip(
                    source_revision.evidence_references,
                    verified_decisions,
                    strict=True,
                )
            ]
            version_metadata = _source_backed_version(
                rule_id=rule_id,
                source_revision=source_revision,
                target_revision=promoted_revision_name,
                evidence_pins=evidence_pins,
                authority_scope=authority_scope,
            )
            command_identity = _promotion_identity(rule_id, "promotion-key-1")
            request_hash = _promotion_request_hash(
                {
                    "rule_id": rule_id,
                    "source_revision": source_revision.revision,
                    "target_revision": promoted_revision_name,
                    "authority_scope": authority_scope,
                    "version_hash": version_metadata.content_hash,
                }
            )
            promotion_audit = _audit(
                "promotion-event",
                actor_id="promoter-actor",
                actor_type="user",
                actor_user_id=promoter.id,
                actor_role=promoter.role,
                authority_scope=authority_scope,
                reason="Synthetic source-backed promotion",
            )
            result = service.promote_source_backed(
                rule_id=rule_id,
                source_revision=source_revision_name,
                revision=promoted_revision_name,
                version_metadata=version_metadata,
                receipt_id="promotion-receipt-1",
                command_identity=command_identity,
                request_hash=request_hash,
                audit=promotion_audit,
                completed_at=datetime(2031, 2, 3, 4, 5, 7, tzinfo=timezone.utc),
            )
            unit_of_work.commit()

    with Session(service_engine) as replay_session, GovernedUnitOfWork(
        replay_session
    ) as replay_uow:
            replay = RuleRegistryService(replay_uow).promote_source_backed(
                rule_id=rule_id,
                source_revision=source_revision_name,
                revision=promoted_revision_name,
                version_metadata=version_metadata,
                receipt_id="promotion-receipt-2",
                command_identity=command_identity,
                request_hash=request_hash,
                audit=promotion_audit,
                completed_at=datetime(2031, 2, 3, 4, 5, 8, tzinfo=timezone.utc),
            )
            assert replay == result

    with Session(service_engine) as conflict_session, GovernedUnitOfWork(
        conflict_session
    ) as conflict_uow, pytest.raises(ValueError, match="idempotency conflict"):
        RuleRegistryService(conflict_uow).promote_source_backed(
            rule_id=rule_id,
            source_revision=source_revision_name,
            revision=promoted_revision_name,
            version_metadata=version_metadata,
            receipt_id="promotion-receipt-3",
            command_identity=command_identity,
            request_hash=_promotion_request_hash(
                {
                    "rule_id": rule_id,
                    "source_revision": source_revision_name,
                    "target_revision": promoted_revision_name,
                    "authority_scope": authority_scope,
                    "version_hash": "different",
                }
            ),
            audit=promotion_audit,
            completed_at=datetime(2031, 2, 3, 4, 5, 9, tzinfo=timezone.utc),
        )

    in_progress_identity = _promotion_identity(rule_id, "promotion-key-2")
    in_progress_request_hash = _promotion_request_hash(
        {
            "rule_id": rule_id,
            "source_revision": source_revision_name,
            "target_revision": promoted_revision_name,
            "authority_scope": authority_scope,
            "version_hash": version_metadata.content_hash,
        }
    )
    with Session(service_engine) as in_progress_session, GovernedUnitOfWork(
        in_progress_session
    ) as in_progress_uow:
            IdempotencyRepository(in_progress_session).add_reserved(
                receipt_id="promotion-receipt-4",
                identity=in_progress_identity,
                request_hash=in_progress_request_hash,
                correlation_id=promotion_audit.correlation_id,
                schema_version=promotion_audit.schema_version,
                software_version=promotion_audit.software_version,
                created_at=promotion_audit.created_at,
            )
            with pytest.raises(RuntimeError, match="already in progress"):
                RuleRegistryService(in_progress_uow).promote_source_backed(
                    rule_id=rule_id,
                    source_revision=source_revision_name,
                    revision=promoted_revision_name,
                    version_metadata=version_metadata,
                    receipt_id="promotion-receipt-5",
                    command_identity=in_progress_identity,
                    request_hash=in_progress_request_hash,
                    audit=promotion_audit,
                    completed_at=datetime(
                        2031, 2, 3, 4, 5, 10, tzinfo=timezone.utc
                    ),
                )

    with Session(service_engine) as read_session:
        repository = RuleRegistryRepository(read_session)
        promoted = repository.get_revision(rule_id, promoted_revision_name)
        source = repository.get_revision(rule_id, source_revision_name)
        assert promoted is not None
        assert source is not None
        assert promoted.evidence_class is EvidenceClass.SOURCE_BACKED
        assert promoted.status is RuleLifecycleStatus.DRAFT
        assert promoted.supersedes_revision_id == source.id
        assert promoted.content_hash == version_metadata.content_hash
        assert len(promoted.evidence_references) == 2
        assert promoted.evidence_references[0].evidence_id == "SOURCE_BACKED_EVIDENCE_A"
        assert promoted.evidence_references[1].evidence_revision == "7"


def test_source_backed_promotion_rejects_verifier_same_as_promoter(
    service_engine,
) -> None:
    rule_id = "SOURCE_BACKED_PROMOTION_DENIAL_RULE"
    authority_scope = VerificationScopeSnapshot(
        project="synthetic-project"
    ).as_dict()

    with Session(service_engine) as session, GovernedUnitOfWork(
        session
    ) as unit_of_work:
        users = _seed_promotion_users(session)
        submitter = users["submitter"]
        verifier = users["verifier"]
        grantor = users["grantor"]
        source_audit = _audit(
            "source-denial-draft-event",
            actor_id="submitter-actor",
            actor_type="user",
            actor_user_id=submitter.id,
            actor_role=submitter.role,
            authority_scope=authority_scope,
            reason="Synthetic source-backed denial draft",
        )
        draft_audit = _audit(
            "source-denial-draft-revision-event",
            actor_id="submitter-actor",
            actor_type="user",
            actor_user_id=submitter.id,
            actor_role=submitter.role,
            authority_scope=authority_scope,
            reason="Synthetic source-backed denial draft",
        )
        service = RuleRegistryService(unit_of_work)
        _create_identity(
            service,
            rule_id,
            "source-denial-root-event",
            audit=source_audit,
        )
        evidence_reference = EvidenceReferenceDraft(
            evidence_id="SOURCE_BACKED_DENIAL_EVIDENCE",
            evidence_revision="3",
            evidence_class=EvidenceClass.UNRESOLVED,
            lifecycle_status=RuleLifecycleStatus.DRAFT,
            created_by_actor_id="submitter-actor",
            created_by_user_id=submitter.id,
            reference_uri="urn:source-backed:denial",
        )
        source_revision = _create_draft(
            service,
            rule_id,
            "draft-1",
            "source-denial-draft-revision-event",
            audit=draft_audit,
            evidence_references=(evidence_reference,),
        )
        verified_decision = _verified_decision_for_reference(
            session,
            evidence_reference=source_revision.evidence_references[0],
            verifier=verifier,
            grantor=grantor,
            verification_id="SOURCE_BACKED_DENIAL_EVIDENCE-verification",
        )
        version_metadata = _source_backed_version(
            rule_id=rule_id,
            source_revision=source_revision,
            target_revision="source-backed-denied",
            evidence_pins=[
                {
                    "evidence_reference_id": source_revision.evidence_references[0].id,
                    "evidence_id": source_revision.evidence_references[0].evidence_id,
                    "evidence_revision": source_revision.evidence_references[0].evidence_revision,
                    "verification_decision_id": verified_decision.id,
                    "verification_revision_number": verified_decision.revision_number,
                    "verifier_user_id": verified_decision.verifier_user_id,
                }
            ],
            authority_scope=authority_scope,
        )
        denial_audit = _audit(
            "promotion-denial-event",
            actor_id="verifier-actor",
            actor_type="user",
            actor_user_id=verifier.id,
            actor_role=verifier.role,
            authority_scope=authority_scope,
            reason="Synthetic source-backed promotion denial",
        )
        result = RuleRegistryService(unit_of_work).promote_source_backed(
            rule_id=rule_id,
            source_revision="draft-1",
            revision="source-backed-denied",
            version_metadata=version_metadata,
            receipt_id="promotion-denial-receipt",
            command_identity=_promotion_identity(rule_id, "promotion-denial-key"),
            request_hash=_promotion_request_hash(
                {
                    "rule_id": rule_id,
                    "source_revision": "draft-1",
                    "target_revision": "source-backed-denied",
                    "authority_scope": authority_scope,
                    "version_hash": version_metadata.content_hash,
                }
            ),
            audit=denial_audit,
            completed_at=datetime(2031, 2, 3, 4, 5, 11, tzinfo=timezone.utc),
        )
        unit_of_work.commit()

    with Session(service_engine) as read_session:
        assert result.result_type == "engineering_rule_promotion_denial"
        assert result.result_revision == "denied"
        assert (
            RuleRegistryRepository(read_session).get_revision(
                rule_id, "source-backed-denied"
            )
            is None
        )


def test_source_backed_enablement_and_activation_create_lifecycle_history(
    service_engine,
) -> None:
    rule_id = "SOURCE_BACKED_LIFECYCLE_RULE"
    authority_scope = VerificationScopeSnapshot(
        project="synthetic-project"
    ).as_dict()

    with Session(service_engine) as session:
        users = _seed_promotion_users(session)
        submitter = users["submitter"]
        verifier = users["verifier"]
        promoter = users["promoter"]
        grantor = users["grantor"]
        submitter_actor_id = submitter.email
        submitter_user_id = submitter.id
        submitter_role = submitter.role
        promoter_actor_id = promoter.email
        promoter_user_id = promoter.id
        promoter_role = promoter.role
        session.commit()
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            _create_identity(
                service,
                rule_id,
                "source-lifecycle-root-event",
            )
            source_revision = _create_draft(
                service,
                rule_id,
                "source-backed-draft",
                "source-lifecycle-draft-event",
                evidence_class=EvidenceClass.SOURCE_BACKED,
                allow_source_backed=True,
                audit=_audit(
                    "source-lifecycle-draft-audit",
                    actor_id=submitter_actor_id,
                    actor_type="user",
                    actor_user_id=submitter_user_id,
                    actor_role=submitter_role,
                    authority_scope=authority_scope,
                    reason="Synthetic source-backed lifecycle draft",
                ),
                evidence_references=(
                    EvidenceReferenceDraft(
                        evidence_id="SOURCE_BACKED_LIFECYCLE_EVIDENCE",
                        evidence_revision="11",
                        evidence_class=EvidenceClass.UNRESOLVED,
                        lifecycle_status=RuleLifecycleStatus.DRAFT,
                        created_by_actor_id="submitter-actor",
                        created_by_user_id=submitter_user_id,
                        reference_uri="urn:source-backed:lifecycle",
                    ),
                ),
            )
            source_revision_id = source_revision.id
            verified_decision = _verified_decision_for_reference(
                session,
                evidence_reference=source_revision.evidence_references[0],
                verifier=verifier,
                grantor=grantor,
                verification_id="SOURCE_BACKED_LIFECYCLE_EVIDENCE-verification",
            )
            enable_basis = _enablement_basis(
                rule_id=rule_id,
                source_revision=source_revision,
                evidence_references=(
                    source_revision.evidence_references[0],
                ),
                verified_decisions=(verified_decision,),
                authority_scope=authority_scope,
            )
            enable_identity = _lifecycle_identity(
                rule_id,
                RuleRegistryService.ENABLEMENT_COMMAND_NAMESPACE,
                "enablement-key-1",
            )
            enable_request_hash = _lifecycle_request_hash(
                {
                    "command": "ENABLE",
                    "rule_id": rule_id,
                    "source_revision": source_revision.revision,
                    "basis_content_hash": enable_basis["content_hash"],
                    "scope_snapshot": authority_scope,
                }
            )
            enable_result = service.enable_source_backed(
                rule_id=rule_id,
                source_revision=source_revision.revision,
                receipt_id="enablement-receipt-1",
                command_identity=enable_identity,
                request_hash=enable_request_hash,
                audit=_audit(
                    "source-lifecycle-enable-audit",
                    actor_id=promoter_actor_id,
                    actor_type="user",
                    actor_user_id=promoter_user_id,
                    actor_role=promoter_role,
                    authority_scope=authority_scope,
                    reason="Synthetic source-backed enablement",
                ),
                effective_from=datetime(
                    2031, 2, 3, 4, 5, 7, tzinfo=timezone.utc
                ),
                expires_at=datetime(
                    2031, 12, 31, 23, 59, 59, tzinfo=timezone.utc
                ),
                completed_at=datetime(
                    2031, 2, 3, 4, 5, 8, tzinfo=timezone.utc
                ),
            )
            unit_of_work.commit()

    with Session(service_engine) as session:
        with GovernedUnitOfWork(session) as replay_uow:
            replay_result = RuleRegistryService(replay_uow).enable_source_backed(
                rule_id=rule_id,
                source_revision="source-backed-draft",
                receipt_id="enablement-receipt-2",
                command_identity=enable_identity,
                request_hash=enable_request_hash,
                audit=_audit(
                    "source-lifecycle-enable-audit",
                    actor_id=promoter_actor_id,
                    actor_type="user",
                    actor_user_id=promoter_user_id,
                    actor_role=promoter_role,
                    authority_scope=authority_scope,
                    reason="Synthetic source-backed enablement replay",
                ),
                effective_from=datetime(2031, 2, 3, 4, 5, 7, tzinfo=timezone.utc),
                expires_at=datetime(2031, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
                completed_at=datetime(2031, 2, 3, 4, 5, 9, tzinfo=timezone.utc),
            )
        assert replay_result == enable_result

    with Session(service_engine) as session, GovernedUnitOfWork(
        session
    ) as unit_of_work:
        activate_identity = _lifecycle_identity(
            rule_id,
            RuleRegistryService.ACTIVATION_COMMAND_NAMESPACE,
            "activation-key-1",
        )
        activate_request_hash = _lifecycle_request_hash(
            {
                "command": "ACTIVATE",
                "rule_id": rule_id,
                "source_revision": "source-backed-draft",
                "basis_content_hash": enable_basis["content_hash"],
                "scope_snapshot": authority_scope,
            }
        )
        activate_result = RuleRegistryService(unit_of_work).activate_source_backed(
            rule_id=rule_id,
            source_revision="source-backed-draft",
            receipt_id="activation-receipt-1",
            command_identity=activate_identity,
            request_hash=activate_request_hash,
            audit=_audit(
                "source-lifecycle-activate-audit",
                actor_id=promoter_actor_id,
                actor_type="user",
                actor_user_id=promoter_user_id,
                actor_role=promoter_role,
                authority_scope=authority_scope,
                reason="Synthetic source-backed activation",
            ),
            effective_from=datetime(
                2031, 2, 3, 4, 5, 10, tzinfo=timezone.utc
            ),
            expires_at=datetime(
                2031, 12, 31, 23, 59, 59, tzinfo=timezone.utc
            ),
            completed_at=datetime(
                2031, 2, 3, 4, 5, 11, tzinfo=timezone.utc
            ),
        )
        unit_of_work.commit()

    with Session(service_engine) as session, GovernedUnitOfWork(
        session
    ) as replay_uow:
        replay_result = RuleRegistryService(replay_uow).activate_source_backed(
            rule_id=rule_id,
            source_revision="source-backed-draft",
            receipt_id="activation-receipt-2",
            command_identity=activate_identity,
            request_hash=activate_request_hash,
            audit=_audit(
                "source-lifecycle-activate-audit",
                actor_id=promoter_actor_id,
                actor_type="user",
                actor_user_id=promoter_user_id,
                actor_role=promoter_role,
                authority_scope=authority_scope,
                reason="Synthetic source-backed activation replay",
            ),
            effective_from=datetime(2031, 2, 3, 4, 5, 10, tzinfo=timezone.utc),
            expires_at=datetime(2031, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
            completed_at=datetime(2031, 2, 3, 4, 5, 12, tzinfo=timezone.utc),
        )
    assert replay_result == activate_result

    with Session(service_engine) as session:
        repository = RuleRegistryRepository(session)
        enable_event = session.get(RuleLifecycleEvent, int(enable_result.result_id))
        activate_event = session.get(RuleLifecycleEvent, int(activate_result.result_id))
        assert enable_event is not None
        assert activate_event is not None
        assert enable_event.event_type is RuleLifecycleEventType.ENABLE
        assert activate_event.event_type is RuleLifecycleEventType.ACTIVATE
        assert enable_event.scope_snapshot == authority_scope
        assert activate_event.scope_snapshot == authority_scope
        latest_event = repository.get_latest_lifecycle_event(
            engineering_rule_revision_id=source_revision_id,
            scope_snapshot=authority_scope,
            event_types=(
                RuleLifecycleEventType.ENABLE,
                RuleLifecycleEventType.ACTIVATE,
            ),
        )
        assert latest_event is not None
        assert latest_event.event_type is RuleLifecycleEventType.ACTIVATE
        assert latest_event.basis_snapshot["content_hash"] == enable_basis["content_hash"]


def test_source_backed_activation_requires_prior_enablement(service_engine) -> None:
    rule_id = "SOURCE_BACKED_ACTIVATION_BLOCKED_RULE"
    authority_scope = VerificationScopeSnapshot(
        project="synthetic-project"
    ).as_dict()

    with Session(service_engine) as session, GovernedUnitOfWork(
        session
    ) as unit_of_work:
        users = _seed_promotion_users(session)
        submitter = users["submitter"]
        verifier = users["verifier"]
        grantor = users["grantor"]
        promoter = users["promoter"]
        service = RuleRegistryService(unit_of_work)
        _create_identity(service, rule_id, "activation-block-root-event")
        source_revision = _create_draft(
            service,
            rule_id,
            "activation-block-draft",
            "activation-block-draft-event",
            evidence_class=EvidenceClass.SOURCE_BACKED,
            allow_source_backed=True,
            audit=_audit(
                "activation-block-draft-audit",
                actor_id=submitter.email,
                actor_type="user",
                actor_user_id=submitter.id,
                actor_role=submitter.role,
                authority_scope=authority_scope,
                reason="Synthetic activation block draft",
            ),
            evidence_references=(
                EvidenceReferenceDraft(
                    evidence_id="ACTIVATION_BLOCK_EVIDENCE",
                    evidence_revision="21",
                    evidence_class=EvidenceClass.UNRESOLVED,
                    lifecycle_status=RuleLifecycleStatus.DRAFT,
                    created_by_actor_id="submitter-actor",
                    created_by_user_id=submitter.id,
                    reference_uri="urn:source-backed:activation-block",
                ),
            ),
        )
        source_revision_id = source_revision.id
        _verified_decision_for_reference(
            session,
            evidence_reference=source_revision.evidence_references[0],
            verifier=verifier,
            grantor=grantor,
            verification_id="ACTIVATION_BLOCK_EVIDENCE-verification",
        )
        activation_result = service.activate_source_backed(
            rule_id=rule_id,
            source_revision="activation-block-draft",
            receipt_id="activation-block-receipt",
            command_identity=_lifecycle_identity(
                rule_id,
                RuleRegistryService.ACTIVATION_COMMAND_NAMESPACE,
                "activation-block-key",
            ),
            request_hash=_lifecycle_request_hash(
                {
                    "command": "ACTIVATE",
                    "rule_id": rule_id,
                    "source_revision": "activation-block-draft",
                    "scope_snapshot": authority_scope,
                }
            ),
            audit=_audit(
                "activation-block-audit",
                actor_id=promoter.email,
                actor_type="user",
                actor_user_id=promoter.id,
                actor_role=promoter.role,
                authority_scope=authority_scope,
                reason="Synthetic activation block",
            ),
            effective_from=datetime(2031, 2, 3, 4, 5, 13, tzinfo=timezone.utc),
            expires_at=None,
            completed_at=datetime(2031, 2, 3, 4, 5, 14, tzinfo=timezone.utc),
        )
        unit_of_work.commit()

    with Session(service_engine) as read_session:
        assert activation_result.result_type == "engineering_rule_lifecycle_denial"
        assert activation_result.result_revision == "denied"
        repository = RuleRegistryRepository(read_session)
        assert (
            repository.get_latest_lifecycle_event(
                engineering_rule_revision_id=source_revision_id,
                scope_snapshot=authority_scope,
                event_types=(
                    RuleLifecycleEventType.ENABLE,
                    RuleLifecycleEventType.ACTIVATE,
                ),
            )
            is None
        )


def test_source_backed_activation_fails_closed_after_evidence_correction(
    service_engine,
) -> None:
    rule_id = "SOURCE_BACKED_CORRECTION_RULE"
    authority_scope = VerificationScopeSnapshot(
        project="synthetic-project"
    ).as_dict()

    with Session(service_engine) as session, GovernedUnitOfWork(
        session
    ) as unit_of_work:
        users = _seed_promotion_users(session)
        submitter = users["submitter"]
        verifier = users["verifier"]
        promoter = users["promoter"]
        grantor = users["grantor"]
        submitter_actor_id = submitter.email
        submitter_user_id = submitter.id
        submitter_role = submitter.role
        verifier_user_id = verifier.id
        promoter_actor_id = promoter.email
        promoter_user_id = promoter.id
        promoter_role = promoter.role
        service = RuleRegistryService(unit_of_work)
        _create_identity(service, rule_id, "correction-root-event")
        source_revision = _create_draft(
            service,
            rule_id,
            "correction-draft",
            "correction-draft-event",
            evidence_class=EvidenceClass.SOURCE_BACKED,
            allow_source_backed=True,
            audit=_audit(
                "correction-draft-audit",
                actor_id=submitter_actor_id,
                actor_type="user",
                actor_user_id=submitter_user_id,
                actor_role=submitter_role,
                authority_scope=authority_scope,
                reason="Synthetic correction draft",
            ),
            evidence_references=(
                EvidenceReferenceDraft(
                    evidence_id="CORRECTION_EVIDENCE",
                    evidence_revision="31",
                    evidence_class=EvidenceClass.UNRESOLVED,
                    lifecycle_status=RuleLifecycleStatus.DRAFT,
                    created_by_actor_id="submitter-actor",
                    created_by_user_id=submitter_user_id,
                    reference_uri="urn:source-backed:correction",
                ),
            ),
        )
        source_revision_id = source_revision.id
        source_evidence_reference_id = source_revision.evidence_references[0].id
        prior_decision = _verified_decision_for_reference(
            session,
            evidence_reference=source_revision.evidence_references[0],
            verifier=verifier,
            grantor=grantor,
            verification_id="CORRECTION_EVIDENCE-verification",
        )
        prior_decision_id = prior_decision.id
        prior_decision_delegation_id = (
            prior_decision.evidence_verification_delegation_id
        )
        prior_decision_authority_snapshot = dict(prior_decision.authority_snapshot)
        prior_decision_authority_snapshot_hash = (
            prior_decision.authority_snapshot_content_hash
        )
        service.enable_source_backed(
            rule_id=rule_id,
            source_revision="correction-draft",
            receipt_id="correction-enable-receipt",
            command_identity=_lifecycle_identity(
                rule_id,
                RuleRegistryService.ENABLEMENT_COMMAND_NAMESPACE,
                "correction-enable-key",
            ),
            request_hash=_lifecycle_request_hash(
                {
                    "command": "ENABLE",
                    "rule_id": rule_id,
                    "source_revision": "correction-draft",
                    "scope_snapshot": authority_scope,
                }
            ),
            audit=_audit(
                "correction-enable-audit",
                actor_id=promoter_actor_id,
                actor_type="user",
                actor_user_id=promoter_user_id,
                actor_role=promoter_role,
                authority_scope=authority_scope,
                reason="Synthetic correction enablement",
            ),
            effective_from=datetime(2031, 2, 3, 4, 5, 15, tzinfo=timezone.utc),
            expires_at=None,
            completed_at=datetime(2031, 2, 3, 4, 5, 16, tzinfo=timezone.utc),
        )
        unit_of_work.commit()

    with Session(service_engine) as session, GovernedUnitOfWork(
        session
    ) as unit_of_work:
        repository = EvidenceVerificationRepository(session)
        repository.create_verification_decision(
            draft=EvidenceVerificationDecisionDraft(
                verification_id="CORRECTION_EVIDENCE-verification",
                revision_number=2,
                evidence_reference_id=source_evidence_reference_id,
                evidence_verification_delegation_id=prior_decision_delegation_id,
                verifier_user_id=verifier_user_id,
                authority_snapshot=prior_decision_authority_snapshot,
                decision_reason="Corrected VERIFIED decision",
                decided_at=datetime(
                    2031, 2, 3, 4, 5, 17, tzinfo=timezone.utc
                ),
                policy_identifier="SDS-115",
                policy_version="0.1 Draft",
                correlation_id="CORRECTION_EVIDENCE-verification-correlation",
                supersedes_verification_decision_id=prior_decision_id,
                created_by_user_id=verifier_user_id,
                created_by_actor_id="verifier-actor",
                schema_version="verification-test-v1",
                canonicalization_version="verification-canonical-v1",
                hash_algorithm="sha256",
                content_hash=hashlib.sha256(
                    json.dumps(
                        {
                            "verification_id": "CORRECTION_EVIDENCE-verification",
                            "evidence_reference_id": source_evidence_reference_id,
                            "delegation_id": prior_decision_delegation_id,
                            "verifier_user_id": verifier_user_id,
                            "authority_snapshot_hash": prior_decision_authority_snapshot_hash,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                software_version="test-build",
            )
        )
        activation_result = RuleRegistryService(unit_of_work).activate_source_backed(
            rule_id=rule_id,
            source_revision="correction-draft",
            receipt_id="correction-activation-receipt",
            command_identity=_lifecycle_identity(
                rule_id,
                RuleRegistryService.ACTIVATION_COMMAND_NAMESPACE,
                "correction-activation-key",
            ),
            request_hash=_lifecycle_request_hash(
                {
                    "command": "ACTIVATE",
                    "rule_id": rule_id,
                    "source_revision": "correction-draft",
                    "scope_snapshot": authority_scope,
                }
            ),
            audit=_audit(
                "correction-activation-audit",
                actor_id=promoter_actor_id,
                actor_type="user",
                actor_user_id=promoter_user_id,
                actor_role=promoter_role,
                authority_scope=authority_scope,
                reason="Synthetic correction activation",
            ),
            effective_from=datetime(2031, 2, 3, 4, 5, 18, tzinfo=timezone.utc),
            expires_at=None,
            completed_at=datetime(2031, 2, 3, 4, 5, 19, tzinfo=timezone.utc),
        )
        unit_of_work.commit()

    with Session(service_engine) as read_session:
        assert activation_result.result_type == "engineering_rule_lifecycle_denial"
        assert activation_result.result_revision == "denied"
        repository = RuleRegistryRepository(read_session)
        latest_event = repository.get_latest_lifecycle_event(
            engineering_rule_revision_id=source_revision_id,
            scope_snapshot=authority_scope,
            event_types=(
                RuleLifecycleEventType.ENABLE,
                RuleLifecycleEventType.ACTIVATE,
            ),
        )
        assert latest_event is not None
        assert latest_event.event_type is RuleLifecycleEventType.ENABLE


def test_enabled_draft_creation_is_rejected(service_engine) -> None:
    with Session(service_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            _create_identity(service, "ENABLED_REJECTED", "enabled-root-event")
            with pytest.raises(RegistryAuthorityError):
                _create_draft(
                    service,
                    "ENABLED_REJECTED",
                    "draft-1",
                    "enabled-revision-event",
                    enabled=True,
                )


def test_activation_and_evidence_promotion_are_not_exposed(service_engine) -> None:
    with Session(service_engine) as session:
        service = RuleRegistryService(GovernedUnitOfWork(session))
        assert not hasattr(service, "activate")
        assert not hasattr(service, "activate_revision")
        assert not hasattr(service, "verify_evidence")
        assert not hasattr(service, "promote_evidence")
        assert hasattr(service, "enable_source_backed")
        assert hasattr(service, "activate_source_backed")
        assert hasattr(service, "promote_source_backed")


def test_explicit_uow_rollback_removes_draft_and_audit(service_engine) -> None:
    with Session(service_engine) as setup_session:
        with GovernedUnitOfWork(setup_session) as setup_uow:
            _create_identity(
                RuleRegistryService(setup_uow),
                "ROLLBACK_DRAFT_RULE",
                "rollback-root-event",
            )
            setup_uow.commit()

    with Session(service_engine) as session:
        unit_of_work = GovernedUnitOfWork(session)
        _create_draft(
            RuleRegistryService(unit_of_work),
            "ROLLBACK_DRAFT_RULE",
            "draft-1",
            "rollback-draft-event",
        )
        unit_of_work.rollback()

    with Session(service_engine) as read_session:
        assert RuleRegistryRepository(read_session).get_revision(
            "ROLLBACK_DRAFT_RULE", "draft-1"
        ) is None
        assert GovernanceRepository(read_session).get_by_event_id(
            "rollback-draft-event"
        ) is None


def test_finalized_uow_refuses_service_write_before_registry_flush(
    service_engine,
) -> None:
    with Session(service_engine) as session:
        unit_of_work = GovernedUnitOfWork(session)
        service = RuleRegistryService(unit_of_work)
        unit_of_work.rollback()
        with pytest.raises(RuntimeError, match="already finalized"):
            _create_identity(service, "AFTER_FINALIZATION", "after-final-event")

    with Session(service_engine) as read_session:
        assert RuleRegistryRepository(read_session).get_by_rule_id(
            "AFTER_FINALIZATION"
        ) is None


def test_audit_metadata_and_revision_identity_persist_exactly(service_engine) -> None:
    audit = _audit("metadata-revision-event", idempotency_key="trace-only-key")
    with Session(service_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            _create_identity(service, "METADATA_RULE", "metadata-root-event")
            revision = _create_draft(
                service,
                "METADATA_RULE",
                "draft-7",
                "unused-event",
                audit=audit,
            )
            expected_hash = revision.content_hash
            unit_of_work.commit()

    with Session(service_engine) as read_session:
        persisted = GovernanceRepository(read_session).get_by_event_id(
            "metadata-revision-event"
        )
        assert persisted is not None
        assert persisted.entity_type == "engineering_rule_revision"
        assert persisted.entity_id == "METADATA_RULE"
        assert persisted.entity_revision == "draft-7"
        assert persisted.action == "CREATE_DRAFT_RULE_REVISION"
        assert persisted.actor_id == "synthetic-actor"
        assert persisted.actor_type == "service"
        assert persisted.actor_role == "synthetic-role"
        assert persisted.authority_scope == {"project": "synthetic-project"}
        assert persisted.reason == "Synthetic draft command"
        assert persisted.correlation_id == "synthetic-correlation"
        assert persisted.idempotency_key == "trace-only-key"
        assert persisted.new_content_hash == expected_hash
        assert persisted.detail["lifecycle_status"] == "DRAFT"
        assert persisted.detail["evidence_class"] == "UNRESOLVED"
        assert persisted.detail["enabled"] is False


def test_idempotency_metadata_does_not_deduplicate_commands(service_engine) -> None:
    for suffix in ("ONE", "TWO"):
        with Session(service_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                RuleRegistryService(unit_of_work).create_identity(
                    rule_id=f"TRACE_METADATA_RULE_{suffix}",
                    audit=_audit(
                        f"trace-event-{suffix.lower()}",
                        idempotency_key="same-non-authoritative-key",
                    ),
                )
                unit_of_work.commit()

    with Session(service_engine) as read_session:
        assert read_session.scalar(select(func.count(EngineeringRule.id))) == 2
        assert read_session.scalar(
            select(func.count(GovernedAuditEvent.id)).where(
                GovernedAuditEvent.idempotency_key
                == "same-non-authoritative-key"
            )
        ) == 2


def test_service_is_threshold_free_and_has_no_forbidden_dependencies() -> None:
    service_path = (
        Path(__file__).parents[1]
        / "app"
        / "application"
        / "rule_registry_service.py"
    )
    source = service_path.read_text(encoding="utf-8")
    forbidden = (
        ".commit(",
        ".rollback(",
        "FastAPI",
        "fastapi",
        "rules_engine",
        "DEFAULT_RULES",
        "app.api",
    )
    assert all(token not in source for token in forbidden)
    assert "min_value" not in inspect.signature(
        RuleRegistryService.create_draft_revision
    ).parameters
    assert "max_value" not in inspect.signature(
        RuleRegistryService.create_draft_revision
    ).parameters
    assert "operator" not in inspect.signature(
        RuleRegistryService.create_draft_revision
    ).parameters


def test_service_does_not_expose_evidence_verification_fields() -> None:
    parameters = inspect.signature(
        RuleRegistryService.create_draft_revision
    ).parameters
    assert "verified_at" not in parameters
    assert "verified_by_actor_id" not in parameters
    assert "approved_at" not in parameters
    assert "approved_by_actor_id" not in parameters


def test_evidence_rows_remain_non_authoritative(service_engine) -> None:
    evidence = EvidenceReferenceDraft(
        evidence_id="TRACE_ONLY_EVIDENCE",
        evidence_revision="draft-1",
        evidence_class=EvidenceClass.PROPOSED,
        lifecycle_status=RuleLifecycleStatus.REVIEW,
        created_by_actor_id="synthetic-actor",
    )
    with Session(service_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            _create_identity(service, "EVIDENCE_RULE", "evidence-root-event")
            _create_draft(
                service,
                "EVIDENCE_RULE",
                "draft-1",
                "evidence-revision-event",
                evidence_class=EvidenceClass.PROPOSED,
                evidence_references=(evidence,),
            )
            unit_of_work.commit()

    with Session(service_engine) as read_session:
        reference = read_session.scalar(select(EvidenceReference))
        assert reference is not None
        assert reference.evidence_class is EvidenceClass.PROPOSED
        assert reference.lifecycle_status is RuleLifecycleStatus.REVIEW
        assert reference.verified_at is None
        assert reference.approved_at is None
