from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from opic.web.app import create_app


def test_an_oversized_answer_is_refused(sessions_root, worker, session_id, client):
    big = b"0" * (2 * 1024 * 1024)
    small_app = create_app(
        root=sessions_root, worker=worker, max_answer_bytes=1024 * 1024,
        clock=lambda: datetime(2026, 8, 31, 14, 0, 0),
    )
    # El mismo navegador contra un servidor configurado más estrecho: se lleva
    # las cookies del que creó la sesión, porque sin la suya no es su dueño y
    # el 404 llegaría antes que el límite de tamaño.
    lean = TestClient(small_app, cookies=client.cookies)
    response = lean.post(
        f"/api/sessions/{session_id}/answers/0",
        files={"audio": ("answer.webm", big, "audio/webm")},
    )
    assert response.status_code == 413


def test_creating_too_many_sessions_is_refused(sessions_root, worker):
    app = create_app(
        root=sessions_root, worker=worker, creates_per_hour=3,
        clock=lambda: datetime(2026, 8, 31, 14, 0, 0),
    )
    client = TestClient(app)
    for _ in range(3):
        assert client.post("/api/sessions").status_code == 201
    assert client.post("/api/sessions").status_code == 429


def test_the_window_moves(sessions_root, worker):
    now = [datetime(2026, 8, 31, 14, 0, 0)]
    app = create_app(
        root=sessions_root, worker=worker, creates_per_hour=1, clock=lambda: now[0]
    )
    client = TestClient(app)
    assert client.post("/api/sessions").status_code == 201
    assert client.post("/api/sessions").status_code == 429
    now[0] = datetime(2026, 8, 31, 15, 30, 0)
    assert client.post("/api/sessions").status_code == 201
