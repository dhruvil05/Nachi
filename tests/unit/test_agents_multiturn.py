"""Diagnostician and Socratic Tutor conversations, driven in-process (no network).

``converse`` mimics the server: the agent's NeedsInput prompt is appended to the task
history, then the learner's reply, and the agent runs again on the full history.
"""

from __future__ import annotations

from typing import Any, TypeVar

from nexus_a2a import Message, NeedsInput, Task
from pydantic import BaseModel

from nachi.agents.diagnostician import Diagnostician, placement_from
from nachi.agents.tutor import SocraticTutor
from nachi.agents.tutor.agent import MAX_HINTS
from nachi.core.llm.fake import FakeLLM
from nachi.core.messages import json_of, user_message
from nachi.core.schemas import (
    ConceptBrief,
    DiagnoseRequest,
    DiagnosticResult,
    ExplainRequest,
    Explanation,
    Grade,
    GradeRequest,
    MasteryLevel,
    Question,
    QuestionType,
    TutorRequest,
    TutorResult,
    TutorTurn,
    TutorTurnKind,
)

R = TypeVar("R", bound=BaseModel)


def concept(cid: str) -> ConceptBrief:
    return ConceptBrief(concept_id=cid, title=cid.upper(), summary=f"about {cid}")


def question(cid: str, qtype: QuestionType = QuestionType.MCQ, answer: str = "x") -> dict[str, Any]:
    options = [answer, "o1", "o2", "o3"] if qtype is QuestionType.MCQ else []
    return Question(
        concept_id=cid,
        type=qtype,
        prompt=f"question about {cid}",
        options=options,
        answer=answer,
        justification="because",
    ).model_dump(mode="json")


async def outputs(agent: Any, task: Task) -> list[Any]:
    result = agent.run(task)
    if hasattr(result, "__aiter__"):
        return [item async for item in result]
    return [await result]


async def converse(agent: Any, task: Task, answer: str | None = None) -> tuple[list[Any], Any]:
    """Append the learner's answer (if any), run the agent, return (chunks, final)."""
    if answer is not None:
        task.history.append(Message.user_text(answer))
    items = await outputs(agent, task)
    final = items[-1]
    if isinstance(final, NeedsInput):
        task.history.append(final.as_message())
    return items[:-1], final


# ── Diagnostician ─────────────────────────────────────────────────────────────

CONCEPTS = [concept(c) for c in "abcde"]


def test_placement_infers_known_below_and_unknown_above_the_frontier() -> None:
    from nachi.core.schemas import ProbeRecord

    probes = [
        ProbeRecord(question=Question.model_validate(question("c")), answer="x", correct=True),
        ProbeRecord(question=Question.model_validate(question("e")), answer="?", correct=False),
    ]
    levels = {p.concept_id: p.level for p in placement_from(CONCEPTS, probes).concepts}
    assert levels == {
        "a": MasteryLevel.KNOWN,
        "b": MasteryLevel.KNOWN,
        "c": MasteryLevel.KNOWN,
        "d": MasteryLevel.SHAKY,
        "e": MasteryLevel.UNKNOWN,
    }


async def test_diagnostician_binary_searches_and_places() -> None:
    # 5 concepts: probe c (right) -> e (wrong) -> d (right) -> frontier closed at e.
    llm = FakeLLM().reply(question("c"), question("e"), question("d"))
    agent = Diagnostician(llm)
    task = Task(history=[user_message(DiagnoseRequest(concepts=CONCEPTS, max_probes=5))])

    _, first = await converse(agent, task)
    assert isinstance(first, NeedsInput)
    assert "question about c" in first.as_message().text()
    _, second = await converse(agent, task, "x")
    assert "question about e" in second.as_message().text()
    _, third = await converse(agent, task, "wrong")
    assert "question about d" in third.as_message().text()
    _, done = await converse(agent, task, "A")  # letter A = first option = "x"

    result = DiagnosticResult.model_validate(done)
    assert [p.correct for p in result.probes] == [True, False, True]
    levels = {p.concept_id: p.level for p in result.placement.concepts}
    assert levels["d"] is MasteryLevel.KNOWN and levels["e"] is MasteryLevel.UNKNOWN
    assert len(llm.calls) == 3


async def test_diagnostician_stops_at_max_probes() -> None:
    llm = FakeLLM().reply(question("c"))
    agent = Diagnostician(llm)
    task = Task(history=[user_message(DiagnoseRequest(concepts=CONCEPTS, max_probes=1))])
    await converse(agent, task)
    _, done = await converse(agent, task, "x")
    assert isinstance(done, dict) and len(done["probes"]) == 1


# ── Socratic Tutor ────────────────────────────────────────────────────────────


class FakePeers:
    """Grades "right" as correct and anything else as wrong; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, BaseModel]] = []

    async def call(self, skill: str, request: BaseModel, response: type[R]) -> R:
        self.calls.append((skill, request))
        if skill == "grade":
            assert isinstance(request, GradeRequest)
            ok = request.answer == "right"
            grade = Grade(
                score=1.0 if ok else 0.0,
                feedback="Correct." if ok else f"The answer is {request.question.answer}.",
                misconception=None if ok else "mixes up items and indexes",
            )
            return response.model_validate(grade.model_dump())
        assert isinstance(request, ExplainRequest)
        return response.model_validate(Explanation(text="Loops run once per item.").model_dump())


def tutor_with(
    *questions: dict[str, Any], hints: int = MAX_HINTS
) -> tuple[SocraticTutor, FakePeers, FakeLLM]:
    llm = FakeLLM().reply(*questions)
    for i in range(hints):
        llm.when(f"hint number: {i + 1}", f"Hint {i + 1}: count the items.")
    peers = FakePeers()
    return SocraticTutor(llm, peers), peers, llm


def turn_of(final: NeedsInput) -> TutorTurn:
    data = json_of(final.as_message())
    assert data is not None
    return TutorTurn.model_validate(data)


def tutor_task(mastery: float = 0.0) -> Task:
    return Task(history=[user_message(TutorRequest(concept=concept("loops"), mastery=mastery))])


async def test_tutor_masters_after_two_right_answers_in_a_row() -> None:
    agent, peers, _ = tutor_with(
        question("loops"), question("loops", QuestionType.PREDICT_OUTPUT, "3")
    )
    task = tutor_task()
    _, first = await converse(agent, task)
    assert turn_of(first).kind is TutorTurnKind.QUESTION
    chunks, second = await converse(agent, task, "right")
    assert chunks == ["Correct.\n\n"]  # feedback is streamed before the pause
    assert turn_of(second).streak == 1 and turn_of(second).question_number == 2
    _, done = await converse(agent, task, "right")

    result = TutorResult.model_validate(done)
    assert result.mastered and len(result.attempts) == 2
    assert [skill for skill, _ in peers.calls] == ["grade", "grade"]


async def test_tutor_hints_without_revealing_then_reteaches_via_explainer() -> None:
    agent, peers, _ = tutor_with(
        question("loops", answer="SECRET"), question("loops", QuestionType.PREDICT_OUTPUT, "3")
    )
    task = tutor_task()
    await converse(agent, task)

    for i in range(MAX_HINTS):
        chunks, hinted = await converse(agent, task, "wrong")
        turn = turn_of(hinted)
        assert turn.kind is TutorTurnKind.HINT and turn.hints_used == i + 1
        assert turn.question_number == 1
        text = hinted.as_message().text()
        assert f"Hint {i + 1}" in text
        assert "The answer is" not in text  # grader feedback that would leak is not shown

    _, retaught = await converse(agent, task, "wrong")
    turn = turn_of(retaught)
    assert turn.kind is TutorTurnKind.RETEACH and turn.question_number == 2
    assert turn.explanation is not None
    assert "SECRET" in retaught.as_message().text()  # revealed only after the hints
    explain_calls = [r for skill, r in peers.calls if skill == "explain"]
    assert len(explain_calls) == 1
    assert isinstance(explain_calls[0], ExplainRequest)
    assert explain_calls[0].focus == "mixes up items and indexes"


async def test_tutor_resumes_from_history_alone() -> None:
    """A fresh agent instance continues a session: all state is in the task."""
    agent, _, _ = tutor_with(question("loops"), question("loops", QuestionType.PREDICT_OUTPUT, "3"))
    task = tutor_task()
    await converse(agent, task)
    await converse(agent, task, "right")

    restarted, _, _ = tutor_with(question("unused"))
    _, done = await converse(restarted, task, "right")
    assert TutorResult.model_validate(done).mastered


async def test_tutor_starts_new_learners_with_multiple_choice() -> None:
    agent, _, llm = tutor_with(question("loops"))
    await converse(agent, tutor_task(mastery=0.1))
    assert "type: mcq" in llm.calls[0].prompt
    agent, _, llm = tutor_with(question("loops", QuestionType.PREDICT_OUTPUT, "3"))
    await converse(agent, tutor_task(mastery=0.7))
    assert "type: output" in llm.calls[0].prompt
