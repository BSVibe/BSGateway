"""Alembic environment for BSGateway (Sprint 3 / S3-5).

Reads the database URL from :class:`bsgateway.core.config.Settings` so the
same ``.env`` that powers the runtime drives migrations. Falls back to a
``DATABASE_URL`` env var so transient tooling (CI smoke tests, ad-hoc
``alembic upgrade head`` against a throwaway PG container) does not need
to duplicate the full settings stack.

The ``asyncpg``-style URL used by the gateway runtime is rewritten to a
psycopg2/sync driver scheme for Alembic since Alembic's ``run_migrations``
helpers are sync. The migrations themselves only do DDL so the driver
choice is incidental.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# this is the Alembic Config object, which provides access to the values
# within the .ini file in use.
config = context.config

# Configure logging from alembic.ini if a config file is supplied.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    """Return a sync DSN suitable for Alembic.

    Resolution order:
    1. ``DATABASE_URL`` env var (lets CI / ad-hoc runs override).
    2. ``COLLECTOR_DATABASE_URL`` env var (matches the gateway runtime).
    3. ``Settings().collector_database_url`` (loads ``.env`` via
       pydantic-settings).
    """
    raw = os.environ.get("DATABASE_URL") or os.environ.get("COLLECTOR_DATABASE_URL")
    if not raw:
        # Lazy import to avoid hard-failing when bsgateway is not on path.
        from bsgateway.core.config import settings

        raw = settings.collector_database_url
    if not raw:
        raise RuntimeError(
            "DATABASE_URL / COLLECTOR_DATABASE_URL must be set for Alembic. "
            "Set it in .env or pass via the environment."
        )
    # Normalise asyncpg → psycopg (sync v3) for Alembic. Migrations are
    # DDL only, so the driver is incidental — but it must be a sync DBAPI
    # because Alembic's run_migrations helpers do not do asyncio.
    if raw.startswith("postgresql+asyncpg://"):
        raw = raw.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    elif raw.startswith("postgresql://"):
        raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


# We do NOT use SQLAlchemy ORM models — migrations are written by hand to
# mirror the existing raw-SQL schema. ``target_metadata = None`` disables
# autogenerate, which would otherwise flag every CREATE as missing.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live DB)."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
