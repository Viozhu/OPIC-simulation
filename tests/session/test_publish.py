from __future__ import annotations

from datetime import datetime

from opic.core.candidate import Candidate
from opic.session.publish import sheet_row
from opic.session.state import Feedback, SessionState


def a_state() -> SessionState:
    state = SessionState.new("Nk7Qz", 1, datetime(2026, 8, 31, 14, 30, 52))
    state = state.with_candidate(Candidate("김민준", "minjun@example.com"))
    return state.with_feedback(Feedback(rating=5, comment="좋았습니다"))


def test_every_column_is_filled_from_the_session():
    row = sheet_row(a_state(), {"final_level": "IH"}, "https://opic.example.com")
    assert row == {
        "timestamp": "2026-08-31T14:30:52",
        "session_id": "Nk7Qz",
        "name": "김민준",
        "email": "minjun@example.com",
        "level": "IH",
        "rating": "5",
        "comment": "좋았습니다",
        "report_url": "https://opic.example.com/api/sessions/Nk7Qz/page",
    }


def test_an_exam_that_never_got_a_grade_leaves_the_level_empty():
    assert sheet_row(a_state(), None, "https://opic.example.com")["level"] == ""


def test_without_a_public_url_there_is_no_link_to_offer():
    assert sheet_row(a_state(), {"final_level": "IH"}, "")["report_url"] == ""


def test_a_trailing_slash_does_not_double_up():
    row = sheet_row(a_state(), None, "https://opic.example.com/")
    assert row["report_url"] == "https://opic.example.com/api/sessions/Nk7Qz/page"


def test_a_session_with_no_candidate_still_makes_a_row():
    state = SessionState.new("Nk7Qz", 1, datetime(2026, 8, 31, 14, 30, 52))
    row = sheet_row(state.with_feedback(Feedback(3, "")), None, "")
    assert row["name"] == ""
    assert row["email"] == ""
    assert row["rating"] == "3"
