"""The two deadlines the sessions folder lives under.

Everything here happens inside `tmp_path`. `data/sessions` holds the only real
exams that exist, and a test that could reach them would only have to be wrong
once.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from opic.core.questions import EXAM_LENGTH
from opic.session import pages, retention, store
from session.test_pages import a_graded_session

NOW = datetime(2026, 9, 1, 12, 0)


def touched(directory: Path, when: datetime) -> None:
    """Backdate a folder and everything in it.

    `expired` reads two clocks — `created_at` for age and the timestamps for
    "is anybody still in here" — so a test that moves one without the other is
    testing a state that cannot happen.
    """
    stamp = when.timestamp()
    for path in [*directory.iterdir(), directory]:
        os.utime(path, (stamp, stamp))


def a_session_aged(root: Path, days: int) -> str:
    """A session whose clock and whose timestamps both say it is `days` old."""
    when = NOW - timedelta(days=days)
    state = store.create(root, seed=7, now=when)
    touched(store.session_dir(root, state.id), when)
    return state.id


# --- the recordings ---------------------------------------------------------


def test_the_audio_goes_once_the_report_is_written(tmp_path, ports, survey):
    session_id = a_graded_session(tmp_path, ports, survey)

    directory = store.session_dir(tmp_path, session_id)
    assert store.page_path(tmp_path, session_id).exists()
    assert list(directory.glob("answer-*.webm")) == []
    # The judgements and the transcripts inside them are what the report is
    # built from; only the audio was supposed to go.
    assert len(list(directory.glob("answer-*.json"))) == EXAM_LENGTH
    assert store.result_path(tmp_path, session_id).exists()


def test_the_recordings_stay_until_the_page_is_actually_there(tmp_path):
    """A result is not a report: the page is written a model call later."""
    state = store.create(tmp_path, seed=7, now=NOW)
    audio = store.answer_audio_path(tmp_path, state.id, 0, ".webm")
    audio.write_bytes(b"webm")
    store.result_path(tmp_path, state.id).write_text("{}", encoding="utf-8")

    assert retention.discard_audio(tmp_path, state.id) == ()
    assert audio.exists()

    store.page_path(tmp_path, state.id).write_text("<html>", encoding="utf-8")

    assert retention.discard_audio(tmp_path, state.id) == (audio,)
    assert not audio.exists()


def test_an_exam_in_progress_is_left_exactly_as_the_sweep_found_it(tmp_path):
    state = store.create(tmp_path, seed=7, now=NOW)
    audio = store.answer_audio_path(tmp_path, state.id, 0, ".webm")
    audio.write_bytes(b"webm")

    assert retention.sweep(tmp_path, NOW) == retention.Swept((), ())
    assert audio.exists()
    assert store.session_dir(tmp_path, state.id).exists()


def test_the_sweep_picks_up_a_session_reported_before_any_of_this_existed(tmp_path):
    """The catch-up: a page written by an older build still owes its audio."""
    session_id = a_session_aged(tmp_path, days=2)
    audio = store.answer_audio_path(tmp_path, session_id, 0, ".webm")
    audio.write_bytes(b"webm")
    store.page_path(tmp_path, session_id).write_text("<html>", encoding="utf-8")

    swept = retention.sweep(tmp_path, NOW)

    assert swept.purged == (session_id,)
    assert swept.expired == ()
    assert not audio.exists()
    assert store.session_dir(tmp_path, session_id).exists()


def test_every_suffix_the_browser_may_upload_is_one_the_purge_knows(tmp_path):
    """The two sets are copies, so drift in either one leaves audio behind."""
    from opic.web.app import ALLOWED_AUDIO_SUFFIXES

    assert ALLOWED_AUDIO_SUFFIXES <= retention.AUDIO_SUFFIXES


# --- the thirty days --------------------------------------------------------


def test_a_session_past_its_thirtieth_day_goes_whole(tmp_path):
    session_id = a_session_aged(tmp_path, days=31)

    assert retention.expired(tmp_path, NOW) == (session_id,)
    assert retention.sweep(tmp_path, NOW).expired == (session_id,)
    assert not store.session_dir(tmp_path, session_id).exists()


def test_a_session_on_its_twenty_ninth_day_stays(tmp_path):
    session_id = a_session_aged(tmp_path, days=29)

    assert retention.expired(tmp_path, NOW) == ()
    retention.sweep(tmp_path, NOW)
    assert (store.session_dir(tmp_path, session_id) / store.SESSION_FILE).exists()


def test_a_session_somebody_is_writing_to_outlives_its_own_deadline(tmp_path):
    """The clock can be wrong; a file written five minutes ago cannot."""
    session_id = a_session_aged(tmp_path, days=31)
    touched(store.session_dir(tmp_path, session_id), NOW - timedelta(minutes=5))

    assert retention.expired(tmp_path, NOW) == ()
    retention.sweep(tmp_path, NOW)
    assert store.session_dir(tmp_path, session_id).exists()


def test_a_session_that_will_not_load_is_left_alone(tmp_path):
    session_id = a_session_aged(tmp_path, days=99)
    directory = store.session_dir(tmp_path, session_id)
    (directory / store.SESSION_FILE).write_text("{ not json", encoding="utf-8")
    touched(directory, NOW - timedelta(days=99))

    assert retention.expired(tmp_path, NOW) == ()
    assert store.session_dir(tmp_path, session_id).exists()


def test_what_is_not_a_session_is_not_a_session(tmp_path):
    """A sessions root also holds the server's lock and whatever else lands."""
    (tmp_path / ".server.lock").write_text("1", encoding="utf-8")
    (tmp_path / "notes").mkdir()

    assert retention.sweep(tmp_path, NOW) == retention.Swept((), ())
    assert (tmp_path / ".server.lock").exists()
    assert (tmp_path / "notes").exists()


def test_a_sessions_folder_that_is_not_there_yet_is_not_an_error(tmp_path):
    assert retention.sweep(tmp_path / "nothing", NOW) == retention.Swept((), ())


# --- what has to survive the deletion ---------------------------------------


def test_the_report_still_rebuilds_once_the_audio_is_gone(tmp_path, ports, survey):
    """`opic --report` reads `result.json`; nothing on that path opens a `.webm`."""
    session_id = a_graded_session(tmp_path, ports, survey)
    page = store.page_path(tmp_path, session_id)
    before = page.read_text(encoding="utf-8")
    page.unlink()
    assert list(store.session_dir(tmp_path, session_id).glob("answer-*.webm")) == []

    assert pages.write_for(tmp_path, session_id) is not None

    assert page.read_text(encoding="utf-8") == before


def test_the_report_command_rebuilds_a_session_that_lost_its_audio(tmp_path, ports, survey):
    from opic.cli import regenerate_report

    session_id = a_graded_session(tmp_path, ports, survey)
    session_dir = store.session_dir(tmp_path, session_id)

    assert regenerate_report(session_dir, use_llm=False, force=True) == 0

    assert "OPIc 모의고사 결과" in store.page_path(tmp_path, session_id).read_text(
        encoding="utf-8"
    )
