"""QuizMaker: questions of one type about one concept.

Ported from smart-study-buddy, now async with validated structured output instead of
stripping code fences. Every question is checked before it leaves the agent.
"""

from __future__ import annotations

from typing import Any

from nexus_a2a import Task, agent

from nachi.core.llm import LLM, LLMError, Tier
from nachi.core.messages import request_of
from nachi.core.prompts import AUDIENCE, concept_block
from nachi.core.schemas import Question, QuestionSet, QuestionType, QuizRequest
from nachi.core.serve import AgentContext

TYPE_RULES = {
    QuestionType.MCQ: "multiple choice with exactly 4 options; `answer` is one option, "
    "copied exactly",
    QuestionType.TRUE_FALSE: 'a statement to judge; `answer` is "true" or "false"; no options',
    QuestionType.FILL_IN: "a sentence or code line with ___ for the blank; `answer` fills it",
    QuestionType.SHORT_ANSWER: "answerable in 1-3 sentences; `answer` is a model answer",
    QuestionType.PREDICT_OUTPUT: "a short Python snippet in the prompt; `answer` is its exact "
    "printed output",
}

SYSTEM = (
    "You are Nachi's quiz writer. You write clear questions that check one learning "
    f"objective each, with a one-sentence justification of the answer. {AUDIENCE}"
)


def check_question(question: Question, concept_id: str, qtype: QuestionType) -> None:
    """Raise LLMError when a generated question breaks the contract."""
    if question.concept_id != concept_id:
        raise LLMError(f"question is for {question.concept_id!r}, expected {concept_id!r}")
    if question.type != qtype:
        raise LLMError(f"question type {question.type} != requested {qtype}")
    if qtype is QuestionType.MCQ:
        if len(question.options) != 4 or question.answer not in question.options:
            raise LLMError("an MCQ needs 4 options and an answer that is one of them")
    if qtype is QuestionType.TRUE_FALSE and question.answer.strip().lower() not in {
        "true",
        "false",
    }:
        raise LLMError("a true/false answer must be 'true' or 'false'")
    if qtype is QuestionType.FILL_IN and "___" not in question.prompt:
        raise LLMError("a fill-in question needs ___ in the prompt")


@agent(
    name="QuizMaker",
    description="Writes intro Python questions (mcq, tf, fill-in, short answer, predict output).",
    version="0.1.0",
    multi_turn=False,
    url="http://127.0.0.1:8104",
    skills=[
        {
            "id": "quiz",
            "name": "Quiz",
            "description": "Questions about one concept. Input: QuizRequest JSON.",
            "tags": ["assessment"],
        }
    ],
)
class QuizMaker:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    async def run(self, task: Task) -> dict[str, Any]:
        request = request_of(task, QuizRequest)
        prompt = (
            f"{concept_block(request.concept)}\n\n"
            f"type: {request.type.value}\ncount: {request.count}\n"
            f"difficulty: {request.difficulty} of 3\n"
            f"Format: {TYPE_RULES[request.type]}.\n"
            f"Set concept_id to {request.concept.concept_id!r} and type to "
            f"{request.type.value!r} on every question."
        )
        result = await self.llm.structured(
            system=SYSTEM, prompt=prompt, schema=QuestionSet, tier=Tier.FAST, max_tokens=4000
        )
        questions = result.questions[: request.count]
        for question in questions:
            check_question(question, request.concept.concept_id, request.type)
        return QuestionSet(questions=questions).model_dump(mode="json")


def build(ctx: AgentContext) -> QuizMaker:
    return QuizMaker(ctx.llm)
