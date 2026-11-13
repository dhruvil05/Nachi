"""The hand-graded set loads, and the objective items agree with the LLM-free grader."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nachi.agents.grader import grade_objective

ROOT = Path(__file__).resolve().parents[2]


def _load_items():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "grader_eval", ROOT / "evals" / "run_grader_eval.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # pydantic resolves the script's annotations from here
    spec.loader.exec_module(module)
    return module.load_items()


def test_dataset_loads_with_sane_ranges() -> None:
    items = _load_items()
    assert len(items) >= 10
    assert len({i.id for i in items}) == len(items)
    for item in items:
        lo, hi = item.expect
        assert 0.0 <= lo <= hi <= 1.0, item.id


def test_objective_items_match_the_deterministic_grader() -> None:
    checked = 0
    for item in _load_items():
        grade = grade_objective(item.question, item.answer)
        if grade is None:
            continue  # needs the model; covered by the nightly eval
        lo, hi = item.expect
        assert lo <= grade.score <= hi, (item.id, grade.score)
        checked += 1
    assert checked >= 4
