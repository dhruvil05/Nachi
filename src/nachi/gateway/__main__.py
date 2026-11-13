"""Run the gateway: migrate and seed the learner database, then serve HTTP.

python -m nachi.gateway --topology topologies/t1-ports.toml
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from nachi.core.config import TOPOLOGY_ENV, load_keys, load_topology
from nachi.core.peers import Peers
from nachi.curriculum import load_curriculum
from nachi.gateway.app import create_app
from nachi.gateway.service import Learning
from nachi.learner.db import database_url, make_engine, make_sessionmaker
from nachi.learner.migrate import prepare

log = logging.getLogger("nachi.gateway")


async def serve(topology_path: str | None, secrets_dir: str | None) -> None:
    topology = load_topology(topology_path)
    keys = load_keys(topology, secrets_dir)
    curriculum = load_curriculum("python")
    url = database_url()
    await prepare(url, curriculum)

    engine = make_engine(url)
    learning = Learning(Peers("gateway", topology, keys), make_sessionmaker(engine), curriculum)
    service = topology.service("gateway")
    config = uvicorn.Config(
        create_app(learning), host=service.host, port=service.port, log_level="warning"
    )
    log.info("gateway serving on %s (topology %s, db %s)", service.url, topology.name, url)
    try:
        await uvicorn.Server(config).serve()
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Nachi gateway.")
    parser.add_argument(
        "--topology", default=None, help=f"topology file (default: ${TOPOLOGY_ENV})"
    )
    parser.add_argument("--secrets-dir", default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(name)s %(message)s")
    try:
        asyncio.run(serve(args.topology, args.secrets_dir))
    except KeyboardInterrupt:
        log.info("gateway stopped")


if __name__ == "__main__":
    main()
