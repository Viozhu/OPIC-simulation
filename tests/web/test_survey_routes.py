from __future__ import annotations


def test_creating_a_session_returns_its_id_and_first_step(client):
    response = client.post("/api/sessions")
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "20260819-143052"
    assert body["step"] == "survey"


def test_the_session_can_be_read_back(client):
    session_id = client.post("/api/sessions").json()["id"]
    body = client.get(f"/api/sessions/{session_id}").json()
    assert body["id"] == session_id
    assert body["questions"] == []
    assert body["questions_ready"] is False


def test_an_unknown_session_is_a_404(client):
    assert client.get("/api/sessions/nope").status_code == 404


def test_the_survey_schema_carries_the_korean_the_ui_renders(client):
    body = client.get("/api/survey").json()
    assert body["min_total_items"] == 12
    assert body["occupations"][0]["label_ko"]
    assert body["housing"][0]["label_ko"]
    groups = {group["id"]: group for group in body["groups"]}
    assert set(groups) == {"leisure", "hobby", "sport", "travel"}
    assert groups["leisure"]["minimum"] == 2
    assert groups["leisure"]["items"][0]["label_ko"]
    assert groups["leisure"]["items"][0]["id"]


def test_a_valid_survey_is_stored_and_moves_the_step(client, a_valid_survey):
    session_id = client.post("/api/sessions").json()["id"]
    response = client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    assert response.status_code == 200
    assert response.json()["step"] == "level"
    assert response.json()["survey"]["occupation"] == "business"


def test_an_invalid_survey_comes_back_with_every_issue(client, a_valid_survey):
    session_id = client.post("/api/sessions").json()["id"]
    a_valid_survey["selected_item_ids"] = ["movies", "listening_music"]
    response = client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)

    assert response.status_code == 422
    issues = response.json()["issues"]
    errors = {issue["error"] for issue in issues}
    assert "too_few_items" in errors
    assert "group_minimum" in errors
    assert all("detail" in issue for issue in issues)


def test_a_rejected_survey_leaves_the_session_where_it_was(client, a_valid_survey):
    session_id = client.post("/api/sessions").json()["id"]
    a_valid_survey["selected_item_ids"] = ["movies"]
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)

    body = client.get(f"/api/sessions/{session_id}").json()
    assert body["step"] == "survey"
    assert body["survey"] is None


def test_an_unknown_occupation_is_rejected_without_a_traceback(client, a_valid_survey):
    session_id = client.post("/api/sessions").json()["id"]
    a_valid_survey["occupation"] = "astronaut"
    response = client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    assert response.status_code == 422
