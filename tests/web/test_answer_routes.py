from __future__ import annotations

import threading
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "answer.webm"

ALLOWED_AUDIO_SUFFIXES = {".webm", ".mp4", ".m4a", ".ogg", ".wav"}


def ready_for_the_test(client, worker, a_valid_survey) -> str:
    session_id = client.post("/api/sessions").json()["id"]
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    client.put(f"/api/sessions/{session_id}/level", json={"level": 4})
    worker.drain()
    for step in ("sample", "test"):
        client.post(f"/api/sessions/{session_id}/step", json={"step": step})
    return session_id


def upload(client, session_id: str, index: int, filename: str = "answer.webm"):
    with FIXTURE.open("rb") as audio:
        return client.post(
            f"/api/sessions/{session_id}/answers/{index}",
            files={"audio": (filename, audio, "audio/webm")},
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


def test_a_pathological_filename_extension_does_not_crash_the_upload(client, worker, a_valid_survey):
    """A 1000-char suffix used to reach `write_bytes` untouched and blow up
    with `OSError: File name too long`. It must now be clamped to a safe
    extension instead, so the upload still succeeds (202) rather than 500."""
    session_id = ready_for_the_test(client, worker, a_valid_survey)
    pathological_filename = "x." + "A" * 1000

    response = upload(client, session_id, 0, filename=pathological_filename)

    assert response.status_code != 500
    assert response.status_code == 202
    session_dir = client.app.state.root / session_id
    stored = [p for p in session_dir.glob("answer-00.*") if not p.name.endswith(".part")]
    assert len(stored) == 1
    assert stored[0].suffix in ALLOWED_AUDIO_SUFFIXES
    assert stored[0].read_bytes() == FIXTURE.read_bytes()


def test_a_traversal_filename_still_lands_inside_the_session_directory(client, worker, a_valid_survey):
    """`Path(...).suffix` drops any embedded slashes, so a filename trying to
    escape the session directory can only ever influence the extension, never
    the location. This pins that behaviour under test."""
    session_id = ready_for_the_test(client, worker, a_valid_survey)

    response = upload(client, session_id, 0, filename="../../etc/passwd")

    assert response.status_code == 202
    session_dir = client.app.state.root / session_id
    stored = [p for p in session_dir.glob("answer-00.*") if not p.name.endswith(".part")]
    assert len(stored) == 1
    assert stored[0].parent == session_dir
    assert stored[0].read_bytes() == FIXTURE.read_bytes()


def test_only_one_of_two_concurrent_uploads_for_the_same_index_wins(client, worker, a_valid_survey):
    """Two genuinely concurrent uploads race for the same answer. `Worker.update`
    serialises them under its lock, so exactly one PENDING -> RECORDED claim
    can win; the other must see the already-RECORDED state and be refused,
    rather than both writing the final path and silently discarding one."""
    session_id = ready_for_the_test(client, worker, a_valid_survey)
    barrier = threading.Barrier(2)
    results: list[int] = []
    results_lock = threading.Lock()

    def attempt() -> None:
        barrier.wait(timeout=5)
        status = upload(client, session_id, 0).status_code
        with results_lock:
            results.append(status)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(results) == [202, 409]
    session_dir = client.app.state.root / session_id
    stored = [p for p in session_dir.glob("answer-00.*") if not p.name.endswith(".part")]
    assert len(stored) == 1
    assert stored[0].read_bytes() == FIXTURE.read_bytes()


def test_a_rejected_upload_leaves_no_part_file_behind(client, worker, a_valid_survey):
    session_id = ready_for_the_test(client, worker, a_valid_survey)
    upload(client, session_id, 0)

    response = upload(client, session_id, 0)

    assert response.status_code == 409
    session_dir = client.app.state.root / session_id
    assert list(session_dir.glob("*.part")) == []
