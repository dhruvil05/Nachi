"""Grader: a score from 0 to 1, one line of feedback, and an optional misconception.

Objective answers are graded without the LLM: multiple choice (by option text or
letter), true/false, and exact matches for fill-in and predict-output. Everything else
goes to the LLM with the question type's rubric from curriculum/<name>/rubrics.yaml.
"""

from __future__ import annotations

import re
from typing import Any

from nexus_a2a import Task, agent

from nachi.core.llm import LLM, Tier
from nachi.core.messages import request_of
from nachi.core.prompts import AUDIENCE, question_block
from nachi.core.schemas import Grade, GradeRequest, Question, QuestionType
from nachi.core.serve import AgentContext
from nachi.curriculum import Rubrics, load_rubrics

SYSTEM = (
    "You are Nachi's grader. Grade the learner's answer against the rubric: add the "
    "points of the criteria it meets and divide by the total to get a score from 0 to 1. "
    "Feedback is one encouraging sentence that says what was right or what to fix. If "
    "the answer shows a specific misunderstanding, name it in a few words in "
    f"`misconception`; otherwise leave it null. {AUDIENCE}"
)
_TRUE = {"true", "t", "yes", "y"}
_FALSE = {"false", "f", "no", "n"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip("\"'`")).lower()


def _correct(question: Question) -> Grade:
    return Grade(score=1.0, feedback=f"Correct. {question.justification}")


def _wrong(question: Question, answer: str) -> Grade:
    return Grade(
        score=0.0,
        feedback=f"Not quite: the answer is {question.answer!r}. {question.justification}",
        misconception=None,
    )


def grade_objective(question: Question, answer: str) -> Grade | None:
    """Grade without the LLM when the answer can be checked exactly; else None."""
    given = _norm(answer)
    if question.type is QuestionType.MCQ:
        letters = {chr(ord("a") + i): opt for i, opt in enumerate(question.options)}
        chosen = letters.get(given.rstrip(").:"), answer)
        return (
            _correct(question)
            if _norm(chosen) == _norm(question.answer)
            else _wrong(question, answer)
        )
    if question.type is QuestionType.TRUE_FALSE:
        expected = _norm(question.answer) in _TRUE
        if given in _TRUE | _FALSE:
            return _correct(question) if (given in _TRUE) == expected else _wrong(question, answer)
        return _wrong(question, answer)
    if question.type in (QuestionType.FILL_IN, QuestionType.PREDICT_OUTPUT):
        if given == _norm(question.answer):
            return _correct(question)
    return None


@agent(
    name="Grader",
    description="Grades a learner's answer to one question with a rubric.",
    version="0.1.0",
    multi_turn=False,
    url="http://127.0.0.1:8105",
    skills=[
        {
            "id": "grade",
            "name": "Grade",
            "description": "Score, feedback and misconception. Input: GradeRequest JSON.",
            "tags": ["assessment"],
        }
    ],
)
class Grader:
    def __init__(self, llm: LLM, rubrics: Rubrics | None = None) -> None:
        self.llm = llm
        self.rubrics = rubrics or load_rubrics("python")

    async def run(self, task: Task) -> dict[str, Any]:
        request = request_of(task, GradeRequest)
        grade = grade_objective(request.question, request.answer)
        if grade is None:
            grade = await self._grade_with_llm(request)
        return grade.model_dump(mode="json")

    async def _grade_with_llm(self, request: GradeRequest) -> Grade:
        rubric = self.rubrics.rubrics[request.question.type]
        criteria = "\n".join(f"- {c.id} ({c.points} pt): {c.guidance}" for c in rubric.criteria)
        prompt = (
            f"{question_block(request.question)}\n"
            f"learner answer: {request.answer}\n\n"
            f"rubric ({rubric.total_points} points total):\n{criteria}"
        )
        return await self.llm.structured(
            system=SYSTEM, prompt=prompt, schema=Grade, tier=Tier.FAST, max_tokens=1500
        )


def build(ctx: AgentContext) -> Grader:
    return Grader(ctx.llm)
