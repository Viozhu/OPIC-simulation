from __future__ import annotations

import pytest

from opic.core.metrics import AnswerMetrics
from opic.core.questions import QuestionSlot, QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import (
    AnswerAssessment,
    DimensionScore,
    aggregate,
    dimension_level,
)


def slot(index: int, qtype: QuestionType, topic_id: str | None, advanced: bool = False):
    return QuestionSlot(
        index=index,
        qtype=qtype,
        topic_id=topic_id,
        combo_id=None if topic_id is None else 0,
        advanced=advanced,
        target=ActflLevel.IM2,
    )


def blueprint_of(n: int) -> tuple[QuestionSlot, ...]:
    return tuple(slot(i, QuestionType.DESCRIPTION, "movies") for i in range(n))


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
    result = aggregate(blueprint_of(3), assessments)
    assert result.final_level is ActflLevel.IM2
    assert result.level_for(Dimension.FLUENCY) is ActflLevel.IM2


def test_one_severely_weak_dimension_pulls_the_final_level_down():
    levels = flat(ActflLevel.IH)
    levels[Dimension.GRAMMAR] = ActflLevel.NH
    assessments = [assessment(i, levels) for i in range(3)]
    result = aggregate(blueprint_of(3), assessments)
    strong = aggregate(blueprint_of(3), [assessment(i, flat(ActflLevel.IH)) for i in range(3)])
    assert result.final_level.rank < strong.final_level.rank


def test_the_pronunciation_proxy_is_averaged_and_flagged_as_indicative():
    assessments = [
        assessment(0, flat(ActflLevel.IM2), mean_confidence=0.8, low_rate=0.2),
        assessment(1, flat(ActflLevel.IM2), mean_confidence=0.6, low_rate=0.4),
    ]
    result = aggregate(blueprint_of(2), assessments)
    assert result.pronunciation.mean_confidence == pytest.approx(0.7)
    assert result.pronunciation.low_confidence_rate == pytest.approx(0.3)
    assert result.pronunciation.indicative is True


def test_aggregation_is_reproducible():
    assessments = [assessment(i, flat(ActflLevel.IM1)) for i in range(4)]
    assert aggregate(blueprint_of(4), assessments) == aggregate(blueprint_of(4), assessments)


def test_no_assessments_is_refused():
    with pytest.raises(ValueError):
        aggregate((), [])


def test_an_assessment_missing_a_dimension_is_refused():
    broken = AnswerAssessment(
        question_index=0,
        dimension_scores=(
            DimensionScore(Dimension.FLUENCY, ActflLevel.IM2, "설명", ()),
        ),
        metrics=metrics(),
    )
    with pytest.raises(ValueError):
        aggregate(blueprint_of(1), [broken])


def test_a_gap_of_exactly_three_drops_the_final_level():
    levels = flat(ActflLevel.AL)
    levels[Dimension.GRAMMAR] = ActflLevel.IM1
    result = aggregate(blueprint_of(3), [assessment(i, levels) for i in range(3)])
    assert result.final_level is ActflLevel.IM3


def test_a_gap_of_two_leaves_the_final_level_alone():
    levels = flat(ActflLevel.AL)
    levels[Dimension.GRAMMAR] = ActflLevel.IM2
    result = aggregate(blueprint_of(3), [assessment(i, levels) for i in range(3)])
    assert result.final_level is ActflLevel.IH


def test_dimension_levels_are_an_immutable_sequence_of_pairs():
    result = aggregate(blueprint_of(3), [assessment(i, flat(ActflLevel.IM2)) for i in range(3)])
    assert isinstance(result.dimension_levels, tuple)
    assert result.level_for(Dimension.GRAMMAR) is ActflLevel.IM2
    with pytest.raises(TypeError):
        result.dimension_levels[0] = (Dimension.GRAMMAR, ActflLevel.AL)


def test_results_break_down_by_question_type():
    bp = (
        slot(0, QuestionType.DESCRIPTION, "movies"),
        slot(1, QuestionType.HABIT, "movies"),
    )
    assessments = [
        assessment(0, flat(ActflLevel.IH)),
        assessment(1, flat(ActflLevel.IL)),
    ]
    by_type = dict(aggregate(bp, assessments).by_type)
    assert by_type[QuestionType.DESCRIPTION] is ActflLevel.IH
    assert by_type[QuestionType.HABIT] is ActflLevel.IL


def test_results_break_down_by_topic():
    bp = (
        slot(0, QuestionType.DESCRIPTION, "movies"),
        slot(1, QuestionType.DESCRIPTION, "yoga"),
    )
    assessments = [
        assessment(0, flat(ActflLevel.IH)),
        assessment(1, flat(ActflLevel.IL)),
    ]
    by_topic = dict(aggregate(bp, assessments).by_topic)
    assert by_topic["movies"] is ActflLevel.IH
    assert by_topic["yoga"] is ActflLevel.IL


def test_a_strong_advanced_combo_raises_the_final_level():
    bp = (
        slot(0, QuestionType.DESCRIPTION, "movies"),
        slot(1, QuestionType.DESCRIPTION, "yoga", advanced=True),
    )
    assessments = [
        assessment(0, flat(ActflLevel.IM2)),
        assessment(1, flat(ActflLevel.AL)),
    ]
    plain = aggregate(
        (slot(0, QuestionType.DESCRIPTION, "movies"), slot(1, QuestionType.DESCRIPTION, "yoga")),
        assessments,
    )
    raised = aggregate(bp, assessments)
    assert raised.final_level.rank == plain.final_level.rank + 1


def test_a_weak_advanced_combo_does_not_lower_the_final_level():
    bp = (
        slot(0, QuestionType.DESCRIPTION, "movies"),
        slot(1, QuestionType.DESCRIPTION, "yoga", advanced=True),
    )
    assessments = [
        assessment(0, flat(ActflLevel.IH)),
        assessment(1, flat(ActflLevel.NL)),
    ]
    plain = aggregate(
        (slot(0, QuestionType.DESCRIPTION, "movies"), slot(1, QuestionType.DESCRIPTION, "yoga")),
        assessments,
    )
    assert aggregate(bp, assessments).final_level is plain.final_level


def test_an_assessment_without_a_matching_slot_is_refused():
    with pytest.raises(ValueError):
        aggregate(blueprint_of(1), [assessment(0, flat(ActflLevel.IM2)), assessment(5, flat(ActflLevel.IM2))])


def test_a_slot_with_no_assessment_is_refused():
    with pytest.raises(ValueError):
        aggregate(blueprint_of(3), [assessment(0, flat(ActflLevel.IM2))])


def test_a_breakdown_agrees_with_the_headline_level():
    levels = flat(ActflLevel.AL)
    levels[Dimension.GRAMMAR] = ActflLevel.IM1
    bp = tuple(slot(i, QuestionType.DESCRIPTION, "movies") for i in range(3))
    result = aggregate(bp, [assessment(i, levels) for i in range(3)])
    assert dict(result.by_type)[QuestionType.DESCRIPTION] is result.final_level
    assert dict(result.by_topic)["movies"] is result.final_level


def test_a_strong_advanced_answer_cannot_cancel_the_weak_dimension_cap():
    levels = flat(ActflLevel.AL)
    levels[Dimension.GRAMMAR] = ActflLevel.IM1
    assessments = [assessment(i, levels) for i in range(3)]
    without = aggregate(
        tuple(slot(i, QuestionType.DESCRIPTION, "movies") for i in range(3)),
        assessments,
    )
    with_advanced = aggregate(
        (
            slot(0, QuestionType.DESCRIPTION, "movies"),
            slot(1, QuestionType.DESCRIPTION, "movies"),
            slot(2, QuestionType.DESCRIPTION, "movies", advanced=True),
        ),
        assessments,
    )
    assert with_advanced.final_level is without.final_level


def test_by_topic_follows_blueprint_order_not_assessment_order():
    bp = (
        slot(0, QuestionType.DESCRIPTION, "movies"),
        slot(1, QuestionType.DESCRIPTION, "yoga"),
        slot(2, QuestionType.DESCRIPTION, "camping"),
    )
    assessments = [
        assessment(2, flat(ActflLevel.IM2)),
        assessment(0, flat(ActflLevel.IM2)),
        assessment(1, flat(ActflLevel.IM2)),
    ]
    topics = [topic for topic, _ in aggregate(bp, assessments).by_topic]
    assert topics == ["movies", "yoga", "camping"]
