"""Test helpers for running nexus-a2a agents for real.

nexus-a2a ships no test helpers today (its fixtures live only in its own
tests/integration/conftest.py). These are written without Nachi specifics where
possible, so they can move into a ``nexus_a2a.testing`` module later.
"""

from tests.support.agents import (
    client_as,
    free_port,
    make_keys,
    make_topology,
    running_agent,
)

__all__ = ["client_as", "free_port", "make_keys", "make_topology", "running_agent"]
