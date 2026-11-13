"""Socratic Tutor: teaches one concept by asking, not telling (multi-turn, streaming).

Each turn the learner's answer goes to the **Grader over A2A** (this agent calls it
itself, as a verified caller). Then:

* right -> streak + 1; two in a row masters the concept, else a new question
* wrong, hints left -> a hint for the same question (the answer is not revealed)
* wrong, no hints left -> the answer is shown, the **Explainer is called over A2A**
  for a focused re-teach, and a new question follows

After ``MAX_QUESTIONS`` questions the session ends unmastered. Every pause is a
``NeedsInput`` whose JSON part (``TutorTurn``) carries the whole session state, so the
agent keeps nothing in memory and a restart mid-session loses nothing. Feedback text is
yielded before each pause, so ``message/stream`` and ``GET /stream`` show it live.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol, TypeVar

from nexus_a2a import NeedsInput, Task, agent
from pydantic import BaseModel

from nachi.agents.quizmaker import check_question
from nachi.core.llm import LLM, LLMError, Tier
from nachi.core.messages import agent_message, last_agent_payload, latest_user_text, request_of
from nachi.core.prompts import AUDIENCE, concept_block, question_block
from nachi.core.render import render_question
from nachi.core.schemas import (
    ExplainRequest,
    Explanation,
    Grade,
    GradeRequest,
    Question,
    QuestionType,
    TutorAttempt,
    TutorRequest,
    TutorResult,
    TutorTurn,
    TutorTurnKind,
)
from nachi.core.serve import AgentContext

STREAK_TO_MASTER = 2
MAX_HINTS = 2
MAX_QUESTIONS = 6

R = TypeVar("R", bound=BaseModel)


class PeerCaller(Protocol):
    async def call(self, skill: str, request: BaseModel, response: type[R]) -> R: ...


QUESTION_SYSTEM = (
    "You are Nachi, a Socratic Python tutor. Write ONE question that makes the learner "
    "think about the concept rather than recall a definition. Build on what they got "
    "right or wrong before, and do not repeat an earlier question. Include a one-sentence "
    f"justification of the answer. {AUDIENCE}"
)
HINT_SYSTEM = (
    "You are Nachi, a Socratic Python tutor. The learner answered wrongly. Give ONE short "
    "hint (one or two sentences) that nudges them toward the answer by asking them to "
    "look at something specific. Never state the answer or eliminate options outright. "
    f"{AUDIENCE}"
)


def question_type_for(number: int, mastery: float) -> QuestionType:
    """Start with multiple choice for new learners, then ask them to produce answers."""
    cycle = [QuestionType.MCQ, QuestionType.PREDICT_OUTPUT, QuestionType.SHORT_ANSWER]
    start = 0 if mastery < 0.4 else 1
    return cycle[(start + number - 1) % len(cycle)]


@agent(
    name="SocraticTutor",
    description="Teaches one intro Python concept through guiding questions, hints and "
    "re-teaching, until the learner answers correctly twice in a row.",
    version="0.1.0",
    url="http://127.0.0.1:8102",
    streaming=True,
    multi_turn=True,
    skills=[
        {
            "id": "tutor",
            "name": "Tutor",
            "description": "Multi-turn Socratic session on one concept. Input: TutorRequest "
            "JSON; answer each question on the same task id.",
            "tags": ["teaching", "multi-turn"],
        }
    ],
)
class SocraticTutor:
    def __init__(self, llm: LLM, peers: PeerCaller) -> None:
        self.llm = llm
        self.peers = peers

    async def run(self, task: Task) -> AsyncIterator[Any]:
        request = request_of(task, TutorRequest)
        turn = last_agent_payload(task, TutorTurn)
        if turn is None:
            question = await self._question(request, 1, [])
            first = TutorTurn(kind=TutorTurnKind.QUESTION, question=question, question_number=1)
            intro = f"Let's work on {request.concept.title}.\n\n"
            yield NeedsInput(agent_message(first, text=intro + render_question(question)))
            return

        answer = latest_user_text(task)
        grade = await self.peers.call(
            "grade", GradeRequest(question=turn.question, answer=answer), Grade
        )
        attempts = [
            *turn.attempts,
            TutorAttempt(question=turn.question, answer=answer, grade=grade),
        ]

        if grade.passed:
            streak = turn.streak + 1
            if streak >= STREAK_TO_MASTER or turn.question_number >= MAX_QUESTIONS:
                yield self._result(request, attempts, mastered=streak >= STREAK_TO_MASTER)
                return
            feedback = f"{grade.feedback}\n\n"
            yield feedback
            question = await self._question(request, turn.question_number + 1, attempts)
            nxt = TutorTurn(
                kind=TutorTurnKind.QUESTION,
                question=question,
                question_number=turn.question_number + 1,
                streak=streak,
                attempts=attempts,
            )
            text = feedback + "Next question:\n" + render_question(question)
            yield NeedsInput(agent_message(nxt, text=text))
            return

        if turn.hints_used < MAX_HINTS:
            hint = await self._hint(turn.question, answer, grade, turn.hints_used + 1)
            text = f"Not quite. {hint}\n\n"
            yield text
            again = turn.model_copy(
                update={
                    "kind": TutorTurnKind.HINT,
                    "hints_used": turn.hints_used + 1,
                    "streak": 0,
                    "attempts": attempts,
                    "explanation": None,
                }
            )
            yield NeedsInput(
                agent_message(again, text=text + "Try again:\n" + render_question(turn.question))
            )
            return

        if turn.question_number >= MAX_QUESTIONS:
            yield self._result(request, attempts, mastered=False)
            return

        focus = grade.misconception or f"answered {answer!r} to: {turn.question.prompt}"
        explanation = await self.peers.call(
            "explain", ExplainRequest(concept=request.concept, focus=focus), Explanation
        )
        reveal = f"The answer was: {turn.question.answer}. {turn.question.justification}\n\n"
        yield reveal + explanation.text + "\n\n"
        question = await self._question(request, turn.question_number + 1, attempts)
        reteach = TutorTurn(
            kind=TutorTurnKind.RETEACH,
            question=question,
            question_number=turn.question_number + 1,
            attempts=attempts,
            explanation=explanation,
        )
        text = reveal + explanation.text + "\n\nNew question:\n" + render_question(question)
        yield NeedsInput(agent_message(reteach, text=text))

    @staticmethod
    def _result(
        request: TutorRequest, attempts: Sequence[TutorAttempt], *, mastered: bool
    ) -> dict[str, Any]:
        result = TutorResult(
            concept_id=request.concept.concept_id, mastered=mastered, attempts=list(attempts)
        )
        return result.model_dump(mode="json")

    async def _question(
        self, request: TutorRequest, number: int, attempts: Sequence[TutorAttempt]
    ) -> Question:
        qtype = question_type_for(number, request.mastery)
        history = (
            "\n".join(
                f"- asked: {a.question.prompt!r}; answered: {a.answer!r}; score {a.grade.score:.1f}"
                for a in attempts[-4:]
            )
            or "- (first question)"
        )
        prompt = (
            f"{concept_block(request.concept)}\n\n"
            f"type: {qtype.value}\nquestion number: {number}\n"
            f"learner mastery so far: {request.mastery:.2f} (0 to 1)\n"
            f"earlier in this session:\n{history}\n\n"
            f"Set concept_id to {request.concept.concept_id!r} and type to {qtype.value!r}."
        )
        last_error: LLMError | None = None
        for _ in range(2):  # one retry if the model breaks the question contract
            question = await self.llm.structured(
                system=QUESTION_SYSTEM, prompt=prompt, schema=Question, tier=Tier.DEEP
            )
            try:
                check_question(question, request.concept.concept_id, qtype)
                return question
            except LLMError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    async def _hint(self, question: Question, answer: str, grade: Grade, hint_number: int) -> str:
        prompt = (
            f"{question_block(question)}\n"
            f"learner answer: {answer}\n"
            f"misconception: {grade.misconception or 'unknown'}\n"
            f"hint number: {hint_number} of {MAX_HINTS} (make the second hint more specific)"
        )
        return await self.llm.text(
            system=HINT_SYSTEM, prompt=prompt, tier=Tier.DEEP, max_tokens=600
        )


def build(ctx: AgentContext) -> SocraticTutor:
    return SocraticTutor(ctx.llm, ctx.peers)
