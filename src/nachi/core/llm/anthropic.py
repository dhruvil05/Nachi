"""Claude implementation of the LLM interface.

* ``Tier.DEEP`` -> Claude Sonnet 5.5, with server-side refusal fallbacks
  (``fallbacks="default"``), so a declined request is retried on a fallback model
  inside the same call.
* ``Tier.FAST`` -> Claude Haiku 5.5. Haiku has no server-side fallback; a refusal
  raises ``LLMRefusal``.

Structured replies use ``messages.parse(output_format=Model)``, which validates the
response against the Pydantic schema. Override models with ``NACHI_MODEL_DEEP`` /
``NACHI_MODEL_FAST``.
"""

from __future__ import annotations

import os
from typing import Any

import anthropic
from pydantic import BaseModel

from nachi.core.llm.base import LLMError, LLMRefusal, T, Tier

DEFAULT_MODELS: dict[Tier, str] = {
    Tier.DEEP: "claude-sonnet-5-5",
    Tier.FAST: "claude-haiku-5-5",
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept server-side refusal fallbacks (Haiku does not).
_FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-2"}


def models_from_env() -> dict[Tier, str]:
    return {
        Tier.DEEP: os.environ.get("NACHI_MODEL_DEEP", DEFAULT_MODELS[Tier.DEEP]),
        Tier.FAST: os.environ.get("NACHI_MODEL_FAST", DEFAULT_MODELS[Tier.FAST]),
    }


class AnthropicLLM:
    """``LLM`` backed by the Anthropic async client."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic | None = None,
        models: dict[Tier, str] | None = None,
    ) -> None:
        self._client = client if client is not None else anthropic.AsyncAnthropic()
        self._models = models or models_from_env()

    def model_for(self, tier: Tier) -> str:
        return self._models[tier]

    def _request(self, tier: Tier, system: str, prompt: str, max_tokens: int) -> dict[str, Any]:
        model = self.model_for(tier)
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if model in _FALLBACK_MODELS:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    def _messages(self, request: dict[str, Any]) -> Any:
        # Fallbacks live on the beta surface; plain requests use the stable one.
        return self._client.beta.messages if "betas" in request else self._client.messages

    @staticmethod
    def _check_refusal(response: Any) -> None:
        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefusal(
                getattr(details, "category", None), getattr(details, "explanation", None)
            )

    async def text(
        self,
        *,
        system: str,
        prompt: str,
        tier: Tier = Tier.FAST,
        max_tokens: int = 4000,
    ) -> str:
        request = self._request(tier, system, prompt, max_tokens)
        try:
            response = await self._messages(request).create(**request)
        except anthropic.APIError as exc:
            raise LLMError(f"{request['model']} call failed: {exc}") from exc
        self._check_refusal(response)
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        if not text:
            raise LLMError(f"{request['model']} returned no text (stop: {response.stop_reason})")
        return text

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        tier: Tier = Tier.FAST,
        max_tokens: int = 4000,
    ) -> T:
        request = self._request(tier, system, prompt, max_tokens)
        try:
            response = await self._messages(request).parse(output_format=schema, **request)
        except anthropic.APIError as exc:
            raise LLMError(f"{request['model']} call failed: {exc}") from exc
        self._check_refusal(response)
        parsed = getattr(response, "parsed_output", None)
        if not isinstance(parsed, BaseModel):
            raise LLMError(
                f"{request['model']} returned no valid {schema.__name__} "
                f"(stop: {response.stop_reason})"
            )
        return schema.model_validate(parsed.model_dump())
