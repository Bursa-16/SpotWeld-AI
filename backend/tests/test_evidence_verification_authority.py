from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest
from app.application.evidence_verification_service import EvidenceVerificationService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import GovernedAuditMetadata
from app.db.session import Base
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    RuleLifecycleStatus,
)
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.domain.rule_registry_types import (
    EvidenceReferenceDraft,
    EvidenceRevisionDraft,
    MissingHandling,
    RuleCategory,
    SafeDefault,
)
from app.domain.verification_types import (
    EvidenceVerificationCommand,
    EvidenceVerificationDecisionDraft,
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
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

NOW = datetime(2035, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
LATER = datetime(2035, 1, 2, 3, 5, 6, tzinfo=timezone.utc)
PAST = datetime(2034, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


@pytest.fixture()
def database():
    yield


@pytest.fixture()
def verification_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _user(session: Session, *, email: str, full_name: str, role: str) -> User:
    user = User(
        email=email,
        full_name=full_name,
        password_hash="hash",
        role=role,
        is_active=True,
    )
    session.add(user)
    session.flush()
    session.expunge(user)
    return user


def _rule_with_evidence(
    session: Session,
    *,
    rule_id: str,
    revision: str,
    submitter: User,
    evidence_id: str,
    evidence_revision: str,
) -> EvidenceReference:
    repository = RuleRegistryRepository(session)
    rule = repository.create_rule(
        rule_id=rule_id,
        created_by_actor_id="submitter-actor",
        created_by_user_id=submitter.id,
    )
    revision_row = repository.create_revision(
        engineering_rule=rule,
        revision=revision,
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
            content_hash=hashlib.sha256(f"{rule_id}:{revision}".encode()).hexdigest(),
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
    evidence_reference = revision_row.evidence_references[0]
    session.expunge(evidence_reference)
    return evidence_reference


def _delegation(
    *,
    delegation_id: str,
    revision_number: int,
    verifier: User,
    grantor: User,
    scope: VerificationScopeSnapshot,
    effective_from: datetime,
    expires_at: datetime | None,
    revoked_by_user_id: int | None,
    revoked_at: datetime | None,
    revoked_reason: str | None,
    status: VerificationDelegationStatus,
    supersedes_delegation_id: int | None = None,
) -> EvidenceVerificationDelegationDraft:
    return EvidenceVerificationDelegationDraft(
        delegation_id=delegation_id,
        revision_number=revision_number,
        verifier_user_id=verifier.id,
        granted_by_user_id=grantor.id,
        revoked_by_user_id=revoked_by_user_id,
        scope_snapshot=scope,
        effective_from=effective_from,
        expires_at=expires_at,
        revoked_at=revoked_at,
        revoked_reason=revoked_reason,
        status=status,
        supersedes_delegation_id=supersedes_delegation_id,
        created_by_user_id=grantor.id,
        created_by_actor_id="grantor-actor",
        schema_version="verification-delegation-v1",
        canonicalization_version="canonical-test-v1",
        hash_algorithm="sha256",
        content_hash=hashlib.sha256(
            json.dumps(
                {
                    "delegation_id": delegation_id,
                    "revision_number": revision_number,
                    "scope": scope.as_dict(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        software_version="test-build",
    )


def _audit(
    *,
    event_id: str,
    actor: User,
    scope: VerificationScopeSnapshot,
    reason: str,
    correlation_id: str = "verification-correlation",
) -> GovernedAuditMetadata:
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id=f"user:{actor.id}",
        actor_type="user",
        actor_role=actor.role,
        authority_scope=scope.as_dict(),
        reason=reason,
        correlation_id=correlation_id,
        schema_version="verification-audit-v1",
        software_version="test-build",
        canonicalization_version="canonical-test-v1",
        hash_algorithm="sha256",
        created_at=NOW,
        actor_user_id=actor.id,
        idempotency_key="verification-key",
    )


def _identity(*, key: str, scope: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace="registry.evidence.verification",
        command_scope=scope,
        idempotency_key=key,
    )


def _request_hash(*, payload: str) -> CanonicalRequestHash:
    return CanonicalRequestHash(
        value=hashlib.sha256(payload.encode()).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="canonical-test-v1",
    )


def _command(evidence_reference_id: int, verifier: User, scope: VerificationScopeSnapshot) -> EvidenceVerificationCommand:
    return EvidenceVerificationCommand(
        evidence_reference_id=evidence_reference_id,
        verifier_user_id=verifier.id,
        requested_scope=scope,
        decision_reason="verification passed",
    )


def _prepare_success_case(session: Session):
    submitter = _user(
        session,
        email="submitter@example.com",
        full_name="Submitter User",
        role="Submitter",
    )
    verifier = _user(
        session,
        email="verifier@example.com",
        full_name="Verifier User",
        role="Verifier",
    )
    grantor = _user(
        session,
        email="grantor@example.com",
        full_name="Grantor User",
        role="Security/Governance Owner",
    )
    evidence = _rule_with_evidence(
        session,
        rule_id="VERIFICATION_RULE",
        revision="draft-1",
        submitter=submitter,
        evidence_id="EVIDENCE-A",
        evidence_revision="document-1",
    )
    session.expunge_all()
    session.commit()
    return submitter, verifier, grantor, evidence


def _verify(
    session: Session,
    *,
    command: EvidenceVerificationCommand,
    audit_actor: User,
    scope: VerificationScopeSnapshot,
    verification_id: str,
    receipt_id: str = "receipt-1",
    idempotency_key: str = "verification-key",
    request_payload: str = "verification-request",
):
    with GovernedUnitOfWork(session) as unit_of_work:
        service = EvidenceVerificationService(unit_of_work)
        result = service.verify_evidence(
            command=command,
            receipt_id=receipt_id,
            command_identity=_identity(key=idempotency_key, scope=verification_id),
            request_hash=_request_hash(payload=request_payload),
            audit=_audit(
                event_id=f"{verification_id}-audit",
                actor=audit_actor,
                scope=scope,
                reason=command.decision_reason,
            ),
            verification_id=verification_id,
            completed_at=LATER,
        )
        unit_of_work.commit()
        return result


def test_verified_success_creates_decision_and_preserves_legacy_metadata(
    verification_engine,
) -> None:
    with Session(verification_engine) as session:
        _submitter, verifier, grantor, evidence = _prepare_success_case(session)
        scope = VerificationScopeSnapshot(
            customer="customer-a",
            project="project-a",
            site="site-a",
            machine="machine-a",
        )
        delegation = EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-A",
                revision_number=1,
                verifier=verifier,
                grantor=grantor,
                scope=scope,
                effective_from=PAST,
                expires_at=None,
                revoked_by_user_id=None,
                revoked_at=None,
                revoked_reason=None,
                status=VerificationDelegationStatus.ACTIVE,
            )
        )
        session.commit()

    with Session(verification_engine) as session:
        result = _verify(
            session,
            command=_command(evidence.id, verifier, scope),
            audit_actor=verifier,
            scope=scope,
            verification_id="VERIFICATION-1",
        )

    with Session(verification_engine) as read_session:
        decision = read_session.scalar(select(EvidenceVerificationDecision))
        assert result.result_type == "evidence_verification_decision"
        assert decision is not None
        assert decision.evidence_reference_id == evidence.id
        assert decision.evidence_verification_delegation_id == delegation.id
        assert decision.verifier_user_id == verifier.id
        assert decision.authority_snapshot["resource_scope"] == scope.as_dict()
        assert decision.authority_snapshot["delegation"]["revision_number"] == 1
        assert read_session.scalar(select(func.count(EvidenceVerificationDecision.id))) == 1
        assert read_session.scalar(select(func.count(GovernedAuditEvent.id))) == 1
        assert read_session.scalar(select(func.count(GovernedCommandReceipt.id))) == 1
        persisted_evidence = read_session.get(EvidenceReference, evidence.id)
        assert persisted_evidence is not None
        assert persisted_evidence.verified_at is None
        assert persisted_evidence.verified_by_user_id is None
        assert persisted_evidence.verified_by_actor_id is None


def test_verified_replay_returns_durable_result_only(verification_engine) -> None:
    with Session(verification_engine) as session:
        _submitter, verifier, grantor, evidence = _prepare_success_case(session)
        scope = VerificationScopeSnapshot(
            customer="customer-a",
            project="project-a",
            site="site-a",
            machine="machine-a",
        )
        EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-A",
                revision_number=1,
                verifier=verifier,
                grantor=grantor,
                scope=scope,
                effective_from=PAST,
                expires_at=None,
                revoked_by_user_id=None,
                revoked_at=None,
                revoked_reason=None,
                status=VerificationDelegationStatus.ACTIVE,
            )
        )
        session.commit()

    with Session(verification_engine) as session:
        first = _verify(
            session,
            command=_command(evidence.id, verifier, scope),
            audit_actor=verifier,
            scope=scope,
            verification_id="VERIFICATION-2",
            receipt_id="receipt-first",
            idempotency_key="verification-key-2",
            request_payload="verification-request-2",
        )

    with Session(verification_engine) as session:  # noqa: SIM117
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            replay = service.verify_evidence(
                command=_command(evidence.id, verifier, scope),
                receipt_id="unused-replay-receipt",
                command_identity=_identity(
                    key="verification-key-2", scope="VERIFICATION-2"
                ),
                request_hash=_request_hash(payload="verification-request-2"),
                audit=_audit(
                    event_id="unused-replay-audit",
                    actor=verifier,
                    scope=scope,
                    reason="verification passed",
                ),
                verification_id="VERIFICATION-2",
                completed_at=LATER,
            )
            assert replay == first

    with Session(verification_engine) as read_session:
        assert read_session.scalar(select(func.count(EvidenceVerificationDecision.id))) == 1
        assert read_session.scalar(select(func.count(GovernedAuditEvent.id))) == 1
        assert read_session.scalar(select(func.count(GovernedCommandReceipt.id))) == 1


def test_conflict_and_in_progress_fail_closed_without_mutation(verification_engine) -> None:
    with Session(verification_engine) as session:
        _, verifier, grantor, evidence = _prepare_success_case(session)
        scope = VerificationScopeSnapshot(
            customer="customer-a",
            project="project-a",
            site="site-a",
            machine="machine-a",
        )
        EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-A",
                revision_number=1,
                verifier=verifier,
                grantor=grantor,
                scope=scope,
                effective_from=PAST,
                expires_at=None,
                revoked_by_user_id=None,
                revoked_at=None,
                revoked_reason=None,
                status=VerificationDelegationStatus.ACTIVE,
            )
        )
        session.commit()

    with Session(verification_engine) as session:
        _verify(
            session,
            command=_command(evidence.id, verifier, scope),
            audit_actor=verifier,
            scope=scope,
            verification_id="VERIFICATION-3",
            receipt_id="receipt-conflict",
            idempotency_key="verification-key-3",
            request_payload="verification-request-3",
        )

    with pytest.raises(ValueError, match="idempotency conflict"):  # noqa: SIM117
        with Session(verification_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                service = EvidenceVerificationService(unit_of_work)
                service.verify_evidence(
                    command=_command(evidence.id, verifier, scope),
                    receipt_id="unused-conflict-receipt",
                    command_identity=_identity(
                        key="verification-key-3", scope="VERIFICATION-3"
                    ),
                    request_hash=_request_hash(payload="different-request"),
                    audit=_audit(
                        event_id="conflict-audit",
                        actor=verifier,
                        scope=scope,
                        reason="verification passed",
                    ),
                    verification_id="VERIFICATION-3",
                    completed_at=LATER,
                )

    with Session(verification_engine) as session:  # noqa: SIM117
        with GovernedUnitOfWork(session) as unit_of_work:
            unit_of_work.idempotency_repository.add_reserved(
                receipt_id="reserved-receipt",
                identity=_identity(key="verification-key-4", scope="VERIFICATION-4"),
                request_hash=_request_hash(payload="verification-request-4"),
                correlation_id="verification-correlation",
                schema_version="verification-audit-v1",
                software_version="test-build",
                created_at=NOW,
            )
            unit_of_work.commit()

    with pytest.raises(RuntimeError, match="already in progress"):  # noqa: SIM117
        with Session(verification_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                service = EvidenceVerificationService(unit_of_work)
                service.verify_evidence(
                    command=_command(evidence.id, verifier, scope),
                    receipt_id="unused-in-progress-receipt",
                    command_identity=_identity(
                        key="verification-key-4", scope="VERIFICATION-4"
                    ),
                    request_hash=_request_hash(payload="verification-request-4"),
                    audit=_audit(
                        event_id="in-progress-audit",
                        actor=verifier,
                        scope=scope,
                        reason="verification passed",
                    ),
                    verification_id="VERIFICATION-4",
                    completed_at=LATER,
                )

    with Session(verification_engine) as read_session:
        assert read_session.scalar(select(func.count(EvidenceVerificationDecision.id))) == 1
        assert read_session.scalar(select(func.count(GovernedAuditEvent.id))) == 1
        assert read_session.scalar(select(func.count(GovernedCommandReceipt.id))) == 2


def test_scope_mismatch_and_separation_of_duties_are_denied_and_audited(
    verification_engine,
) -> None:
    with Session(verification_engine) as session:
        submitter, verifier, grantor, evidence = _prepare_success_case(session)
        matching_scope = VerificationScopeSnapshot(
            customer="customer-a",
            project="project-a",
            site="site-a",
            machine="machine-a",
        )
        mismatched_scope = VerificationScopeSnapshot(
            customer="customer-b",
            project="project-b",
            site="site-b",
            machine="machine-b",
        )
        EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-B",
                revision_number=1,
                verifier=verifier,
                grantor=grantor,
                scope=matching_scope,
                effective_from=PAST,
                expires_at=None,
                revoked_by_user_id=None,
                revoked_at=None,
                revoked_reason=None,
                status=VerificationDelegationStatus.ACTIVE,
            )
        )
        session.commit()

    with Session(verification_engine) as session:  # noqa: SIM117
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            denial = service.verify_evidence(
                command=_command(evidence.id, verifier, mismatched_scope),
                receipt_id="scope-denial-receipt",
                command_identity=_identity(
                    key="verification-key-5", scope="VERIFICATION-5"
                ),
                request_hash=_request_hash(payload="verification-request-5"),
                audit=_audit(
                    event_id="scope-denial-audit",
                    actor=verifier,
                    scope=mismatched_scope,
                    reason="verification passed",
                ),
                verification_id="VERIFICATION-5",
                completed_at=LATER,
            )
            assert denial.result_type == "evidence_verification_denial"
            unit_of_work.commit()

    with Session(verification_engine) as session:  # noqa: SIM117
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            replay = service.verify_evidence(
                command=_command(evidence.id, verifier, mismatched_scope),
                receipt_id="unused-denial-replay",
                command_identity=_identity(
                    key="verification-key-5", scope="VERIFICATION-5"
                ),
                request_hash=_request_hash(payload="verification-request-5"),
                audit=_audit(
                    event_id="scope-denial-replay-audit",
                    actor=verifier,
                    scope=mismatched_scope,
                    reason="verification passed",
                ),
                verification_id="VERIFICATION-5",
                completed_at=LATER,
            )
            assert replay == denial

    with Session(verification_engine) as session:
        assert session.scalar(select(func.count(EvidenceVerificationDecision.id))) == 0
        assert session.scalar(
            select(func.count(GovernedAuditEvent.id)).where(
                GovernedAuditEvent.action == "AUTHORIZE_EVIDENCE_VERIFICATION_DENIED"
            )
        ) == 1
        assert session.scalar(select(func.count(GovernedCommandReceipt.id))) == 1

    with Session(verification_engine) as session:  # noqa: SIM117
        with GovernedUnitOfWork(session) as unit_of_work:
            service = EvidenceVerificationService(unit_of_work)
            denial = service.verify_evidence(
                command=_command(evidence.id, submitter, matching_scope),
                receipt_id="creator-denial-receipt",
                command_identity=_identity(
                    key="verification-key-6", scope="VERIFICATION-6"
                ),
                request_hash=_request_hash(payload="verification-request-6"),
                audit=_audit(
                    event_id="creator-denial-audit",
                    actor=submitter,
                    scope=matching_scope,
                    reason="verification passed",
                ),
                verification_id="VERIFICATION-6",
                completed_at=LATER,
            )
            assert denial.result_type == "evidence_verification_denial"
            unit_of_work.commit()

    with Session(verification_engine) as session:
        assert session.scalar(
            select(func.count(GovernedAuditEvent.id)).where(
                GovernedAuditEvent.action == "AUTHORIZE_EVIDENCE_VERIFICATION_DENIED"
            )
        ) == 2
        assert session.scalar(select(func.count(EvidenceVerificationDecision.id))) == 0


def test_delegation_lifecycle_supersession_and_decision_correction(
    verification_engine,
) -> None:
    with Session(verification_engine) as session:
        _submitter, verifier, grantor, _evidence = _prepare_success_case(session)
        scope = VerificationScopeSnapshot(
            customer="customer-a",
            project="project-a",
            site="site-a",
            machine="machine-a",
        )
        first_delegation = EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-C",
                revision_number=1,
                verifier=verifier,
                grantor=grantor,
                scope=scope,
                effective_from=PAST,
                expires_at=None,
                revoked_by_user_id=None,
                revoked_at=None,
                revoked_reason=None,
                status=VerificationDelegationStatus.ACTIVE,
            )
        )
        revoked_delegation = EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-C",
                revision_number=2,
                verifier=verifier,
                grantor=grantor,
                scope=scope,
                effective_from=PAST,
                expires_at=None,
                revoked_by_user_id=grantor.id,
                revoked_at=NOW,
                revoked_reason="revoked",
                status=VerificationDelegationStatus.REVOKED,
                supersedes_delegation_id=first_delegation.id,
            )
        )
        session.commit()

    with Session(verification_engine) as session:
        repo = EvidenceVerificationRepository(session)
        history = repo.list_delegation_history("DELEGATION-C")
        assert [item.revision_number for item in history] == [1, 2]
        assert history[-1].status is VerificationDelegationStatus.REVOKED
        assert repo.find_matching_delegation(
            verifier_user_id=verifier.id,
            scope_snapshot=scope.as_dict(),
        ).id == revoked_delegation.id

    with pytest.raises(ValueError, match="already has a successor"):  # noqa: SIM117
        with Session(verification_engine) as session:
            EvidenceVerificationRepository(session).create_delegation_revision(
                draft=_delegation(
                    delegation_id="DELEGATION-C",
                    revision_number=2,
                    verifier=verifier,
                    grantor=grantor,
                    scope=scope,
                    effective_from=PAST,
                    expires_at=None,
                    revoked_by_user_id=None,
                    revoked_at=None,
                    revoked_reason=None,
                    status=VerificationDelegationStatus.ACTIVE,
                    supersedes_delegation_id=first_delegation.id,
                )
            )

    with Session(verification_engine) as session:
        active_submitter = _user(
            session,
            email="active-submit@example.com",
            full_name="Active Submitter",
            role="Submitter",
        )
        active_verifier = _user(
            session,
            email="active-verifier@example.com",
            full_name="Active Verifier",
            role="Verifier",
        )
        active_grantor = _user(
            session,
            email="active-grantor@example.com",
            full_name="Active Grantor",
            role="Security/Governance Owner",
        )
        exact_evidence = _rule_with_evidence(
            session,
            rule_id="VERIFICATION_RULE_CORRECTION",
            revision="draft-1",
            submitter=active_submitter,
            evidence_id="EVIDENCE-B",
            evidence_revision="document-1",
        )
        session.commit()

    with Session(verification_engine) as session:
        scope = VerificationScopeSnapshot(
            customer="customer-a",
            project="project-a",
            site="site-a",
            machine="machine-a",
        )
        EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-D",
                revision_number=1,
                verifier=active_verifier,
                grantor=active_grantor,
                scope=scope,
                effective_from=PAST,
                expires_at=None,
                revoked_by_user_id=None,
                revoked_at=None,
                revoked_reason=None,
                status=VerificationDelegationStatus.ACTIVE,
            )
        )
        session.commit()

    with Session(verification_engine) as session:
        _first = _verify(
            session,
            command=_command(exact_evidence.id, active_verifier, scope),
            audit_actor=active_verifier,
            scope=scope,
            verification_id="VERIFICATION-7",
            receipt_id="receipt-7",
            idempotency_key="verification-key-7",
            request_payload="verification-request-7",
        )

    with Session(verification_engine) as session:
        repo = EvidenceVerificationRepository(session)
        prior_decision = repo.list_verification_history("VERIFICATION-7")[0]
        corrected = repo.create_verification_decision(
            draft=EvidenceVerificationDecisionDraft(
                verification_id="VERIFICATION-7",
                revision_number=2,
                evidence_reference_id=exact_evidence.id,
                evidence_verification_delegation_id=prior_decision.evidence_verification_delegation_id,
                verifier_user_id=active_verifier.id,
                decision_outcome=prior_decision.decision_outcome,
                decision_reason="corrected decision",
                authority_snapshot=prior_decision.authority_snapshot,
                decided_at=NOW,
                policy_identifier=prior_decision.policy_identifier,
                policy_version=prior_decision.policy_version,
                correlation_id=prior_decision.correlation_id,
                supersedes_verification_decision_id=prior_decision.id,
                created_by_user_id=active_verifier.id,
                created_by_actor_id="active-verifier-actor",
                schema_version=prior_decision.schema_version,
                canonicalization_version=prior_decision.canonicalization_version,
                hash_algorithm=prior_decision.hash_algorithm,
                content_hash=prior_decision.content_hash,
                software_version=prior_decision.software_version,
            )
        )
        session.commit()
        assert corrected.supersedes_verification_decision_id == prior_decision.id

    with Session(verification_engine) as session:
        repo = EvidenceVerificationRepository(session)
        history = repo.list_verification_history("VERIFICATION-7")
        assert [item.revision_number for item in history] == [1, 2]
        assert history[-1].supersedes_verification_decision_id == history[0].id


def test_exact_evidence_revision_pinning_and_new_revision_flow(verification_engine) -> None:
    with Session(verification_engine) as session:
        submitter, verifier, grantor, evidence = _prepare_success_case(session)
        scope = VerificationScopeSnapshot(
            customer="customer-a",
            project="project-a",
            site="site-a",
            machine="machine-a",
        )
        EvidenceVerificationRepository(session).create_delegation_revision(
            draft=_delegation(
                delegation_id="DELEGATION-E",
                revision_number=1,
                verifier=verifier,
                grantor=grantor,
                scope=scope,
                effective_from=PAST,
                expires_at=None,
                revoked_by_user_id=None,
                revoked_at=None,
                revoked_reason=None,
                status=VerificationDelegationStatus.ACTIVE,
            )
        )
        session.commit()

    with Session(verification_engine) as session:
        first = _verify(
            session,
            command=_command(evidence.id, verifier, scope),
            audit_actor=verifier,
            scope=scope,
            verification_id="VERIFICATION-8",
            receipt_id="receipt-8",
            idempotency_key="verification-key-8",
            request_payload="verification-request-8",
        )

    with Session(verification_engine) as session:
        rule_repo = RuleRegistryRepository(session)
        rule = rule_repo.get_by_rule_id("VERIFICATION_RULE")
        assert rule is not None
        new_revision = rule_repo.create_revision(
            engineering_rule=rule,
            revision="draft-2",
            name="Verification foundation rule revision 2",
            status=RuleLifecycleStatus.DRAFT,
            evidence_class=EvidenceClass.UNRESOLVED,
            category=RuleCategory.OTHER,
            parameter="verification_parameter",
            safe_default=SafeDefault.UNRESOLVED,
            missing_handling=MissingHandling.DATA_INSUFFICIENT,
            enabled=False,
            reason_for_change="Evidence content correction",
            version_metadata=ContentVersionMetadata(
                schema_version="verification-test-v1",
                canonicalization_version="canonical-test-v1",
                hash_algorithm="sha256",
                content_hash=hashlib.sha256(b"VERIFICATION_RULE:draft-2").hexdigest(),
                software_version="test-build",
            ),
            created_by_actor_id="submitter-actor",
            created_by_user_id=submitter.id,
                evidence_references=(
                EvidenceRevisionDraft(
                    evidence_id="EVIDENCE-A",
                    evidence_revision="document-2",
                    evidence_class=EvidenceClass.UNRESOLVED,
                    lifecycle_status=RuleLifecycleStatus.DRAFT,
                    created_by_actor_id="submitter-actor",
                    created_by_user_id=submitter.id,
                    source_document="Verification evidence",
                    section_reference="section-2",
                    schema_version="verification-evidence-v1",
                    hash_algorithm="sha256",
                    content_hash=hashlib.sha256(b"EVIDENCE-A:document-2").hexdigest(),
                    supersedes_evidence_reference_id=evidence.id,
                ),
            ),
        )
        session.commit()
        new_evidence = new_revision.evidence_references[0]

    with Session(verification_engine) as session:
        second = _verify(
            session,
            command=_command(new_evidence.id, verifier, scope),
            audit_actor=verifier,
            scope=scope,
            verification_id="VERIFICATION-9",
            receipt_id="receipt-9",
            idempotency_key="verification-key-9",
            request_payload="verification-request-9",
        )
        assert second.result_type == "evidence_verification_decision"

    with Session(verification_engine) as session:
        history = EvidenceVerificationRepository(session).list_verification_history(
            "VERIFICATION-9"
        )
        assert len(history) == 1
        assert history[0].evidence_reference_id == new_evidence.id
        assert first != second
