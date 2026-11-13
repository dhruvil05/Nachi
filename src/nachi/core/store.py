"""A SQLite-backed nexus-a2a task store, so a paused session survives a restart.

nexus-a2a ships in-memory, Redis and Postgres task stores. Nachi's local setups (T0/T1)
run without Docker, so this store implements the public ``AbstractTaskStore`` interface
on a SQLite file per service. The whole Task, including its server-side ``owner``, is
kept as JSON, the same way ``PostgresTaskStore`` does it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
from nexus_a2a import AbstractTaskStore, Task

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id         TEXT PRIMARY KEY,
    state      TEXT NOT NULL,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tasks_state ON tasks (state);
"""


def _state(task: Task) -> str:
    state = task.state
    return str(getattr(state, "value", state))


class SqliteTaskStore(AbstractTaskStore):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def _connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(self.path)
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.executescript(_SCHEMA)
            await conn.commit()
            self._conn = conn
        return self._conn

    async def save(self, task: Task) -> None:
        async with self._lock:
            conn = await self._connection()
            await conn.execute(
                "INSERT OR REPLACE INTO tasks (id, state, data, updated_at) VALUES (?, ?, ?, ?)",
                (task.id, _state(task), task.model_dump_json(), task.updated_at.isoformat()),
            )
            await conn.commit()

    async def get(self, task_id: str) -> Task | None:
        async with self._lock:
            conn = await self._connection()
            async with conn.execute("SELECT data FROM tasks WHERE id = ?", (task_id,)) as cur:
                row = await cur.fetchone()
        return Task.model_validate_json(row[0]) if row else None

    async def delete(self, task_id: str) -> None:
        async with self._lock:
            conn = await self._connection()
            await conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            await conn.commit()

    async def list_all(self) -> list[Task]:
        async with self._lock:
            conn = await self._connection()
            async with conn.execute("SELECT data FROM tasks") as cur:
                rows = await cur.fetchall()
        return [Task.model_validate_json(r[0]) for r in rows]

    async def list_by_state(self, state: str) -> list[Task]:
        async with self._lock:
            conn = await self._connection()
            async with conn.execute("SELECT data FROM tasks WHERE state = ?", (state,)) as cur:
                rows = await cur.fetchall()
        return [Task.model_validate_json(r[0]) for r in rows]

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
