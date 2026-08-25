from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_evidence_service import RuleEvidenceService
from app.application.rule_registry_service import GovernedAuditMetadata
from app.db.session import Base
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    ImmutableRecordError,
    RegistryAuthorityError,
    RuleLifecycleStatus,
)
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.domain.rule_registry_types import (
    EvidenceAvailability,
    EvidenceRevisionDraft,
    MissingHandling,
    RuleCategory,
    SafeDefault,
)
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.rule_registry import EvidenceReference
from app.repositories.rule_evidence_repository import RuleEvidenceRepository
from app.repositories.rule_registry_repository import RuleRegistryRepository


NOW = datetime(2034, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
LATER = datetime(2034, 1, 2, 3, 5, 6, tzinfo=timezone.utc)


@pytest.fixture()
def evidence_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _create_parent(session: Session, rule_id: str = "SYNTHETIC_EVIDENCE_RULE") -> int:
    repository = RuleRegistryRepository(session)
    rule = repository.create_rule(rule_id=rule_id, created_by_actor_id="test-actor")
    revision = repository.create_revision(
        engineering_rule=rule,
        revision="draft-1",
        name="Synthetic unresolved evidence holder",
        status=RuleLifecycleStatus.DRAFT,
        evidence_class=EvidenceClass.UNRESOLVED,
        category=RuleCategory.OTHER,
        parameter="synthetic_parameter",
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.DATA_INSUFFICIENT,
        enabled=False,
        reason_for_change="Synthetic evidence test",
        version_metadata=ContentVersionMetadata(
            schema_version="registry-test-v1",
            canonicalization_version="canonical-test-v1",
            hash_algorithm="sha256",
            content_hash=hashlib.sha256(rule_id.encode()).hexdigest(),
            software_version="test-build",
        ),
        created_by_actor_id="test-actor",
    )
    session.commit()
    return revision.id


def _draft(
    *,
    revision_number: int = 1,
    prior_id: int | None = None,
    evidence_id: str = "SYNTHETIC_EVIDENCE",
    evidence_revision: str | None = None,
    evidence_class: EvidenceClass = EvidenceClass.UNRESOLVED,
    lifecycle: RuleLifecycleStatus = RuleLifecycleStatus.DRAFT,
) -> EvidenceRevisionDraft:
    return EvidenceRevisionDraft(
        evidence_id=evidence_id,
        evidence_revision=evidence_revision or f"document-{revision_number}",
        revision_number=revision_number,
        supersedes_evidence_reference_id=prior_id,
        availability=EvidenceAvailability.AVAILABLE,
        evidence_class=evidence_class,
        lifecycle_status=lifecycle,
        created_by_actor_id="test-actor",
        source_document="Synthetic controlled reference",
        section_reference="synthetic-section",
        schema_version="evidence-test-v1",
        hash_algorithm="sha256",
        content_hash=hashlib.sha256(f"evidence-{revision_number}".encode()).hexdigest(),
    )


def _identity(key: str = "evidence-command") -> CommandIdentity:
    return CommandIdentity("registry.evidence.draft", "synthetic-rule", key)


def _request_hash(value: str = "request-one") -> CanonicalRequestHash:
    return CanonicalRequestHash(
        hashlib.sha256(value.encode()).hexdigest(),
        "sha256",
        "canonical-test-v1",
    )


def _audit(event_id: str, *, correlation_id: str | None = "correlation"):
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id="test-actor",
        actor_type="user",
        reason="Synthetic evidence correction",
        correlation_id=correlation_id,  # type: ignore[arg-type]
        schema_version="audit-test-v1",
        software_version="test-build",
        canonicalization_version="canonical-test-v1",
        hash_algorithm="sha256",
        created_at=NOW,
        idempotency_key="evidence-command",
    )


def _execute(
    unit_of_work: GovernedUnitOfWork,
    *,
    parent_id: int,
    draft: EvidenceRevisionDraft,
    receipt_id: str,
    event_id: str,
    identity: CommandIdentity | None = None,
    request_hash: CanonicalRequestHash | None = None,
    audit: GovernedAuditMetadata | None = None,
):
    return RuleEvidenceService(unit_of_work).create_draft_revision(
        engineering_rule_revision_id=parent_id,
        draft=draft,
        receipt_id=receipt_id,
        command_identity=identity or _identity(),
        request_hash=request_hash or _request_hash(),
        audit=audit or _audit(event_id),
        completed_at=LATER,
    )


def test_create_and_correct_evidence_preserves_append_only_history(evidence_engine):
    with Session(evidence_engine) as setup:
        parent_id = _create_parent(setup)

    with Session(evidence_engine) as first_session:
        with GovernedUnitOfWork(first_session) as uow:
            first_result = _execute(
                uow,
                parent_id=parent_id,
                draft=_draft(),
                receipt_id="receipt-1",
                event_id="audit-1",
            )
            uow.commit()
    first_id = int(first_result.result_id)

    with Session(evidence_engine) as second_session:
        with GovernedUnitOfWork(second_session) as uow:
            second_result = _execute(
                uow,
                parent_id=parent_id,
                draft=_draft(revision_number=2, prior_id=first_id),
                receipt_id="receipt-2",
                event_id="audit-2",
                identity=_identity("evidence-command-2"),
                request_hash=_request_hash("request-two"),
            )
            uow.commit()

    with Session(evidence_engine) as read_session:
        history = RuleEvidenceRepository(read_session).list_history(
            engineering_rule_revision_id=parent_id,
            evidence_id="SYNTHETIC_EVIDENCE",
        )
        assert [item.revision_number for item in history] == [1, 2]
        assert history[0].evidence_revision == "document-1"
        assert history[0].supersedes_evidence_reference_id is None
        assert history[1].id == int(second_result.result_id)
        assert history[1].supersedes_evidence_reference_id == history[0].id
        assert history[1].evidence_class is EvidenceClass.UNRESOLVED
        assert history[1].verified_at is None
        assert history[1].approved_at is None


def test_identical_command_replays_without_duplicate_state_or_audit(evidence_engine):
    with Session(evidence_engine) as setup:
        parent_id = _create_parent(setup)
    with Session(evidence_engine) as first_session:
        with GovernedUnitOfWork(first_session) as uow:
            first = _execute(
                uow, parent_id=parent_id, draft=_draft(), receipt_id="receipt", event_id="audit"
            )
            uow.commit()
    with Session(evidence_engine) as replay_session:
        with GovernedUnitOfWork(replay_session) as uow:
            replay = _execute(
                uow,
                parent_id=parent_id,
                draft=_draft(),
                receipt_id="unused",
                event_id="unused",
            )
            assert replay == first
    with Session(evidence_engine) as read_session:
        assert read_session.scalar(select(func.count(EvidenceReference.id))) == 1
        assert read_session.scalar(select(func.count(GovernedAuditEvent.id))) == 1
        assert read_session.scalar(select(func.count(GovernedCommandReceipt.id))) == 1


def test_conflicting_command_fails_closed_without_mutation(evidence_engine):
    with Session(evidence_engine) as setup:
        parent_id = _create_parent(setup)
    with Session(evidence_engine) as first_session:
        with GovernedUnitOfWork(first_session) as uow:
            _execute(
                uow, parent_id=parent_id, draft=_draft(), receipt_id="receipt", event_id="audit"
            )
            uow.commit()
    with pytest.raises(ValueError, match="idempotency conflict"):
        with Session(evidence_engine) as conflict_session:
            with GovernedUnitOfWork(conflict_session) as uow:
                _execute(
                    uow,
                    parent_id=parent_id,
                    draft=_draft(),
                    receipt_id="unused",
                    event_id="unused",
                    request_hash=_request_hash("different"),
                )
    with Session(evidence_engine) as read_session:
        assert read_session.scalar(select(func.count(EvidenceReference.id))) == 1
        assert read_session.scalar(select(func.count(GovernedAuditEvent.id))) == 1


@pytest.mark.parametrize(
    ("evidence_class", "lifecycle"),
    [
        (EvidenceClass.SOURCE_BACKED, RuleLifecycleStatus.DRAFT),
        (EvidenceClass.UNRESOLVED, RuleLifecycleStatus.REVIEW),
        (EvidenceClass.UNRESOLVED, RuleLifecycleStatus.ACTIVE),
    ],
)
def test_service_refuses_authority_bearing_states(
    evidence_engine, evidence_class, lifecycle
):
    with Session(evidence_engine) as setup:
        parent_id = _create_parent(setup)
    with pytest.raises(RegistryAuthorityError):
        with Session(evidence_engine) as session:
            with GovernedUnitOfWork(session) as uow:
                _execute(
                    uow,
                    parent_id=parent_id,
                    draft=_draft(evidence_class=evidence_class, lifecycle=lifecycle),
                    receipt_id="receipt",
                    event_id="audit",
                )


def test_invalid_revision_order_and_competing_successor_are_rejected(evidence_engine):
    with Session(evidence_engine) as setup:
        parent_id = _create_parent(setup)
        first = RuleEvidenceRepository(setup).create_revision(
            engineering_rule_revision_id=parent_id, draft=_draft()
        )
        setup.commit()
        first_id = first.id
    with Session(evidence_engine) as session:
        repository = RuleEvidenceRepository(session)
        with pytest.raises(ValueError, match="next revision_number"):
            repository.create_revision(
                engineering_rule_revision_id=parent_id,
                draft=_draft(revision_number=3, prior_id=first_id),
            )
        session.rollback()
        repository.create_revision(
            engineering_rule_revision_id=parent_id,
            draft=_draft(revision_number=2, prior_id=first_id),
        )
        session.commit()
    with Session(evidence_engine) as competing:
        with pytest.raises(ValueError, match="already has a successor"):
            RuleEvidenceRepository(competing).create_revision(
                engineering_rule_revision_id=parent_id,
                draft=_draft(
                    revision_number=2,
                    prior_id=first_id,
                    evidence_revision="alternate-document-2",
                ),
            )


def test_cross_evidence_and_cross_rule_supersession_are_rejected(evidence_engine):
    with Session(evidence_engine) as setup:
        first_parent = _create_parent(setup, "FIRST_RULE")
        second_parent = _create_parent(setup, "SECOND_RULE")
        prior = RuleEvidenceRepository(setup).create_revision(
            engineering_rule_revision_id=first_parent, draft=_draft()
        )
        setup.commit()
        prior_id = prior.id
    with Session(evidence_engine) as session:
        repository = RuleEvidenceRepository(session)
        with pytest.raises(ValueError, match="cross evidence identities"):
            repository.create_revision(
                engineering_rule_revision_id=first_parent,
                draft=_draft(
                    revision_number=2,
                    prior_id=prior_id,
                    evidence_id="OTHER_EVIDENCE",
                ),
            )
        with pytest.raises(ValueError, match="cross rule revisions"):
            repository.create_revision(
                engineering_rule_revision_id=second_parent,
                draft=_draft(revision_number=2, prior_id=prior_id),
            )


def test_evidence_update_delete_and_nested_metadata_mutation_are_rejected(evidence_engine):
    draft = _draft()
    draft = EvidenceRevisionDraft(
        evidence_id=draft.evidence_id,
        evidence_revision=draft.evidence_revision,
        evidence_class=draft.evidence_class,
        lifecycle_status=draft.lifecycle_status,
        created_by_actor_id=draft.created_by_actor_id,
        revision_number=draft.revision_number,
        availability=draft.availability,
        source_document=draft.source_document,
        section_reference=draft.section_reference,
        reference_metadata={"trace": {"state": "draft"}},
        schema_version=draft.schema_version,
        hash_algorithm=draft.hash_algorithm,
        content_hash=draft.content_hash,
    )
    with Session(evidence_engine) as setup:
        parent_id = _create_parent(setup)
        reference = RuleEvidenceRepository(setup).create_revision(
            engineering_rule_revision_id=parent_id, draft=draft
        )
        setup.commit()
        reference_id = reference.id
        with pytest.raises(TypeError, match="immutable"):
            reference.reference_metadata["trace"]["state"] = "changed"
        reference.source_name = "changed"
        with pytest.raises(ImmutableRecordError):
            setup.flush()
        setup.rollback()
        persisted = setup.get(EvidenceReference, reference_id)
        setup.delete(persisted)
        with pytest.raises(ImmutableRecordError):
            setup.flush()


def test_audit_failure_and_explicit_rollback_publish_nothing(evidence_engine):
    with Session(evidence_engine) as setup:
        parent_id = _create_parent(setup)
    with pytest.raises(IntegrityError):
        with Session(evidence_engine) as session:
            with GovernedUnitOfWork(session) as uow:
                _execute(
                    uow,
                    parent_id=parent_id,
                    draft=_draft(),
                    receipt_id="receipt-failed",
                    event_id="audit-failed",
                    identity=_identity("failed"),
                    request_hash=_request_hash("failed"),
                    audit=_audit("audit-failed", correlation_id=None),
                )
                uow.commit()
    with Session(evidence_engine) as check:
        assert check.scalar(select(func.count(EvidenceReference.id))) == 0
        assert check.scalar(select(func.count(GovernedAuditEvent.id))) == 0
        assert check.scalar(select(func.count(GovernedCommandReceipt.id))) == 0
    with Session(evidence_engine) as rollback_session:
        uow = GovernedUnitOfWork(rollback_session)
        _execute(
            uow,
            parent_id=parent_id,
            draft=_draft(),
            receipt_id="receipt-rollback",
            event_id="audit-rollback",
            identity=_identity("rollback"),
            request_hash=_request_hash("rollback"),
        )
        uow.rollback()
    with Session(evidence_engine) as check:
        assert check.scalar(select(func.count(EvidenceReference.id))) == 0
        assert check.scalar(select(func.count(GovernedAuditEvent.id))) == 0
        assert check.scalar(select(func.count(GovernedCommandReceipt.id))) == 0


def test_repository_integrity_failure_rolls_back_receipt_and_audit(evidence_engine):
    with Session(evidence_engine) as setup:
        parent_id = _create_parent(setup)
        first = RuleEvidenceRepository(setup).create_revision(
            engineering_rule_revision_id=parent_id, draft=_draft()
        )
        setup.commit()
        first_id = first.id
    duplicate_external_revision = _draft(
        revision_number=2,
        prior_id=first_id,
        evidence_revision="document-1",
    )
    with pytest.raises(IntegrityError):
        with Session(evidence_engine) as session:
            with GovernedUnitOfWork(session) as uow:
                _execute(
                    uow,
                    parent_id=parent_id,
                    draft=duplicate_external_revision,
                    receipt_id="receipt-integrity-failure",
                    event_id="audit-integrity-failure",
                    identity=_identity("integrity-failure"),
                    request_hash=_request_hash("integrity-failure"),
                )
                uow.commit()
    with Session(evidence_engine) as check:
        assert check.scalar(select(func.count(EvidenceReference.id))) == 1
        assert check.scalar(select(func.count(GovernedAuditEvent.id))) == 0
        assert check.scalar(select(func.count(GovernedCommandReceipt.id))) == 0


def test_database_rejects_self_supersession(evidence_engine):
    with Session(evidence_engine) as setup:
        parent_id = _create_parent(setup)
        first = RuleEvidenceRepository(setup).create_revision(
            engineering_rule_revision_id=parent_id, draft=_draft()
        )
        setup.commit()
        first_id = first.id
    with pytest.raises(IntegrityError):
        with evidence_engine.begin() as connection:
            connection.execute(
                update(EvidenceReference)
                .where(EvidenceReference.id == first_id)
                .values(supersedes_evidence_reference_id=first_id)
            )
