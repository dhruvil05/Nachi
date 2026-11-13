"""Run the whole Nachi network for a test: every agent on its own local port with real
security, plus the gateway app, all talking real HTTP and A2A.

Agents can be stopped and started again individually (``restart`` / ``stop``) to test
faults and recovery. Tasks live in a SQLite store per agent under ``tmp_path``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from nexus_a2a import A2AServer
from sqlalchemy.ext.asyncio import AsyncEngine

from nachi.agents.diagnostician import Diagnostician
from nachi.agents.explainer import Explainer
from nachi.agents.grader import Grader
from nachi.agents.quizmaker import QuizMaker
from nachi.agents.scheduler import ReviewScheduler
from nachi.agents.tutor import SocraticTutor
from nachi.core.config import Topology
from nachi.core.llm import LLM
from nachi.core.llm.demo import DemoLLM
from nachi.core.peers import Peers
from nachi.core.serve import build_server
from nachi.core.store import SqliteTaskStore
from nachi.curriculum import load_curriculum
from nachi.gateway.app import create_app
from nachi.gateway.service import Learning
from nachi.learner.db import make_engine, make_sessionmaker
from nachi.learner.migrate import prepare
from tests.support.agents import make_keys, make_topology

AGENTS = ("diagnostician", "tutor", "explainer", "quizmaker", "grader", "scheduler")


@dataclass
class Network:
    topology: Topology
    keys: dict[str, str]
    llm: LLM
    store_dir: Path
    http: httpx.AsyncClient = field(init=False)
    learning: Learning = field(init=False)
    servers: dict[str, A2AServer] = field(default_factory=dict)
    stores: dict[str, SqliteTaskStore] = field(default_factory=dict)

    def build_agent(self, name: str) -> Any:
        factories: dict[str, Callable[[], Any]] = {
            "diagnostician": lambda: Diagnostician(self.llm),
            "tutor": lambda: SocraticTutor(self.llm, Peers("tutor", self.topology, self.keys)),
            "explainer": lambda: Explainer(self.llm),
            "quizmaker": lambda: QuizMaker(self.llm),
            "grader": lambda: Grader(self.llm),
            "scheduler": lambda: ReviewScheduler(),
        }
        return factories[name]()

    async def start(self, name: str) -> None:
        store = SqliteTaskStore(self.store_dir / f"{name}.tasks.db")
        server = build_server(self.build_agent(name), name, self.topology, self.keys, store=store)
        await server.start()
        self.servers[name], self.stores[name] = server, store

    async def stop(self, name: str) -> None:
        server = self.servers.pop(name)
        await server.stop()
        await self.stores.pop(name).close()

    async def restart(self, name: str) -> None:
        """Stop the agent and start a brand-new instance on the same port and store."""
        await self.stop(name)
        await self.start(name)

    async def student(self, name: str = "Asha") -> dict[str, str]:
        res = await self.http.post("/api/students", json={"display_name": name})
        res.raise_for_status()
        return {"X-Student-Id": res.json()["student_id"]}


@asynccontextmanager
async def nachi_network(tmp_path: Path, llm: LLM | None = None) -> AsyncIterator[Network]:
    topology = make_topology(*AGENTS)
    keys = make_keys(topology)
    net = Network(topology=topology, keys=keys, llm=llm or DemoLLM(), store_dir=tmp_path / "tasks")
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'learner.db').as_posix()}"
    curriculum = load_curriculum("python")
    await prepare(db_url, curriculum)
    engine: AsyncEngine = make_engine(db_url)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(engine.dispose)
        for name in AGENTS:
            await net.start(name)

        async def stop_all() -> None:
            for name in list(net.servers):
                await net.stop(name)

        stack.push_async_callback(stop_all)
        net.learning = Learning(
            Peers("gateway", topology, keys), make_sessionmaker(engine), curriculum
        )
        transport = httpx.ASGITransport(app=create_app(net.learning))
        net.http = await stack.enter_async_context(
            httpx.AsyncClient(transport=transport, base_url="http://gateway", timeout=60.0)
        )
        yield net
