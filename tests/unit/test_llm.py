from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nachi.core.llm import LLMError, LLMRefusal, Tier
from nachi.core.llm.anthropic import FALLBACK_BETA, AnthropicLLM
from nachi.core.llm.fake import FakeLLM
from nachi.core.schemas import Grade

# ── FakeLLM ───────────────────────────────────────────────────────────────────


async def test_fake_replies_in_order_and_records_calls() -> None:
    llm = FakeLLM().reply("first", "second")
    assert await llm.text(system="s", prompt="a") == "first"
    assert await llm.text(system="s", prompt="b", tier=Tier.DEEP) == "second"
    assert [c.prompt for c in llm.calls] == ["a", "b"]
    assert llm.calls[1].tier is Tier.DEEP


async def test_fake_rules_match_prompt_text_and_persist() -> None:
    llm = FakeLLM().when("loops", "Loops repeat code.")
    for _ in range(2):
        assert await llm.text(system="", prompt="explain loops") == "Loops repeat code."


async def test_fake_structured_validates_against_schema() -> None:
    llm = FakeLLM().reply({"score": 1.0, "feedback": "Correct."})
    grade = await llm.structured(system="", prompt="grade", schema=Grade)
    assert grade == Grade(score=1.0, feedback="Correct.")


async def test_fake_raises_when_unscripted_or_told_to() -> None:
    with pytest.raises(LLMError, match="no scripted reply"):
        await FakeLLM().text(system="", prompt="x")
    with pytest.raises(LLMRefusal):
        await FakeLLM().reply(LLMRefusal("cyber")).text(system="", prompt="x")


# ── AnthropicLLM against a stub client (no network) ──────────────────────────


class _Endpoint:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return self.response

    async def parse(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return self.response


def _stub(response: Any) -> tuple[Any, _Endpoint, _Endpoint]:
    stable, beta = _Endpoint(response), _Endpoint(response)
    client = SimpleNamespace(messages=stable, beta=SimpleNamespace(messages=beta))
    return client, stable, beta


def _text_response(text: str, stop: str = "end_turn") -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason=stop, stop_details=None
    )


async def test_deep_tier_uses_sonnet_with_server_side_fallbacks() -> None:
    client, stable, beta = _stub(_text_response("hi"))
    llm = AnthropicLLM(client=client)
    assert await llm.text(system="s", prompt="p", tier=Tier.DEEP) == "hi"
    assert not stable.requests
    request = beta.requests[0]
    assert request["model"] == "claude-sonnet-5-5"
    assert request["betas"] == [FALLBACK_BETA]
    assert request["fallbacks"] == "default"


async def test_fast_tier_uses_haiku_on_the_stable_endpoint() -> None:
    client, stable, beta = _stub(_text_response("hi"))
    await AnthropicLLM(client=client).text(system="s", prompt="p", tier=Tier.FAST)
    assert not beta.requests
    assert stable.requests[0]["model"] == "claude-haiku-5-5"
    assert "betas" not in stable.requests[0]


async def test_structured_passes_the_schema_and_returns_it() -> None:
    parsed = Grade(score=0.5, feedback="Half right.")
    response = SimpleNamespace(parsed_output=parsed, stop_reason="end_turn", stop_details=None)
    client, stable, _ = _stub(response)
    grade = await AnthropicLLM(client=client).structured(system="s", prompt="p", schema=Grade)
    assert grade == parsed
    assert stable.requests[0]["output_format"] is Grade


async def test_refusal_raises_with_its_category() -> None:
    response = SimpleNamespace(
        content=[],
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber", explanation="declined"),
    )
    client, _, _ = _stub(response)
    with pytest.raises(LLMRefusal) as info:
        await AnthropicLLM(client=client).text(system="s", prompt="p")
    assert info.value.category == "cyber"


async def test_empty_text_and_missing_parse_raise() -> None:
    client, _, _ = _stub(_text_response(""))
    with pytest.raises(LLMError, match="no text"):
        await AnthropicLLM(client=client).text(system="s", prompt="p")
    response = SimpleNamespace(parsed_output=None, stop_reason="max_tokens", stop_details=None)
    client, _, _ = _stub(response)
    with pytest.raises(LLMError, match="no valid Grade"):
        await AnthropicLLM(client=client).structured(system="s", prompt="p", schema=Grade)
