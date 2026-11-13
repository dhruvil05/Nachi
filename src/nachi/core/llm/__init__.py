"""LLM layer: one async interface, a Claude implementation, a demo and a scripted fake."""

from __future__ import annotations

import os

from nachi.core.llm.base import LLM, LLMError, LLMRefusal, Tier

LLM_ENV = "NACHI_LLM"


def make_llm(kind: str | None = None) -> LLM:
    """``anthropic`` (default) or ``demo`` (no API key, deterministic canned replies)."""
    kind = (kind or os.environ.get(LLM_ENV) or "anthropic").lower()
    if kind == "anthropic":
        from nachi.core.llm.anthropic import AnthropicLLM

        return AnthropicLLM()
    if kind == "demo":
        from nachi.core.llm.demo import DemoLLM

        return DemoLLM()
    raise ValueError(f"{LLM_ENV} must be 'anthropic' or 'demo', not {kind!r}")


__all__ = ["LLM", "LLMError", "LLMRefusal", "Tier", "make_llm"]
