from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from opic.core.questions import QuestionType
from opic.core.survey import Housing, Occupation, RecentCourse, SurveyAnswers
from opic.session import store
from opic.session.state import AnswerRecord, AnswerState, QuestionRecord, SessionState, Step


def a_survey() -> SurveyAnswers:
    return SurveyAnswers(
        occupation=Occupation.TEACHER,
        is_student=False,
        housing=Housing.WITH_FAMILY,
        selected_item_ids=("movies", "listening_music"),
        recent_course=RecentCourse.DEGREE,
    )


def test_the_id_is_the_creation_timestamp():
    assert store.new_session_id(datetime(2026, 8, 19, 14, 30, 52)) == "20260819-143052"


def test_create_writes_a_session_that_loads_back(tmp_path: Path):
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 19, 14, 30, 52))
    assert store.load(tmp_path, state.id) == state
    assert (tmp_path / state.id / "session.json").exists()


def test_a_full_state_survives_the_round_trip(tmp_path: Path):
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 19, 14, 30, 52))
    state = state.with_survey(a_survey()).with_level(4)
    state = state.with_questions(
        (
            QuestionRecord(0, QuestionType.SELF_INTRO.value, None, None, False, "IM1", "Tell me about yourself.", "/cache/a.wav"),
            QuestionRecord(1, QuestionType.DESCRIPTION.value, "movies", 0, True, "IH", "Describe a film.", None),
        )
    )
    state = state.with_answer(AnswerRecord(0, AnswerState.FAILED, "answer-00.webm", "boom"))
    store.save(tmp_path, state)

    loaded = store.load(tmp_path, state.id)
    assert loaded == state
    assert loaded.survey.recent_course is RecentCourse.DEGREE
    assert loaded.questions[1].topic_id == "movies"
    assert loaded.answers[0].error == "boom"


def test_save_never_leaves_a_half_written_file(tmp_path: Path):
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 19, 14, 30, 52))
    path = tmp_path / state.id / "session.json"
    before = path.read_text(encoding="utf-8")

    original = Path.replace

    def explode(self, target):
        raise OSError("disk full")

    Path.replace = explode
    try:
        with pytest.raises(OSError):
            store.save(tmp_path, state.with_level(4))
    finally:
        Path.replace = original

    assert path.read_text(encoding="utf-8") == before
    assert json.loads(before)["self_assess_level"] is None


def test_unfinished_sessions_are_the_ones_without_a_result(tmp_path: Path):
    done = store.create(tmp_path, seed=1, now=datetime(2026, 8, 19, 10, 0, 0))
    pending = store.create(tmp_path, seed=2, now=datetime(2026, 8, 19, 11, 0, 0))
    (tmp_path / done.id / "result.json").write_text("{}", encoding="utf-8")

    assert store.list_unfinished(tmp_path) == (pending.id,)


def test_the_answer_audio_path_carries_the_browser_suffix(tmp_path: Path):
    path = store.answer_audio_path(tmp_path, "s", 3, ".webm")
    assert path == tmp_path / "s" / "answer-03.webm"


def test_loading_a_session_that_does_not_exist_says_so(tmp_path: Path):
    with pytest.raises(FileNotFoundError) as excinfo:
        store.load(tmp_path, "nope")
    assert "nope" in str(excinfo.value)
