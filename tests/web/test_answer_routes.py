from __future__ import annotations

from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "answer.webm"


def ready_for_the_test(client, worker, a_valid_survey) -> str:
    session_id = client.post("/api/sessions").json()["id"]
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    client.put(f"/api/sessions/{session_id}/level", json={"level": 4})
    worker.drain()
    for step in ("sample", "test"):
        client.post(f"/api/sessions/{session_id}/step", json={"step": step})
    return session_id


def upload(client, session_id: str, index: int):
    with FIXTURE.open("rb") as audio:
        return client.post(
            f"/api/sessions/{session_id}/answers/{index}",
            files={"audio": ("answer.webm", audio, "audio/webm")},
        )


def test_a_step_can_only_advance_to_the_next_one(client, worker, a_valid_survey):
    session_id = client.post("/api/sessions").json()["id"]
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    client.put(f"/api/sessions/{session_id}/level", json={"level": 4})

    assert client.post(f"/api/sessions/{session_id}/step", json={"step": "test"}).status_code == 409
    assert client.post(f"/api/sessions/{session_id}/step", json={"step": "sample"}).status_code == 200


def test_uploading_an_answer_stores_it_and_answers_immediately(client, worker, a_valid_survey):
    session_id = ready_for_the_test(client, worker, a_valid_survey)

    response = upload(client, session_id, 0)

    assert response.status_code == 202
    assert response.json()["answers"][0]["state"] == "recorded"
    stored = client.app.state.root / session_id / "answer-00.webm"
    assert stored.exists()
    assert stored.read_bytes() == FIXTURE.read_bytes()


def test_the_queued_answer_is_scored_when_the_worker_runs(client, worker, a_valid_survey):
    session_id = ready_for_the_test(client, worker, a_valid_survey)
    upload(client, session_id, 0)

    worker.drain()

    progress = client.get(f"/api/sessions/{session_id}/progress").json()
    assert progress["scored"] == 1
    assert progress["failed"] == 0
    assert progress["total"] == progress["expected"]
    assert progress["done"] is False


def test_uploading_to_a_session_that_is_not_in_the_test_is_refused(client, worker, a_valid_survey):
    session_id = client.post("/api/sessions").json()["id"]
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    assert upload(client, session_id, 0).status_code == 409


def test_uploading_the_same_answer_twice_is_refused(client, worker, a_valid_survey):
    session_id = ready_for_the_test(client, worker, a_valid_survey)
    upload(client, session_id, 0)
    assert upload(client, session_id, 0).status_code == 409


def test_the_result_is_a_404_until_it_exists(client, worker, a_valid_survey):
    session_id = ready_for_the_test(client, worker, a_valid_survey)
    assert client.get(f"/api/sessions/{session_id}/result").status_code == 404


def test_a_whole_exam_ends_with_a_level(client, worker, a_valid_survey):
    session_id = ready_for_the_test(client, worker, a_valid_survey)
    total = len(client.get(f"/api/sessions/{session_id}").json()["questions"])
    for index in range(total):
        upload(client, session_id, index)
    client.post(f"/api/sessions/{session_id}/step", json={"step": "grading"})
    worker.drain()

    progress = client.get(f"/api/sessions/{session_id}/progress").json()
    assert progress["done"] is True

    result = client.get(f"/api/sessions/{session_id}/result").json()
    assert result["final_level"]
    assert result["scored_answers"] == total
    assert result["expected_answers"] == total
    assert client.get(f"/api/sessions/{session_id}").json()["step"] == "done"
