from __future__ import annotations

import pytest

from opic.core.questions import Question, QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import (
    AnswerAssessment,
    DimensionScore,
    aggregate,
    dimension_level,
)

from core.helpers import assessment, blueprint_of, flat, metrics, slot, transcript_for


def test_dimension_level_takes_the_median_across_answers():
    assessments = [
        assessment(0, flat(ActflLevel.IL)),
        assessment(1, flat(ActflLevel.IM2)),
        assessment(2, flat(ActflLevel.IM3)),
    ]
    assert dimension_level(assessments, Dimension.GRAMMAR) is ActflLevel.IM2


def test_an_even_count_takes_the_midpoint_of_the_two_middles():
    assessments = [
        assessment(0, flat(ActflLevel.IL)),
        assessment(1, flat(ActflLevel.IM2)),
    ]
    assert dimension_level(assessments, Dimension.GRAMMAR) is ActflLevel.IM1


def test_an_even_count_with_adjacent_middles_rounds_the_tie_up():
    assessments = [
        assessment(0, flat(ActflLevel.IL)),
        assessment(1, flat(ActflLevel.IM1)),
    ]
    assert dimension_level(assessments, Dimension.GRAMMAR) is ActflLevel.IM1


def test_a_weighted_mean_just_below_a_band_rounds_up_to_it():
    """The bias this exists to catch cost two real exams a whole band.

    Fluency IM1, grammar IM1, vocabulary IM2, coherence IM2, relevance IH are
    the per-dimension medians of `data/sessions/20260821-140338`. They weigh to
    4.85 — five sixths of the way from IM1 to IM2 — which `math.floor` reported
    as IM1.
    """
    levels = {
        Dimension.FLUENCY: ActflLevel.IM1,
        Dimension.GRAMMAR: ActflLevel.IM1,
        Dimension.VOCABULARY: ActflLevel.IM2,
        Dimension.COHERENCE: ActflLevel.IM2,
        Dimension.RELEVANCE: ActflLevel.IH,
    }
    result = aggregate(blueprint_of(3), [assessment(i, levels) for i in range(3)])
    assert result.final_level is ActflLevel.IM2


def test_a_weighted_mean_just_above_a_band_stays_on_it():
    """The counterpart: rounding up is nearest-band, not a free promotion."""
    levels = {
        Dimension.FLUENCY: ActflLevel.IM1,
        Dimension.GRAMMAR: ActflLevel.IM1,
        Dimension.VOCABULARY: ActflLevel.IM2,
        Dimension.COHERENCE: ActflLevel.IM1,
        Dimension.RELEVANCE: ActflLevel.IM2,
    }
    result = aggregate(blueprint_of(3), [assessment(i, levels) for i in range(3)])
    assert result.final_level is ActflLevel.IM1


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
        question=Question(
            slot=slot(0, QuestionType.DESCRIPTION, "movies"),
            text_en="Tell me about that.",
        ),
        transcript=transcript_for(),
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


def test_an_assessment_knows_its_question_and_what_was_said():
    a = assessment(3, flat(ActflLevel.IM2))
    assert a.question_index == 3
    assert a.question.text_en.endswith("?") or a.question.text_en.endswith(".")
    assert "beach" in a.transcript.text


def test_question_index_follows_the_question_and_cannot_drift():
    a = assessment(3, flat(ActflLevel.IM2))
    assert a.question_index == a.question.slot.index
    with pytest.raises(Exception):
        a.question_index = 9


from opic.core.scoring import limiting_dimension


def test_no_limiting_dimension_when_the_cap_did_not_fire():
    level = {d: ActflLevel.IM2 for d in Dimension}
    assessments = [assessment(i, level) for i in range(3)]
    assert limiting_dimension(blueprint_of(3), assessments) is None


def test_the_limiting_dimension_is_the_weak_one_and_reports_the_uncapped_level():
    level = {d: ActflLevel.IH for d in Dimension}
    level[Dimension.GRAMMAR] = ActflLevel.NH
    assessments = [assessment(i, level) for i in range(3)]

    limiting = limiting_dimension(blueprint_of(3), assessments)

    assert limiting is not None
    dimension, without_cap = limiting
    assert dimension is Dimension.GRAMMAR
    assert without_cap.rank > aggregate(blueprint_of(3), assessments).final_level.rank


def test_a_tie_for_weakest_resolves_in_dimension_declaration_order():
    level = {d: ActflLevel.IH for d in Dimension}
    level[Dimension.GRAMMAR] = ActflLevel.NH
    level[Dimension.VOCABULARY] = ActflLevel.NH
    assessments = [assessment(i, level) for i in range(3)]

    dimension, _ = limiting_dimension(blueprint_of(3), assessments)

    assert dimension is Dimension.GRAMMAR
