from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opic.session import store


def test_it_saves_the_feedback_and_answers(
    client: TestClient, worker, sessions_root: Path, scored_session: str
):
    response = client.post(
        f"/api/sessions/{scored_session}/feedback",
        json={"rating": 5, "comment": "좋았습니다"},
    )
    assert response.status_code == 202
    saved = store.load(sessions_root, scored_session).feedback
    assert saved.rating == 5
    assert saved.comment == "좋았습니다"


def test_the_row_goes_out_when_the_worker_runs(
    client: TestClient, worker, sessions_root: Path, scored_session: str
):
    client.post(f"/api/sessions/{scored_session}/feedback", json={"rating": 4, "comment": ""})
    worker.drain()
    assert store.load(sessions_root, scored_session).feedback.published is True


def test_a_rating_out_of_range_is_refused(client: TestClient, scored_session: str):
    response = client.post(
        f"/api/sessions/{scored_session}/feedback", json={"rating": 9, "comment": ""}
    )
    assert response.status_code == 422
    assert response.json()["issues"][0]["message_ko"].strip()


def test_a_very_long_comment_is_cut_not_refused(
    client: TestClient, worker, sessions_root: Path, scored_session: str
):
    client.post(
        f"/api/sessions/{scored_session}/feedback",
        json={"rating": 3, "comment": "가" * 5000},
    )
    assert len(store.load(sessions_root, scored_session).feedback.comment) == 2000


def test_an_unknown_session_is_a_404(client: TestClient):
    response = client.post("/api/sessions/nope/feedback", json={"rating": 3, "comment": ""})
    assert response.status_code == 404


def test_a_second_submission_after_publishing_is_refused(
    client: TestClient, worker, sessions_root: Path, scored_session: str
):
    client.post(
        f"/api/sessions/{scored_session}/feedback",
        json={"rating": 5, "comment": "좋았습니다"},
    )
    worker.drain()

    response = client.post(
        f"/api/sessions/{scored_session}/feedback",
        json={"rating": 1, "comment": "다시 생각해보니 별로였습니다"},
    )

    assert response.status_code == 409
    assert response.json()["issues"][0]["message_ko"].strip()
    saved = store.load(sessions_root, scored_session).feedback
    assert saved.rating == 5
    assert saved.comment == "좋았습니다"


def test_a_second_submission_while_still_pending_overwrites_it(
    client: TestClient, sessions_root: Path, scored_session: str
):
    client.post(
        f"/api/sessions/{scored_session}/feedback",
        json={"rating": 5, "comment": "좋았습니다"},
    )

    response = client.post(
        f"/api/sessions/{scored_session}/feedback",
        json={"rating": 2, "comment": "다시 생각해보니 별로였습니다"},
    )

    assert response.status_code == 202
    saved = store.load(sessions_root, scored_session).feedback
    assert saved.rating == 2
    assert saved.comment == "다시 생각해보니 별로였습니다"
    assert saved.published is False


def test_overwriting_a_pending_submission_still_sends_only_one_row(
    client: TestClient, worker, sheet, scored_session: str
):
    client.post(
        f"/api/sessions/{scored_session}/feedback",
        json={"rating": 5, "comment": "좋았습니다"},
    )
    client.post(
        f"/api/sessions/{scored_session}/feedback",
        json={"rating": 2, "comment": "다시 생각해보니 별로였습니다"},
    )
    worker.drain()

    assert len(sheet.rows) == 1
