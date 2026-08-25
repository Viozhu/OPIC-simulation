"""The narrative model, and the set the adapter's guard is checked against."""

from __future__ import annotations

from opic.core.narrative import (
    AnswerRewrite,
    Narrative,
    quotes_in_report,
)
from core.test_report_real_data import (
    aggregate_available_from,
    load_assessments,
)
from opic.core.report import build_report


def real_report():
    assessments = load_assessments()
    questions = [a.question for a in assessments]
    return build_report(aggregate_available_from(questions, assessments), questions)


def test_quotes_come_from_the_per_answer_detail_not_the_capped_summary():
    report = real_report()

    quotes = quotes_in_report(report)

    # 73 evidence items across the real run, and the exam-level summary keeps
    # at most three per dimension — so a guard built from the summary would
    # reject quotes the rater really produced.
    summary = {
        (item.quote, item.correction_en)
        for dimension in report.dimensions
        for item in dimension.evidence
    }
    assert len(quotes) > len(summary)
    assert summary <= quotes

    for answer in report.answers:
        for score in answer.scores:
            for item in score.evidence:
                assert (item.quote, item.correction_en) in quotes


def test_a_rewrite_is_found_by_answer_index_and_missing_ones_are_none():
    narrative = Narrative(
        analysis=None,
        rewrites=(
            AnswerRewrite(answer_index=3, text_en="x", why_ko="y", invented=False),
        ),
    )

    assert narrative.rewrite_for(3).text_en == "x"
    assert narrative.rewrite_for(4) is None
