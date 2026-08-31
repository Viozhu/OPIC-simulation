from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opic.session.worker import Worker
from opic.web.app import create_app

from doubles import FakeQuestionWriter, FakeRater, FakeSpeechToText, FakeTextToSpeech

TWELVE_ITEMS = [
    "movies", "clubbing", "live_shows", "concerts", "museums", "parks",
    "listening_music", "cooking", "yoga", "walking", "domestic_travel", "overseas_travel",
]


@pytest.fixture
def sessions_root(tmp_path: Path) -> Path:
    return tmp_path / "sessions"


@pytest.fixture
def sheet():
    from doubles import FakeSheet

    return FakeSheet()


@pytest.fixture
def worker(sessions_root: Path, tmp_path: Path, sheet) -> Worker:
    return Worker(
        root=sessions_root,
        tts=FakeTextToSpeech(tmp_path / "tts_cache"),
        stt=FakeSpeechToText(),
        writer=FakeQuestionWriter(),
        rater=FakeRater(),
        sheet=sheet,
        public_url="https://opic.example.com",
        sleeper=lambda _: None,
    )


@pytest.fixture
def client(sessions_root: Path, worker: Worker) -> TestClient:
    """A client whose clock is frozen, so `created_at` is predictable.

    The id is random now, so nothing here may hardcode one: read it from the
    response.
    """
    app = create_app(
        root=sessions_root,
        worker=worker,
        clock=lambda: datetime(2026, 8, 19, 14, 30, 52),
    )
    return TestClient(app)


@pytest.fixture
def a_valid_survey() -> dict:
    return {
        "occupation": "business",
        "is_student": False,
        "housing": "alone",
        "selected_item_ids": TWELVE_ITEMS,
        "recent_course": "language",
    }


@pytest.fixture
def identified(client: TestClient) -> str:
    """Una sesión con la identidad ya enviada, parada en la encuesta."""
    session_id = client.post("/api/sessions").json()["id"]
    client.put(
        f"/api/sessions/{session_id}/identity",
        json={"name": "김민준", "email": "minjun@example.com"},
    )
    return session_id


@pytest.fixture
def session_id(client: TestClient, worker: Worker, identified: str, a_valid_survey: dict) -> str:
    """A session that has reached the TEST step, ready to receive answers."""
    session_id = identified
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    client.put(f"/api/sessions/{session_id}/level", json={"level": 4})
    worker.drain()
    for step in ("sample", "test"):
        client.post(f"/api/sessions/{session_id}/step", json={"step": step})
    return session_id


@pytest.fixture
def scored_session(client: TestClient, worker: Worker, session_id: str) -> str:
    """A session driven all the way to a written `result.json`."""
    fixture = Path(__file__).parent / "fixtures" / "answer.webm"
    total = len(client.get(f"/api/sessions/{session_id}").json()["questions"])
    for index in range(total):
        with fixture.open("rb") as audio:
            client.post(
                f"/api/sessions/{session_id}/answers/{index}",
                files={"audio": ("answer.webm", audio, "audio/webm")},
            )
    client.post(f"/api/sessions/{session_id}/step", json={"step": "grading"})
    worker.drain()
    return session_id
