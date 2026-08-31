from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from opic.web.app import create_app


def test_it_answers_ok(client: TestClient):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_it_answers_without_the_share_token(sessions_root, worker):
    """Un vigilante externo no tiene el token, y no debe necesitarlo."""
    app = create_app(root=sessions_root, worker=worker, share_token="s3cret")
    guarded = TestClient(app)
    assert guarded.get("/").status_code == 404
    assert guarded.get("/healthz").status_code == 200


def test_it_says_nothing_else(client: TestClient):
    assert set(client.get("/healthz").json()) == {"status"}


def test_a_dead_worker_is_a_503(sessions_root, worker):
    class DeadWorker:
        alive = False

        def update(self, *args, **kwargs):
            raise AssertionError("not reached")

    app = create_app(root=sessions_root, worker=DeadWorker())
    assert TestClient(app).get("/healthz").status_code == 503
