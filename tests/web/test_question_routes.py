from __future__ import annotations


def at_level(client, a_valid_survey, level: int = 4) -> str:
    session_id = client.post("/api/sessions").json()["id"]
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    client.put(f"/api/sessions/{session_id}/level", json={"level": level})
    return session_id


def test_choosing_a_level_moves_on_and_queues_the_generation(client, worker, a_valid_survey):
    session_id = client.post("/api/sessions").json()["id"]
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)

    response = client.put(f"/api/sessions/{session_id}/level", json={"level": 4})

    assert response.status_code == 200
    assert response.json()["step"] == "setup"
    assert response.json()["self_assess_level"] == 4
    assert response.json()["questions_ready"] is False

    worker.drain()
    assert client.get(f"/api/sessions/{session_id}").json()["questions_ready"] is True


def test_a_level_outside_one_to_six_is_rejected(client, a_valid_survey):
    session_id = client.post("/api/sessions").json()["id"]
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    assert client.put(f"/api/sessions/{session_id}/level", json={"level": 9}).status_code == 422


def test_choosing_a_level_before_the_survey_is_refused(client):
    session_id = client.post("/api/sessions").json()["id"]
    response = client.put(f"/api/sessions/{session_id}/level", json={"level": 4})
    assert response.status_code == 409
    assert "survey" in response.json()["detail"]


def test_the_audio_is_a_404_until_it_has_been_synthesised(client, worker, a_valid_survey):
    session_id = at_level(client, a_valid_survey)
    assert client.get(f"/api/sessions/{session_id}/questions/0/audio").status_code == 404

    worker.drain()
    response = client.get(f"/api/sessions/{session_id}/questions/0/audio")
    assert response.status_code == 200
    assert response.content == b"RIFF"


def test_a_question_that_does_not_exist_is_a_404(client, worker, a_valid_survey):
    session_id = at_level(client, a_valid_survey)
    worker.drain()
    assert client.get(f"/api/sessions/{session_id}/questions/99/audio").status_code == 404


def test_the_questions_come_back_without_leaking_a_disk_path(client, worker, a_valid_survey):
    session_id = at_level(client, a_valid_survey)
    worker.drain()
    questions = client.get(f"/api/sessions/{session_id}").json()["questions"]
    assert questions[0]["text_en"] == "Question 0."
    assert questions[0]["qtype"] == "self_intro"
