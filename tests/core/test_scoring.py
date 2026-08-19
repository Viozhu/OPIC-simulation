from __future__ import annotations

import pytest

from opic.core.metrics import AnswerMetrics
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import (
    AnswerAssessment,
    DimensionScore,
    aggregate,
    dimension_level,
)


def metrics(mean_confidence: float = 0.9, low_rate: float = 0.1) -> AnswerMetrics:
    return AnswerMetrics(
        duration_s=60.0,
        word_count=120,
        words_per_minute=120.0,
        pause_ratio=0.1,
        filler_count=3,
        filler_rate=0.025,
        type_token_ratio=0.6,
        mean_utterance_length=8.0,
        mean_confidence=mean_confidence,
        low_confidence_rate=low_rate,
    )


def assessment(
    index: int,
    levels: dict[Dimension, ActflLevel],
    mean_confidence: float = 0.9,
    low_rate: float = 0.1,
) -> AnswerAssessment:
    return AnswerAssessment(
        question_index=index,
        dimension_scores=tuple(
            DimensionScore(
                dimension=dimension,
                level=levels[dimension],
                comment_ko="설명",
                evidence=(),
            )
            for dimension in Dimension
        ),
        metrics=metrics(mean_confidence, low_rate),
    )


def flat(level: ActflLevel) -> dict[Dimension, ActflLevel]:
    return {dimension: level for dimension in Dimension}


def test_dimension_level_takes_the_median_across_answers():
    assessments = [
        assessment(0, flat(ActflLevel.IL)),
        assessment(1, flat(ActflLevel.IM2)),
        assessment(2, flat(ActflLevel.IM3)),
    ]
    assert dimension_level(assessments, Dimension.GRAMMAR) is ActflLevel.IM2


def test_an_even_count_takes_the_lower_middle():
    assessments = [
        assessment(0, flat(ActflLevel.IL)),
        assessment(1, flat(ActflLevel.IM2)),
    ]
    assert dimension_level(assessments, Dimension.GRAMMAR) is ActflLevel.IL


def test_a_uniform_performance_lands_on_that_level():
    assessments = [assessment(i, flat(ActflLevel.IM2)) for i in range(3)]
    result = aggregate(assessments)
    assert result.final_level is ActflLevel.IM2
    assert result.dimension_levels[Dimension.FLUENCY] is ActflLevel.IM2


def test_one_severely_weak_dimension_pulls_the_final_level_down():
    levels = flat(ActflLevel.IH)
    levels[Dimension.GRAMMAR] = ActflLevel.NH
    assessments = [assessment(i, levels) for i in range(3)]
    result = aggregate(assessments)
    strong = aggregate([assessment(i, flat(ActflLevel.IH)) for i in range(3)])
    assert result.final_level.rank < strong.final_level.rank


def test_the_pronunciation_proxy_is_averaged_and_flagged_as_indicative():
    assessments = [
        assessment(0, flat(ActflLevel.IM2), mean_confidence=0.8, low_rate=0.2),
        assessment(1, flat(ActflLevel.IM2), mean_confidence=0.6, low_rate=0.4),
    ]
    result = aggregate(assessments)
    assert result.pronunciation.mean_confidence == pytest.approx(0.7)
    assert result.pronunciation.low_confidence_rate == pytest.approx(0.3)
    assert result.pronunciation.indicative is True


def test_aggregation_is_reproducible():
    assessments = [assessment(i, flat(ActflLevel.IM1)) for i in range(4)]
    assert aggregate(assessments) == aggregate(assessments)


def test_no_assessments_is_refused():
    with pytest.raises(ValueError):
        aggregate([])


def test_an_assessment_missing_a_dimension_is_refused():
    broken = AnswerAssessment(
        question_index=0,
        dimension_scores=(
            DimensionScore(Dimension.FLUENCY, ActflLevel.IM2, "설명", ()),
        ),
        metrics=metrics(),
    )
    with pytest.raises(ValueError):
        aggregate([broken])


def test_a_gap_of_exactly_three_drops_the_final_level():
    levels = flat(ActflLevel.AL)
    levels[Dimension.GRAMMAR] = ActflLevel.IM1
    result = aggregate([assessment(i, levels) for i in range(3)])
    assert result.final_level is ActflLevel.IM3


def test_a_gap_of_two_leaves_the_final_level_alone():
    levels = flat(ActflLevel.AL)
    levels[Dimension.GRAMMAR] = ActflLevel.IM2
    result = aggregate([assessment(i, levels) for i in range(3)])
    assert result.final_level is ActflLevel.IH
