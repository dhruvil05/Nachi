"""Calling other agents by skill.

A Nachi service never hard-codes another agent's URL. ``Peers`` asks nexus-a2a's
``AgentRegistry`` for an agent that offers a skill. On a miss it registers the agents
this service is *allowed* to call (from the topology and ``TRUST_RULES``) by fetching
their cards, then asks again. So moving an agent means changing the topology only, and
a card refresh picks up the new address.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypeVar

from nexus_a2a import (
    A2AHttpClient,
    AgentRegistry,
    CircuitBreaker,
    Message,
    StreamEvent,
    Task,
    TaskState,
    TransportError,
)
from pydantic import BaseModel

from nachi.core.config import Topology
from nachi.core.identity import API_KEY_HEADER, targets_of
from nachi.core.messages import result_of, user_message

R = TypeVar("R", bound=BaseModel)


class PeerError(RuntimeError):
    """A peer agent could not be found, or its task did not complete."""


class Peers:
    def __init__(
        self,
        me: str,
        topology: Topology,
        keys: dict[str, str],
        *,
        registry: AgentRegistry | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.me = me
        self.topology = topology
        self._key = keys[me]
        self.registry = registry or AgentRegistry(card_ttl_seconds=60.0)
        self._timeout = timeout
        self._breakers: dict[str, CircuitBreaker] = {}

    def _allowed_urls(self, skill: str) -> list[str]:
        return [
            self.topology.url(target)
            for target, skills in targets_of(self.me).items()
            if skill in skills and target in self.topology
        ]

    def _match(self, skill: str, allowed: list[str]) -> str | None:
        for card in self.registry.find_by_skill(skill):
            url = str(card.url).rstrip("/")
            if url in allowed:
                return url
        return None

    async def resolve(self, skill: str) -> str:
        """Base URL of an allowed, registered agent offering ``skill``."""
        allowed = self._allowed_urls(skill)
        if not allowed:
            raise PeerError(f"{self.me} is not allowed to call skill {skill!r}")
        url = self._match(skill, allowed)
        if url:
            return url
        errors: list[str] = []
        for candidate in allowed:
            try:
                await self.registry.register_url(candidate)
            except Exception as exc:  # noqa: BLE001 - try the next candidate
                errors.append(f"{candidate}: {exc}")
        url = self._match(skill, allowed)
        if url:
            return url
        raise PeerError(f"no reachable agent offers {skill!r} ({'; '.join(errors) or 'none'})")

    def client(self, url: str, **kwargs: Any) -> A2AHttpClient:
        breaker = self._breakers.setdefault(url, CircuitBreaker())
        return A2AHttpClient(
            url,
            caller_url=self.topology.url(self.me),
            headers={API_KEY_HEADER: self._key},
            circuit_breaker=breaker,
            timeout=kwargs.pop("timeout", self._timeout),
            **kwargs,
        )

    async def send(self, skill: str, message: Message, task_id: str | None = None) -> Task:
        url = await self.resolve(skill)
        try:
            async with self.client(url) as client:
                return await client.send_message(message, skill_id=skill, task_id=task_id)
        except TransportError as exc:
            raise PeerError(f"{skill} call to {url} failed: {exc}") from exc

    async def stream(
        self, skill: str, message: Message, task_id: str | None = None
    ) -> AsyncIterator[StreamEvent]:
        """Send with ``message/stream`` and yield the events as they arrive."""
        url = await self.resolve(skill)
        try:
            async with self.client(url) as client:
                async for event in client.stream_message(message, skill_id=skill, task_id=task_id):
                    yield event
        except TransportError as exc:
            raise PeerError(f"{skill} stream from {url} failed: {exc}") from exc

    async def get_task(self, skill: str, task_id: str) -> Task:
        url = await self.resolve(skill)
        try:
            async with self.client(url) as client:
                return await client.get_task(task_id)
        except TransportError as exc:
            raise PeerError(f"{skill} get_task on {url} failed: {exc}") from exc

    async def call(self, skill: str, request: BaseModel, response: type[R]) -> R:
        """Send ``request`` to the agent offering ``skill`` and return its JSON result."""
        task = await self.send(skill, user_message(request))
        if task.state != TaskState.COMPLETED:
            raise PeerError(f"{skill} task ended {task.state}: {task.error or 'no error given'}")
        return result_of(task, response)
