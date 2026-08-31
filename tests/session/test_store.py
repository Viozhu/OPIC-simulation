from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from opic.core.candidate import Candidate
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


def test_the_id_is_not_guessable():
    first = store.new_session_id()
    second = store.new_session_id()
    assert first != second
    assert len(first) >= 22
    assert "-" not in first or not first[:8].isdigit()


def test_create_records_when_it_happened(tmp_path: Path):
    made = datetime(2026, 8, 31, 14, 30, 52)
    state = store.create(tmp_path, seed=7, now=made)
    assert state.created_at == made
    assert store.load(tmp_path, state.id).created_at == made


def test_two_sessions_in_the_same_second_do_not_share_a_folder(tmp_path: Path):
    same = datetime(2026, 8, 31, 14, 30, 52)
    first = store.create(tmp_path, seed=1, now=same)
    second = store.create(tmp_path, seed=2, now=same)
    assert first.id != second.id
    assert store.load(tmp_path, first.id).seed == 1
    assert store.load(tmp_path, second.id).seed == 2


def test_a_legacy_session_takes_its_date_from_its_folder_name(tmp_path: Path):
    directory = tmp_path / "20260819-143052"
    directory.mkdir(parents=True)
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 31, 14, 0, 0))
    payload = json.loads((tmp_path / state.id / "session.json").read_text(encoding="utf-8"))
    del payload["created_at"]
    payload["id"] = "20260819-143052"
    (directory / "session.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert store.load(tmp_path, "20260819-143052").created_at == datetime(2026, 8, 19, 14, 30, 52)


def test_unfinished_sessions_come_back_oldest_first(tmp_path: Path):
    late = store.create(tmp_path, seed=1, now=datetime(2026, 8, 31, 18, 0, 0))
    early = store.create(tmp_path, seed=2, now=datetime(2026, 8, 31, 9, 0, 0))
    assert store.list_unfinished(tmp_path) == (early.id, late.id)


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


def test_replay_timings_survive_the_round_trip(tmp_path: Path):
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 19, 14, 30, 52))
    state = state.with_questions(
        (QuestionRecord(0, QuestionType.SELF_INTRO.value, None, None, False, "IM1", "Tell me.", None),)
    )
    state = state.with_answer(
        AnswerRecord(0, AnswerState.RECORDED, "answer-00.webm", replay_spans=((2.0, 7.5),))
    )
    store.save(tmp_path, state)

    assert store.load(tmp_path, state.id).answers[0].replay_spans == ((2.0, 7.5),)


def test_an_answer_written_before_replay_timings_still_loads(tmp_path: Path):
    """A session already in progress has answers on disk without the key."""
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 19, 14, 30, 52))
    state = state.with_questions(
        (QuestionRecord(0, QuestionType.SELF_INTRO.value, None, None, False, "IM1", "Tell me.", None),)
    )
    state = state.with_answer(AnswerRecord(0, AnswerState.RECORDED, "answer-00.webm"))
    store.save(tmp_path, state)
    path = tmp_path / state.id / "session.json"
    payload = json.loads(path.read_text())
    del payload["answers"][0]["replay_spans"]
    path.write_text(json.dumps(payload))

    assert store.load(tmp_path, state.id).answers[0].replay_spans == ()


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


def test_the_candidate_survives_the_round_trip(tmp_path: Path):
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 31, 14, 0, 0))
    state = state.with_candidate(Candidate("김민준", "minjun@example.com"))
    store.save(tmp_path, state)
    assert store.load(tmp_path, state.id).candidate == Candidate("김민준", "minjun@example.com")


def test_a_session_saved_before_candidates_existed_loads_without_one(tmp_path: Path):
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 31, 14, 0, 0))
    payload = json.loads((tmp_path / state.id / "session.json").read_text(encoding="utf-8"))
    del payload["candidate"]
    (tmp_path / state.id / "session.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert store.load(tmp_path, state.id).candidate is None
