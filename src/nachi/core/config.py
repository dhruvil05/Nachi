"""Topology and secrets loading.

A *topology* says where every Nachi service lives: its URL, optionally the address
it binds to, and which module runs it. The same agent code runs in every setup
(T0 one process, T1 ports, T2 containers, T3 servers); only the topology file changes.

Example (``topologies/t1-ports.toml``)::

    name = "t1-ports"

    [services.gateway]
    url = "http://127.0.0.1:8000"

    [services.echo]
    url = "http://127.0.0.1:8100"
    module = "nachi.agents.echo"

Secrets live outside the repo, one API key per service, in ``secrets/<name>.toml``::

    [keys]
    gateway = "..."
    echo = "..."

``NACHI_KEY_<SERVICE>`` environment variables override the file.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

TOPOLOGY_ENV = "NACHI_TOPOLOGY"
SECRETS_DIR_ENV = "NACHI_SECRETS_DIR"
DEFAULT_SECRETS_DIR = Path("secrets")
MIN_KEY_LENGTH = 32

_SERVICE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class ConfigError(ValueError):
    """A topology or secrets file is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class Service:
    """One Nachi service: where callers reach it and where it listens."""

    name: str
    url: str
    module: str | None = None
    bind: str | None = None

    @property
    def host(self) -> str:
        """Address to bind: ``bind`` if given, else the URL's host."""
        if self.bind:
            return self.bind
        return urlsplit(self.url).hostname or "127.0.0.1"

    @property
    def port(self) -> int:
        parts = urlsplit(self.url)
        if parts.port is not None:
            return parts.port
        return 443 if parts.scheme == "https" else 80


@dataclass(frozen=True)
class Topology:
    """Every service in one deployment setup."""

    name: str
    services: dict[str, Service] = field(default_factory=dict)

    def service(self, name: str) -> Service:
        try:
            return self.services[name]
        except KeyError:
            known = ", ".join(sorted(self.services)) or "none"
            raise ConfigError(
                f"topology {self.name!r} has no service {name!r} (known: {known})"
            ) from None

    def url(self, name: str) -> str:
        return self.service(name).url

    def __contains__(self, name: object) -> bool:
        return name in self.services


def _parse_service(name: str, raw: object, source: str) -> Service:
    if not _SERVICE_NAME.match(name):
        raise ConfigError(f"{source}: service name {name!r} must be lowercase snake_case")
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: [services.{name}] must be a table")
    url = raw.get("url")
    if not isinstance(url, str) or not url:
        raise ConfigError(f"{source}: [services.{name}] needs a url")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError(f"{source}: [services.{name}] url {url!r} must be http(s)://host[:port]")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ConfigError(f"{source}: [services.{name}] url {url!r} must be a base URL")
    unknown = set(raw) - {"url", "module", "bind"}
    if unknown:
        raise ConfigError(f"{source}: [services.{name}] has unknown keys {sorted(unknown)}")
    module = raw.get("module")
    bind = raw.get("bind")
    if module is not None and not isinstance(module, str):
        raise ConfigError(f"{source}: [services.{name}] module must be a string")
    if bind is not None and not isinstance(bind, str):
        raise ConfigError(f"{source}: [services.{name}] bind must be a string")
    return Service(name=name, url=url.rstrip("/"), module=module, bind=bind)


def parse_topology(data: dict[str, object], source: str = "<topology>") -> Topology:
    """Build a Topology from already-parsed TOML data."""
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{source}: missing top-level name")
    raw_services = data.get("services")
    if not isinstance(raw_services, dict) or not raw_services:
        raise ConfigError(f"{source}: needs at least one [services.<name>] table")
    services = {
        svc_name: _parse_service(svc_name, raw, source) for svc_name, raw in raw_services.items()
    }
    seen: dict[str, str] = {}
    for svc in services.values():
        if svc.url in seen:
            raise ConfigError(f"{source}: {svc.name} and {seen[svc.url]} share url {svc.url}")
        seen[svc.url] = svc.name
    return Topology(name=name, services=services)


def load_topology(path: str | os.PathLike[str] | None = None) -> Topology:
    """Load a topology file; defaults to ``$NACHI_TOPOLOGY``."""
    if path is None:
        path = os.environ.get(TOPOLOGY_ENV)
        if not path:
            raise ConfigError(f"no topology given: pass a path or set {TOPOLOGY_ENV}")
    file = Path(path)
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"topology file not found: {file}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file}: invalid TOML: {exc}") from None
    return parse_topology(data, source=str(file))


def secrets_path(topology: Topology, secrets_dir: str | os.PathLike[str] | None = None) -> Path:
    base = Path(secrets_dir or os.environ.get(SECRETS_DIR_ENV) or DEFAULT_SECRETS_DIR)
    return base / f"{topology.name}.toml"


def load_keys(
    topology: Topology, secrets_dir: str | os.PathLike[str] | None = None
) -> dict[str, str]:
    """Return one API key per service in the topology.

    Keys come from ``secrets/<topology>.toml``; ``NACHI_KEY_<SERVICE>`` overrides.
    Every key must be at least 32 characters, and no two services may share a key:
    nexus-a2a treats a credential as proof of identity only when it is unique.
    """
    file = secrets_path(topology, secrets_dir)
    keys: dict[str, str] = {}
    if file.exists():
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{file}: invalid TOML: {exc}") from None
        raw = data.get("keys", {})
        if not isinstance(raw, dict):
            raise ConfigError(f"{file}: [keys] must be a table")
        keys.update({str(k): str(v) for k, v in raw.items()})
    for name in topology.services:
        env_value = os.environ.get(f"NACHI_KEY_{name.upper()}")
        if env_value:
            keys[name] = env_value

    missing = sorted(set(topology.services) - set(keys))
    if missing:
        raise ConfigError(
            f"no API key for {', '.join(missing)}; run scripts/gen_keys.py or set "
            f"NACHI_KEY_<SERVICE> (looked in {file})"
        )
    short = sorted(name for name in topology.services if len(keys[name]) < MIN_KEY_LENGTH)
    if short:
        raise ConfigError(f"keys shorter than {MIN_KEY_LENGTH} characters: {', '.join(short)}")
    by_value: dict[str, str] = {}
    for name in topology.services:
        other = by_value.setdefault(keys[name], name)
        if other != name:
            raise ConfigError(f"services {other} and {name} share an API key")
    return {name: keys[name] for name in topology.services}
