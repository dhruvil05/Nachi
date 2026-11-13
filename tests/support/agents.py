"""Start agents on free local ports with real security, and call them as any identity."""

from __future__ import annotations

import secrets
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from nexus_a2a import A2AHttpClient, A2AServer, RetryConfig

from nachi.core.config import Service, Topology
from nachi.core.identity import client_for
from nachi.core.serve import build_server

# Identities every test topology has: the probe (allowed by TRUST_RULES), the gateway,
# and a stranger that has a key but no trust rule anywhere.
BASE_IDENTITIES = ("probe", "gateway", "stranger")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def make_topology(*services: str, name: str = "test") -> Topology:
    """A topology on 127.0.0.1 with a free port per service, plus the base identities."""
    names = dict.fromkeys([*BASE_IDENTITIES, *services])
    return Topology(
        name=name,
        services={n: Service(name=n, url=f"http://127.0.0.1:{free_port()}") for n in names},
    )


def make_keys(topology: Topology) -> dict[str, str]:
    return {name: secrets.token_urlsafe(32) for name in topology.services}


@asynccontextmanager
async def running_agent(
    agent: Any, name: str, topology: Topology, keys: dict[str, str]
) -> AsyncIterator[A2AServer]:
    """Serve ``agent`` as service ``name`` exactly as production does, then stop it."""
    server = build_server(agent, name, topology, keys)
    async with server:
        yield server


def client_as(
    caller: str, target: str, topology: Topology, keys: dict[str, str], **kwargs: Any
) -> A2AHttpClient:
    """A client calling ``target`` as ``caller``, with a single attempt so rejections are fast.

    Note: ``RetryConfig.max_retries`` counts *attempts including the first*, so 1 means
    "no retries" and 0 sends nothing at all (see FINDINGS.md).
    """
    kwargs.setdefault("retry", RetryConfig(max_retries=1))
    kwargs.setdefault("timeout", 10.0)
    return client_for(caller, target, topology, keys, **kwargs)
