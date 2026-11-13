from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, inspect, select

from nachi.curriculum import load_curriculum
from nachi.learner.db import make_engine, make_sessionmaker, sync_url
from nachi.learner.models import Base, Concept, ConceptPrerequisite
from nachi.learner.seed import seed_curriculum

ROOT = Path(__file__).resolve().parents[2]
TABLES = {
    "students",
    "concepts",
    "concept_prerequisites",
    "mastery",
    "attempts",
    "cards",
    "study_sessions",
}


def _alembic(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", sync_url(url).replace("%", "%%"))
    return cfg


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'nachi.db').as_posix()}"


def test_sync_url_swaps_only_the_driver() -> None:
    assert sync_url("sqlite+aiosqlite:///C:/x/nachi.db") == "sqlite:///C:/x/nachi.db"
    assert (
        sync_url("postgresql+asyncpg://u:p%40ss@db:5432/nachi")
        == "postgresql+psycopg://u:p%40ss@db:5432/nachi"
    )


def test_migrations_create_every_table_and_match_the_models(db_url: str) -> None:
    command.upgrade(_alembic(db_url), "head")
    engine = create_engine(sync_url(db_url))
    try:
        assert TABLES <= set(inspect(engine).get_table_names())
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == [], f"models and migrations differ: {diff}"
    finally:
        engine.dispose()


def test_migrations_downgrade_cleanly(db_url: str) -> None:
    cfg = _alembic(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(sync_url(db_url))
    try:
        assert not (TABLES & set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()


async def test_seed_curriculum_is_idempotent(db_url: str) -> None:
    command.upgrade(_alembic(db_url), "head")
    curriculum = load_curriculum("python")
    engine = make_engine(db_url)
    sessions = make_sessionmaker(engine)
    try:
        for _ in range(2):
            async with sessions() as session:
                assert await seed_curriculum(session, curriculum) == len(curriculum.concepts)
        async with sessions() as session:
            concepts = await session.scalar(select(func.count()).select_from(Concept))
            links = await session.scalar(select(func.count()).select_from(ConceptPrerequisite))
        assert concepts == len(curriculum.concepts)
        assert links == sum(len(c.prerequisites) for c in curriculum.concepts)
    finally:
        await engine.dispose()
