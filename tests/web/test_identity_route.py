from __future__ import annotations

from fastapi.testclient import TestClient


def test_a_new_session_asks_for_the_identity_first(client: TestClient):
    created = client.post("/api/sessions").json()
    assert created["step"] == "identity"
    assert created["candidate"] is None


def test_sending_it_advances_to_the_survey(client: TestClient):
    session_id = client.post("/api/sessions").json()["id"]
    response = client.put(
        f"/api/sessions/{session_id}/identity",
        json={"name": "김민준", "email": "minjun@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["step"] == "survey"
    assert body["candidate"] == {"name": "김민준", "email": "minjun@example.com"}


def test_a_bad_address_comes_back_with_korean_to_show(client: TestClient):
    session_id = client.post("/api/sessions").json()["id"]
    response = client.put(
        f"/api/sessions/{session_id}/identity",
        json={"name": "김민준", "email": "minjun"},
    )
    assert response.status_code == 422
    issue = response.json()["issues"][0]
    assert issue["error"] == "bad_email"
    assert issue["message_ko"].strip()


def test_the_survey_is_refused_before_the_identity(client: TestClient, a_valid_survey: dict):
    session_id = client.post("/api/sessions").json()["id"]
    response = client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    assert response.status_code == 409


def test_surrounding_whitespace_is_trimmed(client: TestClient):
    session_id = client.post("/api/sessions").json()["id"]
    body = client.put(
        f"/api/sessions/{session_id}/identity",
        json={"name": "  김민준  ", "email": "  minjun@example.com  "},
    ).json()
    assert body["candidate"] == {"name": "김민준", "email": "minjun@example.com"}


def test_sending_it_twice_is_refused(client: TestClient):
    session_id = client.post("/api/sessions").json()["id"]
    payload = {"name": "김민준", "email": "minjun@example.com"}
    client.put(f"/api/sessions/{session_id}/identity", json=payload)
    assert client.put(f"/api/sessions/{session_id}/identity", json=payload).status_code == 409
