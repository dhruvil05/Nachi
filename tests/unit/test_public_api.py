"""Nachi uses only nexus-a2a's public API: names exported from ``nexus_a2a`` itself.

Importing a submodule (``nexus_a2a.security.auth``) or a private name (``_log``) ties
Nachi to internals. If Nachi needs something that is not exported, that is a library
finding: log it in FINDINGS.md and ask for a public hook, rather than reaching in.
"""

from __future__ import annotations

import ast
from pathlib import Path

import nexus_a2a

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ["src", "scripts", "tests"]


def _python_files() -> list[Path]:
    return [p for d in SCANNED for p in (ROOT / d).rglob("*.py") if ".venv" not in p.parts]


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        where = f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("nexus_a2a."):
                    found.append(f"{where} imports submodule {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("nexus_a2a."):
                found.append(f"{where} imports from submodule {node.module}")
            elif node.module == "nexus_a2a":
                for alias in node.names:
                    if alias.name.startswith("_"):
                        found.append(f"{where} imports private name {alias.name}")
                    elif alias.name not in nexus_a2a.__all__:
                        found.append(f"{where} imports unexported name {alias.name}")
        elif (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("_")
            and not (node.attr.startswith("__") and node.attr.endswith("__"))
        ):
            base = node.value
            if isinstance(base, ast.Name) and base.id == "nexus_a2a":
                found.append(f"{where} uses private attribute nexus_a2a.{node.attr}")
    return found


def test_only_public_nexus_a2a_api_is_used() -> None:
    problems = [v for path in _python_files() for v in _violations(path)]
    assert not problems, "\n".join(problems)
