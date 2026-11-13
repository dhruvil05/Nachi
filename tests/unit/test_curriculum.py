from __future__ import annotations

import pytest
from pydantic import ValidationError

from nachi.core.schemas import QuestionType
from nachi.curriculum import Curriculum, load_curriculum, load_rubrics


def test_python_curriculum_loads_in_prerequisite_order() -> None:
    curriculum = load_curriculum("python")
    position = {cid: i for i, cid in enumerate(curriculum.order)}
    assert len(position) == len(curriculum.concepts)
    for concept in curriculum.concepts:
        for prereq in concept.prerequisites:
            assert position[prereq] < position[concept.id], (prereq, concept.id)
    assert curriculum.order[0] == "values_and_types"


def test_rubrics_cover_every_question_type() -> None:
    rubrics = load_rubrics("python")
    assert set(rubrics.rubrics) == set(QuestionType)
    assert all(r.total_points > 0 for r in rubrics.rubrics.values())


def _curriculum(concepts: list[dict[str, object]]) -> dict[str, object]:
    return {"curriculum": "c", "title": "C", "concepts": concepts}


def _concept(cid: str, *prereqs: str) -> dict[str, object]:
    return {"id": cid, "title": cid, "summary": "s", "prerequisites": list(prereqs),
            "objectives": ["o"]}  # fmt: skip


@pytest.mark.parametrize(
    ("concepts", "message"),
    [
        ([_concept("a"), _concept("a")], "duplicate"),
        ([_concept("a", "missing")], "unknown prerequisites"),
        ([_concept("a", "a")], "itself"),
        ([_concept("a", "b"), _concept("b", "a")], "cycle"),
    ],
)
def test_bad_graphs_are_rejected(concepts: list[dict[str, object]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Curriculum.model_validate(_curriculum(concepts))
