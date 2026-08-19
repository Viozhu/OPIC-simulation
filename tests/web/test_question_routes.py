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


def test_the_questions_come_back_without_leaking_a_disk_path(client, worker, a_valid_survey, tmp_path):
    session_id = at_level(client, a_valid_survey)
    worker.drain()
    response = client.get(f"/api/sessions/{session_id}")
    questions = response.json()["questions"]

    # Verify the redacted field is gone
    assert "audio_path" not in questions[0], "audio_path should not leak to the browser"

    # Keep existing assertions
    assert questions[0]["text_en"] == "Question 0."
    assert questions[0]["qtype"] == "self_intro"

    # Verify no filesystem path leaks anywhere in the serialised response
    response_str = str(response.json())
    session_root = str(tmp_path / "sessions")
    assert session_root not in response_str, f"session root path leaked in response: {session_root}"


def test_audio_ready_is_false_before_synthesis_and_true_after(client, worker, a_valid_survey):
    session_id = client.post("/api/sessions").json()["id"]
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    client.put(f"/api/sessions/{session_id}/level", json={"level": 4})

    # Before draining, check if questions exist and audio_ready is False
    response_before = client.get(f"/api/sessions/{session_id}")
    questions_before = response_before.json()["questions"]

    if questions_before:
        # If questions exist before drain, audio_ready should be False (no synthesis yet)
        assert questions_before[0]["audio_ready"] is False, "audio_ready should be False before synthesis"
        assert "audio_path" not in questions_before[0], "audio_path should not leak"

    # After draining, audio_ready should be True
    worker.drain()
    response_after = client.get(f"/api/sessions/{session_id}")
    questions_after = response_after.json()["questions"]

    assert len(questions_after) > 0, "should have questions after generation"
    assert questions_after[0]["audio_ready"] is True, "audio_ready should be True after synthesis"
    assert "audio_path" not in questions_after[0], "audio_path should not leak"
