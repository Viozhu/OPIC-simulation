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
def worker(tmp_path: Path) -> Worker:
    return Worker(
        root=tmp_path / "sessions",
        tts=FakeTextToSpeech(tmp_path / "tts_cache"),
        stt=FakeSpeechToText(),
        writer=FakeQuestionWriter(),
        rater=FakeRater(),
        sleeper=lambda _: None,
    )


@pytest.fixture
def client(tmp_path: Path, worker: Worker) -> TestClient:
    """A client whose clock is frozen, so session ids are predictable."""
    app = create_app(
        root=tmp_path / "sessions",
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
