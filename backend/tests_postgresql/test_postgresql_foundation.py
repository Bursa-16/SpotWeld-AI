'''Real-PostgreSQL foundation tests for Phase 6A1.'''

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.governed_idempotency_service import GovernedIdempotencyService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
    CommandReceiptStatus,
    CommandResultReference,
    IdempotencyDisposition,
)
from app.models.entities import AuditLog, Project
from app.repositories.idempotency_repository import IdempotencyRepository


NOW = datetime(2032, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
LATER = datetime(2032, 3, 4, 5, 7, 8, tzinfo=timezone.utc)
EXPECTED_HEAD = '0010_digital_weld_passport'
EARLIER_REVISION = '0004_persistent_idempotency'
LONG_REVISION = '0005_registry_evidence_applicability'
EXPECTED_GOVERNED_TABLES = {
    'engineering_rules',
    'engineering_rule_revisions',
    'governed_audit_events',
    'governed_command_receipts',
    'rule_evaluations',
    'machine_readiness_assessments',
    'digital_weld_passports',
}


def _identity(suffix: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace='phase6a1.postgresql',
        command_scope=f'scope-{suffix}',
        idempotency_key=f'key-{suffix}',
    )


def _request_hash(payload: str) -> CanonicalRequestHash:
    return CanonicalRequestHash(
        value=hashlib.sha256(payload.encode('utf-8')).hexdigest(),
        hash_algorithm='sha256',
        canonicalization_version='phase6a1-canonical-v1',
    )


def _reserve(
    service: GovernedIdempotencyService,
    *,
    suffix: str,
    identity: CommandIdentity,
    request_hash: CanonicalRequestHash,
):
    return service.reserve_or_inspect(
        receipt_id=f'receipt-{suffix}',
        identity=identity,
        request_hash=request_hash,
        correlation_id=f'correlation-{suffix}',
        schema_version='phase6a1-test-v1',
        software_version='phase6a1-test',
        created_at=NOW,
    )


def _current_revision(database_engine) -> str:
    with database_engine.connect() as connection:
        return connection.scalar(text('SELECT version_num FROM alembic_version'))


def test_fresh_postgresql_dialect_and_alembic_head(postgresql_engine) -> None:
    assert postgresql_engine.dialect.name == 'postgresql'
    assert _current_revision(postgresql_engine) == EXPECTED_HEAD
    assert EXPECTED_GOVERNED_TABLES <= set(inspect(postgresql_engine).get_table_names())


def test_postgresql_upgrade_from_earlier_revision_preserves_full_revision_id(
    earlier_revision_postgresql,
) -> None:
    migration = earlier_revision_postgresql
    assert migration.engine.dialect.name == 'postgresql'
    assert _current_revision(migration.engine) == EARLIER_REVISION

    migration.upgrade(LONG_REVISION)
    assert _current_revision(migration.engine) == LONG_REVISION
    with migration.engine.connect() as connection:
        version_capacity = connection.scalar(
            text(
                '''
                SELECT character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'alembic_version'
                  AND column_name = 'version_num'
                '''
            )
        )
    assert version_capacity is not None
    assert version_capacity >= len(LONG_REVISION)

    migration.upgrade('head')
    assert _current_revision(migration.engine) == EXPECTED_HEAD


def test_postgresql_transaction_commit_and_rollback(postgresql_engine) -> None:
    suffix = uuid4().hex
    committed_code = f'P6A1-COMMIT-{suffix}'
    rolled_back_code = f'P6A1-ROLLBACK-{suffix}'

    with Session(postgresql_engine) as session:
        session.add(Project(project_code=committed_code, project_name='Committed'))
        session.commit()
        session.add(Project(project_code=rolled_back_code, project_name='Rolled back'))
        session.flush()
        session.rollback()

    with Session(postgresql_engine) as session:
        committed = session.scalar(
            select(Project).where(Project.project_code == committed_code)
        )
        assert committed is not None
        assert session.scalar(
            select(Project).where(Project.project_code == rolled_back_code)
        ) is None
        session.delete(committed)
        session.commit()


def test_postgresql_enforces_foreign_key_constraint(postgresql_engine) -> None:
    with Session(postgresql_engine) as session:
        session.add(
            AuditLog(
                user_id=2_147_483_647,
                action='phase6a1-fk-check',
                entity_type='postgresql_test',
                entity_id='missing-user',
                detail={},
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_governed_idempotency_persists_and_enforces_uniqueness(
    postgresql_engine,
) -> None:
    suffix = uuid4().hex
    identity = _identity(suffix)
    request_hash = _request_hash(suffix)
    result_reference = CommandResultReference(
        result_type='phase6a1_result',
        result_id=f'result-{suffix}',
        result_revision='1',
    )

    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            service = GovernedIdempotencyService(unit_of_work)
            assert _reserve(
                service,
                suffix=suffix,
                identity=identity,
                request_hash=request_hash,
            ).disposition is IdempotencyDisposition.NEW
            assert service.complete(
                identity=identity,
                request_hash=request_hash,
                result_reference=result_reference,
                completed_at=LATER,
            ).disposition is IdempotencyDisposition.COMPLETED
            unit_of_work.commit()

    with Session(postgresql_engine) as session:
        with GovernedUnitOfWork(session) as unit_of_work:
            replay = _reserve(
                GovernedIdempotencyService(unit_of_work),
                suffix=f'replay-{suffix}',
                identity=identity,
                request_hash=request_hash,
            )
            assert replay.disposition is IdempotencyDisposition.REPLAY
            assert replay.status is CommandReceiptStatus.COMPLETED
            assert replay.result_reference == result_reference
            unit_of_work.rollback()

    with Session(postgresql_engine) as session:
        with pytest.raises(IntegrityError):
            IdempotencyRepository(session).add_reserved(
                receipt_id=f'duplicate-{suffix}',
                identity=identity,
                request_hash=request_hash,
                correlation_id=f'duplicate-correlation-{suffix}',
                schema_version='phase6a1-test-v1',
                software_version='phase6a1-test',
                created_at=NOW,
            )
        session.rollback()
