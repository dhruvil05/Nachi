"""HTTP routes for the gateway.

Phase 1 identifies the learner with an ``X-Student-Id`` header that the web page keeps
in local storage. That is *not* authentication: Phase 2 adds real sign-in. Session
ownership is still enforced on every call, so one student id cannot reach another's
sessions or cards.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from nachi.core.peers import PeerError
from nachi.gateway.service import Conflict, Learning, NotFound, SessionView

STATIC = Path(__file__).parent / "static"


class NewStudent(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class StartTutoring(BaseModel):
    concept_id: str | None = None


class AnswerBody(BaseModel):
    answer: str = Field(max_length=4000)


class ReviewBody(BaseModel):
    score: float = Field(ge=0.0, le=1.0)


def _student(x_student_id: Annotated[str, Header(max_length=64)]) -> str:
    return x_student_id


# Module level: route annotations are strings (future annotations), so FastAPI must be
# able to resolve this name from the module's globals.
StudentId = Annotated[str, Depends(_student)]


def create_app(learning: Learning) -> FastAPI:
    app = FastAPI(title="Nachi gateway", docs_url=None, redoc_url=None)

    async def guarded(coro: Any) -> Any:
        try:
            return await coro
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except PeerError as exc:
            raise HTTPException(502, f"an agent call failed: {exc}") from None

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/students")
    async def create_student(body: NewStudent) -> dict[str, str]:
        return await learning.create_student(body.display_name)

    @app.get("/api/me")
    async def me(student_id: StudentId) -> dict[str, Any]:
        return await guarded(learning.overview(student_id))  # type: ignore[no-any-return]

    @app.post("/api/diagnosis")
    async def diagnose(student_id: StudentId) -> SessionView:
        return await guarded(learning.start_diagnosis(student_id))  # type: ignore[no-any-return]

    @app.post("/api/tutoring")
    async def tutor(student_id: StudentId, body: StartTutoring) -> SessionView:
        return await guarded(learning.start_tutoring(student_id, body.concept_id))  # type: ignore[no-any-return]

    @app.get("/api/sessions/{session_id}")
    async def session(student_id: StudentId, session_id: str) -> SessionView:
        return await guarded(learning.view(student_id, session_id))  # type: ignore[no-any-return]

    @app.post("/api/sessions/{session_id}/answer")
    async def answer(student_id: StudentId, session_id: str, body: AnswerBody) -> SessionView:
        return await guarded(learning.answer(student_id, session_id, body.answer))  # type: ignore[no-any-return]

    @app.post("/api/sessions/{session_id}/answer/stream")
    async def answer_stream(
        student_id: StudentId, session_id: str, body: AnswerBody
    ) -> StreamingResponse:
        events = learning.answer_stream(student_id, session_id, body.answer)
        try:  # surface ownership/state errors as HTTP codes before the stream starts
            first = await guarded(events.__anext__())
        except StopAsyncIteration:
            first = None

        async def sse() -> AsyncIterator[str]:
            pending = [first] if first is not None else []
            try:
                for event in pending:
                    yield f"data: {json.dumps(event)}\n\n"
                async for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
            except (PeerError, NotFound, Conflict) as exc:
                yield f"data: {json.dumps({'event': 'error', 'message': str(exc)})}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    @app.get("/api/cards/due")
    async def due(student_id: StudentId) -> list[dict[str, Any]]:
        return await guarded(learning.due_cards(student_id))  # type: ignore[no-any-return]

    @app.post("/api/cards/{card_id}/review")
    async def review(student_id: StudentId, card_id: int, body: ReviewBody) -> dict[str, Any]:
        return await guarded(learning.review_card(student_id, card_id, body.score))  # type: ignore[no-any-return]

    return app
