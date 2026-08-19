from __future__ import annotations


def test_the_six_levels_come_with_their_korean_description(client):
    body = client.get("/api/levels").json()
    assert [option["level"] for option in body["options"]] == [1, 2, 3, 4, 5, 6]
    assert all(option["description_ko"].strip() for option in body["options"])
    assert body["options"][0]["sample_audio_id"] == "sample_1"
