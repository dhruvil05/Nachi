"""Run nexus-a2a's conformance check against one running Nachi service.

Calls ``nexus verify`` as the ``probe`` service, with probe's own API key, so the
check goes through the same auth and trust rules as any other caller.

    uv run python scripts/verify_agent.py topologies/t1-ports.toml echo
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from nachi.core.config import load_keys, load_topology
from nachi.core.identity import API_KEY_HEADER, targets_of

PROBE = "probe"


def verify_command(url: str, probe_url: str, probe_key: str, skill: str | None) -> list[str]:
    nexus = shutil.which("nexus")
    if nexus is None:
        raise SystemExit("the `nexus` CLI is not on PATH; run this through `uv run`")
    cmd = [
        nexus,
        "verify",
        url,
        "--caller-url",
        probe_url,
        "--api-key",
        probe_key,
        "--api-key-header",
        API_KEY_HEADER,
    ]
    if skill:
        cmd += ["--skill", skill]
    return cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("topology")
    parser.add_argument("service")
    parser.add_argument("--secrets-dir", default=None)
    parser.add_argument("--strict", action="store_true", help="fail on warnings as well")
    args = parser.parse_args(argv)

    topology = load_topology(args.topology)
    keys = load_keys(topology, args.secrets_dir)
    skills = targets_of(PROBE).get(args.service)
    if not skills:
        raise SystemExit(f"the probe identity is not allowed to call {args.service!r}")
    cmd = verify_command(topology.url(args.service), topology.url(PROBE), keys[PROBE], skills[0])
    if args.strict:
        cmd.append("--strict")
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
