"""Review Scheduler: SM-2 spaced repetition. No LLM.

The agent is stateless: the gateway sends a card's current SM-2 state plus the latest
score and stores what comes back. (smart-study-buddy's version only knew right/wrong;
this one maps the 0-1 score to SM-2's 0-5 quality.)
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from nexus_a2a import Task, agent

from nachi.core.messages import request_of
from nachi.core.schemas import ReviewRequest, ReviewResult
from nachi.core.serve import AgentContext

MIN_EFACTOR = 1.3


def sm2(request: ReviewRequest) -> ReviewResult:
    quality = max(0, min(5, round(request.score * 5)))
    if quality < 3:
        repetitions, interval = 0, 1
    else:
        if request.repetitions == 0:
            interval = 1
        elif request.repetitions == 1:
            interval = 6
        else:
            interval = max(1, round(request.interval_days * request.efactor))
        repetitions = request.repetitions + 1
    miss = 5 - quality
    efactor = max(MIN_EFACTOR, request.efactor + (0.1 - miss * (0.08 + miss * 0.02)))
    return ReviewResult(
        quality=quality,
        interval_days=interval,
        repetitions=repetitions,
        efactor=round(efactor, 4),
        next_due=request.reviewed_at + timedelta(days=interval),
    )


@agent(
    name="ReviewScheduler",
    description="Schedules the next review of a card with SM-2 spaced repetition.",
    version="0.1.0",
    multi_turn=False,
    url="http://127.0.0.1:8106",
    skills=[
        {
            "id": "schedule_review",
            "name": "Schedule review",
            "description": "Next SM-2 state and due date. Input: ReviewRequest JSON.",
            "tags": ["spaced-repetition"],
        }
    ],
)
class ReviewScheduler:
    async def run(self, task: Task) -> dict[str, Any]:
        return sm2(request_of(task, ReviewRequest)).model_dump(mode="json")


def build(ctx: AgentContext) -> ReviewScheduler:
    return ReviewScheduler()
