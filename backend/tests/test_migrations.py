from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import app.models  # noqa: F401
import pytest
from alembic import command
from alembic.config import Config
from app.db.session import Base
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    RuleLifecycleStatus,
)
from app.domain.rule_registry_types import MissingHandling, RuleCategory, SafeDefault
from app.models.rule_registry import EngineeringRuleRevision
from app.repositories.rule_registry_repository import RuleRegistryRepository
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).parents[1]
BASE_REGISTRY_TABLES = {
    "engineering_rules",
    "engineering_rule_revisions",
    "evidence_references",
    "governed_audit_events",
    "governed_command_receipts",
    "rule_applicabilities",
}
LIFECYCLE_TABLES = {
    "rule_lifecycle_events",
}
VERIFICATION_TABLES = {
    "evidence_verification_delegations",
    "evidence_verification_decisions",
}
ALL_GOVERNED_TABLES = BASE_REGISTRY_TABLES | LIFECYCLE_TABLES | VERIFICATION_TABLES


def _sqlite_url(database_path: Path) -> str:
    return f"sqlite:///{database_path.as_posix()}"


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def _run_upgrade(monkeypatch, database_url: str, revision: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), revision)


def _run_downgrade(monkeypatch, database_url: str, revision: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.downgrade(_alembic_config(), revision)


@contextmanager
def _sqlite_engine(database_url: str):
    database_engine = create_engine(database_url)

    @event.listens_for(database_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    try:
        yield database_engine
    finally:
        database_engine.dispose()


@pytest.fixture()
def database():
    yield


@pytest.fixture()
def migration_database_dir():
    with TemporaryDirectory(prefix="registry-migration-") as path:
        yield Path(path)


def _type_signature(column_type) -> tuple[type, int | None]:
    return column_type._type_affinity, getattr(column_type, "length", None)


def _unique_columns_from_model(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _foreign_keys_from_model(
    table_name: str,
) -> set[tuple[tuple[str, ...], str, tuple[str, ...], str | None]]:
    table = Base.metadata.tables[table_name]
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            constraint.elements[0].column.table.name,
            tuple(element.column.name for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _assert_registry_schema_matches_models(
    database_engine,
    table_names=BASE_REGISTRY_TABLES,
) -> None:
    schema_inspector = inspect(database_engine)
    for table_name in table_names:
        model_table = Base.metadata.tables[table_name]
        migrated_columns = {
            column["name"]: column
            for column in schema_inspector.get_columns(table_name)
        }
        assert set(migrated_columns) == set(model_table.columns.keys())
        for column_name, model_column in model_table.columns.items():
            migrated_column = migrated_columns[column_name]
            assert migrated_column["nullable"] is model_column.nullable
            assert bool(migrated_column["primary_key"]) is model_column.primary_key
            assert _type_signature(migrated_column["type"]) == _type_signature(
                model_column.type
            )
            assert migrated_column["default"] is model_column.server_default

        migrated_unique_columns = {
            tuple(constraint["column_names"])
            for constraint in schema_inspector.get_unique_constraints(table_name)
        }
        assert migrated_unique_columns == _unique_columns_from_model(table_name)

        migrated_indexes = {
            (
                index["name"],
                tuple(index["column_names"]),
                bool(index["unique"]),
            )
            for index in schema_inspector.get_indexes(table_name)
        }
        model_indexes = {
            (
                index.name,
                tuple(column.name for column in index.columns),
                bool(index.unique),
            )
            for index in model_table.indexes
        }
        assert migrated_indexes == model_indexes

        migrated_foreign_keys = {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
                constraint.get("options", {}).get("ondelete"),
            )
            for constraint in schema_inspector.get_foreign_keys(table_name)
        }
        assert migrated_foreign_keys == _foreign_keys_from_model(table_name)

        migrated_check_names = {
            constraint["name"]
            for constraint in schema_inspector.get_check_constraints(table_name)
        }
        model_check_names = {
            constraint.name
            for constraint in model_table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert migrated_check_names == model_check_names


def _create_unresolved_revision(
    session: Session,
    *,
    rule_id: str,
    revision: str,
):
    repository = RuleRegistryRepository(session)
    rule = repository.get_by_rule_id(rule_id)
    if rule is None:
        rule = repository.create_rule(
            rule_id=rule_id,
            created_by_actor_id="migration-test-actor",
        )
    return repository.create_revision(
        engineering_rule=rule,
        revision=revision,
        name="Synthetic migrated unresolved requirement",
        status=RuleLifecycleStatus.DRAFT,
        evidence_class=EvidenceClass.UNRESOLVED,
        category=RuleCategory.OTHER,
        parameter="synthetic_parameter",
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.DATA_INSUFFICIENT,
        enabled=False,
        reason_for_change="Migration constraint test",
        version_metadata=ContentVersionMetadata(
            schema_version="migration-test-v1",
            canonicalization_version="test-canonical-v1",
            hash_algorithm="sha256",
            content_hash=f"{rule_id}-{revision}",
            software_version="test-build",
        ),
        created_by_actor_id="migration-test-actor",
    )


def test_sqlite_registry_migration_upgrades_empty_and_downgrades_cleanly(
    migration_database_dir,
    monkeypatch,
):
    database_url = _sqlite_url(
        migration_database_dir / "empty_registry_migration.db"
    )

    _run_upgrade(monkeypatch, database_url, "head")

    with _sqlite_engine(database_url) as migrated_engine:
        migrated_tables = set(inspect(migrated_engine).get_table_names())
        assert ALL_GOVERNED_TABLES <= migrated_tables
        with migrated_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0007_rule_lifecycle_events"
            )
            for table_name in ALL_GOVERNED_TABLES:
                assert connection.scalar(text(f"SELECT COUNT(*) FROM {table_name}")) == 0
        _assert_registry_schema_matches_models(migrated_engine, ALL_GOVERNED_TABLES)

    _run_downgrade(monkeypatch, database_url, "0002_auth_audit")

    with _sqlite_engine(database_url) as downgraded_engine:
        downgraded_tables = set(inspect(downgraded_engine).get_table_names())
        assert ALL_GOVERNED_TABLES.isdisjoint(downgraded_tables)
        assert {"projects", "users", "audit_logs", "test_results"} <= downgraded_tables
        with downgraded_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0002_auth_audit"
            )

    _run_upgrade(monkeypatch, database_url, "head")
    with _sqlite_engine(database_url) as reupgraded_engine:
        assert ALL_GOVERNED_TABLES <= set(inspect(reupgraded_engine).get_table_names())
        with reupgraded_engine.connect() as connection:
            for table_name in ALL_GOVERNED_TABLES:
                assert connection.scalar(text(f"SELECT COUNT(*) FROM {table_name}")) == 0


def test_sqlite_upgrade_from_previous_head_preserves_legacy_data(
    migration_database_dir,
    monkeypatch,
):
    database_url = _sqlite_url(
        migration_database_dir / "prior_head_registry_migration.db"
    )
    _run_upgrade(monkeypatch, database_url, "0002_auth_audit")

    with _sqlite_engine(database_url) as legacy_engine:
        now = datetime.now(timezone.utc).isoformat()
        with legacy_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO projects (
                        project_code,
                        project_name,
                        customer,
                        vehicle_platform,
                        status,
                        created_at,
                        updated_at
                    ) VALUES (
                        :project_code,
                        :project_name,
                        :customer,
                        :vehicle_platform,
                        :status,
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "project_code": "MIGRATION-PRESERVATION",
                    "project_name": "Migration preservation fixture",
                    "customer": "",
                    "vehicle_platform": "",
                    "status": "Test",
                    "created_at": now,
                    "updated_at": now,
                },
            )

    _run_upgrade(monkeypatch, database_url, "head")

    with _sqlite_engine(database_url) as upgraded_engine:  # noqa: SIM117
        with upgraded_engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT COUNT(*) FROM projects "
                    "WHERE project_code = 'MIGRATION-PRESERVATION'"
                )
            ) == 1
            for table_name in BASE_REGISTRY_TABLES:
                assert connection.scalar(text(f"SELECT COUNT(*) FROM {table_name}")) == 0

    _run_downgrade(monkeypatch, database_url, "0002_auth_audit")

    with _sqlite_engine(database_url) as downgraded_engine:
        with downgraded_engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT COUNT(*) FROM projects "
                    "WHERE project_code = 'MIGRATION-PRESERVATION'"
                )
            ) == 1
        assert BASE_REGISTRY_TABLES.isdisjoint(
            inspect(downgraded_engine).get_table_names()
        )


def test_sqlite_migrated_constraints_reject_duplicate_and_cross_rule_history(
    migration_database_dir,
    monkeypatch,
):
    database_url = _sqlite_url(migration_database_dir / "registry_constraints.db")
    _run_upgrade(monkeypatch, database_url, "head")

    with _sqlite_engine(database_url) as migrated_engine:
        with Session(migrated_engine) as session:
            first = _create_unresolved_revision(
                session,
                rule_id="MIGRATION_RULE_ONE",
                revision="1.0",
            )
            second = _create_unresolved_revision(
                session,
                rule_id="MIGRATION_RULE_TWO",
                revision="1.0",
            )
            session.commit()
            first_id = first.id
            second_id = second.id

        with Session(migrated_engine) as duplicate_session:
            with pytest.raises(IntegrityError):
                _create_unresolved_revision(
                    duplicate_session,
                    rule_id="MIGRATION_RULE_ONE",
                    revision="1.0",
                )
            duplicate_session.rollback()

        with pytest.raises(IntegrityError):  # noqa: SIM117
            with migrated_engine.begin() as connection:
                connection.execute(
                    update(EngineeringRuleRevision)
                    .where(EngineeringRuleRevision.id == second_id)
                    .values(supersedes_revision_id=first_id)
                )

        with pytest.raises(IntegrityError):  # noqa: SIM117
            with migrated_engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE engineering_rule_revisions "
                        "SET status = 'UNKNOWN_LIFECYCLE' WHERE id = :revision_id"
                    ),
                    {"revision_id": first_id},
                )

        with pytest.raises(IntegrityError):  # noqa: SIM117
            with migrated_engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE engineering_rule_revisions "
                        "SET supersedes_revision_id = id WHERE id = :revision_id"
                    ),
                    {"revision_id": first_id},
                )

        with pytest.raises(IntegrityError):  # noqa: SIM117
            with migrated_engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE engineering_rule_revisions "
                        "SET effective_date = :effective_date, expiry_date = :expiry_date "
                        "WHERE id = :revision_id"
                    ),
                    {
                        "effective_date": "2030-01-01T00:00:00+00:00",
                        "expiry_date": "2029-01-01T00:00:00+00:00",
                        "revision_id": first_id,
                    },
                )


def test_registry_migration_contains_no_seed_or_prototype_import():
    migration_path = (
        BACKEND_ROOT / "alembic" / "versions" / "0003_registry_foundation.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    normalized = source.lower()

    assert "bulk_insert" not in normalized
    assert "op.execute" not in normalized
    assert "get_bind" not in normalized
    assert "rules_engine" not in normalized
    assert "default_rules" not in normalized
    assert "app.domain.engine" not in normalized


def test_persistent_idempotency_migration_downgrades_to_registry_head(
    migration_database_dir,
    monkeypatch,
):
    database_url = _sqlite_url(
        migration_database_dir / "idempotency_downgrade.db"
    )
    _run_upgrade(monkeypatch, database_url, "head")

    with _sqlite_engine(database_url) as upgraded_engine:
        assert "governed_command_receipts" in inspect(
            upgraded_engine
        ).get_table_names()

    _run_downgrade(monkeypatch, database_url, "0003_registry_foundation")

    with _sqlite_engine(database_url) as downgraded_engine:
        tables = set(inspect(downgraded_engine).get_table_names())
        assert "governed_command_receipts" not in tables
        assert {
            "engineering_rules",
            "engineering_rule_revisions",
            "evidence_references",
            "governed_audit_events",
        } <= tables
        with downgraded_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0003_registry_foundation"
            )


def test_persistent_idempotency_migration_contains_no_seed_or_prototype_import():
    migration_path = (
        BACKEND_ROOT / "alembic" / "versions" / "0004_persistent_idempotency.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    normalized = source.lower()

    assert 'down_revision = "0003_registry_foundation"' in source
    assert "bulk_insert" not in normalized
    assert "op.execute" not in normalized
    assert "get_bind" not in normalized
    assert "rules_engine" not in normalized
    assert "default_rules" not in normalized
    assert "app.domain.engine" not in normalized


def test_registry_evidence_applicability_migration_round_trip(
    migration_database_dir,
    monkeypatch,
):
    database_url = _sqlite_url(migration_database_dir / "registry_r2_round_trip.db")
    _run_upgrade(monkeypatch, database_url, "0004_persistent_idempotency")
    with _sqlite_engine(database_url) as prior_engine:
        assert "rule_applicabilities" not in inspect(prior_engine).get_table_names()
        assert "revision_number" not in {
            column["name"]
            for column in inspect(prior_engine).get_columns("evidence_references")
        }

    _run_upgrade(monkeypatch, database_url, "0005_registry_evidence_applicability")
    with _sqlite_engine(database_url) as upgraded_engine:
        inspector = inspect(upgraded_engine)
        assert "rule_applicabilities" in inspector.get_table_names()
        evidence_columns = {
            column["name"] for column in inspector.get_columns("evidence_references")
        }
        assert {"revision_number", "supersedes_evidence_reference_id", "availability"} <= evidence_columns
        _assert_registry_schema_matches_models(upgraded_engine, BASE_REGISTRY_TABLES)

    _run_downgrade(monkeypatch, database_url, "0004_persistent_idempotency")
    with _sqlite_engine(database_url) as downgraded_engine:
        inspector = inspect(downgraded_engine)
        assert "rule_applicabilities" not in inspector.get_table_names()
        evidence_columns = {
            column["name"] for column in inspector.get_columns("evidence_references")
        }
        assert "revision_number" not in evidence_columns
        with downgraded_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0004_persistent_idempotency"
            )


def test_registry_evidence_applicability_migration_has_no_seed_or_prototype_import():
    migration_path = (
        BACKEND_ROOT
        / "alembic"
        / "versions"
        / "0005_registry_evidence_applicability.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    normalized = source.lower()
    assert 'down_revision = "0004_persistent_idempotency"' in source
    assert "bulk_insert" not in normalized
    assert "rules_engine" not in normalized
    assert "default_rules" not in normalized


def test_verification_authority_migration_round_trip(
    migration_database_dir,
    monkeypatch,
):
    database_url = _sqlite_url(
        migration_database_dir / "verification_authority_migration.db"
    )
    _run_upgrade(monkeypatch, database_url, "0005_registry_evidence_applicability")
    with _sqlite_engine(database_url) as prior_engine:
        assert VERIFICATION_TABLES.isdisjoint(inspect(prior_engine).get_table_names())

    _run_upgrade(monkeypatch, database_url, "head")
    with _sqlite_engine(database_url) as upgraded_engine:
        upgraded_tables = set(inspect(upgraded_engine).get_table_names())
        assert VERIFICATION_TABLES <= upgraded_tables
        _assert_registry_schema_matches_models(upgraded_engine, ALL_GOVERNED_TABLES)
        with upgraded_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0007_rule_lifecycle_events"
            )

    _run_downgrade(monkeypatch, database_url, "0005_registry_evidence_applicability")
    with _sqlite_engine(database_url) as downgraded_engine:
        assert VERIFICATION_TABLES.isdisjoint(
            inspect(downgraded_engine).get_table_names()
        )
        with downgraded_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0005_registry_evidence_applicability"
            )
