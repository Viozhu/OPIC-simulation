from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.report import build_report
from opic.core.rubric import DIMENSION_LABELS_KO, ActflLevel, Dimension
from opic.core.scoring import AnswerAssessment, DimensionScore, Evidence, aggregate
from opic.core.transcript import Span, Transcript, Word
from opic.session import assessments as sut
from opic.session.state import AnswerRecord, AnswerState, QuestionRecord, SessionState, Step


def a_record(index: int, advanced: bool = False) -> QuestionRecord:
    return QuestionRecord(
        index=index,
        qtype=QuestionType.DESCRIPTION.value,
        topic_id="movies",
        combo_id=0,
        advanced=advanced,
        target="IM1",
        text_en=f"Question {index}.",
        audio_path="/cache/a.wav",
    )


def an_assessment(index: int) -> AnswerAssessment:
    transcript = Transcript(
        text="I like films",
        words=(
            Word("I", 0.0, 0.2, 0.9),
            Word("like", 0.2, 0.5, 0.8),
            Word("films", 0.5, 0.9, 0.7),
        ),
        speech_spans=(Span(0.0, 0.9),),
        duration_s=1.0,
    )
    return AnswerAssessment(
        question=sut.question_from_record(a_record(index)),
        transcript=transcript,
        dimension_scores=tuple(
            DimensionScore(
                dimension=dimension,
                level=ActflLevel.IM1,
                comment_ko="문장이 짧습니다.",
                evidence=(Evidence("I like films", "너무 짧다", "I really enjoy films."),),
            )
            for dimension in Dimension
        ),
        metrics=AnswerMetrics(
            duration_s=1.0,
            word_count=3,
            words_per_minute=180.0,
            pause_ratio=0.1,
            type_token_ratio=1.0,
            mean_utterance_length=3.0,
            mean_confidence=0.8,
            low_confidence_rate=0.0,
        ),
    )


def a_state(questions: tuple[QuestionRecord, ...], scored: set[int]) -> SessionState:
    """A session whose questions exist, with the given indices SCORED and
    every other index left PENDING."""
    answers = tuple(
        AnswerRecord(
            index=q.index,
            state=AnswerState.SCORED if q.index in scored else AnswerState.PENDING,
        )
        for q in questions
    )
    return SessionState(
        id="s",
        created_at=datetime(2026, 8, 19, 14, 30, 52),
        step=Step.GRADING,
        seed=1,
        survey=None,
        candidate=None,
        self_assess_level=4,
        questions=questions,
        answers=answers,
    )


def test_a_record_becomes_the_question_core_expects():
    question = sut.question_from_record(a_record(2))
    assert isinstance(question, Question)
    assert question.slot == QuestionSlot(
        index=2,
        qtype=QuestionType.DESCRIPTION,
        topic_id="movies",
        combo_id=0,
        advanced=False,
        target=ActflLevel.IM1,
    )
    assert question.text_en == "Question 2."


def test_an_assessment_survives_the_round_trip(tmp_path: Path):
    sut.write_answer(tmp_path, "s", an_assessment(0))
    loaded = sut.read_answer(tmp_path, "s", 0)
    assert loaded == an_assessment(0)


def test_the_saved_file_is_readable_by_a_human(tmp_path: Path):
    sut.write_answer(tmp_path, "s", an_assessment(0))
    payload = json.loads((tmp_path / "s" / "answer-00.json").read_text(encoding="utf-8"))
    assert payload["question_en"] == "Question 0."
    assert payload["transcript"]["text"] == "I like films"
    assert payload["scores"][0]["comment_ko"] == "문장이 짧습니다."


def test_reading_them_all_skips_answers_not_yet_scored(tmp_path: Path):
    questions = (a_record(0), a_record(1))
    sut.write_answer(tmp_path, "s", an_assessment(0))
    state = a_state(questions, scored={0})
    loaded = sut.read_all_answers(tmp_path, "s", state)
    assert [a.question_index for a in loaded] == [0]


def test_reading_them_all_ignores_stale_files_from_a_previous_run(tmp_path: Path):
    """A second exam into the same directory overwrites `session.json` but
    leaves the previous run's `answer-NN.json` files on disk. Selection has to
    go by the CURRENT state (SCORED), not by which files happen to exist —
    otherwise a fresh exam whose rater failed every call would silently pick
    up the previous exam's answers and report ITS level instead.
    """
    questions = (a_record(0), a_record(1), a_record(2))
    for record in questions:
        sut.write_answer(tmp_path, "s", an_assessment(record.index))

    # Every answer in THIS run failed, even though their files still exist
    # from a previous run.
    state = a_state(questions, scored=set())
    loaded = sut.read_all_answers(tmp_path, "s", state)
    assert loaded == ()


def test_stale_answer_files_do_not_survive_into_a_new_aggregate(tmp_path: Path):
    """Same scenario, run through the exact path `_aggregate` and `run_exam`
    use: write the files, mark every answer FAILED, then aggregate. It must
    not produce a level from the stale files — aggregating zero answers is an
    error, not a grade.
    """
    questions = (a_record(0), a_record(1), a_record(2))
    for record in questions:
        sut.write_answer(tmp_path, "s", an_assessment(record.index))

    state = a_state(questions, scored=set())
    judged = sut.read_all_answers(tmp_path, "s", state)
    with pytest.raises(ValueError):
        sut.aggregate_available(questions, judged)


def test_aggregating_uses_only_the_answers_that_exist():
    questions = (a_record(0), a_record(1), a_record(2))
    result = sut.aggregate_available(questions, [an_assessment(0), an_assessment(2)])
    assert [a.question_index for a in result.assessments] == [0, 2]
    assert result.final_level is ActflLevel.IM1


def test_aggregating_nothing_is_an_error():
    with pytest.raises(ValueError):
        sut.aggregate_available((a_record(0),), [])


def test_the_result_declares_how_many_answers_it_used():
    questions = (a_record(0), a_record(1), a_record(2))
    result = sut.aggregate_available(questions, [an_assessment(0), an_assessment(2)])
    payload = sut.result_json(result, expected=len(questions))
    assert payload["scored_answers"] == 2
    assert payload["expected_answers"] == 3
    assert payload["final_level"] == "IM1"
    assert payload["answers"][0]["question_en"] == "Question 0."


def test_every_dimension_in_the_result_carries_a_korean_label():
    questions = (a_record(0),)
    result = sut.aggregate_available(questions, [an_assessment(0)])
    payload = sut.result_json(result, expected=len(questions))
    assert set(payload["dimensions"]) == {d.value for d in Dimension}
    for dimension in Dimension:
        entry = payload["dimensions"][dimension.value]
        assert entry["label_ko"] == DIMENSION_LABELS_KO[dimension]
        assert entry["label_ko"]


def an_assessment_with_levels(index: int, levels: dict[Dimension, ActflLevel]) -> AnswerAssessment:
    """Like `an_assessment`, but with a controllable level per dimension so
    the weak-dimension cap (and therefore `Report.limiting`) can be made to
    fire on demand."""
    transcript = Transcript(
        text="I like films",
        words=(
            Word("I", 0.0, 0.2, 0.9),
            Word("like", 0.2, 0.5, 0.8),
            Word("films", 0.5, 0.9, 0.7),
        ),
        speech_spans=(Span(0.0, 0.9),),
        duration_s=1.0,
    )
    return AnswerAssessment(
        question=sut.question_from_record(a_record(index)),
        transcript=transcript,
        dimension_scores=tuple(
            DimensionScore(
                dimension=dimension,
                level=levels[dimension],
                comment_ko="문장이 짧습니다.",
                evidence=(Evidence("I like films", "너무 짧다", "I really enjoy films."),),
            )
            for dimension in Dimension
        ),
        metrics=AnswerMetrics(
            duration_s=1.0,
            word_count=3,
            words_per_minute=180.0,
            pause_ratio=0.1,
            type_token_ratio=1.0,
            mean_utterance_length=3.0,
            mean_confidence=0.8,
            low_confidence_rate=0.0,
        ),
    )


def test_report_json_carries_every_key_done_js_reads():
    """`FakeRater` (used by the `/report` route's own test fixture) gives
    every dimension the same level, so the weak-dimension cap — and
    `report_json`'s `limiting` branch — can never fire there. Build a
    `Report` whose cap genuinely fires here instead, so a rename of any key
    below (in particular `limiting.without_cap`) is caught by a test rather
    than by a candidate reading `그 제한이 없었다면 undefined입니다` in the
    browser.
    """
    levels = {d: ActflLevel.IH for d in Dimension}
    levels[Dimension.GRAMMAR] = ActflLevel.NH
    questions = tuple(a_record(i) for i in range(3))
    blueprint = tuple(sut.question_from_record(q).slot for q in questions)
    assessments = [an_assessment_with_levels(i, levels) for i in range(3)]
    result = aggregate(blueprint, assessments)
    report_questions = [sut.question_from_record(q) for q in questions]
    report = build_report(result, report_questions)
    assert report.limiting is not None  # the branch this test exists to cover

    payload = sut.report_json(report)

    assert {"final_level", "scored_answers", "expected_answers", "limiting", "dimensions",
            "unclear", "by_type", "by_topic", "averages", "answers", "scale"} <= payload.keys()

    # done.js draws the ladder straight from this list and marks nothing
    # itself, so the order and the flag have to survive serialisation.
    assert [rung["level"] for rung in payload["scale"]] == [
        level.name for level in sorted(ActflLevel, key=lambda band: -band.rank)
    ]
    assert [rung["level"] for rung in payload["scale"] if rung["is_final"]] == [
        report.final_level.name
    ]
    assert any(rung["dimensions"] for rung in payload["scale"])
    for rung in payload["scale"]:
        assert {"level", "is_final", "dimensions"} <= rung.keys()

    assert {"dimension", "label_ko", "level", "without_cap"} <= payload["limiting"].keys()

    assert payload["dimensions"]
    for dimension in payload["dimensions"]:
        assert {"dimension", "label_ko", "weight", "level", "evidence"} <= dimension.keys()
        for evidence in dimension["evidence"]:
            assert {"quote", "issue_ko", "correction_en", "answer_index"} <= evidence.keys()

    for word in payload["unclear"]:
        assert {"text", "probability", "context", "answer_index"} <= word.keys()

    for entry in payload["by_type"]:
        assert {"id", "label_ko", "level"} <= entry.keys()
    for entry in payload["by_topic"]:
        assert {"id", "label_ko", "level"} <= entry.keys()

    assert {"duration_s", "word_count", "words_per_minute", "pause_ratio",
            "mean_utterance_length"} <= payload["averages"].keys()

    assert payload["answers"]
    for answer in payload["answers"]:
        assert {"index", "question_en", "qtype_label_ko", "topic_label_ko", "state",
                "transcript_text", "metrics", "scores"} <= answer.keys()
        for score in answer["scores"]:
            assert {"dimension", "label_ko", "level", "comment_ko",
                    "evidence"} <= score.keys()


def test_report_json_serves_metrics_already_formatted_for_display():
    """done.js must not decide how a metric looks — that drifted before
    (word_count and mean_utterance_length lost their units in the browser
    while the CLI kept them). report_json now carries the formatted string
    alongside the raw number, for both an answer's metrics and the exam
    average, so the browser only has to print what Python already built.
    """
    questions = (a_record(0),)
    result = sut.aggregate_available(questions, [an_assessment(0)])
    report = build_report(result, [sut.question_from_record(q) for q in questions])

    payload = sut.report_json(report)

    assert payload["averages_display"]["word_count"].endswith("개")
    assert payload["averages_display"]["mean_utterance_length"].endswith("단어")
    assert payload["averages_display"]["words_per_minute"].endswith("단어/분")
    scored = next(a for a in payload["answers"] if a["state"] == "scored")
    assert scored["metrics_display"]["word_count"].endswith("개")
    assert scored["metrics_display"]["mean_utterance_length"].endswith("단어")
    # the raw numbers are still there too — nothing was removed, only added
    assert isinstance(scored["metrics"]["word_count"], (int, float))


def test_a_schema_mismatched_answer_is_reported_unreadable_not_raised(
    tmp_path: Path, capsys
):
    """An `answer-NN.json` from an older schema is syntactically valid JSON
    but carries an enum value `QuestionType` no longer recognises.
    `_answer_from_json` raises `ValueError` on that — a plain
    `(OSError, json.JSONDecodeError)` catch would let it escape and 500 the
    whole `/report` route. It must be skipped and marked unreadable like any
    other broken file, and the failure must not be swallowed silently: the
    traceback goes to the server console.
    """
    questions = (a_record(0),)
    sut.write_answer(tmp_path, "s", an_assessment(0))
    path = tmp_path / "s" / "answer-00.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["slot"]["qtype"] = "no-longer-a-real-question-type"
    path.write_text(json.dumps(payload), encoding="utf-8")

    state = a_state(questions, scored={0})
    found, broken = sut.read_answers_tolerantly(tmp_path, "s", state)

    assert found == ()
    assert broken == (0,)
    assert "ValueError" in capsys.readouterr().err


def test_an_answer_missing_a_metrics_field_is_reported_unreadable_not_raised(
    tmp_path: Path, capsys
):
    """An `answer-NN.json` from before `mean_utterance_length` existed is
    syntactically valid JSON but its `metrics` object is missing that key.
    `_answer_from_json` does `AnswerMetrics(**metrics)`, which raises
    `TypeError` on a missing keyword argument — a different exception than
    the bad-enum case above, and one a plain
    `(OSError, json.JSONDecodeError, KeyError, ValueError)` catch would still
    let escape and 500 the whole `/report` route.
    """
    questions = (a_record(0),)
    sut.write_answer(tmp_path, "s", an_assessment(0))
    path = tmp_path / "s" / "answer-00.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["metrics"]["mean_utterance_length"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    state = a_state(questions, scored={0})
    found, broken = sut.read_answers_tolerantly(tmp_path, "s", state)

    assert found == ()
    assert broken == (0,)
    assert "TypeError" in capsys.readouterr().err
