"""Database URLs and engines.

The app runs async (``sqlite+aiosqlite`` locally, ``postgresql+asyncpg`` in deployment).
Alembic migrations run sync, so ``sync_url()`` maps an async URL to its sync driver.
"""

from __future__ import annotations

import os

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

DATABASE_URL_ENV = "NACHI_DATABASE_URL"
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///nachi.db"

_SYNC_DRIVERS = {
    "sqlite+aiosqlite": "sqlite",
    "postgresql+asyncpg": "postgresql+psycopg",
}


def database_url() -> str:
    return os.environ.get(DATABASE_URL_ENV, DEFAULT_DATABASE_URL)


def sync_url(url: str) -> str:
    """Swap an async driver for its sync one, leaving the rest of the URL untouched.

    (Re-rendering through SQLAlchemy would percent-encode Windows paths like C:/...)
    """
    driver = make_url(url).drivername
    sync_driver = _SYNC_DRIVERS.get(driver, driver)
    scheme, rest = url.split("://", 1)
    return f"{sync_driver}://{rest}" if scheme == driver else url


def make_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(url or database_url())


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:  # type: ignore[type-arg]
    return async_sessionmaker(engine, expire_on_commit=False)
