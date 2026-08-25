"""Tests for durable governed-command idempotency infrastructure."""

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

from app.application.governed_idempotency_service import (
    GovernedIdempotencyService,
)
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import (
    GovernedAuditMetadata,
    RuleRegistryService,
)
from app.db.session import Base
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    ImmutableRecordError,
)
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
    CommandReceiptStatus,
    CommandResultReference,
    IdempotencyDisposition,
)
from app.domain.rule_registry_types import MissingHandling, RuleCategory, SafeDefault
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.rule_registry import EngineeringRule, EngineeringRuleRevision
from app.repositories.idempotency_repository import IdempotencyRepository


NOW = datetime(2032, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
LATER = datetime(2032, 3, 4, 5, 7, 8, tzinfo=timezone.utc)


@pytest.fixture()
def idempotency_engine():
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


def _identity(key: str = "synthetic-key") -> CommandIdentity:
    return CommandIdentity(
        command_namespace="registry.draft",
        command_scope="synthetic-project",
        idempotency_key=key,
    )


def _request_hash(payload: str = "same-request") -> CanonicalRequestHash:
    return CanonicalRequestHash(
        value=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="canonical-test-v1",
    )


def _result(
    result_id: str = "SYNTHETIC_RULE",
    revision: str = "draft-1",
) -> CommandResultReference:
    return CommandResultReference(
        result_type="engineering_rule_revision",
        result_id=result_id,
        result_revision=revision,
    )


def _reserve(
    service: GovernedIdempotencyService,
    *,
    receipt_id: str = "receipt-1",
    identity: CommandIdentity | None = None,
    request_hash: CanonicalRequestHash | None = None,
):
    return service.reserve_or_inspect(
        receipt_id=receipt_id,
        identity=identity or _identity(),
        request_hash=request_hash or _request_hash(),
        correlation_id="synthetic-correlation",
        schema_version="idempotency-test-v1",
        software_version="test-build",
        created_at=NOW,
    )


def _audit(event_id: str, *, correlation_id: str | None = "synthetic-correlation"):
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id="synthetic-actor",
        actor_type="service",
        reason="Synthetic governed command",
        correlation_id=correlation_id,
        schema_version="audit-test-v1",
        software_version="test-build",
        canonicalization_version="canonical-test-v1",
        hash_algorithm="sha256",
        created_at=NOW,
        idempotency_key="synthetic-key",
    )


def _version(rule_id: str, revision: str) -> ContentVersionMetadata:
    payload = json.dumps(
        {"rule_id": rule_id, "revision": revision},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ContentVersionMetadata(
        schema_version="registry-test-v1",
        canonicalization_version="canonical-test-v1",
        hash_algorithm="sha256",
        content_hash=hashlib.sha256(payload).hexdigest(),
        software_version="test-build",
    )


def _create_draft(service: RuleRegistryService) -> EngineeringRuleRevision:
    service.create_identity(
        rule_id="SYNTHETIC_IDEMPOTENT_RULE",
        audit=_audit("identity-audit-event"),
    )
    return service.create_draft_revision(
        rule_id="SYNTHETIC_IDEMPOTENT_RULE",
        revision="draft-1",
        name="Synthetic idempotency draft",
        evidence_class=EvidenceClass.UNRESOLVED,
        category=RuleCategory.OTHER,
        parameter="synthetic_parameter",
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.DATA_INSUFFICIENT,
        reason_for_change="Synthetic idempotency test",
        version_metadata=_version("SYNTHETIC_IDEMPOTENT_RULE", "draft-1"),
        audit=_audit("revision-audit-event"),
    )


def test_first_identity_and_request_reserves_new_receipt(idempotency_engine) -> None:
    with Session(idempotency_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            decision = _reserve(GovernedIdempotencyService(unit_of_work))
            assert decision.disposition is IdempotencyDisposition.NEW
            assert decision.status is CommandReceiptStatus.RESERVED
            unit_of_work.commit()


def test_completed_identical_request_replays_same_result(idempotency_engine) -> None:
    with Session(idempotency_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = GovernedIdempotencyService(unit_of_work)
            _reserve(service)
            completed = service.complete(
                identity=_identity(),
                request_hash=_request_hash(),
                result_reference=_result(),
                completed_at=LATER,
            )
            assert completed.disposition is IdempotencyDisposition.COMPLETED
            unit_of_work.commit()

    with Session(idempotency_engine) as replay_session:
        with GovernedUnitOfWork(replay_session) as replay_uow:
            replay = _reserve(
                GovernedIdempotencyService(replay_uow),
                receipt_id="unused-replay-receipt",
            )
            assert replay.disposition is IdempotencyDisposition.REPLAY
            assert replay.receipt_id == "receipt-1"
            assert replay.result_reference == _result()


def test_same_identity_with_different_request_conflicts(idempotency_engine) -> None:
    with Session(idempotency_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = GovernedIdempotencyService(unit_of_work)
            _reserve(service)
            service.complete(
                identity=_identity(),
                request_hash=_request_hash(),
                result_reference=_result(),
                completed_at=LATER,
            )
            unit_of_work.commit()

    with Session(idempotency_engine) as conflict_session:
        with GovernedUnitOfWork(conflict_session) as conflict_uow:
            conflict = _reserve(
                GovernedIdempotencyService(conflict_uow),
                receipt_id="unused-conflict-receipt",
                request_hash=_request_hash("different-request"),
            )
            assert conflict.disposition is IdempotencyDisposition.CONFLICT
            assert conflict.result_reference is None


def test_incomplete_receipt_is_explicitly_in_progress(idempotency_engine) -> None:
    with Session(idempotency_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            _reserve(GovernedIdempotencyService(unit_of_work))
            unit_of_work.commit()

    with Session(idempotency_engine) as inspect_session:
        with GovernedUnitOfWork(inspect_session) as inspect_uow:
            decision = _reserve(
                GovernedIdempotencyService(inspect_uow),
                receipt_id="unused-in-progress-receipt",
            )
            assert decision.disposition is IdempotencyDisposition.IN_PROGRESS
            assert decision.result_reference is None


def test_invalid_identity_and_request_hash_fail_closed() -> None:
    with pytest.raises(ValueError, match="idempotency_key"):
        CommandIdentity("registry.draft", "synthetic-project", " ")
    with pytest.raises(ValueError, match="canonical request hash"):
        CanonicalRequestHash("", "sha256", "canonical-test-v1")


def test_database_uniqueness_rejects_duplicate_durable_identity(
    idempotency_engine,
) -> None:
    with Session(idempotency_engine) as first_session:
        IdempotencyRepository(first_session).add_reserved(
            receipt_id="first-receipt",
            identity=_identity(),
            request_hash=_request_hash(),
            correlation_id="first-correlation",
            schema_version="idempotency-test-v1",
            software_version="test-build",
            created_at=NOW,
        )
        first_session.commit()

    with Session(idempotency_engine) as duplicate_session:
        with pytest.raises(IntegrityError):
            IdempotencyRepository(duplicate_session).add_reserved(
                receipt_id="second-receipt",
                identity=_identity(),
                request_hash=_request_hash(),
                correlation_id="second-correlation",
                schema_version="idempotency-test-v1",
                software_version="test-build",
                created_at=NOW,
            )
        duplicate_session.rollback()

    with Session(idempotency_engine) as read_session:
        assert read_session.scalar(select(func.count(GovernedCommandReceipt.id))) == 1


def test_state_audit_receipt_and_completion_commit_atomically(
    idempotency_engine,
) -> None:
    with Session(idempotency_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            idempotency = GovernedIdempotencyService(unit_of_work)
            assert _reserve(idempotency).disposition is IdempotencyDisposition.NEW
            revision = _create_draft(RuleRegistryService(unit_of_work))
            completed = idempotency.complete(
                identity=_identity(),
                request_hash=_request_hash(),
                result_reference=_result(
                    result_id="SYNTHETIC_IDEMPOTENT_RULE",
                    revision=revision.revision,
                ),
                completed_at=LATER,
            )
            assert completed.status is CommandReceiptStatus.COMPLETED
            unit_of_work.commit()

    with Session(idempotency_engine) as read_session:
        receipt = IdempotencyRepository(read_session).get_by_identity(_identity())
        assert receipt is not None
        assert receipt.status is CommandReceiptStatus.COMPLETED
        assert read_session.scalar(select(func.count(EngineeringRule.id))) == 1
        assert read_session.scalar(select(func.count(EngineeringRuleRevision.id))) == 1
        assert read_session.scalar(select(func.count(GovernedAuditEvent.id))) == 2


def test_audit_failure_rolls_back_receipt_registry_and_audit(
    idempotency_engine,
) -> None:
    with pytest.raises(IntegrityError):
        with Session(idempotency_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                _reserve(GovernedIdempotencyService(unit_of_work))
                RuleRegistryService(unit_of_work).create_identity(
                    rule_id="AUDIT_FAILURE_RULE",
                    audit=_audit("invalid-audit", correlation_id=None),
                )
                unit_of_work.commit()

    with Session(idempotency_engine) as read_session:
        assert read_session.scalar(select(func.count(GovernedCommandReceipt.id))) == 0
        assert read_session.scalar(select(func.count(EngineeringRule.id))) == 0
        assert read_session.scalar(select(func.count(GovernedAuditEvent.id))) == 0


def test_business_failure_rolls_back_receipt_and_creates_no_audit(
    idempotency_engine,
) -> None:
    with Session(idempotency_engine) as setup_session:
        with GovernedUnitOfWork(setup_session) as setup_uow:
            RuleRegistryService(setup_uow).create_identity(
                rule_id="DUPLICATE_RULE",
                audit=_audit("setup-audit"),
            )
            setup_uow.commit()

    with pytest.raises(IntegrityError):
        with Session(idempotency_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                _reserve(GovernedIdempotencyService(unit_of_work))
                RuleRegistryService(unit_of_work).create_identity(
                    rule_id="DUPLICATE_RULE",
                    audit=_audit("duplicate-audit"),
                )
                unit_of_work.commit()

    with Session(idempotency_engine) as read_session:
        assert read_session.scalar(select(func.count(GovernedCommandReceipt.id))) == 0
        assert read_session.scalar(
            select(func.count(GovernedAuditEvent.id)).where(
                GovernedAuditEvent.event_id == "duplicate-audit"
            )
        ) == 0


def test_explicit_rollback_removes_all_participants(idempotency_engine) -> None:
    with Session(idempotency_engine) as session:
        unit_of_work = GovernedUnitOfWork(session)
        idempotency = GovernedIdempotencyService(unit_of_work)
        _reserve(idempotency)
        revision = _create_draft(RuleRegistryService(unit_of_work))
        idempotency.complete(
            identity=_identity(),
            request_hash=_request_hash(),
            result_reference=_result(revision=revision.revision),
            completed_at=LATER,
        )
        unit_of_work.rollback()

    with Session(idempotency_engine) as read_session:
        assert read_session.scalar(select(func.count(GovernedCommandReceipt.id))) == 0
        assert read_session.scalar(select(func.count(EngineeringRule.id))) == 0
        assert read_session.scalar(select(func.count(GovernedAuditEvent.id))) == 0


def test_idempotency_failure_rolls_back_tentative_registry_and_audit(
    idempotency_engine,
) -> None:
    with Session(idempotency_engine) as setup_session:
        IdempotencyRepository(setup_session).add_reserved(
            receipt_id="winning-receipt",
            identity=_identity(),
            request_hash=_request_hash(),
            correlation_id="winning-correlation",
            schema_version="idempotency-test-v1",
            software_version="test-build",
            created_at=NOW,
        )
        setup_session.commit()

    with pytest.raises(IntegrityError):
        with Session(idempotency_engine) as session:
            with GovernedUnitOfWork(session) as unit_of_work:
                RuleRegistryService(unit_of_work).create_identity(
                    rule_id="ROLLED_BACK_AFTER_IDEMPOTENCY_FAILURE",
                    audit=_audit("rolled-back-audit"),
                )
                unit_of_work.idempotency_repository.add_reserved(
                    receipt_id="losing-receipt",
                    identity=_identity(),
                    request_hash=_request_hash(),
                    correlation_id="losing-correlation",
                    schema_version="idempotency-test-v1",
                    software_version="test-build",
                    created_at=NOW,
                )
                unit_of_work.commit()

    with Session(idempotency_engine) as read_session:
        assert read_session.scalar(select(func.count(GovernedCommandReceipt.id))) == 1
        assert read_session.scalar(select(func.count(EngineeringRule.id))) == 0
        assert read_session.scalar(
            select(func.count(GovernedAuditEvent.id)).where(
                GovernedAuditEvent.event_id == "rolled-back-audit"
            )
        ) == 0


def test_completed_receipt_identity_and_result_are_immutable(
    idempotency_engine,
) -> None:
    with Session(idempotency_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = GovernedIdempotencyService(unit_of_work)
            _reserve(service)
            service.complete(
                identity=_identity(),
                request_hash=_request_hash(),
                result_reference=_result(),
                completed_at=LATER,
            )
            unit_of_work.commit()

    with Session(idempotency_engine) as mutation_session:
        receipt = IdempotencyRepository(mutation_session).get_by_identity(_identity())
        assert receipt is not None
        receipt.result_id = "CHANGED_RESULT"
        with pytest.raises(ImmutableRecordError):
            mutation_session.flush()
        mutation_session.rollback()

        receipt = IdempotencyRepository(mutation_session).get_by_identity(_identity())
        assert receipt is not None
        receipt.idempotency_key = "changed-key"
        with pytest.raises(ImmutableRecordError):
            mutation_session.flush()


def test_completed_receipt_cannot_be_deleted(idempotency_engine) -> None:
    with Session(idempotency_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = GovernedIdempotencyService(unit_of_work)
            _reserve(service)
            service.complete(
                identity=_identity(),
                request_hash=_request_hash(),
                result_reference=_result(),
                completed_at=LATER,
            )
            unit_of_work.commit()

    with Session(idempotency_engine) as delete_session:
        receipt = IdempotencyRepository(delete_session).get_by_identity(_identity())
        assert receipt is not None
        delete_session.delete(receipt)
        with pytest.raises(ImmutableRecordError):
            delete_session.flush()


def test_replay_does_not_reexecute_registry_creation(idempotency_engine) -> None:
    with Session(idempotency_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            idempotency = GovernedIdempotencyService(unit_of_work)
            _reserve(idempotency)
            revision = _create_draft(RuleRegistryService(unit_of_work))
            idempotency.complete(
                identity=_identity(),
                request_hash=_request_hash(),
                result_reference=_result(revision=revision.revision),
                completed_at=LATER,
            )
            unit_of_work.commit()

    with Session(idempotency_engine) as replay_session:
        with GovernedUnitOfWork(replay_session) as replay_uow:
            replay = _reserve(
                GovernedIdempotencyService(replay_uow),
                receipt_id="unused-replay-id",
            )
            assert replay.disposition is IdempotencyDisposition.REPLAY

    with Session(idempotency_engine) as read_session:
        assert read_session.scalar(select(func.count(EngineeringRule.id))) == 1
        assert read_session.scalar(select(func.count(EngineeringRuleRevision.id))) == 1
        assert read_session.scalar(select(func.count(GovernedAuditEvent.id))) == 2


def test_finalized_uow_refuses_idempotency_writes(idempotency_engine) -> None:
    with Session(idempotency_engine) as session:
        unit_of_work = GovernedUnitOfWork(session)
        service = GovernedIdempotencyService(unit_of_work)
        unit_of_work.rollback()
        with pytest.raises(RuntimeError, match="already finalized"):
            _reserve(service)


def test_model_registers_without_models_init_change() -> None:
    assert "governed_command_receipts" in Base.metadata.tables


def test_domain_contract_is_pure_and_immutable() -> None:
    identity = _identity()
    with pytest.raises(Exception):
        identity.idempotency_key = "changed"
    source_path = (
        Path(__file__).parents[1] / "app" / "domain" / "idempotency_types.py"
    )
    source = source_path.read_text(encoding="utf-8")
    assert "sqlalchemy" not in source.lower()
    assert "fastapi" not in source.lower()
    assert "Session" not in source


def test_idempotency_infrastructure_has_no_forbidden_dependencies_or_finalization() -> None:
    root = Path(__file__).parents[1] / "app"
    paths = (
        root / "repositories" / "idempotency_repository.py",
        root / "application" / "governed_idempotency_service.py",
        root / "domain" / "idempotency_types.py",
    )
    forbidden = (
        "FastAPI",
        "fastapi",
        "rules_engine",
        "DEFAULT_RULES",
        "app.api",
        "frontend",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert all(token not in source for token in forbidden)
    for path in paths[:2]:
        source = path.read_text(encoding="utf-8")
        assert ".commit(" not in source
        assert ".rollback(" not in source


def test_service_exposes_no_authority_or_evaluation_commands(
    idempotency_engine,
) -> None:
    with Session(idempotency_engine) as session:
        service = GovernedIdempotencyService(GovernedUnitOfWork(session))
        forbidden_methods = (
            "verify_evidence",
            "promote_source_backed",
            "enable_rule",
            "activate_revision",
            "supersede_revision",
            "retire_revision",
            "evaluate_rule",
            "publish_readiness",
            "publish_passport",
        )
        assert all(not hasattr(service, method) for method in forbidden_methods)
        assert set(inspect.signature(service.reserve_or_inspect).parameters) >= {
            "receipt_id",
            "identity",
            "request_hash",
        }
