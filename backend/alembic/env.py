from logging.config import fileConfig
import os
from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.session import Base
import app.models  # noqa: F401

POSTGRESQL_ALEMBIC_VERSION_LENGTH = 255

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url")))
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction(): context.run_migrations()


def prepare_postgresql_version_table(connection):
    """Allow Alembic to persist this repository's descriptive revision IDs."""
    if connection.dialect.name != "postgresql":
        return

    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS alembic_version ("
        f"version_num VARCHAR({POSTGRESQL_ALEMBIC_VERSION_LENGTH}) NOT NULL, "
        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    connection.exec_driver_sql(
        "ALTER TABLE alembic_version ALTER COLUMN version_num "
        f"TYPE VARCHAR({POSTGRESQL_ALEMBIC_VERSION_LENGTH})"
    )
    connection.commit()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        prepare_postgresql_version_table(connection)
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction(): context.run_migrations()

if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
