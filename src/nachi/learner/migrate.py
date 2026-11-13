"""Bring a database up to date: run Alembic migrations, then load the curriculum."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from nachi.curriculum import Curriculum
from nachi.learner.db import make_engine, make_sessionmaker, sync_url
from nachi.learner.seed import seed_curriculum

REPO_ROOT = Path(__file__).resolve().parents[3]


def upgrade(url: str) -> None:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", sync_url(url).replace("%", "%%"))
    command.upgrade(cfg, "head")


async def prepare(url: str, curriculum: Curriculum) -> None:
    await asyncio.to_thread(upgrade, url)
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine)() as session:
            await seed_curriculum(session, curriculum)
    finally:
        await engine.dispose()
