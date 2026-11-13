"""A deterministic stand-in LLM for running Nachi without an API key (NACHI_LLM=demo).

It reads the ``concept_block`` / ``question_block`` lines every Nachi prompt carries
and builds valid replies from them, so the whole network of agents can run end to end
on T1 for free. The content is obviously canned; it exists to exercise nexus-a2a and
the agent logic, not to teach.

Rules a human can follow in the UI:
* Multiple-choice questions: the correct option is the concept's title.
* Every other question: answer ``demo`` (true/false: ``true``).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from nachi.core.llm.base import LLMError, T, Tier
from nachi.core.schemas import Explanation, Grade, Question, QuestionSet, QuestionType


def _field(text: str, name: str, default: str = "") -> str:
    match = re.search(rf"^{re.escape(name)}: *(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else default


def _mcq(concept_id: str, title: str, n: int) -> dict[str, Any]:
    return {
        "concept_id": concept_id,
        "type": QuestionType.MCQ.value,
        "prompt": f"[demo {n}] Which topic is this question about?",
        "options": [title, "Unrelated topic", "Neither", "Both of these"],
        "answer": title,
        "justification": f"The question is about {title}.",
    }


_DEMO_PROMPTS = {
    QuestionType.TRUE_FALSE: ("[demo {n}] True or false: this question is a demo.", "true"),
    QuestionType.FILL_IN: ("[demo {n}] Type the word demo: ___", "demo"),
    QuestionType.SHORT_ANSWER: ("[demo {n}] Answer with a sentence containing 'demo'.", "demo"),
    QuestionType.PREDICT_OUTPUT: ("[demo {n}] What does print('demo') print?", "demo"),
}


def _question(concept_id: str, title: str, qtype: QuestionType, n: int) -> dict[str, Any]:
    if qtype is QuestionType.MCQ:
        return _mcq(concept_id, title, n)
    prompt, answer = _DEMO_PROMPTS[qtype]
    return {
        "concept_id": concept_id,
        "type": qtype.value,
        "prompt": prompt.format(n=n),
        "options": [],
        "answer": answer,
        "justification": "Demo question.",
    }


class DemoLLM:
    def __init__(self) -> None:
        self._counter = 0

    async def text(
        self, *, system: str, prompt: str, tier: Tier = Tier.FAST, max_tokens: int = 4000
    ) -> str:
        title = _field(prompt, "title") or _field(prompt, "concept_id", "this concept")
        return f"Hint (demo): look again at what the question asks about {title}."

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        tier: Tier = Tier.FAST,
        max_tokens: int = 4000,
    ) -> T:
        self._counter += 1
        concept_id = _field(prompt, "concept_id", "unknown")
        title = _field(prompt, "title", concept_id)
        data: dict[str, Any] | BaseModel
        qtype = QuestionType(_field(prompt, "type", QuestionType.MCQ.value))
        if schema is Question:
            data = _question(concept_id, title, qtype, self._counter)
        elif schema is QuestionSet:
            count = int(_field(prompt, "count", "1") or 1)
            data = {
                "questions": [
                    _question(concept_id, title, qtype, self._counter + i) for i in range(count)
                ]
            }
        elif schema is Explanation:
            summary = _field(prompt, "summary", "")
            data = {"text": f"(demo) {title}: {summary}", "key_points": [title]}
        elif schema is Grade:
            expected = _field(prompt, "expected answer").lower()
            answer = _field(prompt, "learner answer").lower()
            ok = bool(expected) and expected in answer
            data = {
                "score": 1.0 if ok else 0.2,
                "feedback": "Correct (demo)." if ok else "Not quite (demo).",
                "misconception": None if ok else "demo: answer did not match",
            }
        else:
            raise LLMError(f"DemoLLM cannot produce {schema.__name__}")
        return schema.model_validate(data)
