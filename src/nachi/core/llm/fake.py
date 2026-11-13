"""A scripted LLM for tests and the T0 baseline: free, fast and repeatable.

Script replies in order with ``reply()``, or by prompt content with ``when()``::

    llm = FakeLLM()
    llm.when("Explain", "Loops repeat code.")
    llm.reply({"score": 1.0, "feedback": "Correct.", "misconception": None})

``when()`` rules are checked first (substring of system + prompt) and stay in place;
``reply()`` entries are used once each, in order. Every call is recorded in ``calls``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from nachi.core.llm.base import LLMError, T, Tier

Reply = str | dict[str, Any] | BaseModel | Exception


@dataclass
class FakeCall:
    kind: str  # "text" or "structured"
    system: str
    prompt: str
    tier: Tier
    schema: type[BaseModel] | None = None


@dataclass
class FakeLLM:
    calls: list[FakeCall] = field(default_factory=list)
    _queue: list[Reply] = field(default_factory=list)
    _rules: list[tuple[str, Reply]] = field(default_factory=list)

    def reply(self, *replies: Reply) -> FakeLLM:
        self._queue.extend(replies)
        return self

    def when(self, contains: str, reply: Reply) -> FakeLLM:
        self._rules.append((contains, reply))
        return self

    def _next(self, system: str, prompt: str) -> Reply:
        haystack = f"{system}\n{prompt}"
        for needle, scripted in self._rules:
            if needle in haystack:
                return scripted
        if self._queue:
            return self._queue.pop(0)
        raise LLMError(f"FakeLLM has no scripted reply for prompt: {prompt[:80]!r}")

    async def text(
        self,
        *,
        system: str,
        prompt: str,
        tier: Tier = Tier.FAST,
        max_tokens: int = 4000,
    ) -> str:
        self.calls.append(FakeCall("text", system, prompt, tier))
        scripted = self._next(system, prompt)
        if isinstance(scripted, Exception):
            raise scripted
        if isinstance(scripted, BaseModel):
            return scripted.model_dump_json()
        if isinstance(scripted, dict):
            raise LLMError("FakeLLM: a dict reply was scripted for a text() call")
        return scripted

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        tier: Tier = Tier.FAST,
        max_tokens: int = 4000,
    ) -> T:
        self.calls.append(FakeCall("structured", system, prompt, tier, schema))
        scripted = self._next(system, prompt)
        if isinstance(scripted, Exception):
            raise scripted
        if isinstance(scripted, BaseModel):
            return schema.model_validate(scripted.model_dump())
        if isinstance(scripted, dict):
            return schema.model_validate(scripted)
        return schema.model_validate_json(scripted)
