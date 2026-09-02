'''Fixtures for the explicit real-PostgreSQL integration-test path.'''

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.schema import CreateSchema, DropSchema


BACKEND_ROOT = Path(__file__).parents[1]
TEST_DATABASE_ENV = 'POSTGRES_TEST_DATABASE_URL'


def _required_postgresql_url() -> str:
    database_url = os.getenv(TEST_DATABASE_ENV)
    if not database_url:
        raise RuntimeError(
            f'{TEST_DATABASE_ENV} is required; PostgreSQL tests have no SQLite fallback'
        )
    if make_url(database_url).get_backend_name() != 'postgresql':
        raise RuntimeError(
            f'{TEST_DATABASE_ENV} must use the PostgreSQL dialect; '
            'SQLite fallback is forbidden'
        )
    return database_url


POSTGRESQL_URL = _required_postgresql_url()
os.environ['DATABASE_URL'] = POSTGRESQL_URL


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND_ROOT / 'alembic'))
    return config


def _upgrade(database_url: str, revision: str) -> None:
    prior_database_url = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = database_url
    try:
        command.upgrade(_alembic_config(), revision)
    finally:
        if prior_database_url is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = prior_database_url


def _schema_url(schema_name: str) -> str:
    return make_url(POSTGRESQL_URL).update_query_dict(
        {'options': f'-csearch_path={schema_name}'}
    ).render_as_string(hide_password=False)


def _create_schema(base_engine: Engine, prefix: str) -> tuple[str, str, Engine]:
    schema_name = f'{prefix}_{uuid4().hex}'
    with base_engine.begin() as connection:
        connection.execute(CreateSchema(schema_name))
    database_url = _schema_url(schema_name)
    return schema_name, database_url, create_engine(database_url, pool_pre_ping=True)


def _drop_schema(base_engine: Engine, schema_name: str) -> None:
    with base_engine.begin() as connection:
        connection.execute(DropSchema(schema_name, cascade=True))


@dataclass(frozen=True)
class PostgreSQLMigrationHarness:
    engine: Engine
    database_url: str

    def upgrade(self, revision: str) -> None:
        self.engine.dispose()
        _upgrade(self.database_url, revision)


@pytest.fixture(scope='session')
def postgresql_database_engine() -> Engine:
    database_engine = create_engine(POSTGRESQL_URL, pool_pre_ping=True)
    if database_engine.dialect.name != 'postgresql':
        database_engine.dispose()
        raise RuntimeError('PostgreSQL tests connected to a non-PostgreSQL dialect')
    with database_engine.connect() as connection:
        connection.exec_driver_sql('SELECT 1')
    yield database_engine
    database_engine.dispose()


@pytest.fixture(scope='session')
def postgresql_engine(postgresql_database_engine: Engine) -> Engine:
    '''Upgrade an isolated empty PostgreSQL schema through Alembic head.'''

    schema_name, database_url, database_engine = _create_schema(
        postgresql_database_engine,
        'phase6a1_fresh',
    )
    try:
        _upgrade(database_url, 'head')
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_schema(postgresql_database_engine, schema_name)


@pytest.fixture(scope='session')
def earlier_revision_postgresql(
    postgresql_database_engine: Engine,
) -> PostgreSQLMigrationHarness:
    '''Create an isolated PostgreSQL schema migrated only through revision 0004.'''

    schema_name, database_url, database_engine = _create_schema(
        postgresql_database_engine,
        'phase6a1_earlier',
    )
    try:
        _upgrade(database_url, '0004_persistent_idempotency')
        yield PostgreSQLMigrationHarness(database_engine, database_url)
    finally:
        database_engine.dispose()
        _drop_schema(postgresql_database_engine, schema_name)
