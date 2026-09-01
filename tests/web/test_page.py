from __future__ import annotations


def test_the_root_serves_the_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>" in response.text
    assert 'type="module"' in response.text


def test_the_static_files_are_served(client):
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/steps/survey.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_the_screen_that_asks_for_a_name_says_what_is_kept_and_for_how_long(client):
    """The retention promise is only kept if the candidate is told before typing.

    Asserted from the outside, on what the browser actually downloads: the
    deadlines in `session/retention.py` and this notice have to move together
    or one of them is a lie.
    """
    served = client.get("/static/steps/identity.js").text

    assert "30일" in served
    assert "삭제" in served
    assert "이 컴퓨터를 벗어나지 않으며" in served
