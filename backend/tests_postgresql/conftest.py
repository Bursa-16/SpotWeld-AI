'''Fixtures for the explicit real-PostgreSQL integration-test path.'''

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url


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


@pytest.fixture(scope='session')
def postgresql_engine() -> Engine:
    '''Upgrade the dedicated PostgreSQL database through the current Alembic head.'''

    config = Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND_ROOT / 'alembic'))
    command.upgrade(config, 'head')

    database_engine = create_engine(POSTGRESQL_URL, pool_pre_ping=True)
    if database_engine.dialect.name != 'postgresql':
        database_engine.dispose()
        raise RuntimeError('PostgreSQL tests connected to a non-PostgreSQL dialect')
    with database_engine.connect() as connection:
        connection.exec_driver_sql('SELECT 1')

    yield database_engine
    database_engine.dispose()
