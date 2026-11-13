"""Message contracts shared by Nachi agents.

Agents exchange these as JSON artifacts. Keeping them in one module means a format
change is one commit across every agent, wherever each one runs.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MasteryLevel(StrEnum):
    KNOWN = "known"
    SHAKY = "shaky"
    UNKNOWN = "unknown"


class ConceptPlacement(_Strict):
    concept_id: str
    level: MasteryLevel


class Placement(_Strict):
    """Diagnostician output: where the learner stands on each concept probed."""

    concepts: list[ConceptPlacement]


class QuestionType(StrEnum):
    MCQ = "mcq"
    TRUE_FALSE = "tf"
    FILL_IN = "fi"
    SHORT_ANSWER = "sa"
    PREDICT_OUTPUT = "output"


class Question(_Strict):
    concept_id: str
    type: QuestionType
    prompt: str
    options: list[str] = Field(default_factory=list)
    answer: str
    justification: str


class Grade(_Strict):
    """Grader output for one answer."""

    score: float = Field(ge=0.0, le=1.0)
    feedback: str
    misconception: str | None = None
