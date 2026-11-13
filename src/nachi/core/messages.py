"""Helpers for putting Nachi contracts into A2A messages and reading them back.

Requests and structured replies travel as a JSON part (the Pydantic model dumped to a
dict), usually next to a human-readable text part. Agents reconstruct everything from
the task history, so they keep no state between turns.
"""

from __future__ import annotations

from typing import Any, TypeVar

from nexus_a2a import Artifact, Message, MessageRole, Part, PartType, Task
from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)


class ContractError(ValueError):
    """A message did not carry the contract an agent expected."""


def _parts(payload: BaseModel | dict[str, Any] | None, text: str | None) -> list[Part]:
    parts: list[Part] = []
    if text:
        parts.append(Part(type=PartType.TEXT, content=text))
    if payload is not None:
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        parts.append(Part(type=PartType.JSON, content=data))
    if not parts:
        raise ValueError("a message needs text, a payload, or both")
    return parts


def user_message(
    payload: BaseModel | dict[str, Any] | None = None, text: str | None = None
) -> Message:
    return Message(role=MessageRole.USER, parts=_parts(payload, text))


def agent_message(
    payload: BaseModel | dict[str, Any] | None = None, text: str | None = None
) -> Message:
    return Message(role=MessageRole.AGENT, parts=_parts(payload, text))


def json_of(message: Message | Artifact) -> dict[str, Any] | None:
    """The first JSON part's content, or None."""
    for part in message.parts:
        if part.type == PartType.JSON and isinstance(part.content, dict):
            return part.content
    return None


def read(message: Message | Artifact, model: type[M]) -> M:
    data = json_of(message)
    if data is None:
        raise ContractError(f"expected a {model.__name__} JSON part, found none")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ContractError(f"invalid {model.__name__}: {exc}") from exc


def _by_role(task: Task, role: MessageRole) -> list[Message]:
    return [m for m in task.history if m.role == role]


def request_of(task: Task, model: type[M]) -> M:
    """The request that opened the task: the first user message's JSON part."""
    users = _by_role(task, MessageRole.USER)
    if not users:
        raise ContractError("task has no user message")
    return read(users[0], model)


def last_agent_payload(task: Task, model: type[M]) -> M | None:
    """The most recent agent message carrying a ``model`` JSON part, if any."""
    for message in reversed(_by_role(task, MessageRole.AGENT)):
        if json_of(message) is not None:
            return read(message, model)
    return None


def latest_user_text(task: Task) -> str:
    users = _by_role(task, MessageRole.USER)
    return users[-1].text().strip() if users else ""


def user_turns(task: Task) -> int:
    return len(_by_role(task, MessageRole.USER))


def result_of(task: Task, model: type[M]) -> M:
    """The task's final JSON artifact as ``model``."""
    for artifact in reversed(task.artifacts):
        if json_of(artifact) is not None:
            return read(artifact, model)
    raise ContractError(f"task {task.id} has no {model.__name__} artifact (state {task.state})")
