"""The report, built from a real graded exam rather than invented fixtures.

`evidence/sample-answers/answer-NN.json` are fifteen real `answer-NN.json`
files copied out of a completed acceptance run: real speech through
faster-whisper, real judgements from qwen3:14b. See
`evidence/sample-answers/README.md` for provenance. Pinning the report to
this run — rather than to hand-written data — is what catches cases a
fixture author would not have thought to write, such as one answer's model
output carrying two evidence items for a single dimension though the prompt
asks for at most one.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Sequence

from opic.core.questions import Question
from opic.core.report import (
    EXAM_EVIDENCE_PER_DIMENSION,
    UNCLEAR_WORDS_SHOWN,
    build_report,
    render_text,
)
from opic.core.scoring import AnswerAssessment, ExamResult, aggregate
from opic.session.assessments import _answer_from_json

EVIDENCE = pathlib.Path(__file__).resolve().parents[2] / "evidence"


def aggregate_available_from(
    questions: Sequence[Question], assessments: Sequence[AnswerAssessment]
) -> ExamResult:
    """The fixture is a complete fifteen-answer run, so plain `aggregate` applies."""
    return aggregate(tuple(q.slot for q in questions), list(assessments))


def load_assessments() -> list[AnswerAssessment]:
    files = sorted((EVIDENCE / "sample-answers").glob("answer-*.json"))
    return [_answer_from_json(json.loads(f.read_text(encoding="utf-8"))) for f in files]


def test_a_real_exam_builds_a_report_without_raising():
    assessments = load_assessments()
    questions = [a.question for a in assessments]
    result = aggregate_available_from(questions, assessments)

    report = build_report(result, questions)

    assert report.scored_answers == 15


def test_exam_level_evidence_is_capped_but_per_answer_detail_keeps_everything():
    assessments = load_assessments()
    questions = [a.question for a in assessments]
    report = build_report(aggregate_available_from(questions, assessments), questions)

    quoted = [e for d in report.dimensions for e in d.evidence]
    assert quoted, "the real run produced evidence; the report dropped it"
    for dimension in report.dimensions:
        assert len(dimension.evidence) <= EXAM_EVIDENCE_PER_DIMENSION

    # The raw data has 73 evidence items across 71 dimension scores (one
    # answer's model output carried two items for one dimension), so at
    # least one dimension collects more evidence than the exam-level cap
    # allows, and the per-answer detail must keep every item the model
    # produced instead of applying that cap.
    per_answer_evidence_counts = [
        len(score.evidence) for answer in report.answers for score in answer.scores
    ]
    assert sum(per_answer_evidence_counts) == 73
    assert any(count > 1 for count in per_answer_evidence_counts)


def test_unclear_words_are_deduplicated_and_capped():
    assessments = load_assessments()
    questions = [a.question for a in assessments]
    report = build_report(aggregate_available_from(questions, assessments), questions)

    assert report.unclear
    assert len(report.unclear) <= UNCLEAR_WORDS_SHOWN
    from opic.core.metrics import _normalise

    normalised = [_normalise(word.text) for word in report.unclear]
    assert len(normalised) == len(set(normalised))


def test_the_real_report_renders_as_text_without_raising():
    assessments = load_assessments()
    questions = [a.question for a in assessments]
    text = render_text(build_report(aggregate_available_from(questions, assessments), questions))

    assert "최종 등급" in text
    assert "왜 이 등급인가" in text
    assert "또렷하게 인식되지 않은 단어" in text
    assert "유형별 · 주제별" in text
    assert "답변별 상세" in text
