"""Explainer, QuizMaker, Grader and Review Scheduler, called directly (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from nexus_a2a import Task

from nachi.agents.explainer import Explainer
from nachi.agents.grader import Grader, grade_objective
from nachi.agents.quizmaker import QuizMaker
from nachi.agents.scheduler import sm2
from nachi.core.llm import LLMError
from nachi.core.llm.fake import FakeLLM
from nachi.core.messages import ContractError, user_message
from nachi.core.schemas import (
    ConceptBrief,
    ExplainRequest,
    Grade,
    GradeRequest,
    Question,
    QuestionType,
    QuizRequest,
    ReviewRequest,
)

LOOPS = ConceptBrief(
    concept_id="for_loops",
    title="for loops and range",
    summary="Repeating code once per item.",
    objectives=["Trace a for loop over a list"],
)


def task_with(payload: object) -> Task:
    return Task(history=[user_message(payload)])  # type: ignore[arg-type]


def mcq(answer: str = "3") -> Question:
    return Question(
        concept_id="for_loops",
        type=QuestionType.MCQ,
        prompt="How many times does `for x in [1, 2, 3]` run?",
        options=["1", "2", "3", "4"],
        answer=answer,
        justification="The list has three items.",
    )


# ── Explainer ─────────────────────────────────────────────────────────────────


async def test_explainer_returns_explanation_and_passes_focus() -> None:
    llm = FakeLLM().reply({"text": "A for loop repeats.", "key_points": ["one pass per item"]})
    out = await Explainer(llm).run(task_with(ExplainRequest(concept=LOOPS, focus="off by one")))
    assert out == {"text": "A for loop repeats.", "key_points": ["one pass per item"]}
    assert "off by one" in llm.calls[0].prompt
    assert "concept_id: for_loops" in llm.calls[0].prompt


async def test_agents_reject_a_missing_request() -> None:
    with pytest.raises(ContractError):
        await Explainer(FakeLLM()).run(Task(history=[]))


# ── QuizMaker ─────────────────────────────────────────────────────────────────


async def test_quizmaker_trims_to_count_and_checks_questions() -> None:
    llm = FakeLLM().reply({"questions": [mcq().model_dump(mode="json")] * 3})
    out = await QuizMaker(llm).run(task_with(QuizRequest(concept=LOOPS, count=2)))
    assert len(out["questions"]) == 2


async def test_quizmaker_rejects_an_mcq_whose_answer_is_not_an_option() -> None:
    bad = mcq(answer="three").model_dump(mode="json")
    llm = FakeLLM().reply({"questions": [bad]})
    with pytest.raises(LLMError, match="4 options"):
        await QuizMaker(llm).run(task_with(QuizRequest(concept=LOOPS, count=1)))


# ── Grader ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("answer", "score"), [("3", 1.0), ("c", 1.0), ("C)", 1.0), ("2", 0.0)])
def test_mcq_is_graded_without_the_llm(answer: str, score: float) -> None:
    grade = grade_objective(mcq(), answer)
    assert grade is not None and grade.score == score


@pytest.mark.parametrize(("answer", "score"), [("True", 1.0), ("yes", 1.0), ("false", 0.0)])
def test_true_false_is_graded_without_the_llm(answer: str, score: float) -> None:
    question = mcq().model_copy(
        update={"type": QuestionType.TRUE_FALSE, "options": [], "answer": "true"}
    )
    grade = grade_objective(question, answer)
    assert grade is not None and grade.score == score


async def test_short_answer_goes_to_the_llm_with_its_rubric() -> None:
    question = mcq().model_copy(
        update={"type": QuestionType.SHORT_ANSWER, "options": [], "answer": "once per item"}
    )
    llm = FakeLLM().reply({"score": 0.75, "feedback": "Good.", "misconception": None})
    out = await Grader(llm).run(task_with(GradeRequest(question=question, answer="it repeats")))
    assert Grade.model_validate(out).score == 0.75
    prompt = llm.calls[0].prompt
    assert "learner answer: it repeats" in prompt
    assert "core_idea" in prompt  # the short-answer rubric


async def test_exact_predict_output_skips_the_llm() -> None:
    question = mcq().model_copy(
        update={"type": QuestionType.PREDICT_OUTPUT, "options": [], "answer": "1\n2\n3"}
    )
    llm = FakeLLM()
    out = await Grader(llm).run(task_with(GradeRequest(question=question, answer=" 1\n2\n3 ")))
    assert out["score"] == 1.0 and not llm.calls


# ── Review Scheduler (SM-2) ───────────────────────────────────────────────────

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def test_sm2_first_two_successes_use_1_then_6_days() -> None:
    first = sm2(ReviewRequest(score=1.0, reviewed_at=NOW))
    assert (first.interval_days, first.repetitions) == (1, 1)
    second = sm2(
        ReviewRequest(
            score=1.0,
            interval_days=first.interval_days,
            repetitions=first.repetitions,
            efactor=first.efactor,
            reviewed_at=NOW,
        )
    )
    assert (second.interval_days, second.repetitions) == (6, 2)
    assert second.next_due == NOW + timedelta(days=6)


def test_sm2_a_miss_resets_and_lowers_ease_but_not_below_floor() -> None:
    result = sm2(
        ReviewRequest(score=0.0, interval_days=20, repetitions=5, efactor=1.35, reviewed_at=NOW)
    )
    assert (result.interval_days, result.repetitions) == (1, 0)
    assert result.efactor == 1.3
    assert result.quality == 0


def test_sm2_grows_interval_by_ease_after_two_reps() -> None:
    result = sm2(
        ReviewRequest(score=0.8, interval_days=6, repetitions=2, efactor=2.5, reviewed_at=NOW)
    )
    assert result.quality == 4
    assert result.interval_days == 15
