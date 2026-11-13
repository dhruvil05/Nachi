"""Message contracts shared by Nachi agents.

Agents exchange these as JSON artifacts. Keeping them in one module means a format
change is one commit across every agent, wherever each one runs.
"""

from __future__ import annotations

from datetime import datetime
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

    @property
    def passed(self) -> bool:
        return self.score >= PASS_SCORE


PASS_SCORE = 0.8


# ── Shared pieces ─────────────────────────────────────────────────────────────


class ConceptBrief(_Strict):
    """What an agent needs to know about one concept."""

    concept_id: str
    title: str
    summary: str
    objectives: list[str] = Field(default_factory=list)


class PublicQuestion(_Strict):
    """A question as the learner sees it: no answer, no justification."""

    concept_id: str
    type: QuestionType
    prompt: str
    options: list[str] = Field(default_factory=list)


def public(question: Question) -> PublicQuestion:
    return PublicQuestion(
        concept_id=question.concept_id,
        type=question.type,
        prompt=question.prompt,
        options=list(question.options),
    )


# ── Explainer (skill: explain) ────────────────────────────────────────────────


class ExplainRequest(_Strict):
    concept: ConceptBrief
    focus: str | None = None  # a misconception or a missed question to address


class Explanation(_Strict):
    text: str
    key_points: list[str] = Field(default_factory=list, max_length=5)


# ── QuizMaker (skill: quiz) ───────────────────────────────────────────────────


class QuizRequest(_Strict):
    concept: ConceptBrief
    type: QuestionType = QuestionType.MCQ
    count: int = Field(default=3, ge=1, le=5)
    difficulty: int = Field(default=1, ge=1, le=3)


class QuestionSet(_Strict):
    questions: list[Question] = Field(min_length=1)


# ── Grader (skill: grade) ─────────────────────────────────────────────────────


class GradeRequest(_Strict):
    question: Question
    answer: str


# ── Review Scheduler (skill: schedule_review) ─────────────────────────────────


class ReviewRequest(_Strict):
    """Current SM-2 state of a card plus how well the learner just did."""

    score: float = Field(ge=0.0, le=1.0)
    interval_days: int = Field(default=0, ge=0)
    repetitions: int = Field(default=0, ge=0)
    efactor: float = Field(default=2.5, ge=1.3)
    reviewed_at: datetime


class ReviewResult(_Strict):
    quality: int = Field(ge=0, le=5)
    interval_days: int = Field(ge=0)
    repetitions: int = Field(ge=0)
    efactor: float = Field(ge=1.3)
    next_due: datetime


# ── Diagnostician (skill: diagnose, multi-turn) ───────────────────────────────


class DiagnoseRequest(_Strict):
    concepts: list[ConceptBrief] = Field(min_length=1)  # in prerequisite order
    max_probes: int = Field(default=4, ge=1, le=10)


class ProbeRecord(_Strict):
    question: Question
    answer: str
    correct: bool


class DiagnosticTurn(_Strict):
    """Payload of each Diagnostician pause: the next probe, plus what came before."""

    number: int
    question: Question
    probes: list[ProbeRecord] = Field(default_factory=list)


class DiagnosticResult(_Strict):
    placement: Placement
    probes: list[ProbeRecord]


# ── Socratic Tutor (skill: tutor, multi-turn) ─────────────────────────────────


class TutorRequest(_Strict):
    concept: ConceptBrief
    mastery: float = Field(default=0.0, ge=0.0, le=1.0)


class TutorAttempt(_Strict):
    question: Question
    answer: str
    grade: Grade


class TutorTurnKind(StrEnum):
    QUESTION = "question"  # a new question
    HINT = "hint"  # same question again, with a hint
    RETEACH = "reteach"  # an explanation from the Explainer, then a new question


class TutorTurn(_Strict):
    """Payload of each Tutor pause. The Tutor rebuilds its state from the latest one."""

    kind: TutorTurnKind
    question: Question
    question_number: int
    hints_used: int = 0
    streak: int = 0
    attempts: list[TutorAttempt] = Field(default_factory=list)
    explanation: Explanation | None = None


class TutorResult(_Strict):
    concept_id: str
    mastered: bool
    attempts: list[TutorAttempt]

    @property
    def mastery_estimate(self) -> float:
        """Mean score of the last three answers (0 when there are none)."""
        recent = [a.grade.score for a in self.attempts[-3:]]
        return sum(recent) / len(recent) if recent else 0.0
