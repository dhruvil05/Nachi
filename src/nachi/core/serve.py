"""Run one Nachi agent as its own A2A service.

Every agent package has a ``__main__`` that calls ``main(AgentClass, "<service>")``, so
any agent can run alone on the port or machine its topology assigns::

    python -m nachi.agents.echo --topology topologies/t1-ports.toml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from nexus_a2a import A2AServer

from nachi.core.config import TOPOLOGY_ENV, Topology, load_keys, load_topology
from nachi.core.identity import build_security

log = logging.getLogger("nachi.serve")


def build_server(agent: Any, name: str, topology: Topology, keys: dict[str, str]) -> A2AServer:
    """An A2AServer for service ``name``: bound per the topology, security always on."""
    service = topology.service(name)
    return A2AServer(
        agent,
        host=service.host,
        port=service.port,
        public_url=service.url,
        security=build_security(name, topology, keys),
    )


async def run_agent(
    agent: Any,
    name: str,
    topology: Topology,
    keys: dict[str, str],
    *,
    stop: asyncio.Event | None = None,
) -> None:
    """Serve until ``stop`` is set (or forever)."""
    stop = stop or asyncio.Event()
    server = build_server(agent, name, topology, keys)
    async with server:
        log.info("%s serving on %s (topology %s)", name, topology.url(name), topology.name)
        await stop.wait()


def main(agent: Any, name: str, argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"Run the Nachi {name} agent.")
    parser.add_argument(
        "--topology",
        default=None,
        help=f"topology file (default: ${TOPOLOGY_ENV})",
    )
    parser.add_argument("--secrets-dir", default=None, help="directory holding <topology>.toml")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(name)s %(message)s")
    topology = load_topology(args.topology)
    keys = load_keys(topology, args.secrets_dir)
    try:
        asyncio.run(run_agent(agent, name, topology, keys))
    except KeyboardInterrupt:
        log.info("%s stopped", name)
