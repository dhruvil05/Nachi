"""Prompt pieces shared by agents.

Every prompt about a concept starts with the same ``concept_block``. Keeping it
identical helps prompt caching, and lets the demo LLM read the concept back.
"""

from __future__ import annotations

from nachi.core.schemas import ConceptBrief, Question


def concept_block(concept: ConceptBrief) -> str:
    objectives = "\n".join(f"- {o}" for o in concept.objectives) or "- (none listed)"
    return (
        f"concept_id: {concept.concept_id}\n"
        f"title: {concept.title}\n"
        f"summary: {concept.summary}\n"
        f"objectives:\n{objectives}"
    )


def question_block(question: Question) -> str:
    options = "\n".join(f"  - {o}" for o in question.options)
    lines = [
        f"concept_id: {question.concept_id}",
        f"type: {question.type.value}",
        f"question: {question.prompt}",
    ]
    if options:
        lines.append(f"options:\n{options}")
    lines += [f"expected answer: {question.answer}", f"why: {question.justification}"]
    return "\n".join(lines)


AUDIENCE = (
    "The learner is a self-taught beginner studying intro Python in English. "
    "Use plain words and short sentences. Code samples are Python 3."
)
