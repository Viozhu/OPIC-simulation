"""The rendered report, served whole.

`core/page.py` renders it and the worker writes it to disk when grading ends;
this route is how the browser gets it. The endpoint decides nothing — it reads
what `session/pages.py` hands over.
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from opic.session import store
from opic.web.app import SHARE_COOKIE, create_app


def test_the_page_is_a_404_until_the_exam_is_scored(client, session_id):
    assert client.get(f"/api/sessions/{session_id}/page").status_code == 404


def test_an_unknown_session_is_a_404(client):
    assert client.get("/api/sessions/nope/page").status_code == 404


def test_the_written_page_is_served_as_it_is(client, scored_session, sessions_root):
    """Byte for byte: the file on disk is the one with the narrative in it."""
    store.page_path(sessions_root, scored_session).write_text(
        "<!doctype html>\n<html lang=\"ko\">written</html>", encoding="utf-8"
    )

    response = client.get(f"/api/sessions/{scored_session}/page")

    assert response.status_code == 200
    assert response.text == "<!doctype html>\n<html lang=\"ko\">written</html>"
    assert response.headers["content-type"].startswith("text/html")


def test_a_missing_page_is_provisional_and_says_so(
    client, scored_session, sessions_root
):
    """The minute between `result.json` and the written page is the whole
    reason for the status: the body is a real report, but the narrative is
    still being paid for, so the browser is told to ask again rather than
    keep this one."""
    store.page_path(sessions_root, scored_session).unlink()

    response = client.get(f"/api/sessions/{scored_session}/page")

    assert response.status_code == 202
    assert response.text.startswith("<!doctype html>")
    assert "AL 목표 답변" not in response.text


def test_the_written_page_is_never_provisional(client, scored_session, sessions_root):
    """A 200 is the promise that nothing better is coming."""
    store.page_path(sessions_root, scored_session).write_text(
        "<!doctype html>\n<html lang=\"ko\">written</html>", encoding="utf-8"
    )

    assert client.get(f"/api/sessions/{scored_session}/page").status_code == 200


def test_every_answer_unreadable_and_no_page_is_a_404(
    client, scored_session, sessions_root
):
    """`result.json` is there but nothing can be built from the answers, and
    there is no written page to fall back on. A 404, not a 500."""
    store.page_path(sessions_root, scored_session).unlink()
    for answer_file in (sessions_root / scored_session).glob("answer-*.json"):
        answer_file.write_text("{ not json", encoding="utf-8")

    assert client.get(f"/api/sessions/{scored_session}/page").status_code == 404


def test_the_share_gate_covers_the_page(sessions_root, worker, scored_session):
    """A tunnel makes this route reachable by strangers like every other one."""
    guarded = TestClient(
        create_app(
            root=sessions_root,
            worker=worker,
            clock=lambda: datetime(2026, 8, 24, 17, 0, 0),
            share_token="s3cret",
        )
    )

    assert guarded.get(f"/api/sessions/{scored_session}/page").status_code == 404

    guarded.cookies.set(SHARE_COOKIE, "s3cret")
    assert guarded.get(f"/api/sessions/{scored_session}/page").status_code == 200
