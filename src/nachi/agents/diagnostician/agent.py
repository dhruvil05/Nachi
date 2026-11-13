"""Diagnostician: a short placement check before tutoring starts (multi-turn).

It binary-searches the curriculum's prerequisite order for the learner's *frontier*:
the first concept they do not know yet. Each turn asks one multiple-choice probe with
``NeedsInput``; a correct answer moves the search later, a wrong one earlier. After
``max_probes`` answers (or when the search closes) it returns a ``Placement``:

* probed and right -> known; probed and wrong -> unknown
* not probed, before the frontier -> known (inferred)
* not probed, inside the undecided range -> shaky
* not probed, after it -> unknown

Probes are multiple choice, so correctness is checked exactly without the LLM. All
state lives in the task history, so a restart between answers loses nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from nexus_a2a import NeedsInput, Task, agent

from nachi.agents.grader import grade_objective
from nachi.agents.quizmaker import check_question
from nachi.core.llm import LLM, Tier
from nachi.core.messages import agent_message, last_agent_payload, latest_user_text, request_of
from nachi.core.prompts import AUDIENCE, concept_block
from nachi.core.render import render_question
from nachi.core.schemas import (
    ConceptBrief,
    ConceptPlacement,
    DiagnoseRequest,
    DiagnosticResult,
    DiagnosticTurn,
    MasteryLevel,
    Placement,
    ProbeRecord,
    Question,
    QuestionType,
)
from nachi.core.serve import AgentContext

SYSTEM = (
    "You are Nachi's diagnostician. Write one multiple-choice question that shows "
    "whether a learner already understands the concept: one clear right option and "
    f"three plausible wrong ones. {AUDIENCE}"
)


def _search(concepts: Sequence[ConceptBrief], probes: Sequence[ProbeRecord]) -> tuple[int, int]:
    """Replay the probes; return the frontier's bounds [lo, hi)."""
    index = {c.concept_id: i for i, c in enumerate(concepts)}
    lo, hi = 0, len(concepts)
    for probe in probes:
        i = index[probe.question.concept_id]
        if probe.correct:
            lo = max(lo, i + 1)
        else:
            hi = min(hi, i)
    return lo, max(lo, hi)


def placement_from(concepts: Sequence[ConceptBrief], probes: Sequence[ProbeRecord]) -> Placement:
    lo, hi = _search(concepts, probes)
    probed = {p.question.concept_id: p.correct for p in probes}
    levels: list[ConceptPlacement] = []
    for i, concept in enumerate(concepts):
        if concept.concept_id in probed:
            level = MasteryLevel.KNOWN if probed[concept.concept_id] else MasteryLevel.UNKNOWN
        elif i < lo:
            level = MasteryLevel.KNOWN
        elif i < hi:
            level = MasteryLevel.SHAKY
        else:
            level = MasteryLevel.UNKNOWN
        levels.append(ConceptPlacement(concept_id=concept.concept_id, level=level))
    return Placement(concepts=levels)


@agent(
    name="Diagnostician",
    description="Places a learner on the curriculum with a few adaptive multiple-choice probes.",
    version="0.1.0",
    url="http://127.0.0.1:8101",
    multi_turn=True,
    skills=[
        {
            "id": "diagnose",
            "name": "Diagnose",
            "description": "Multi-turn placement check. Input: DiagnoseRequest JSON; answer each "
            "probe on the same task id.",
            "tags": ["assessment", "multi-turn"],
        }
    ],
)
class Diagnostician:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    async def run(self, task: Task) -> NeedsInput | dict[str, Any]:
        request = request_of(task, DiagnoseRequest)
        last = last_agent_payload(task, DiagnosticTurn)
        probes: list[ProbeRecord] = []
        if last is not None:
            answer = latest_user_text(task)
            grade = grade_objective(last.question, answer)
            probes = [*last.probes, ProbeRecord(
                question=last.question, answer=answer, correct=bool(grade and grade.passed)
            )]  # fmt: skip

        lo, hi = _search(request.concepts, probes)
        if len(probes) >= request.max_probes or lo >= hi:
            result = DiagnosticResult(
                placement=placement_from(request.concepts, probes), probes=probes
            )
            return result.model_dump(mode="json")

        target = request.concepts[(lo + hi) // 2]
        question = await self._probe(target, len(probes) + 1)
        turn = DiagnosticTurn(number=len(probes) + 1, question=question, probes=probes)
        text = f"Placement question {turn.number} of up to {request.max_probes}:\n"
        return NeedsInput(agent_message(turn, text=text + render_question(question)))

    async def _probe(self, concept: ConceptBrief, number: int) -> Question:
        prompt = (
            f"{concept_block(concept)}\n\ntype: mcq\nprobe number: {number}\n"
            f"Set concept_id to {concept.concept_id!r}, type to 'mcq', 4 options, and "
            "`answer` copied exactly from the options."
        )
        question = await self.llm.structured(
            system=SYSTEM, prompt=prompt, schema=Question, tier=Tier.FAST, max_tokens=2000
        )
        check_question(question, concept.concept_id, QuestionType.MCQ)
        return question


def build(ctx: AgentContext) -> Diagnostician:
    return Diagnostician(ctx.llm)
