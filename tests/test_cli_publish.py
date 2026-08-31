from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from opic.cli import publish_session
from opic.core.candidate import Candidate
from opic.session import store
from opic.session.state import Feedback

from doubles import ExplodingSheet, FakeSheet


def a_session_with_feedback(root: Path, published: bool = False) -> str:
    state = store.create(root, seed=1, now=datetime(2026, 8, 31, 14, 30, 52))
    state = state.with_candidate(Candidate("김민준", "minjun@example.com"))
    store.save(root, state.with_feedback(Feedback(5, "좋았습니다", published=published)))
    return state.id


def test_it_sends_the_row_and_marks_it(tmp_path: Path):
    session_id = a_session_with_feedback(tmp_path)
    sheet = FakeSheet()
    assert publish_session(tmp_path, session_id, sink=sheet, public_url="", out=lambda _: None) == 0
    assert sheet.rows[0]["email"] == "minjun@example.com"
    assert store.load(tmp_path, session_id).feedback.published is True


def test_it_resends_one_that_was_already_published(tmp_path: Path):
    session_id = a_session_with_feedback(tmp_path, published=True)
    sheet = FakeSheet()
    assert publish_session(tmp_path, session_id, sink=sheet, public_url="", out=lambda _: None) == 0
    assert len(sheet.rows) == 1


def test_no_feedback_is_reported_not_sent(tmp_path: Path):
    state = store.create(tmp_path, seed=1, now=datetime(2026, 8, 31, 14, 30, 52))
    sheet = FakeSheet()
    assert publish_session(tmp_path, state.id, sink=sheet, public_url="", out=lambda _: None) == 1
    assert sheet.rows == []


def test_a_sheet_that_is_down_reports_a_failure(tmp_path: Path):
    session_id = a_session_with_feedback(tmp_path)
    assert (
        publish_session(tmp_path, session_id, sink=ExplodingSheet(), public_url="", out=lambda _: None)
        == 1
    )
    assert store.load(tmp_path, session_id).feedback.published is False


def test_an_unknown_session_reports_a_failure(tmp_path: Path):
    assert publish_session(tmp_path, "nope", sink=FakeSheet(), public_url="", out=lambda _: None) == 1
