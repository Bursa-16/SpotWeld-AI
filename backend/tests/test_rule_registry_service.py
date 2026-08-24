"""Tests for non-authoritative Registry draft service orchestration."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from app.domain.rule_registry_types import (
    EvidenceReferenceDraft,
    MissingHandling,
    RuleCategory,
    SafeDefault,
)
from app.models.governance import GovernedAuditEvent
from app.models.rule_registry import (
    EngineeringRule,
    EngineeringRuleRevision,
    EvidenceReference,
)
from app.repositories.governance_repository import GovernanceRepository
from app.repositories.rule_registry_repository import RuleRegistryRepository


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
) -> GovernedAuditMetadata:
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id="synthetic-actor",
        actor_type="service",
        actor_role="synthetic-role",
        authority_scope={"project": "synthetic-project"},
        reason="Synthetic draft command",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        schema_version="audit-test-v1",
        software_version="test-build",
        canonicalization_version="audit-canonical-v1",
        hash_algorithm="sha256",
        detail={"caller_trace": "synthetic"},
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
) -> EngineeringRule:
    return service.create_identity(rule_id=rule_id, audit=_audit(event_id))


def _create_draft(
    service: RuleRegistryService,
    rule_id: str,
    revision: str,
    event_id: str,
    *,
    evidence_class: EvidenceClass = EvidenceClass.UNRESOLVED,
    enabled: bool = False,
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
    )


def test_create_registry_identity_within_uow(service_engine) -> None:
    with Session(service_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
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
    with Session(service_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
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
