from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from opic.core.transcript import Span, Transcript, Word
from opic.session.worker import Worker
from opic.web.app import create_app

from doubles import FakeQuestionWriter, FakeRater, FakeTextToSpeech


def test_an_oversized_answer_is_refused(sessions_root, worker, session_id, client):
    big = b"0" * (2 * 1024 * 1024)
    small_app = create_app(
        root=sessions_root, worker=worker, max_answer_bytes=1024 * 1024,
        clock=lambda: datetime(2026, 8, 31, 14, 0, 0),
    )
    lean = TestClient(small_app)
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


def test_the_day_has_a_ceiling_too(sessions_root, worker):
    """Cada dirección por debajo de su límite, y aun así el día se acaba."""
    now = [datetime(2026, 8, 31, 14, 0, 0)]
    app = create_app(
        root=sessions_root, worker=worker,
        creates_per_hour=10, creates_per_day=2, clock=lambda: now[0],
    )
    client = TestClient(app)
    for address in ("203.0.113.1", "203.0.113.2"):
        created = client.post("/api/sessions", headers={"cf-connecting-ip": address})
        assert created.status_code == 201
    refused = client.post("/api/sessions", headers={"cf-connecting-ip": "203.0.113.3"})
    assert refused.status_code == 429

    now[0] = datetime(2026, 9, 1, 14, 0, 1)
    assert client.post("/api/sessions", headers={"cf-connecting-ip": "203.0.113.3"}).status_code == 201


def test_the_two_ceilings_do_not_say_the_same_thing(sessions_root, worker):
    """El de la dirección se pasa en una hora; el del día, no. El navegador
    tiene que poder distinguirlos sin leerse la frase en inglés."""
    def clock():
        return datetime(2026, 8, 31, 14, 0, 0)

    per_address = create_app(
        root=sessions_root, worker=worker, creates_per_hour=1, creates_per_day=99, clock=clock
    )
    client = TestClient(per_address)
    assert client.post("/api/sessions").status_code == 201
    assert client.post("/api/sessions").json()["detail"]["reason"] == "too_many_sessions"

    per_day = create_app(
        root=sessions_root, worker=worker, creates_per_hour=99, creates_per_day=1, clock=clock
    )
    client = TestClient(per_day)
    assert client.post("/api/sessions").status_code == 201
    assert client.post("/api/sessions").json()["detail"]["reason"] == "too_many_sessions_today"


def test_a_forwarded_for_header_no_longer_buys_a_new_origin(sessions_root, worker):
    """Dos peticiones del mismo socket son el mismo origen, diga la cabecera lo
    que diga: quien la pone es el cliente."""
    app = create_app(
        root=sessions_root, worker=worker, creates_per_hour=1,
        clock=lambda: datetime(2026, 8, 31, 14, 0, 0),
    )
    client = TestClient(app)
    assert client.post("/api/sessions", headers={"x-forwarded-for": "203.0.113.1"}).status_code == 201
    assert client.post("/api/sessions", headers={"x-forwarded-for": "203.0.113.2"}).status_code == 429


def test_cloudflares_header_still_tells_two_guests_apart(sessions_root, worker):
    """El arreglo de arriba no puede llevarse por delante el caso normal: dos
    invitados detrás del túnel siguen siendo dos."""
    app = create_app(
        root=sessions_root, worker=worker, creates_per_hour=1,
        clock=lambda: datetime(2026, 8, 31, 14, 0, 0),
    )
    client = TestClient(app)
    assert client.post("/api/sessions", headers={"cf-connecting-ip": "203.0.113.1"}).status_code == 201
    assert client.post("/api/sessions", headers={"cf-connecting-ip": "203.0.113.2"}).status_code == 201


class HalfAnHourOfSpeech:
    """Un `SpeechToText` que devuelve media hora de habla, dure lo que dure el
    fichero: lo que vería el worker si alguien sube una grabación sin fin."""

    def transcribe(self, audio: Path) -> Transcript:
        words = tuple(Word("word", float(i), i + 0.5, 0.9) for i in range(1800))
        return Transcript(
            text=" ".join(word.text for word in words),
            words=words,
            speech_spans=(Span(0.0, 1800.0),),
            duration_s=1800.0,
        )


def test_an_answer_past_the_ceiling_is_judged_only_up_to_it(
    sessions_root, tmp_path, sheet, a_valid_survey
):
    """Se corrige recortada, no se pierde: el candidato no decide cuándo para
    la grabación, y una nota menos por un botón atascado sería suya sin serlo."""
    worker = Worker(
        root=sessions_root,
        tts=FakeTextToSpeech(tmp_path / "tts_cache"),
        stt=HalfAnHourOfSpeech(),
        writer=FakeQuestionWriter(),
        rater=FakeRater(),
        sheet=sheet,
        sleeper=lambda _: None,
        max_answer_seconds=60.0,
    )
    app = create_app(
        root=sessions_root, worker=worker, clock=lambda: datetime(2026, 8, 31, 14, 0, 0)
    )
    client = TestClient(app)

    session_id = client.post("/api/sessions").json()["id"]
    client.put(
        f"/api/sessions/{session_id}/identity",
        json={"name": "김민준", "email": "minjun@example.com"},
    )
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    client.put(f"/api/sessions/{session_id}/level", json={"level": 4})
    worker.drain()
    for step in ("sample", "test"):
        client.post(f"/api/sessions/{session_id}/step", json={"step": step})

    fixture = Path(__file__).parent / "fixtures" / "answer.webm"
    with fixture.open("rb") as audio:
        accepted = client.post(
            f"/api/sessions/{session_id}/answers/0",
            files={"audio": ("answer.webm", audio, "audio/webm")},
        )
    assert accepted.status_code == 202
    worker.drain()

    state = client.get(f"/api/sessions/{session_id}").json()
    assert state["answers"][0]["state"] == "scored"

    judged = json.loads(
        (sessions_root / session_id / "answer-00.json").read_text(encoding="utf-8")
    )
    assert judged["transcript"]["duration_s"] == 60.0
    # Sesenta palabras enteras caben en sesenta segundos; la que cruza la marca
    # no cuenta, y nada de lo de después llega al corrector.
    assert judged["metrics"]["word_count"] == 60
    assert len(judged["transcript"]["words"]) == 60


def test_the_ceiling_leaves_an_ordinary_answer_alone(sessions_root, worker, session_id, client):
    """La respuesta de siempre dura un segundo en los dobles y se corrige entera:
    el recorte no puede tocar nada que quepa por debajo del techo."""
    fixture = Path(__file__).parent / "fixtures" / "answer.webm"
    with fixture.open("rb") as audio:
        client.post(
            f"/api/sessions/{session_id}/answers/0",
            files={"audio": ("answer.webm", audio, "audio/webm")},
        )
    worker.drain()

    judged = json.loads(
        (sessions_root / session_id / "answer-00.json").read_text(encoding="utf-8")
    )
    assert judged["transcript"]["duration_s"] == 1.0
    assert judged["transcript"]["text"] == "I like films"
