"""Phase 0 gate: the placeholder agent runs on its own port with real auth and trust,
refuses everyone it should, and passes nexus-a2a's own conformance check."""

from __future__ import annotations

import asyncio
import shutil

import pytest
from nexus_a2a import A2AHttpClient, Message, RetryConfig, TaskState, TransportError

from nachi.agents.echo import EchoAgent
from nachi.core.identity import API_KEY_HEADER
from tests.support import client_as, make_keys, make_topology, running_agent

pytestmark = pytest.mark.contract


@pytest.fixture
def topology():  # type: ignore[no-untyped-def]
    return make_topology("echo")


@pytest.fixture
def keys(topology):  # type: ignore[no-untyped-def]
    return make_keys(topology)


def _artifact_text(task) -> str:  # type: ignore[no-untyped-def]
    return str(task.artifacts[0].parts[0].content)


@pytest.mark.parametrize("caller", ["probe", "gateway"])
async def test_allowed_callers_get_their_message_back(topology, keys, caller):  # type: ignore[no-untyped-def]
    async with running_agent(EchoAgent, "echo", topology, keys):
        async with client_as(caller, "echo", topology, keys) as client:
            task = await client.send_message(Message.user_text("namaste"), skill_id="echo")
    assert task.state == TaskState.COMPLETED
    assert _artifact_text(task) == "namaste"


async def test_anonymous_caller_is_refused(topology, keys):  # type: ignore[no-untyped-def]
    async with running_agent(EchoAgent, "echo", topology, keys):
        async with A2AHttpClient(
            topology.url("echo"), retry=RetryConfig(max_retries=1), timeout=10.0
        ) as client:
            with pytest.raises(TransportError, match="401"):
                await client.send_message(Message.user_text("hi"))


async def test_caller_with_someone_elses_key_is_refused(topology, keys):  # type: ignore[no-untyped-def]
    async with running_agent(EchoAgent, "echo", topology, keys):
        async with A2AHttpClient(
            topology.url("echo"),
            caller_url=topology.url("probe"),
            headers={API_KEY_HEADER: keys["gateway"]},
            retry=RetryConfig(max_retries=1),
            timeout=10.0,
        ) as client:
            with pytest.raises(TransportError, match="401"):
                await client.send_message(Message.user_text("hi"))


async def test_identity_without_a_trust_rule_is_refused(topology, keys):  # type: ignore[no-untyped-def]
    async with running_agent(EchoAgent, "echo", topology, keys):
        async with client_as("stranger", "echo", topology, keys) as client:
            with pytest.raises(TransportError, match="40[13]"):
                await client.send_message(Message.user_text("hi"))


async def test_allowed_caller_cannot_invoke_a_skill_it_was_not_granted(topology, keys):  # type: ignore[no-untyped-def]
    async with running_agent(EchoAgent, "echo", topology, keys):
        async with client_as("probe", "echo", topology, keys) as client:
            with pytest.raises(TransportError, match="403"):
                await client.send_message(Message.user_text("hi"), skill_id="admin")


async def test_nexus_verify_passes(topology, keys):  # type: ignore[no-untyped-def]
    nexus = shutil.which("nexus")
    assert nexus, "the nexus CLI must be installed with nexus-a2a"
    async with running_agent(EchoAgent, "echo", topology, keys):
        proc = await asyncio.create_subprocess_exec(
            nexus,
            "verify",
            topology.url("echo"),
            "--caller-url",
            topology.url("probe"),
            "--api-key",
            keys["probe"],
            "--api-key-header",
            API_KEY_HEADER,
            "--skill",
            "echo",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    report = out.decode(errors="replace")
    assert proc.returncode == 0, report
    assert "0 fail" in report, report
