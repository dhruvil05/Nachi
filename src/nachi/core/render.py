"""Turn a question into the plain text a learner reads (no answer, no justification)."""

from __future__ import annotations

from nachi.core.schemas import Question, QuestionType

_HOW_TO_ANSWER = {
    QuestionType.MCQ: "Answer with the letter or the option text.",
    QuestionType.TRUE_FALSE: "Answer true or false.",
    QuestionType.FILL_IN: "Answer with what goes in the blank.",
    QuestionType.SHORT_ANSWER: "Answer in one to three sentences.",
    QuestionType.PREDICT_OUTPUT: "Answer with exactly what the code prints.",
}


def render_question(question: Question) -> str:
    lines = [question.prompt]
    for i, option in enumerate(question.options):
        lines.append(f"  {chr(ord('A') + i)}) {option}")
    lines.append(_HOW_TO_ANSWER[question.type])
    return "\n".join(lines)
