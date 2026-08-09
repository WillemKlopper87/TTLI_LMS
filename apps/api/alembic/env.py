"""Alembic environment.

Migrations run synchronously against psycopg2 while the application runs on
asyncpg. The URL comes from Settings so no connection string is committed.
"""

from __future__ import annotations

import re
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings
from src.models import Base

_PARTITION_NAME = re.compile(r"^events_\d{4}_\d{2}$")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_sync_url = get_settings().sync_database_url
# Migrations need the superuser (DDL, CREATE ROLE). If DATABASE_URL_SYNC is
# unset, sync_database_url derives from DATABASE_URL — which is app_user's
# and cannot run migrations. Fail with the real reason instead of a
# permission error twenty statements in.
if "app_user" in _sync_url.split("@", 1)[0]:
    raise RuntimeError(
        "The migration connection resolves to the app_user role, which cannot run DDL. "
        "Set DATABASE_URL_SYNC to the superuser connection string."
    )
config.set_main_option("sqlalchemy.url", _sync_url)


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    """Keep autogenerate away from things it did not create.

    The extensions are installed by postgres-init, not by a migration.
    Monthly `events` partitions (events_2026_08, ...) are pure DDL managed by
    migrations, not modelled individually — only the partitioned parent
    `events` table is (src/models/event.py). Without this, autogenerate would
    see each partition as an "extra" table absent from Base.metadata and
    propose dropping it.
    """
    if type_ == "table" and (name in {"spatial_ref_sys"} or _PARTITION_NAME.match(name)):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
