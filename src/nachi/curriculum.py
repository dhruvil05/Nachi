"""Load and validate a curriculum: concepts, their prerequisites and grading rubrics."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nachi.core.schemas import QuestionType

CURRICULUM_ROOT = Path(__file__).resolve().parents[2] / "curriculum"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Concept(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    summary: str
    prerequisites: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(min_length=1)


class Curriculum(_Strict):
    curriculum: str
    title: str
    language: str = "en"
    concepts: list[Concept] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_graph(self) -> Curriculum:
        ids = [c.id for c in self.concepts]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate concept ids: {dupes}")
        known = set(ids)
        for concept in self.concepts:
            missing = sorted(set(concept.prerequisites) - known)
            if missing:
                raise ValueError(f"{concept.id} has unknown prerequisites {missing}")
            if concept.id in concept.prerequisites:
                raise ValueError(f"{concept.id} lists itself as a prerequisite")
        self._topological_order()  # raises on a cycle
        return self

    def _topological_order(self) -> list[str]:
        remaining = {c.id: set(c.prerequisites) for c in self.concepts}
        order: list[str] = []
        while remaining:
            ready = sorted(cid for cid, prereqs in remaining.items() if not prereqs)
            if not ready:
                raise ValueError(f"prerequisite cycle among {sorted(remaining)}")
            for cid in ready:
                order.append(cid)
                del remaining[cid]
            for prereqs in remaining.values():
                prereqs.difference_update(ready)
        return order

    @cached_property
    def order(self) -> list[str]:
        """Concept ids so that every concept comes after its prerequisites."""
        return self._topological_order()

    def concept(self, concept_id: str) -> Concept:
        for concept in self.concepts:
            if concept.id == concept_id:
                return concept
        raise KeyError(concept_id)


class Criterion(_Strict):
    id: str
    points: int = Field(gt=0)
    guidance: str


class Rubric(_Strict):
    description: str
    criteria: list[Criterion] = Field(min_length=1)

    @property
    def total_points(self) -> int:
        return sum(c.points for c in self.criteria)


class Rubrics(_Strict):
    rubrics: dict[QuestionType, Rubric]

    @model_validator(mode="after")
    def _every_type_covered(self) -> Rubrics:
        missing = sorted(set(QuestionType) - set(self.rubrics))
        if missing:
            raise ValueError(f"no rubric for question types {missing}")
        return self


def _load_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_curriculum(name: str = "python", root: Path = CURRICULUM_ROOT) -> Curriculum:
    return Curriculum.model_validate(_load_yaml(root / name / "concepts.yaml"))


def load_rubrics(name: str = "python", root: Path = CURRICULUM_ROOT) -> Rubrics:
    return Rubrics.model_validate(_load_yaml(root / name / "rubrics.yaml"))
