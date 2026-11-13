"""Explainer: a short, beginner-friendly explanation of one concept.

Called by the Tutor when a learner is stuck (with ``focus`` naming the misconception),
and by the gateway. One fast LLM call; output is a validated ``Explanation``.
"""

from __future__ import annotations

from typing import Any

from nexus_a2a import Task, agent

from nachi.core.llm import LLM, Tier
from nachi.core.messages import request_of
from nachi.core.prompts import AUDIENCE, concept_block
from nachi.core.schemas import ExplainRequest, Explanation
from nachi.core.serve import AgentContext

SYSTEM = (
    "You are Nachi's explainer. You explain one Python concept to a beginner in under "
    "150 words, with one tiny code example when it helps, then list up to five key "
    f"points. {AUDIENCE}"
)


@agent(
    name="Explainer",
    description="Explains one intro Python concept in plain words, optionally focused on a "
    "misconception.",
    version="0.1.0",
    multi_turn=False,
    url="http://127.0.0.1:8103",
    skills=[
        {
            "id": "explain",
            "name": "Explain",
            "description": "Short explanation of a concept. Input: ExplainRequest JSON.",
            "tags": ["teaching"],
        }
    ],
)
class Explainer:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    async def run(self, task: Task) -> dict[str, Any]:
        request = request_of(task, ExplainRequest)
        prompt = concept_block(request.concept)
        if request.focus:
            prompt += (
                f"\n\nThe learner is stuck on this: {request.focus}\n"
                "Address that misunderstanding directly."
            )
        explanation = await self.llm.structured(
            system=SYSTEM, prompt=prompt, schema=Explanation, tier=Tier.FAST, max_tokens=2000
        )
        return explanation.model_dump(mode="json")


def build(ctx: AgentContext) -> Explainer:
    return Explainer(ctx.llm)
