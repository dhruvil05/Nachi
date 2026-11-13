"""EchoAgent: returns the text it receives.

It has no logic on purpose. It exists to prove that a Nachi service runs on its own
port with real auth and trust rules, and passes ``nexus verify``. The real agents in
Phase 1 are served the same way.
"""

from __future__ import annotations

from nexus_a2a import Task, agent


@agent(
    name="EchoAgent",
    description="Nachi placeholder agent. Returns the text of the latest message unchanged.",
    version="0.1.0",
    # The served card's URL comes from the topology (public_url); this is only a default.
    url="http://127.0.0.1:8100",
    skills=[
        {
            "id": "echo",
            "name": "Echo",
            "description": "Returns the message text unchanged.",
            "tags": ["test", "placeholder"],
            "examples": ["hello"],
        }
    ],
)
class EchoAgent:
    async def run(self, task: Task) -> str:
        message = task.latest_message()
        return message.text() if message is not None else ""
