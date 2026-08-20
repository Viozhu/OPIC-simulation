from __future__ import annotations

from opic.core.questions import QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.report import build_report
from opic.core.scoring import aggregate

from core.conftest import assessment, blueprint_of, slot


def questions_of(n: int):
    from opic.core.questions import Question

    return tuple(
        Question(slot=slot(i, QuestionType.DESCRIPTION, "movies"), text_en=f"Question {i}")
        for i in range(n)
    )


def report_of(n: int, level: dict | None = None):
    level = level or {d: ActflLevel.IM2 for d in Dimension}
    assessments = [assessment(i, level) for i in range(n)]
    result = aggregate(blueprint_of(n), assessments)
    return build_report(result, questions_of(n))


def test_the_header_counts_scored_against_expected():
    report = report_of(3)
    assert report.scored_answers == 3
    assert report.expected_answers == 3
    assert report.final_level is ActflLevel.IM2


def test_dimensions_come_in_descending_weight_order():
    report = report_of(3)
    weights = [d.weight for d in report.dimensions]
    assert weights == sorted(weights, reverse=True)
    assert report.dimensions[0].dimension is Dimension.FLUENCY
    assert report.dimensions[0].label_ko == "유창성"


def test_no_limiting_dimension_when_the_cap_did_not_fire():
    assert report_of(3).limiting is None


def test_the_limiting_dimension_is_named_in_korean():
    level = {d: ActflLevel.IH for d in Dimension}
    level[Dimension.GRAMMAR] = ActflLevel.NH
    report = report_of(3, level)
    assert report.limiting is not None
    assert report.limiting.label_ko == "문법"
    assert report.limiting.without_cap.rank > report.final_level.rank
