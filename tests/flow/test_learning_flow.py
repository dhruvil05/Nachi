"""The Phase 1 loop over real HTTP and A2A: diagnose -> tutor -> grade -> schedule.

Every agent runs on its own local port with real auth and trust rules. The Tutor calls
the Grader and Explainer itself, as a verified caller. The demo LLM makes it
deterministic: multiple-choice answer "A" (the concept title), otherwise "demo".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from nachi.learner.models import Attempt, Card
from tests.support.network import Network, nachi_network

pytestmark = pytest.mark.flow


def right_answer(view: dict[str, Any]) -> str:
    question = view["question"]
    if question["options"]:
        return "A"
    return "true" if question["type"] == "tf" else "demo"


async def run_to_end(
    net: Network, headers: dict[str, str], view: dict[str, Any], answer: Any
) -> dict[str, Any]:
    for _ in range(20):
        if view["done"]:
            return view
        assert view["state"] == "input_required", view
        res = await net.http.post(
            f"/api/sessions/{view['session_id']}/answer",
            json={"answer": answer(view)},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        view = res.json()
    raise AssertionError("session did not finish")


@pytest.fixture
async def net(tmp_path: Path):  # type: ignore[no-untyped-def]
    async with nachi_network(tmp_path) as network:
        yield network


async def test_full_loop_diagnose_then_master_a_concept(net: Network) -> None:
    me = await net.student()

    start = await net.http.post("/api/diagnosis", headers=me)
    assert start.status_code == 200, start.text
    view = start.json()
    assert view["question"]["options"], "placement probes are multiple choice"
    assert "answer" not in view["question"], "answers never reach the learner"
    answers = iter(["A", "A", "B", "B"])  # right, right, then wrong: a frontier mid-way
    done = await run_to_end(net, me, view, lambda _view: next(answers))
    assert done["result"]["probes"] == 4
    placement = done["result"]["placement"]
    assert placement["values_and_types"] == "known"
    assert "unknown" in placement.values()

    overview = (await net.http.get("/api/me", headers=me)).json()
    assert overview["diagnosed"]
    target = overview["next_concept"]
    assert target is not None

    view = (await net.http.post("/api/tutoring", json={}, headers=me)).json()
    assert view["kind"] == "tutor" and view["question"]["concept_id"] == target
    done = await run_to_end(net, me, view, right_answer)
    assert done["result"]["mastered"] is True
    assert done["result"]["answers"] == 2

    after = (await net.http.get("/api/me", headers=me)).json()
    mastery = {c["concept_id"]: c["mastery"] for c in after["concepts"]}
    assert mastery[target] >= 0.9

    async with net.learning.sessions() as db:
        attempts = await db.scalar(select(func.count()).select_from(Attempt))
        card = await db.scalar(select(Card).where(Card.concept_id == target))
    assert attempts == 2
    assert card is not None and card.repetitions == 1 and card.interval_days == 1


async def test_wrong_answers_get_hints_then_a_reteach_from_the_explainer(net: Network) -> None:
    me = await net.student()
    view = (
        await net.http.post("/api/tutoring", json={"concept_id": "variables"}, headers=me)
    ).json()
    texts = []
    for _ in range(3):
        res = await net.http.post(
            f"/api/sessions/{view['session_id']}/answer", json={"answer": "no idea"}, headers=me
        )
        view = res.json()
        texts.append(view["text"])
    assert texts[0].startswith("Not quite.") and "Hint (demo)" in texts[0]
    assert "The answer was:" not in texts[0] + texts[1]
    assert "The answer was:" in texts[2] and "(demo) Variables and assignment" in texts[2]

    done = await run_to_end(net, me, view, right_answer)
    assert done["result"]["answers"] == 5  # 3 wrong + 2 right


async def test_streamed_answer_relays_feedback_then_the_session(net: Network) -> None:
    me = await net.student()
    view = (
        await net.http.post("/api/tutoring", json={"concept_id": "values_and_types"}, headers=me)
    ).json()
    async with net.http.stream(
        "POST",
        f"/api/sessions/{view['session_id']}/answer/stream",
        json={"answer": right_answer(view)},
        headers=me,
    ) as res:
        assert res.status_code == 200
        events = [
            json.loads(line[6:]) async for line in res.aiter_lines() if line.startswith("data: ")
        ]
    kinds = [e["event"] for e in events]
    assert kinds[-1] == "session"
    assert "chunk" in kinds, "the Tutor's feedback should arrive before the next question"
    assert events[-1]["session"]["state"] == "input_required"


async def test_streaming_a_completion_relays_no_raw_json(net: Network) -> None:
    """A non-streaming agent's final result arrives as one chunk; it must not be shown."""
    me = await net.student()
    view = (await net.http.post("/api/diagnosis", headers=me)).json()
    for _ in range(4):
        async with net.http.stream(
            "POST",
            f"/api/sessions/{view['session_id']}/answer/stream",
            json={"answer": "A"},
            headers=me,
        ) as res:
            events = [
                json.loads(line[6:])
                async for line in res.aiter_lines()
                if line.startswith("data: ")
            ]
        assert not [e for e in events if e["event"] == "chunk" and e["text"].lstrip()[:1] in "{["]
        view = events[-1]["session"]
    assert view["done"] and view["result"]["probes"] == 4


async def test_learners_cannot_reach_each_others_sessions(net: Network) -> None:
    asha, ravi = await net.student("Asha"), await net.student("Ravi")
    view = (
        await net.http.post("/api/tutoring", json={"concept_id": "variables"}, headers=asha)
    ).json()
    url = f"/api/sessions/{view['session_id']}"
    assert (await net.http.get(url, headers=ravi)).status_code == 404
    res = await net.http.post(f"{url}/answer", json={"answer": "A"}, headers=ravi)
    assert res.status_code == 404
    assert (await net.http.get(url, headers=asha)).status_code == 200


async def test_answering_a_finished_session_is_a_conflict(net: Network) -> None:
    me = await net.student()
    view = (
        await net.http.post("/api/tutoring", json={"concept_id": "variables"}, headers=me)
    ).json()
    done = await run_to_end(net, me, view, right_answer)
    res = await net.http.post(
        f"/api/sessions/{done['session_id']}/answer", json={"answer": "A"}, headers=me
    )
    assert res.status_code == 409


async def test_due_cards_can_be_reviewed(net: Network) -> None:
    me = await net.student()
    view = (
        await net.http.post("/api/tutoring", json={"concept_id": "variables"}, headers=me)
    ).json()
    await run_to_end(net, me, view, right_answer)
    async with net.learning.sessions() as db:
        card = await db.scalar(select(Card))
        assert card is not None
        card.next_due = card.next_due.replace(year=2000)  # make it due now
        await db.commit()
        card_id = card.id
    due = (await net.http.get("/api/cards/due", headers=me)).json()
    assert [c["card_id"] for c in due] == [card_id]
    review = await net.http.post(f"/api/cards/{card_id}/review", json={"score": 1.0}, headers=me)
    assert review.status_code == 200 and review.json()["interval_days"] == 6
    assert (await net.http.get("/api/cards/due", headers=me)).json() == []
