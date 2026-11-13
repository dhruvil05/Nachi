"""The LLM interface every Nachi agent uses.

Agents never import a provider SDK directly. They take an ``LLM`` and ask for either
plain text or a validated Pydantic object. Failures raise ``LLMError``, so nexus-a2a
marks the task FAILED and the DLQ can keep it; there are no "[error: ...]" strings.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Tier(StrEnum):
    """How much reasoning a call needs; each tier maps to a model."""

    DEEP = "deep"  # multi-turn reasoning about the learner: Tutor, Diagnostician
    FAST = "fast"  # short, well-specified tasks: grading, quizzes, explanations


class LLMError(RuntimeError):
    """A model call failed or returned something unusable."""


class LLMRefusal(LLMError):
    """The model declined the request (stop_reason == "refusal")."""

    def __init__(self, category: str | None, explanation: str | None = None) -> None:
        detail = f" ({category})" if category else ""
        super().__init__(f"model refused the request{detail}: {explanation or 'no explanation'}")
        self.category = category
        self.explanation = explanation


class LLM(Protocol):
    async def text(
        self,
        *,
        system: str,
        prompt: str,
        tier: Tier = Tier.FAST,
        max_tokens: int = 4000,
    ) -> str:
        """Return the model's text reply."""
        ...

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        tier: Tier = Tier.FAST,
        max_tokens: int = 4000,
    ) -> T:
        """Return the reply parsed and validated as ``schema``."""
        ...
