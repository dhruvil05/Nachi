"""Create the learner tables (if needed) and load a curriculum into the database.

    uv run alembic upgrade head
    uv run python scripts/seed_curriculum.py python

Uses NACHI_DATABASE_URL (default: sqlite+aiosqlite:///nachi.db).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from nachi.curriculum import load_curriculum
from nachi.learner.db import database_url, make_engine, make_sessionmaker
from nachi.learner.seed import seed_curriculum


async def _seed(name: str) -> int:
    curriculum = load_curriculum(name)
    engine = make_engine()
    try:
        async with make_sessionmaker(engine)() as session:
            return await seed_curriculum(session, curriculum)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load a curriculum into the database.")
    parser.add_argument("curriculum", nargs="?", default="python")
    args = parser.parse_args(argv)
    count = asyncio.run(_seed(args.curriculum))
    print(f"seeded {count} concepts from curriculum/{args.curriculum} into {database_url()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
