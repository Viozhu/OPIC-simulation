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
