"""Atomicity tests for the threshold-free governed audit foundation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.governed_audit_service import GovernedAuditService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.db.session import Base
from app.domain.governance_types import ImmutableRecordError
from app.models.governance import GovernedAuditEvent
from app.models.rule_registry import EngineeringRule
from app.repositories.governance_repository import GovernanceRepository
from app.repositories.rule_registry_repository import RuleRegistryRepository


@pytest.fixture()
def governed_engine():
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


def _record_audit(
    service: GovernedAuditService,
    *,
    event_id: str,
    rule_id: str,
    correlation_id: str | None = "correlation-1",
) -> GovernedAuditEvent:
    return service.record_event(
        event_id=event_id,
        entity_type="engineering_rule",
        entity_id=rule_id,
        entity_revision="identity",
        action="CREATE_RULE_IDENTITY",
        actor_id="synthetic-actor",
        actor_type="service",
        actor_role="synthetic-role",
        authority_scope={"scope": {"project": "synthetic-project"}},
        reason="Synthetic atomicity test",
        correlation_id=correlation_id,
        idempotency_key="synthetic-request-key",
        schema_version="audit-test-v1",
        software_version="test-build",
        canonicalization_version="canonical-test-v1",
        hash_algorithm="sha256",
        prior_content_hash=None,
        new_content_hash="a" * 64,
        detail={"result": {"state": "created"}},
        created_at=datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )


def _create_rule(unit_of_work: GovernedUnitOfWork, rule_id: str) -> EngineeringRule:
    return RuleRegistryRepository(unit_of_work.session).create_rule(
        rule_id=rule_id,
        created_by_actor_id="synthetic-actor",
    )


def test_successful_owner_commit_persists_governed_write_and_audit(
    governed_engine,
) -> None:
    with Session(governed_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            assert unit_of_work.governance_repository.session is session
            _create_rule(unit_of_work, "ATOMIC_SUCCESS_RULE")
            _record_audit(
                GovernedAuditService(unit_of_work),
                event_id="atomic-success-event",
                rule_id="ATOMIC_SUCCESS_RULE",
            )
            unit_of_work.commit()

    with Session(governed_engine) as read_session:
        assert read_session.scalar(
            select(EngineeringRule).where(
                EngineeringRule.rule_id == "ATOMIC_SUCCESS_RULE"
            )
        ) is not None
        assert GovernanceRepository(read_session).get_by_event_id(
            "atomic-success-event"
        ) is not None


def test_audit_flush_failure_rolls_back_governed_write(governed_engine) -> None:
    with pytest.raises(IntegrityError):
        with Session(governed_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                _create_rule(unit_of_work, "AUDIT_FAILURE_RULE")
                _record_audit(
                    GovernedAuditService(unit_of_work),
                    event_id="invalid-audit-event",
                    rule_id="AUDIT_FAILURE_RULE",
                    correlation_id=None,
                )
                unit_of_work.commit()

    with Session(governed_engine) as read_session:
        assert read_session.scalar(
            select(EngineeringRule).where(
                EngineeringRule.rule_id == "AUDIT_FAILURE_RULE"
            )
        ) is None
        assert GovernanceRepository(read_session).get_by_event_id(
            "invalid-audit-event"
        ) is None


def test_governed_write_failure_leaves_no_audit(governed_engine) -> None:
    with Session(governed_engine) as setup_session:
        setup_session.add(
            EngineeringRule(
                rule_id="DUPLICATE_RULE",
                created_by_actor_id="setup-actor",
            )
        )
        setup_session.commit()

    with pytest.raises(IntegrityError):
        with Session(governed_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                _create_rule(unit_of_work, "DUPLICATE_RULE")
                _record_audit(
                    GovernedAuditService(unit_of_work),
                    event_id="must-not-persist",
                    rule_id="DUPLICATE_RULE",
                )
                unit_of_work.commit()

    with Session(governed_engine) as read_session:
        assert GovernanceRepository(read_session).get_by_event_id(
            "must-not-persist"
        ) is None


def test_governance_repository_never_commits(governed_engine) -> None:
    with Session(governed_engine) as session:
        commits: list[bool] = []
        event.listen(session, "after_commit", lambda _session: commits.append(True))
        event_record = GovernedAuditEvent(
            event_id="repository-no-commit",
            entity_type="engineering_rule",
            entity_id="SYNTHETIC_RULE",
            entity_revision="identity",
            action="CREATE_RULE_IDENTITY",
            actor_id="synthetic-actor",
            actor_type="service",
            reason="Synthetic repository transaction test",
            correlation_id="repository-correlation",
            schema_version="audit-test-v1",
            software_version="test-build",
            canonicalization_version="canonical-test-v1",
            hash_algorithm="sha256",
            created_at=datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        )
        GovernanceRepository(session).add_event(event_record)
        assert commits == []
        session.rollback()


def test_governed_audit_service_never_commits(governed_engine) -> None:
    with Session(governed_engine) as session:
        commits: list[bool] = []
        event.listen(session, "after_commit", lambda _session: commits.append(True))
        unit_of_work = GovernedUnitOfWork(session)
        service = GovernedAuditService(unit_of_work)
        _record_audit(
            service,
            event_id="service-no-commit",
            rule_id="SYNTHETIC_RULE",
        )
        assert commits == []
        unit_of_work.rollback()


def test_governed_audit_service_refuses_write_after_uow_finalization(
    governed_engine,
) -> None:
    with Session(governed_engine) as session:
        unit_of_work = GovernedUnitOfWork(session)
        service = GovernedAuditService(unit_of_work)
        unit_of_work.rollback()

        with pytest.raises(RuntimeError, match="already finalized"):
            _record_audit(
                service,
                event_id="after-finalization-event",
                rule_id="SYNTHETIC_RULE",
            )

    with Session(governed_engine) as read_session:
        assert GovernanceRepository(read_session).get_by_event_id(
            "after-finalization-event"
        ) is None


def test_explicit_rollback_removes_both_pending_writes(governed_engine) -> None:
    with Session(governed_engine) as session:
        unit_of_work = GovernedUnitOfWork(session)
        _create_rule(unit_of_work, "EXPLICIT_ROLLBACK_RULE")
        _record_audit(
            GovernedAuditService(unit_of_work),
            event_id="explicit-rollback-event",
            rule_id="EXPLICIT_ROLLBACK_RULE",
        )
        unit_of_work.rollback()

    with Session(governed_engine) as read_session:
        assert read_session.scalar(
            select(EngineeringRule).where(
                EngineeringRule.rule_id == "EXPLICIT_ROLLBACK_RULE"
            )
        ) is None
        assert GovernanceRepository(read_session).get_by_event_id(
            "explicit-rollback-event"
        ) is None


def test_context_manager_exception_rolls_back_both_writes(governed_engine) -> None:
    with pytest.raises(RuntimeError, match="synthetic operation failure"):
        with Session(governed_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                _create_rule(unit_of_work, "CONTEXT_ROLLBACK_RULE")
                _record_audit(
                    GovernedAuditService(unit_of_work),
                    event_id="context-rollback-event",
                    rule_id="CONTEXT_ROLLBACK_RULE",
                )
                raise RuntimeError("synthetic operation failure")

    with Session(governed_engine) as read_session:
        assert read_session.scalar(
            select(EngineeringRule).where(
                EngineeringRule.rule_id == "CONTEXT_ROLLBACK_RULE"
            )
        ) is None
        assert GovernanceRepository(read_session).get_by_event_id(
            "context-rollback-event"
        ) is None


def test_context_manager_without_explicit_commit_rolls_back(governed_engine) -> None:
    with Session(governed_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            _create_rule(unit_of_work, "NO_HIDDEN_COMMIT_RULE")
            _record_audit(
                GovernedAuditService(unit_of_work),
                event_id="no-hidden-commit-event",
                rule_id="NO_HIDDEN_COMMIT_RULE",
            )

    with Session(governed_engine) as read_session:
        assert read_session.scalar(
            select(EngineeringRule).where(
                EngineeringRule.rule_id == "NO_HIDDEN_COMMIT_RULE"
            )
        ) is None
        assert GovernanceRepository(read_session).get_by_event_id(
            "no-hidden-commit-event"
        ) is None


def test_governed_audit_event_remains_append_only(governed_engine) -> None:
    with Session(governed_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            event_record = _record_audit(
                GovernedAuditService(unit_of_work),
                event_id="append-only-event",
                rule_id="SYNTHETIC_RULE",
            )
            event_record_id = event_record.id
            unit_of_work.commit()

    with Session(governed_engine) as session:
        persisted = session.get(GovernedAuditEvent, event_record_id)
        assert persisted is not None
        persisted.action = "MUTATED_ACTION"
        with pytest.raises(ImmutableRecordError):
            session.flush()
        session.rollback()

        persisted = session.get(GovernedAuditEvent, event_record_id)
        assert persisted is not None
        session.delete(persisted)
        with pytest.raises(ImmutableRecordError):
            session.flush()


def test_required_audit_metadata_persists_exactly(governed_engine) -> None:
    with Session(governed_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            _record_audit(
                GovernedAuditService(unit_of_work),
                event_id="metadata-event",
                rule_id="METADATA_RULE",
            )
            unit_of_work.commit()

    with Session(governed_engine) as read_session:
        persisted = GovernanceRepository(read_session).get_by_event_id(
            "metadata-event"
        )
        assert persisted is not None
        assert persisted.entity_type == "engineering_rule"
        assert persisted.entity_id == "METADATA_RULE"
        assert persisted.entity_revision == "identity"
        assert persisted.action == "CREATE_RULE_IDENTITY"
        assert persisted.actor_id == "synthetic-actor"
        assert persisted.actor_type == "service"
        assert persisted.actor_role == "synthetic-role"
        assert persisted.authority_scope == {
            "scope": {"project": "synthetic-project"}
        }
        assert persisted.reason == "Synthetic atomicity test"
        assert persisted.correlation_id == "correlation-1"
        assert persisted.idempotency_key == "synthetic-request-key"
        assert persisted.schema_version == "audit-test-v1"
        assert persisted.software_version == "test-build"
        assert persisted.canonicalization_version == "canonical-test-v1"
        assert persisted.hash_algorithm == "sha256"
        assert persisted.new_content_hash == "a" * 64
        assert persisted.detail == {"result": {"state": "created"}}
        assert persisted.created_at == datetime(2030, 1, 2, 3, 4, 5)


def test_only_unit_of_work_owns_commit_and_rollback_calls() -> None:
    backend_root = Path(__file__).parents[1]
    repository_source = (
        backend_root / "app" / "repositories" / "governance_repository.py"
    ).read_text(encoding="utf-8")
    service_source = (
        backend_root / "app" / "application" / "governed_audit_service.py"
    ).read_text(encoding="utf-8")
    unit_of_work_source = (
        backend_root / "app" / "application" / "governed_unit_of_work.py"
    ).read_text(encoding="utf-8")

    assert ".commit(" not in repository_source
    assert ".rollback(" not in repository_source
    assert ".commit(" not in service_source
    assert ".rollback(" not in service_source
    assert ".commit(" in unit_of_work_source
    assert ".rollback(" in unit_of_work_source


def test_new_governed_path_does_not_import_legacy_audit_or_prototypes() -> None:
    backend_root = Path(__file__).parents[1]
    new_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            backend_root / "app" / "repositories" / "governance_repository.py",
            backend_root / "app" / "application" / "governed_unit_of_work.py",
            backend_root / "app" / "application" / "governed_audit_service.py",
        )
    )
    assert "app.application.audit_service" not in new_sources
    assert "rules_engine" not in new_sources
    assert "DEFAULT_RULES" not in new_sources
