from __future__ import annotations

import json


def test_the_report_is_a_404_until_the_exam_is_scored(client, session_id):
    assert client.get(f"/api/sessions/{session_id}/report").status_code == 404


def test_the_report_carries_the_sections_the_screen_needs(client, scored_session):
    payload = client.get(f"/api/sessions/{scored_session}/report").json()

    assert payload["final_level"]
    assert payload["expected_answers"] >= payload["scored_answers"]
    assert len(payload["dimensions"]) == 5
    assert payload["dimensions"][0]["label_ko"] == "유창성"
    assert "unclear" in payload
    assert "answers" in payload


def test_a_corrupt_answer_file_does_not_cost_the_whole_report(
    client, scored_session, sessions_root
):
    broken = sessions_root / scored_session / "answer-00.json"
    broken.write_text("{ not json", encoding="utf-8")

    payload = client.get(f"/api/sessions/{scored_session}/report").json()

    assert payload["answers"][0]["state"] == "unreadable"
    assert payload["scored_answers"] >= 1


def test_every_answer_unreadable_is_still_a_404_not_a_500(
    client, scored_session, sessions_root
):
    """`result.json` exists, but not a single `answer-NN.json` can be read.

    Distinct from the single-broken-file case above: there `judged` still has
    entries, so a report can be built. Here `judged` is empty, and the route
    must 404 rather than crash or return an empty report."""
    session_dir = sessions_root / scored_session
    for answer_file in session_dir.glob("answer-*.json"):
        answer_file.write_text("{ not json", encoding="utf-8")

    response = client.get(f"/api/sessions/{scored_session}/report")

    assert response.status_code == 404


def test_the_raw_result_route_is_unchanged(client, scored_session):
    payload = client.get(f"/api/sessions/{scored_session}/result").json()
    assert set(payload) >= {
        "final_level",
        "scored_answers",
        "expected_answers",
        "dimensions",
        "by_type",
        "by_topic",
        "pronunciation",
        "answers",
    }
