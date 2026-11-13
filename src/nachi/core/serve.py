"""Run one Nachi agent as its own A2A service.

Every agent package has a ``__main__`` that calls ``main(factory, "<service>")``. The
factory receives an ``AgentContext`` (LLM, peers, topology) and returns the agent, so
the same agent runs alone on whatever port or machine the topology assigns::

    python -m nachi.agents.tutor --topology topologies/t1-ports.toml

Tasks are kept in a SQLite file per service (``$NACHI_DATA_DIR/<topology>/<service>
.tasks.db``), so a paused session survives a restart. ``NACHI_TASK_STORE=memory``
keeps them in memory instead.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexus_a2a import A2AServer, AbstractTaskStore, InMemoryTaskStore

from nachi.core.config import TOPOLOGY_ENV, Topology, load_keys, load_topology
from nachi.core.identity import build_security
from nachi.core.llm import LLM, make_llm
from nachi.core.peers import Peers
from nachi.core.store import SqliteTaskStore

log = logging.getLogger("nachi.serve")

DATA_DIR_ENV = "NACHI_DATA_DIR"
STORE_ENV = "NACHI_TASK_STORE"


@dataclass
class AgentContext:
    name: str
    topology: Topology
    keys: dict[str, str]
    llm: LLM
    peers: Peers


AgentFactory = Callable[[AgentContext], Any]


def task_store_for(name: str, topology: Topology) -> AbstractTaskStore:
    if os.environ.get(STORE_ENV, "sqlite").lower() == "memory":
        return InMemoryTaskStore()
    base = Path(os.environ.get(DATA_DIR_ENV, "data"))
    return SqliteTaskStore(base / topology.name / f"{name}.tasks.db")


def build_server(
    agent: Any,
    name: str,
    topology: Topology,
    keys: dict[str, str],
    *,
    store: AbstractTaskStore | None = None,
) -> A2AServer:
    """An A2AServer for service ``name``: bound per the topology, security always on."""
    service = topology.service(name)
    return A2AServer(
        agent,
        host=service.host,
        port=service.port,
        public_url=service.url,
        security=build_security(name, topology, keys),
        store=store,
    )


async def run_agent(
    factory: AgentFactory,
    name: str,
    topology: Topology,
    keys: dict[str, str],
    *,
    llm: LLM | None = None,
    store: AbstractTaskStore | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Build the agent, serve it until ``stop`` is set (or forever)."""
    stop = stop or asyncio.Event()
    context = AgentContext(
        name=name,
        topology=topology,
        keys=keys,
        llm=llm or make_llm(),
        peers=Peers(name, topology, keys),
    )
    store = store or task_store_for(name, topology)
    server = build_server(factory(context), name, topology, keys, store=store)
    try:
        async with server:
            log.info("%s serving on %s (topology %s)", name, topology.url(name), topology.name)
            await stop.wait()
    finally:
        close = getattr(store, "close", None)
        if close is not None:
            await close()


def main(factory: AgentFactory, name: str, argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"Run the Nachi {name} agent.")
    parser.add_argument(
        "--topology", default=None, help=f"topology file (default: ${TOPOLOGY_ENV})"
    )
    parser.add_argument("--secrets-dir", default=None, help="directory holding <topology>.toml")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(name)s %(message)s")
    topology = load_topology(args.topology)
    keys = load_keys(topology, args.secrets_dir)
    try:
        asyncio.run(run_agent(factory, name, topology, keys))
    except KeyboardInterrupt:
        log.info("%s stopped", name)
