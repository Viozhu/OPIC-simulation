from __future__ import annotations

import json
from pathlib import Path

import pytest

from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import AnswerAssessment, DimensionScore, Evidence
from opic.core.transcript import Span, Transcript, Word
from opic.session import assessments as sut
from opic.session.state import QuestionRecord


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


def test_reading_them_all_skips_the_ones_not_written_yet(tmp_path: Path):
    questions = (a_record(0), a_record(1))
    sut.write_answer(tmp_path, "s", an_assessment(0))
    loaded = sut.read_all_answers(tmp_path, "s", questions)
    assert [a.question_index for a in loaded] == [0]


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
