"""Grader agreement eval: how often the real Grader lands in a human's accepted range.

Calls Claude for the free-text items, so it costs money and needs ANTHROPIC_API_KEY.
It is meant to run nightly (or by hand), never as a merge gate.

    uv run python evals/run_grader_eval.py            # real model
    uv run python evals/run_grader_eval.py --demo     # plumbing check, no API calls
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml
from nexus_a2a import Task
from pydantic import BaseModel, Field

from nachi.agents.grader import Grader
from nachi.core.llm import make_llm
from nachi.core.messages import user_message
from nachi.core.schemas import Grade, GradeRequest, Question

DATASET = Path(__file__).parent / "grader_agreement" / "python.yaml"


class Item(BaseModel):
    id: str
    question: Question
    answer: str
    expect: tuple[float, float] = Field(description="accepted score range, inclusive")


def load_items(path: Path = DATASET) -> list[Item]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Item.model_validate(raw) for raw in data["items"]]


async def run(demo: bool) -> int:
    grader = Grader(make_llm("demo" if demo else "anthropic"))
    items = load_items()
    hits = 0
    for item in items:
        task = Task(
            history=[user_message(GradeRequest(question=item.question, answer=item.answer))]
        )
        grade = Grade.model_validate(await grader.run(task))
        lo, hi = item.expect
        ok = lo <= grade.score <= hi
        hits += ok
        print(f"{'ok  ' if ok else 'MISS'} {item.id:<22} score {grade.score:.2f}  expect {lo}-{hi}")
    print(f"\nagreement: {hits}/{len(items)} ({hits / len(items):.0%})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="use the demo LLM (no API calls)")
    return asyncio.run(run(parser.parse_args().demo))


if __name__ == "__main__":
    sys.exit(main())
