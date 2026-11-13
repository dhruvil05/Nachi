from __future__ import annotations

from nexus_a2a import SecurityMiddleware

from nachi.core.identity import TRUST_RULES, build_security, callers_of, targets_of
from tests.support import make_keys, make_topology


def test_callers_are_limited_to_services_in_the_topology() -> None:
    topology = make_topology("grader")
    assert callers_of("grader", topology) == {"gateway": ["grade"]}  # no tutor here
    topology = make_topology("grader", "tutor")
    assert callers_of("grader", topology) == {"gateway": ["grade"], "tutor": ["grade"]}


def test_tutor_calls_grader_and_explainer_only() -> None:
    assert targets_of("tutor") == {"grader": ["grade"], "explainer": ["explain"]}


def test_explainer_and_quizmaker_call_no_one() -> None:
    assert targets_of("explainer") == {}
    assert targets_of("quizmaker") == {}


def test_trust_rules_only_name_known_skills() -> None:
    skills = {skill for targets in TRUST_RULES.values() for s in targets.values() for skill in s}
    assert skills <= {
        "echo",
        "diagnose",
        "tutor",
        "quiz",
        "grade",
        "explain",
        "schedule_review",
        "plan_path",
        "run_code",
    }


def test_build_security_returns_middleware() -> None:
    topology = make_topology("echo")
    security = build_security("echo", topology, make_keys(topology))
    assert isinstance(security, SecurityMiddleware)
