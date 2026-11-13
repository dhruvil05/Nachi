"""Faults and recovery: the Phase 1 gate says a restart mid-session loses nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.flow.test_learning_flow import right_answer, run_to_end
from tests.support.network import Network, nachi_network

pytestmark = pytest.mark.fault


@pytest.fixture
async def net(tmp_path: Path):  # type: ignore[no-untyped-def]
    async with nachi_network(tmp_path) as network:
        yield network


async def _answer(net: Network, me: dict[str, str], view: dict[str, str], answer: str) -> dict:  # type: ignore[type-arg]
    res = await net.http.post(
        f"/api/sessions/{view['session_id']}/answer", json={"answer": answer}, headers=me
    )
    assert res.status_code == 200, res.text
    return res.json()  # type: ignore[no-any-return]


async def test_tutor_restart_mid_session_loses_nothing(net: Network) -> None:
    me = await net.student()
    view = (
        await net.http.post("/api/tutoring", json={"concept_id": "variables"}, headers=me)
    ).json()
    view = await _answer(net, me, view, right_answer(view))
    assert view["state"] == "input_required"

    await net.restart("tutor")  # new process-equivalent: fresh agent, same port and store

    after = (await net.http.get(f"/api/sessions/{view['session_id']}", headers=me)).json()
    assert after["state"] == "input_required" and after["text"] == view["text"]
    done = await run_to_end(net, me, after, right_answer)
    assert done["result"]["mastered"] is True and done["result"]["answers"] == 2


async def test_diagnostician_restart_mid_placement_loses_nothing(net: Network) -> None:
    me = await net.student()
    view = (await net.http.post("/api/diagnosis", headers=me)).json()
    view = await _answer(net, me, view, "A")
    await net.restart("diagnostician")
    done = await run_to_end(net, me, view, right_answer)
    assert done["result"]["probes"] == 4


async def test_grader_down_fails_the_answer_cleanly_and_the_tutor_recovers(net: Network) -> None:
    me = await net.student()
    view = (
        await net.http.post("/api/tutoring", json={"concept_id": "variables"}, headers=me)
    ).json()

    await net.stop("grader")
    failed = await _answer(net, me, view, right_answer(view))
    assert failed["state"] == "failed" and failed["done"] is True
    assert "grade" in (failed["error"] or "")

    await net.start("grader")
    fresh = (
        await net.http.post("/api/tutoring", json={"concept_id": "variables"}, headers=me)
    ).json()
    done = await run_to_end(net, me, fresh, right_answer)
    assert done["result"]["mastered"] is True
