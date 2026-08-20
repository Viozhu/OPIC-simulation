from __future__ import annotations

from opic.core.questions import Question, QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.report import build_report, render_text
from opic.core.scoring import AnswerAssessment, DimensionScore, Evidence, aggregate
from opic.core.transcript import Span, Transcript, Word

from core.helpers import assessment, blueprint_of, metrics, slot, transcript_for


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


def transcript_with_marked_word(marker: str, word: str, probability: float) -> Transcript:
    spoken = f"{marker} one {word} {marker} two".split()
    words = tuple(
        Word(w, i * 0.4, i * 0.4 + 0.3, probability if w == word else 0.95)
        for i, w in enumerate(spoken)
    )
    return Transcript(
        text=" ".join(spoken),
        words=words,
        speech_spans=(Span(0.0, len(spoken) * 0.4),),
        duration_s=30.0,
    )


def assessment_with_word(index: int, marker: str, word: str, probability: float) -> AnswerAssessment:
    level = {d: ActflLevel.IM2 for d in Dimension}
    return AnswerAssessment(
        question=questions_of(index + 1)[index],
        transcript=transcript_with_marked_word(marker, word, probability),
        dimension_scores=tuple(
            DimensionScore(dimension=d, level=level[d], comment_ko="괜찮습니다", evidence=())
            for d in Dimension
        ),
        metrics=metrics(),
    )


def test_the_same_word_across_answers_collapses_to_its_worst_appearance():
    # "and" shows up unclear in three different answers, at three different
    # probabilities. It must appear on the report exactly once, carrying the
    # lowest-probability appearance's own context and answer_index — not the
    # first one seen, not an average.
    assessments = [
        assessment_with_word(0, "alpha", "and", 0.5),
        assessment_with_word(1, "beta", "and", 0.2),
        assessment_with_word(2, "gamma", "and", 0.4),
    ]
    result = aggregate(blueprint_of(3), assessments)

    report = build_report(result, questions_of(3))

    assert [w.text for w in report.unclear] == ["and"]
    assert report.unclear[0].probability == 0.2
    assert report.unclear[0].answer_index == 1
    assert "beta" in report.unclear[0].context


def transcript_with_many_unclear_words(count: int) -> Transcript:
    words = tuple(
        Word(f"word{i}", i * 0.4, i * 0.4 + 0.3, 0.1 + i * 0.01) for i in range(count)
    )
    return Transcript(
        text=" ".join(w.text for w in words),
        words=words,
        speech_spans=(Span(0.0, count * 0.4),),
        duration_s=30.0,
    )


def test_more_than_ten_distinct_unclear_words_is_capped_at_the_ten_lowest():
    level = {d: ActflLevel.IM2 for d in Dimension}
    assessment_ = AnswerAssessment(
        question=questions_of(1)[0],
        transcript=transcript_with_many_unclear_words(15),
        dimension_scores=tuple(
            DimensionScore(dimension=d, level=level[d], comment_ko="설명", evidence=())
            for d in Dimension
        ),
        metrics=metrics(),
    )
    result = aggregate(blueprint_of(1), [assessment_])

    report = build_report(result, questions_of(1))

    assert len(report.unclear) == 10
    probabilities = [w.probability for w in report.unclear]
    assert probabilities == sorted(probabilities)
    assert probabilities == [0.1 + i * 0.01 for i in range(10)]


def test_breakdowns_carry_korean_labels():
    report = report_of(3)
    assert report.by_type[0][1] == "묘사"
    assert report.by_topic[0][0] == "movies"
    assert report.by_topic[0][1] == "영화보기"


def test_averages_are_the_mean_of_the_shown_metrics():
    report = report_of(3)
    assert report.averages is not None
    assert report.averages.words_per_minute == 120.0
    assert not hasattr(report.averages, "type_token_ratio")


def test_every_question_appears_even_when_it_was_not_scored():
    level = {d: ActflLevel.IM2 for d in Dimension}
    assessments = [assessment(i, level) for i in range(2)]
    result = aggregate(blueprint_of(2), assessments)

    report = build_report(result, questions_of(3))

    assert [a.index for a in report.answers] == [0, 1, 2]
    assert report.answers[2].state == "not_scored"
    assert report.answers[2].metrics is None
    assert report.answers[2].scores == ()


def test_an_unreadable_answer_is_marked_apart_from_a_missing_one():
    level = {d: ActflLevel.IM2 for d in Dimension}
    assessments = [assessment(i, level) for i in range(2)]
    result = aggregate(blueprint_of(2), assessments)

    report = build_report(result, questions_of(3), unreadable=[2])

    assert report.answers[2].state == "unreadable"


def test_a_scored_answer_carries_its_comment_and_its_question():
    report = report_of(1)
    detail = report.answers[0]
    assert detail.state == "scored"
    assert detail.question_en == "Question 0"
    assert detail.qtype_label_ko == "묘사"
    assert detail.scores[0].comment_ko


def test_the_text_report_names_every_section_and_the_level():
    text = render_text(report_of(3))
    assert "최종 등급: IM2" in text
    assert "왜 이 등급인가" in text
    assert "유창성" in text
    assert "유형별" in text
    assert "답변별 상세" in text


def test_the_text_report_says_when_everything_was_understood():
    assert "또렷하게 인식되지 않은 단어는 없습니다" in render_text(report_of(3))


def test_the_text_report_explains_the_cap_when_it_fired():
    level = {d: ActflLevel.IH for d in Dimension}
    level[Dimension.GRAMMAR] = ActflLevel.NH
    assert "문법" in render_text(report_of(3, level))


def _assessment_with_fluency_evidence(index: int, quote_count: int) -> AnswerAssessment:
    """An assessment whose FLUENCY score carries `quote_count` real Evidence items.

    Every other dimension gets no evidence, so the cap behaviour under test
    is isolated to FLUENCY.
    """
    level = {d: ActflLevel.IM2 for d in Dimension}
    letters = "abcdefgh"
    fluency_evidence = tuple(
        Evidence(
            quote=f"quote {index}{letters[n]}",
            issue_ko="설명",
            correction_en=f"correction {letters[n]}",
        )
        for n in range(quote_count)
    )
    return AnswerAssessment(
        question=Question(
            slot=slot(index, QuestionType.DESCRIPTION, "movies"),
            text_en="Tell me about the last movie you saw.",
        ),
        transcript=transcript_for(),
        dimension_scores=tuple(
            DimensionScore(
                dimension=dimension,
                level=level[dimension],
                comment_ko="설명",
                evidence=fluency_evidence if dimension is Dimension.FLUENCY else (),
            )
            for dimension in Dimension
        ),
        metrics=metrics(),
    )


def test_exam_level_evidence_is_capped_and_spread_across_answers():
    from opic.core.report import EXAM_EVIDENCE_PER_DIMENSION

    assessments = [_assessment_with_fluency_evidence(i, 2) for i in range(6)]
    result = aggregate(blueprint_of(6), assessments)

    report = build_report(result, questions_of(6))
    fluency = next(d for d in report.dimensions if d.dimension is Dimension.FLUENCY)

    assert len(fluency.evidence) == EXAM_EVIDENCE_PER_DIMENSION
    assert len({e.answer_index for e in fluency.evidence}) == EXAM_EVIDENCE_PER_DIMENSION


def test_the_fallback_pass_draws_a_second_quote_from_an_earlier_answer():
    """When the first pass (one quote per answer) can't fill the cap, a
    second quote is drawn from an already-used answer — the earliest one
    that still has quotes left, in ascending order.
    """
    from opic.core.report import EXAM_EVIDENCE_PER_DIMENSION

    assert EXAM_EVIDENCE_PER_DIMENSION == 3
    assessments = [
        _assessment_with_fluency_evidence(0, 3),
        _assessment_with_fluency_evidence(1, 1),
    ]
    result = aggregate(blueprint_of(2), assessments)

    report = build_report(result, questions_of(2))
    fluency = next(d for d in report.dimensions if d.dimension is Dimension.FLUENCY)

    assert len(fluency.evidence) == EXAM_EVIDENCE_PER_DIMENSION
    first, second, third = fluency.evidence
    assert {first.answer_index, second.answer_index} == {0, 1}
    assert first.answer_index != second.answer_index
    assert third.answer_index == 0
    assert third.quote == "quote 0b"


def test_the_text_report_shows_per_answer_evidence():
    # done.js already prints every Evidence under a per-answer dimension
    # (quote / issue_ko / -> correction_en); render_text must show the same
    # thing, not stop at the level and comment.
    assessments = [_assessment_with_fluency_evidence(0, 2)]
    result = aggregate(blueprint_of(1), assessments)
    report = build_report(result, questions_of(1))

    text = render_text(report)

    assert "quote 0a" in text
    assert "설명" in text
    assert "correction a" in text


def test_the_text_report_shows_the_topic_next_to_the_type():
    text = render_text(report_of(1))
    assert "영화보기" in text


def test_the_topic_label_is_omitted_cleanly_when_there_is_none():
    level = {d: ActflLevel.IM2 for d in Dimension}
    question = Question(
        slot=slot(0, QuestionType.SELF_INTRO, None), text_en="Tell me about yourself."
    )
    an_answer = AnswerAssessment(
        question=question,
        transcript=transcript_for(),
        dimension_scores=tuple(
            DimensionScore(dimension=d, level=level[d], comment_ko="설명", evidence=())
            for d in Dimension
        ),
        metrics=metrics(),
    )
    result = aggregate((question.slot,), [an_answer])
    report = build_report(result, [question])

    assert report.answers[0].topic_label_ko is None
    assert "None" not in render_text(report)


def test_the_text_report_shows_all_five_metrics_against_the_average():
    from opic.core.report import METRIC_LABELS_KO

    text = render_text(report_of(2))

    for label in METRIC_LABELS_KO.values():
        assert label in text
    assert "평균" in text


def test_format_metrics_gives_every_field_a_unit_python_and_js_both_use():
    """The one place formatting is decided (residual finding: done.js used to
    keep its own copy of these units, which is how word_count and
    mean_utterance_length drifted between the CLI and the browser).
    `report_json` serialises this same dict, so a unit added here reaches
    both renderers without done.js deciding anything.
    """
    from opic.core.report import format_metrics

    display = format_metrics(report_of(2).averages)

    assert display["duration_s"].endswith("초")
    assert display["word_count"].endswith("개")
    assert display["words_per_minute"].endswith("단어/분")
    assert display["pause_ratio"].endswith("%")
    assert display["mean_utterance_length"].endswith("단어")


def test_state_label_ko_is_set_for_unscored_answers_and_empty_for_scored_ones():
    assessments = [assessment(0, {d: ActflLevel.IM2 for d in Dimension})]
    result = aggregate(blueprint_of(1), assessments)

    report = build_report(result, questions_of(3), unreadable=[2])

    assert report.answers[0].state_label_ko == ""
    assert report.answers[1].state_label_ko == "채점하지 못한 답변"
    assert report.answers[2].state_label_ko == "읽을 수 없는 파일"


def test_the_text_report_uses_the_state_label_for_an_unscored_answer():
    assessments = [assessment(0, {d: ActflLevel.IM2 for d in Dimension})]
    result = aggregate(blueprint_of(1), assessments)

    report = build_report(result, questions_of(2))

    assert "채점하지 못한 답변" in render_text(report)


def test_fewer_quotes_than_the_cap_are_all_kept():
    from opic.core.report import EXAM_EVIDENCE_PER_DIMENSION

    assessments = [
        _assessment_with_fluency_evidence(0, 2),
        _assessment_with_fluency_evidence(1, 0),
    ]
    result = aggregate(blueprint_of(2), assessments)

    report = build_report(result, questions_of(2))
    fluency = next(d for d in report.dimensions if d.dimension is Dimension.FLUENCY)

    assert len(fluency.evidence) == 2
    assert len(fluency.evidence) < EXAM_EVIDENCE_PER_DIMENSION
    assert {e.quote for e in fluency.evidence} == {"quote 0a", "quote 0b"}
    assert all(e.answer_index == 0 for e in fluency.evidence)
