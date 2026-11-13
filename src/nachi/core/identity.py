"""Who may call whom, and how each Nachi service proves who it is.

This is the only module that touches credentials and trust rules.

* Every service has its own API key (see ``config.load_keys``). A caller sends its
  own key, so nexus-a2a can treat the caller as *verified*: the key belongs to exactly
  one registered caller URL.
* ``TRUST_RULES`` is the whole call graph, by service name and skill. A service only
  registers the callers that are allowed to reach it, so anyone else is refused.
* Security is always on. Nachi never uses ``allow_insecure=True``.
"""

from __future__ import annotations

from typing import Any

from nexus_a2a import (
    A2AHttpClient,
    AgentCredentialConfig,
    AuthManager,
    AuthScheme,
    RateLimitConfig,
    RateLimiter,
    SecurityMiddleware,
    TrustBoundary,
)

from nachi.core.config import Topology

API_KEY_HEADER = "X-API-Key"

# caller -> target -> skills the caller may invoke on that target.
# Matches the design doc's trust rules; services missing from a topology are ignored.
TRUST_RULES: dict[str, dict[str, list[str]]] = {
    "gateway": {
        "echo": ["echo"],
        "diagnostician": ["diagnose"],
        "tutor": ["tutor"],
        "quizmaker": ["quiz"],
        "grader": ["grade"],
        "scheduler": ["schedule_review"],
        "planner": ["plan_path"],
    },
    "tutor": {
        "grader": ["grade"],
        "explainer": ["explain"],
    },
    "grader": {
        "coderunner": ["run_code"],
    },
    # Identity used by `nexus verify` and the contract tests.
    "probe": {
        "echo": ["echo"],
    },
}

DEFAULT_RATE_LIMIT = RateLimitConfig(rate=20.0, burst=40.0)


def callers_of(target: str, topology: Topology) -> dict[str, list[str]]:
    """Callers allowed to reach ``target`` in this topology, with their skills."""
    return {
        caller: skills_by_target[target]
        for caller, skills_by_target in TRUST_RULES.items()
        if target in skills_by_target and caller in topology
    }


def targets_of(caller: str) -> dict[str, list[str]]:
    """Services ``caller`` may call, with the skills it may invoke."""
    return dict(TRUST_RULES.get(caller, {}))


def build_security(
    me: str,
    topology: Topology,
    keys: dict[str, str],
    *,
    rate_limit: RateLimitConfig = DEFAULT_RATE_LIMIT,
) -> SecurityMiddleware:
    """SecurityMiddleware for service ``me``: auth, trust and rate limits.

    Only callers in ``TRUST_RULES`` for ``me`` are registered, each with its own key,
    so an unknown caller fails authentication and a known one can call only its skills.
    """
    my_url = topology.url(me)
    auth = AuthManager()
    trust = TrustBoundary()
    for caller, skills in callers_of(me, topology).items():
        caller_url = topology.url(caller)
        auth.register_agent(
            caller_url,
            AgentCredentialConfig(
                scheme=AuthScheme.API_KEY,
                api_key=keys[caller],
                header_name=API_KEY_HEADER,
            ),
        )
        trust.allow(caller_url, my_url, skills=list(skills))
    return SecurityMiddleware(
        auth=auth,
        trust=trust,
        rate_limiter=RateLimiter(default_config=rate_limit),
        server_url=my_url,
        require_caller=True,
    )


def client_for(
    me: str,
    target: str,
    topology: Topology,
    keys: dict[str, str],
    **client_kwargs: Any,
) -> A2AHttpClient:
    """An A2A client that calls ``target`` as service ``me``, with ``me``'s own key."""
    headers = dict(client_kwargs.pop("headers", None) or {})
    headers[API_KEY_HEADER] = keys[me]
    return A2AHttpClient(
        topology.url(target),
        caller_url=topology.url(me),
        headers=headers,
        **client_kwargs,
    )
