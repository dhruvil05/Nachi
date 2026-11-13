"""Alembic environment for Nachi's learner tables (sync engine)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from nachi.learner.db import database_url, sync_url
from nachi.learner.models import Base

config = context.config
target_metadata = Base.metadata

# A URL set by the caller (e.g. tests) wins; otherwise use NACHI_DATABASE_URL.
if not config.get_main_option("sqlalchemy.url"):
    # configparser treats % as interpolation, so escape it.
    config.set_main_option("sqlalchemy.url", sync_url(database_url()).replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
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
        # render_as_batch lets ALTER-style migrations work on SQLite too.
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
