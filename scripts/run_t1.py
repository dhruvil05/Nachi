"""Start every Nachi service as its own process on its own port (setup T1).

    uv run python scripts/gen_keys.py topologies/t1-ports.toml   # once
    NACHI_LLM=demo uv run python scripts/run_t1.py               # no API key needed
    uv run python scripts/run_t1.py                              # real Claude models

Then open the gateway URL (http://127.0.0.1:8000). Ctrl+C stops everything.
Each agent keeps its tasks in data/<topology>/<service>.tasks.db, so stopping and
restarting one agent mid-session loses nothing.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request

from nachi.core.config import load_keys, load_topology

GATEWAY = "gateway"


def wait_healthy(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as resp:  # noqa: S310
                if resp.status == 200:
                    return True
        except OSError:
            time.sleep(0.3)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--topology", default="topologies/t1-ports.toml")
    parser.add_argument("--only", nargs="*", help="start only these services")
    args = parser.parse_args(argv)

    topology = load_topology(args.topology)
    load_keys(topology)  # fail early if keys are missing
    services = [s for s in topology.services.values() if s.module]
    if args.only:
        services = [s for s in services if s.name in args.only]
    # Agents first, gateway last: it registers agents on first use, not at start.
    services.sort(key=lambda s: s.name == GATEWAY)

    procs: dict[str, subprocess.Popen[bytes]] = {}
    try:
        for service in services:
            cmd = [sys.executable, "-m", str(service.module), "--topology", args.topology]
            procs[service.name] = subprocess.Popen(cmd)
        for service in services:
            ok = wait_healthy(service.url)
            print(f"  {'up  ' if ok else 'DOWN'} {service.name:<14} {service.url}", flush=True)
            if not ok:
                return 1
        print(f"\nNachi is running. Open {topology.url(GATEWAY)} (Ctrl+C to stop).", flush=True)
        # Keep the others running when one exits: stopping an agent mid-session is a
        # fault scenario worth trying. Restart it by hand with its `python -m` command.
        reported: set[str] = set()
        while any(p.poll() is None for p in procs.values()):
            for name, proc in procs.items():
                if proc.poll() is not None and name not in reported:
                    reported.add(name)
                    print(f"  {name} exited with code {proc.returncode}", flush=True)
            time.sleep(0.5)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for proc in procs.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in procs.values():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
