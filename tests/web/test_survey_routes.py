from __future__ import annotations


def test_creating_a_session_returns_its_id_and_first_step(client):
    response = client.post("/api/sessions")
    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["created_at"] == "2026-08-19T14:30:52"
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


def test_the_survey_schema_carries_the_question_stems(client):
    body = client.get("/api/survey").json()
    assert body["question_labels"]["occupation"]
    assert body["question_labels"]["is_student"]
    assert body["question_labels"]["recent_course"]
    assert body["question_labels"]["housing"]
    yes_no_ids = {option["id"] for option in body["yes_no"]}
    assert yes_no_ids == {"yes", "no"}
    assert all(option["label_ko"] for option in body["yes_no"])


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
    assert all(issue["message_ko"].strip() for issue in issues)


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
    issues = response.json()["issues"]
    assert issues[0]["error"] == "unknown_value"
    assert issues[0]["message_ko"].strip()


def test_resubmitting_the_survey_after_it_already_advanced_is_a_409(client, a_valid_survey):
    session_id = client.post("/api/sessions").json()["id"]
    first = client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    assert first.status_code == 200

    second = client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    assert second.status_code == 409
    body = second.json()
    assert "detail" in body
    assert "level" in body["detail"] and "setup" in body["detail"]

    body = client.get(f"/api/sessions/{session_id}").json()
    assert body["step"] == "level"
    assert body["survey"]["occupation"] == "business"
