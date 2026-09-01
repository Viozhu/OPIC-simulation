"""Cada sesión tiene dueño, y su informe una llave aparte.

La puerta compartida (`test_share_gate.py`) es un único secreto que tienen
todos los invitados a la vez: impide que un desconocido llegue, no que un
invitado lea el examen de otro. Esto es la capa de encima. Son dos claves
porque son dos personas:

- la del dueño viaja en una cookie que sólo recibe quien creó la sesión, y
  abre todo lo suyo;
- la de lectura viaja en la URL que va a la hoja de cálculo, y abre sólo el
  informe de esa sesión — que es lo que deja al dueño del servidor leerlo
  desde su propio navegador, el que nunca tuvo la cookie del candidato.

`TestClient` guarda cookies como un navegador, así que "otro navegador" aquí
es sencillamente un `TestClient` nuevo sobre la misma aplicación.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opic.session import store
from opic.session.publish import sheet_row
from opic.web.app import OWNER_COOKIE


@pytest.fixture
def stranger(client: TestClient) -> TestClient:
    """El segundo invitado: la misma aplicación, otro tarro de cookies."""
    return TestClient(client.app)


def _read_key(sessions_root: Path, session_id: str) -> str:
    key = store.load(sessions_root, session_id).read_key
    assert key is not None
    return key


def _forget_the_keys(sessions_root: Path, session_id: str) -> None:
    """Dejar `session.json` como lo dejaron las sesiones de antes de este cambio.

    Diecinueve carpetas reales en `data/sessions/` están así, y siguen siendo
    lo único que queda de exámenes reales.
    """
    path = store.session_dir(sessions_root, session_id) / store.SESSION_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["owner_key"]
    del payload["read_key"]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_a_second_guest_cannot_read_the_first_ones_exam(client, stranger, session_id):
    assert client.get(f"/api/sessions/{session_id}").status_code == 200
    assert stranger.get(f"/api/sessions/{session_id}").status_code == 404


def test_a_refused_session_looks_exactly_like_one_that_never_existed(
    client, stranger, session_id
):
    """404 y no 403, por lo mismo que la puerta compartida: un 403 confirmaría
    que ese id existe, que es justo lo que el id oculta."""
    mine = stranger.get(f"/api/sessions/{session_id}")
    invented = stranger.get("/api/sessions/no-such-session-at-all")

    assert mine.status_code == invented.status_code == 404
    assert mine.json() == invented.json()


def test_a_second_guest_cannot_write_to_the_first_ones_exam(
    client, stranger, session_id
):
    """Leer no es lo peor que puede hacer: escribir le arruina el examen."""
    assert (
        stranger.post(
            f"/api/sessions/{session_id}/step", json={"step": "grading"}
        ).status_code
        == 404
    )
    assert (
        stranger.put(
            f"/api/sessions/{session_id}/identity",
            json={"name": "다른사람", "email": "someone@example.com"},
        ).status_code
        == 404
    )
    assert (
        stranger.post(
            f"/api/sessions/{session_id}/feedback", json={"rating": 1, "comment": "x"}
        ).status_code
        == 404
    )


def test_a_second_guest_cannot_upload_an_answer_to_the_first_ones_exam(
    stranger, session_id
):
    fixture = Path(__file__).parent / "fixtures" / "answer.webm"
    with fixture.open("rb") as audio:
        response = stranger.post(
            f"/api/sessions/{session_id}/answers/0",
            files={"audio": ("answer.webm", audio, "audio/webm")},
        )

    assert response.status_code == 404


def test_a_second_guest_cannot_hear_the_first_ones_questions(
    client, stranger, session_id
):
    assert client.get(f"/api/sessions/{session_id}/questions/0/audio").status_code == 200
    assert (
        stranger.get(f"/api/sessions/{session_id}/questions/0/audio").status_code == 404
    )


def test_a_second_guest_cannot_watch_the_first_ones_progress(
    client, stranger, session_id
):
    assert client.get(f"/api/sessions/{session_id}/progress").status_code == 200
    assert stranger.get(f"/api/sessions/{session_id}/progress").status_code == 404


def test_a_second_guest_cannot_read_the_first_ones_result(
    client, stranger, scored_session
):
    assert client.get(f"/api/sessions/{scored_session}/result").status_code == 200
    assert stranger.get(f"/api/sessions/{scored_session}/result").status_code == 404


def test_the_owner_of_the_session_keeps_working_exactly_as_before(
    client, scored_session
):
    """La cookie llega sola: el navegador que creó la sesión la tiene desde el
    `POST /api/sessions` y no hay nada que el candidato deba hacer."""
    assert client.get(f"/api/sessions/{scored_session}").status_code == 200
    assert client.get(f"/api/sessions/{scored_session}/page").status_code == 200
    assert client.get(f"/api/sessions/{scored_session}/result").status_code == 200


def test_the_read_key_opens_the_report_from_a_browser_that_never_had_the_cookie(
    stranger, scored_session, sessions_root
):
    """El caso que sostiene todo esto: el dueño pincha el enlace de la hoja."""
    key = _read_key(sessions_root, scored_session)

    response = stranger.get(f"/api/sessions/{scored_session}/page?r={key}")

    assert response.status_code == 200


def test_the_report_json_opens_with_the_read_key_too(
    stranger, scored_session, sessions_root
):
    key = _read_key(sessions_root, scored_session)

    assert stranger.get(f"/api/sessions/{scored_session}/report?r={key}").status_code == 200


def test_the_read_key_opens_the_report_and_nothing_else(
    stranger, scored_session, sessions_root
):
    """Es una llave de lectura de un documento, no una sesión iniciada."""
    key = _read_key(sessions_root, scored_session)

    assert stranger.get(f"/api/sessions/{scored_session}?r={key}").status_code == 404
    assert (
        stranger.get(f"/api/sessions/{scored_session}/result?r={key}").status_code == 404
    )
    assert (
        stranger.get(f"/api/sessions/{scored_session}/progress?r={key}").status_code
        == 404
    )
    assert (
        stranger.post(
            f"/api/sessions/{scored_session}/feedback?r={key}",
            json={"rating": 1, "comment": "x"},
        ).status_code
        == 404
    )


def test_the_read_key_of_one_exam_does_not_open_another(
    client, stranger, scored_session, sessions_root
):
    """El coste aceptado es que la clave viva en la hoja. Sólo se sostiene si
    cada clave está acotada a su propio examen."""
    key = _read_key(sessions_root, scored_session)
    another = client.post("/api/sessions").json()["id"]

    assert stranger.get(f"/api/sessions/{another}/page?r={key}").status_code == 404


def test_a_wrong_read_key_is_indistinguishable_from_none(stranger, scored_session):
    assert stranger.get(f"/api/sessions/{scored_session}/page").status_code == 404
    assert (
        stranger.get(f"/api/sessions/{scored_session}/page?r=not-the-key").status_code
        == 404
    )


def test_the_link_that_goes_to_the_sheet_is_the_one_that_opens(
    stranger, scored_session, sessions_root
):
    """El lazo entre `publish.py` y esta ruta, cerrado: lo que se escribe en la
    hoja es exactamente lo que abre el informe."""
    row = sheet_row(store.load(sessions_root, scored_session), None, "http://testserver")

    assert stranger.get(row["report_url"].removeprefix("http://testserver")).status_code == 200


def test_the_keys_never_leave_the_disk_in_a_response(client, session_id):
    """La cookie ya lleva la del dueño y JavaScript no la lee; devolverlas en el
    JSON las metería en el DOM y en cualquier consola abierta."""
    payload = client.get(f"/api/sessions/{session_id}").json()

    assert "owner_key" not in payload
    assert "read_key" not in payload


def test_the_cookie_is_not_readable_from_javascript(client):
    response = client.post("/api/sessions")

    cookie = response.headers["set-cookie"]
    assert OWNER_COOKIE in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.replace("samesite", "SameSite")


def test_the_cookie_is_scoped_to_its_own_session(client):
    """Con `Path=/` habría una sola cookie por navegador y la segunda sesión
    pisaría a la primera."""
    response = client.post("/api/sessions")
    session_id = response.json()["id"]

    assert f"Path=/api/sessions/{session_id}" in response.headers["set-cookie"]


def test_one_browser_can_hold_two_exams_at_once(client):
    """Un candidato que empieza otro examen no puede perder el anterior: el
    informe del primero es lo único que le queda de él."""
    first = client.post("/api/sessions").json()["id"]
    second = client.post("/api/sessions").json()["id"]

    assert client.get(f"/api/sessions/{first}").status_code == 200
    assert client.get(f"/api/sessions/{second}").status_code == 200


def test_an_exam_recorded_before_the_keys_existed_still_loads(
    stranger, scored_session, sessions_root
):
    """Sin clave guardada no hay nada contra qué comparar. Inventarle una al
    cargarla no protegería nada — nadie la tendría — y volvería ilegibles las
    diecinueve sesiones que ya están en disco."""
    _forget_the_keys(sessions_root, scored_session)

    assert store.load(sessions_root, scored_session).owner_key is None
    assert stranger.get(f"/api/sessions/{scored_session}").status_code == 200
    assert stranger.get(f"/api/sessions/{scored_session}/page").status_code == 200
    assert stranger.get(f"/api/sessions/{scored_session}/result").status_code == 200
