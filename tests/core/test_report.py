from __future__ import annotations

from opic.core.questions import QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.report import build_report
from opic.core.scoring import AnswerAssessment, DimensionScore, aggregate
from opic.core.transcript import Span, Transcript, Word

from core.helpers import assessment, blueprint_of, metrics, slot


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
    # GRAMMAR, VOCABULARY, COHERENCE are all tied at weight 0.20; the sort
    # must be stable and keep them in Dimension declaration order.
    assert [d.dimension for d in report.dimensions] == [
        Dimension.FLUENCY,
        Dimension.GRAMMAR,
        Dimension.VOCABULARY,
        Dimension.COHERENCE,
        Dimension.RELEVANCE,
    ]


def test_no_limiting_dimension_when_the_cap_did_not_fire():
    assert report_of(3).limiting is None


def test_the_limiting_dimension_is_named_in_korean():
    level = {d: ActflLevel.IH for d in Dimension}
    level[Dimension.GRAMMAR] = ActflLevel.NH
    report = report_of(3, level)
    assert report.limiting is not None
    assert report.limiting.label_ko == "문법"
    assert report.limiting.without_cap.rank > report.final_level.rank


def transcript_with_a_mumble() -> Transcript:
    spoken = "I went to the beach and we take a bath there last summer".split()
    words = []
    for i, text in enumerate(spoken):
        probability = 0.4 if text == "bath" else 0.95
        words.append(Word(text, i * 0.4, i * 0.4 + 0.3, probability))
    return Transcript(
        text=" ".join(spoken),
        words=tuple(words),
        speech_spans=(Span(0.0, len(spoken) * 0.4),),
        duration_s=30.0,
    )


def mumbled_assessment(index: int) -> AnswerAssessment:
    level = {d: ActflLevel.IM2 for d in Dimension}
    return AnswerAssessment(
        question=questions_of(index + 1)[index],
        transcript=transcript_with_a_mumble(),
        dimension_scores=tuple(
            DimensionScore(dimension=d, level=level[d], comment_ko="괜찮습니다", evidence=())
            for d in Dimension
        ),
        metrics=metrics(),
    )


def test_unclear_words_are_listed_with_their_context_and_answer():
    assessments = [mumbled_assessment(0)]
    result = aggregate(blueprint_of(1), assessments)

    report = build_report(result, questions_of(1))

    assert [w.text for w in report.unclear] == ["bath"]
    assert report.unclear[0].answer_index == 0
    assert "we take a bath there last" in report.unclear[0].context


def test_no_unclear_words_gives_an_empty_tuple_not_a_placeholder():
    assert report_of(3).unclear == ()
