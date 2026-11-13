from __future__ import annotations

from pathlib import Path

import pytest

from nachi.core.config import ConfigError, load_keys, load_topology, parse_topology

ROOT = Path(__file__).resolve().parents[2]


def _topo(**services: dict[str, str]) -> dict[str, object]:
    return {"name": "t", "services": services}


def test_repo_topology_files_load() -> None:
    for path in (ROOT / "topologies").glob("*.toml"):
        topology = load_topology(path)
        assert topology.services, path


def test_service_host_port_and_bind() -> None:
    topology = parse_topology(
        _topo(
            echo={"url": "http://grader:8000", "bind": "0.0.0.0"},
            probe={"url": "https://probe.example"},
        )
    )
    assert topology.service("echo").host == "0.0.0.0"
    assert topology.service("echo").port == 8000
    assert topology.service("probe").host == "probe.example"
    assert topology.service("probe").port == 443


def test_trailing_slash_is_dropped() -> None:
    topology = parse_topology(_topo(echo={"url": "http://127.0.0.1:8100/"}))
    assert topology.url("echo") == "http://127.0.0.1:8100"


@pytest.mark.parametrize(
    ("services", "message"),
    [
        ({"echo": {}}, "needs a url"),
        ({"echo": {"url": "ftp://x:1"}}, "must be http"),
        ({"echo": {"url": "http://x:1/api"}}, "base URL"),
        ({"echo": {"url": "http://x:1", "port": "1"}}, "unknown keys"),
        ({"Echo": {"url": "http://x:1"}}, "snake_case"),
        ({"a": {"url": "http://x:1"}, "b": {"url": "http://x:1"}}, "share url"),
    ],
)
def test_bad_topologies_are_rejected(services: dict[str, dict[str, str]], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_topology(_topo(**services))


def test_unknown_service_lookup_names_the_known_ones() -> None:
    topology = parse_topology(_topo(echo={"url": "http://x:1"}))
    with pytest.raises(ConfigError, match="known: echo"):
        topology.service("grader")


def _write_keys(tmp_path: Path, body: str) -> None:
    (tmp_path / "t.toml").write_text(body, encoding="utf-8")


def test_keys_load_from_file_and_env_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    topology = parse_topology(_topo(echo={"url": "http://x:1"}, probe={"url": "http://x:2"}))
    _write_keys(tmp_path, f'[keys]\necho = "{"e" * 32}"\nprobe = "{"p" * 32}"\n')
    monkeypatch.setenv("NACHI_KEY_PROBE", "q" * 40)
    keys = load_keys(topology, tmp_path)
    assert keys == {"echo": "e" * 32, "probe": "q" * 40}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('[keys]\necho = "' + "e" * 32 + '"\n', "no API key for probe"),
        ('[keys]\necho = "short"\nprobe = "' + "p" * 32 + '"\n', "shorter than 32"),
        ('[keys]\necho = "' + "s" * 32 + '"\nprobe = "' + "s" * 32 + '"\n', "share an API key"),
    ],
)
def test_bad_keys_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, message: str
) -> None:
    monkeypatch.delenv("NACHI_KEY_ECHO", raising=False)
    monkeypatch.delenv("NACHI_KEY_PROBE", raising=False)
    topology = parse_topology(_topo(echo={"url": "http://x:1"}, probe={"url": "http://x:2"}))
    _write_keys(tmp_path, body)
    with pytest.raises(ConfigError, match=message):
        load_keys(topology, tmp_path)
