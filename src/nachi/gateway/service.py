"""The learning flow, independent of HTTP.

* Every agent session is a row in ``study_sessions`` tying the agent's task id to one
  student. nexus-a2a binds the task to the *gateway* (the verified caller), so this
  table is what keeps students apart: another student's session id is "not found".
* Learners only ever see the agent's text and the *public* form of a question: answers
  and justifications in the agents' JSON never leave the gateway.
* When a session completes, its result is applied once: placement seeds mastery; a
  tutoring result records attempts, updates mastery and schedules a review card.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from nexus_a2a import Message, MessageRole, StreamEventType, Task, TaskState
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nachi.core.messages import json_of, result_of, user_message
from nachi.core.peers import Peers
from nachi.core.schemas import (
    ConceptBrief,
    DiagnoseRequest,
    DiagnosticResult,
    DiagnosticTurn,
    MasteryLevel,
    PublicQuestion,
    ReviewRequest,
    ReviewResult,
    TutorRequest,
    TutorResult,
    TutorTurn,
    public,
)
from nachi.curriculum import Curriculum
from nachi.gateway.picker import is_ready, next_concept
from nachi.learner.models import Attempt, Card, Mastery, Student, StudySession

PLACEMENT_SCORES = {MasteryLevel.KNOWN: 0.9, MasteryLevel.SHAKY: 0.5, MasteryLevel.UNKNOWN: 0.1}
SKILLS = {"diagnose": ("diagnostician", "diagnose"), "tutor": ("tutor", "tutor")}
DIAGNOSTIC_PROBES = 4


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    pass


class SessionView(BaseModel):
    """What a learner sees of a session."""

    session_id: str
    kind: str
    state: str
    text: str = ""
    question: PublicQuestion | None = None
    done: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _state(task: Task) -> str:
    return str(getattr(task.state, "value", task.state))


def _is_structured(chunk: str) -> bool:
    """True for a JSON object/array chunk: a non-streaming agent's whole result.

    nexus-a2a streams a non-streaming agent's output as one chunk, so a final JSON
    result can arrive as "text". Learners get results from the settled session instead.
    """
    text = chunk.strip()
    if not text.startswith(("{", "[")):
        return False
    try:
        return isinstance(json.loads(text), dict | list)
    except ValueError:
        return False


class Learning:
    def __init__(
        self,
        peers: Peers,
        sessions: async_sessionmaker[AsyncSession],
        curriculum: Curriculum,
        *,
        diagnostic_probes: int = DIAGNOSTIC_PROBES,
    ) -> None:
        self.peers = peers
        self.sessions = sessions
        self.curriculum = curriculum
        self.diagnostic_probes = diagnostic_probes

    # ── Students and overview ────────────────────────────────────────────────

    async def create_student(self, display_name: str) -> dict[str, str]:
        async with self.sessions() as db:
            student = Student(display_name=display_name.strip()[:100] or "Learner")
            db.add(student)
            await db.commit()
            return {"student_id": student.id, "display_name": student.display_name}

    async def _student(self, db: AsyncSession, student_id: str) -> Student:
        student = await db.get(Student, student_id)
        if student is None:
            raise NotFound("unknown student")
        return student

    async def _mastery(self, db: AsyncSession, student_id: str) -> dict[str, float]:
        rows = await db.scalars(select(Mastery).where(Mastery.student_id == student_id))
        return {row.concept_id: row.score for row in rows}

    async def overview(self, student_id: str) -> dict[str, Any]:
        async with self.sessions() as db:
            student = await self._student(db, student_id)
            mastery = await self._mastery(db, student_id)
            due = await db.scalars(
                select(Card).where(Card.student_id == student_id, Card.next_due <= _now())
            )
            return {
                "student_id": student.id,
                "display_name": student.display_name,
                "diagnosed": bool(mastery),
                "next_concept": next_concept(self.curriculum, mastery),
                "due_cards": len(list(due)),
                "concepts": [
                    {
                        "concept_id": c.id,
                        "title": c.title,
                        "mastery": round(mastery.get(c.id, 0.0), 2),
                        "ready": is_ready(self.curriculum, c.id, mastery),
                    }
                    for c in (self.curriculum.concept(cid) for cid in self.curriculum.order)
                ],
            }

    def _brief(self, concept_id: str) -> ConceptBrief:
        c = self.curriculum.concept(concept_id)
        return ConceptBrief(
            concept_id=c.id, title=c.title, summary=c.summary, objectives=list(c.objectives)
        )

    # ── Starting sessions ────────────────────────────────────────────────────

    async def start_diagnosis(self, student_id: str) -> SessionView:
        request = DiagnoseRequest(
            concepts=[self._brief(cid) for cid in self.curriculum.order],
            max_probes=self.diagnostic_probes,
        )
        return await self._start(student_id, "diagnose", user_message(request))

    async def start_tutoring(self, student_id: str, concept_id: str | None = None) -> SessionView:
        async with self.sessions() as db:
            await self._student(db, student_id)
            mastery = await self._mastery(db, student_id)
        concept_id = concept_id or next_concept(self.curriculum, mastery)
        if concept_id is None:
            raise Conflict("every concept is mastered")
        try:
            brief = self._brief(concept_id)
        except KeyError:
            raise NotFound(f"unknown concept {concept_id!r}") from None
        request = TutorRequest(concept=brief, mastery=mastery.get(concept_id, 0.0))
        return await self._start(student_id, "tutor", user_message(request))

    async def _start(self, student_id: str, kind: str, message: Message) -> SessionView:
        async with self.sessions() as db:
            await self._student(db, student_id)
        _, skill = SKILLS[kind]
        task = await self.peers.send(skill, message)
        async with self.sessions() as db:
            session = StudySession(
                student_id=student_id,
                kind=kind,
                agent=SKILLS[kind][0],
                task_id=task.id,
                state=_state(task),
            )
            db.add(session)
            await db.flush()
            view = await self._settle(db, session, task)
            await db.commit()
            return view

    # ── Answering ─────────────────────────────────────────────────────────────

    async def _owned(self, db: AsyncSession, student_id: str, session_id: str) -> StudySession:
        session = await db.get(StudySession, session_id)
        if session is None or session.student_id != student_id:
            raise NotFound("unknown session")  # same answer for "not yours"
        return session

    async def _open_session(self, student_id: str, session_id: str) -> tuple[str, str]:
        async with self.sessions() as db:
            session = await self._owned(db, student_id, session_id)
            if session.state != TaskState.INPUT_REQUIRED.value:
                raise Conflict(f"session is {session.state}, not waiting for an answer")
            return session.kind, session.task_id

    async def answer(self, student_id: str, session_id: str, answer: str) -> SessionView:
        kind, task_id = await self._open_session(student_id, session_id)
        task = await self.peers.send(SKILLS[kind][1], Message.user_text(answer), task_id=task_id)
        return await self._record(student_id, session_id, task)

    async def answer_stream(
        self, student_id: str, session_id: str, answer: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Relay the agent's streamed text, then the settled session."""
        kind, task_id = await self._open_session(student_id, session_id)
        skill = SKILLS[kind][1]
        async for event in self.peers.stream(skill, Message.user_text(answer), task_id=task_id):
            if event.type == StreamEventType.ARTIFACT_CHUNK:
                content = event.data.get("content")
                if isinstance(content, str) and not _is_structured(content):
                    yield {"event": "chunk", "text": content}
            elif event.type == StreamEventType.ERROR:
                yield {"event": "error", "message": str(event.data.get("message", "stream error"))}
        task = await self.peers.get_task(skill, task_id)
        view = await self._record(student_id, session_id, task)
        yield {"event": "session", "session": view.model_dump(mode="json")}

    async def view(self, student_id: str, session_id: str) -> SessionView:
        async with self.sessions() as db:
            session = await self._owned(db, student_id, session_id)
            kind, task_id = session.kind, session.task_id
        task = await self.peers.get_task(SKILLS[kind][1], task_id)
        return await self._record(student_id, session_id, task)

    async def _record(self, student_id: str, session_id: str, task: Task) -> SessionView:
        async with self.sessions() as db:
            session = await self._owned(db, student_id, session_id)
            view = await self._settle(db, session, task)
            await db.commit()
            return view

    # ── Turning a task into a view, applying results once ────────────────────

    async def _settle(self, db: AsyncSession, session: StudySession, task: Task) -> SessionView:
        state = _state(task)
        view = SessionView(session_id=session.id, kind=session.kind, state=state)
        if state == TaskState.INPUT_REQUIRED.value:
            message = next(m for m in reversed(task.history) if m.role == MessageRole.AGENT)
            view.text = message.text()
            payload = json_of(message)
            turn_model = DiagnosticTurn if session.kind == "diagnose" else TutorTurn
            if payload is not None:
                view.question = public(turn_model.model_validate(payload).question)
        elif state == TaskState.COMPLETED.value:
            view.done = True
            first_time = session.state != TaskState.COMPLETED.value
            if session.kind == "diagnose":
                view.result = await self._apply_diagnosis(db, session, task, first_time)
            else:
                view.result = await self._apply_tutoring(db, session, task, first_time)
        else:
            view.done = state in (TaskState.FAILED.value, TaskState.CANCELLED.value)
            view.error = task.error
        session.state = state
        return view

    async def _set_mastery(
        self, db: AsyncSession, student_id: str, concept_id: str, score: float
    ) -> None:
        await db.merge(
            Mastery(student_id=student_id, concept_id=concept_id, score=max(0.0, min(1.0, score)))
        )

    async def _apply_diagnosis(
        self, db: AsyncSession, session: StudySession, task: Task, first_time: bool
    ) -> dict[str, Any]:
        result = result_of(task, DiagnosticResult)
        if first_time:
            for placed in result.placement.concepts:
                await self._set_mastery(
                    db, session.student_id, placed.concept_id, PLACEMENT_SCORES[placed.level]
                )
        return {
            "placement": {p.concept_id: p.level.value for p in result.placement.concepts},
            "probes": len(result.probes),
        }

    async def _apply_tutoring(
        self, db: AsyncSession, session: StudySession, task: Task, first_time: bool
    ) -> dict[str, Any]:
        result = result_of(task, TutorResult)
        estimate = result.mastery_estimate
        summary = {
            "concept_id": result.concept_id,
            "title": self.curriculum.concept(result.concept_id).title,
            "mastered": result.mastered,
            "questions": len({a.question.prompt for a in result.attempts}),
            "answers": len(result.attempts),
            "score": round(estimate, 2),
        }
        if not first_time:
            return summary
        student_id = session.student_id
        for attempt in result.attempts:
            db.add(
                Attempt(
                    student_id=student_id,
                    concept_id=result.concept_id,
                    question=attempt.question.model_dump_json(),
                    answer=attempt.answer,
                    score=attempt.grade.score,
                    feedback=attempt.grade.feedback,
                    misconception=attempt.grade.misconception,
                )
            )
        old = (await self._mastery(db, student_id)).get(result.concept_id, 0.0)
        new = max(old, 0.9) if result.mastered else 0.5 * old + 0.5 * estimate
        await self._set_mastery(db, student_id, result.concept_id, new)
        await self._schedule_card(db, student_id, result, estimate)
        return summary

    async def _schedule_card(
        self, db: AsyncSession, student_id: str, result: TutorResult, score: float
    ) -> None:
        card = await db.scalar(
            select(Card).where(Card.student_id == student_id, Card.concept_id == result.concept_id)
        )
        if card is None:
            last = result.attempts[-1].question
            concept = self.curriculum.concept(result.concept_id)
            card = Card(
                student_id=student_id,
                concept_id=result.concept_id,
                front=f"{concept.title}: {last.prompt}",
                back=f"{last.answer}. {last.justification}",
            )
            db.add(card)
        await self._review(db, card, score)

    async def _review(self, db: AsyncSession, card: Card, score: float) -> ReviewResult:
        review = await self.peers.call(
            "schedule_review",
            ReviewRequest(
                score=score,
                interval_days=card.interval_days or 0,
                repetitions=card.repetitions or 0,
                efactor=card.efactor or 2.5,
                reviewed_at=_now(),
            ),
            ReviewResult,
        )
        card.interval_days = review.interval_days
        card.repetitions = review.repetitions
        card.efactor = review.efactor
        card.next_due = review.next_due
        return review

    # ── Review cards ─────────────────────────────────────────────────────────

    async def due_cards(self, student_id: str) -> list[dict[str, Any]]:
        async with self.sessions() as db:
            await self._student(db, student_id)
            cards = await db.scalars(
                select(Card)
                .where(Card.student_id == student_id, Card.next_due <= _now())
                .order_by(Card.next_due)
            )
            return [
                {"card_id": c.id, "concept_id": c.concept_id, "front": c.front, "back": c.back}
                for c in cards
            ]

    async def review_card(self, student_id: str, card_id: int, score: float) -> dict[str, Any]:
        async with self.sessions() as db:
            card = await db.get(Card, card_id)
            if card is None or card.student_id != student_id:
                raise NotFound("unknown card")
            review = await self._review(db, card, score)
            await db.commit()
            return review.model_dump(mode="json")
