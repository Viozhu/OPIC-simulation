from __future__ import annotations

from datetime import datetime

import pytest

from opic.core.candidate import Candidate
from opic.core.questions import QuestionType
from opic.core.survey import Housing, Occupation, RecentCourse, SurveyAnswers
from opic.session.state import (
    AnswerRecord,
    AnswerState,
    QuestionRecord,
    SessionState,
    Step,
    TransitionError,
    advance,
)


def a_survey() -> SurveyAnswers:
    return SurveyAnswers(
        occupation=Occupation.BUSINESS,
        is_student=False,
        housing=Housing.ALONE,
        selected_item_ids=("movies",),
        recent_course=RecentCourse.LANGUAGE,
    )


_CREATED_AT = datetime(2026, 8, 19, 14, 30, 52)


def an_identified_session(session_id: str) -> SessionState:
    """A session already past IDENTITY, ready for the survey transitions below."""
    state = SessionState.new(session_id, seed=7, created_at=_CREATED_AT)
    state = state.with_candidate(Candidate("김민준", "minjun@example.com"))
    return advance(state, Step.SURVEY)


def test_a_new_session_starts_at_the_survey():
    state = an_identified_session("20260819-143052")
    assert state.step is Step.SURVEY
    assert state.survey is None
    assert state.questions == ()
    assert state.answers == ()


def test_legal_transitions_move_the_step():
    state = an_identified_session("s")
    for step in (Step.LEVEL, Step.SETUP, Step.SAMPLE, Step.TEST, Step.GRADING, Step.DONE):
        state = advance(state, step)
    assert state.step is Step.DONE


def test_skipping_a_step_is_rejected():
    state = SessionState.new("s", seed=7, created_at=_CREATED_AT)
    with pytest.raises(TransitionError) as excinfo:
        advance(state, Step.TEST)
    assert "survey" in str(excinfo.value)
    assert "test" in str(excinfo.value)


def test_going_backwards_is_rejected():
    state = advance(an_identified_session("s"), Step.LEVEL)
    with pytest.raises(TransitionError):
        advance(state, Step.SURVEY)


def test_recording_the_survey_keeps_the_step():
    state = an_identified_session("s").with_survey(a_survey())
    assert state.survey == a_survey()
    assert state.step is Step.SURVEY


def test_questions_create_one_pending_answer_each():
    questions = (
        QuestionRecord(0, QuestionType.SELF_INTRO.value, None, None, False, "IM1", "Tell me about yourself.", None),
        QuestionRecord(1, QuestionType.DESCRIPTION.value, "movies", 0, False, "IM1", "Describe your favourite film.", None),
    )
    state = SessionState.new("s", seed=7, created_at=_CREATED_AT).with_questions(questions)
    assert [a.state for a in state.answers] == [AnswerState.PENDING, AnswerState.PENDING]
    assert state.pending_indices() == (0, 1)


def test_an_answer_can_be_replaced_by_index():
    questions = (
        QuestionRecord(0, QuestionType.SELF_INTRO.value, None, None, False, "IM1", "Tell me about yourself.", None),
    )
    state = SessionState.new("s", seed=7, created_at=_CREATED_AT).with_questions(questions)
    state = state.with_answer(AnswerRecord(0, AnswerState.SCORED, "answer-00.webm"))
    assert state.answers[0].state is AnswerState.SCORED
    assert state.scored_indices() == (0,)
    assert state.pending_indices() == ()


def test_a_failed_answer_counts_as_neither_pending_nor_scored():
    questions = (
        QuestionRecord(0, QuestionType.SELF_INTRO.value, None, None, False, "IM1", "Tell me about yourself.", None),
    )
    state = SessionState.new("s", seed=7, created_at=_CREATED_AT).with_questions(questions)
    state = state.with_answer(AnswerRecord(0, AnswerState.FAILED, "answer-00.webm", "ollama timed out"))
    assert state.pending_indices() == ()
    assert state.scored_indices() == ()
    assert state.answers[0].error == "ollama timed out"


def test_attaching_audio_touches_only_that_question():
    questions = (
        QuestionRecord(0, QuestionType.SELF_INTRO.value, None, None, False, "IM1", "Tell me about yourself.", None),
        QuestionRecord(1, QuestionType.DESCRIPTION.value, "movies", 0, False, "IM1", "Describe a film.", None),
    )
    state = SessionState.new("s", seed=7, created_at=_CREATED_AT).with_questions(questions)
    state = state.with_question_audio(1, "/cache/b.wav")
    assert state.questions[0].audio_path is None
    assert state.questions[1].audio_path == "/cache/b.wav"
    assert state.questions[1].text_en == "Describe a film."


def test_questions_are_ready_only_when_every_one_has_audio():
    without_audio = QuestionRecord(0, QuestionType.SELF_INTRO.value, None, None, False, "IM1", "Hi.", None)
    with_audio = QuestionRecord(0, QuestionType.SELF_INTRO.value, None, None, False, "IM1", "Hi.", "/cache/ab.wav")
    assert (
        SessionState.new("s", 7, created_at=_CREATED_AT).with_questions((without_audio,)).questions_ready is False
    )
    assert (
        SessionState.new("s", 7, created_at=_CREATED_AT).with_questions((with_audio,)).questions_ready is True
    )


def test_advancing_past_the_last_step_is_rejected():
    state = an_identified_session("s")
    for step in (Step.LEVEL, Step.SETUP, Step.SAMPLE, Step.TEST, Step.GRADING, Step.DONE):
        state = advance(state, step)
    with pytest.raises(TransitionError) as excinfo:
        advance(state, Step.DONE)
    assert "last step" in str(excinfo.value)


def test_a_new_session_starts_at_identity():
    state = SessionState.new("abc", 7, datetime(2026, 8, 31, 14, 0, 0))
    assert state.step is Step.IDENTITY
    assert state.candidate is None


def test_identity_advances_to_survey():
    state = SessionState.new("abc", 7, datetime(2026, 8, 31, 14, 0, 0))
    named = state.with_candidate(Candidate("김민준", "minjun@example.com"))
    assert advance(named, Step.SURVEY).step is Step.SURVEY
    assert named.candidate.email == "minjun@example.com"


def test_identity_cannot_be_skipped():
    state = SessionState.new("abc", 7, datetime(2026, 8, 31, 14, 0, 0))
    with pytest.raises(TransitionError):
        advance(state, Step.LEVEL)
