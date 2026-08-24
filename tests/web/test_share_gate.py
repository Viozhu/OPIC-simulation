"""The gate that makes a shared link safe to hand to one person.

The app has no notion of who owns a session: `GET /api/sessions/{id}` answers
anybody. When the server is only reachable on localhost that is fine. Behind a
tunnel it is not, so the whole app goes behind one shared secret carried in the
link itself.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from opic.web.app import SHARE_COOKIE, create_app

TOKEN = "s3cret-token-for-the-family"


@pytest.fixture
def guarded(sessions_root, worker) -> TestClient:
    app = create_app(
        root=sessions_root,
        worker=worker,
        clock=lambda: datetime(2026, 8, 24, 17, 0, 0),
        share_token=TOKEN,
    )
    return TestClient(app)


def test_without_a_token_the_app_is_open(client):
    """Localhost keeps working exactly as before; the gate is opt in."""
    assert client.get("/api/levels").status_code == 200


def test_a_visitor_with_no_key_is_told_nothing(guarded):
    response = guarded.get("/", follow_redirects=False)
    assert response.status_code == 404


def test_the_api_is_behind_the_gate_too_not_just_the_page(guarded):
    """The interesting things to steal are under /api, so it is not enough
    to guard the front page."""
    assert guarded.get("/api/levels").status_code == 404
    assert guarded.post("/api/sessions").status_code == 404


def test_a_wrong_key_is_indistinguishable_from_no_key(guarded):
    assert guarded.get("/?k=not-the-token", follow_redirects=False).status_code == 404


def test_the_right_key_opens_the_door_and_the_key_leaves_the_url(guarded):
    response = guarded.get(f"/?k={TOKEN}", follow_redirects=False)

    assert response.status_code == 303
    # The candidate reloads, bookmarks and shows this URL to other people. The
    # token has no business staying in the address bar, the history or a
    # Referer header once the cookie exists.
    assert response.headers["location"] == "http://testserver/"


def test_once_through_the_gate_the_cookie_carries_it(guarded):
    guarded.get(f"/?k={TOKEN}")

    assert guarded.get("/api/levels").status_code == 200
    assert guarded.post("/api/sessions").status_code == 201


def test_the_cookie_is_not_readable_from_javascript(guarded):
    response = guarded.get(f"/?k={TOKEN}", follow_redirects=False)

    cookie = response.headers["set-cookie"]
    assert SHARE_COOKIE in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.replace("samesite", "SameSite")


def test_behind_a_tunnel_the_cookie_is_marked_secure(guarded):
    """cloudflared speaks plain HTTP to the app and reports the real scheme in
    a header. Without reading it, the cookie would never carry the Secure flag
    in the one deployment where it matters."""
    response = guarded.get(
        f"/?k={TOKEN}",
        headers={"x-forwarded-proto": "https"},
        follow_redirects=False,
    )

    assert "Secure" in response.headers["set-cookie"]


def test_on_plain_http_the_cookie_is_not_secure_or_it_would_never_arrive(guarded):
    response = guarded.get(f"/?k={TOKEN}", follow_redirects=False)

    assert "Secure" not in response.headers["set-cookie"]


def test_a_key_in_a_deep_link_survives_the_redirect(guarded):
    """The link that gets shared may point anywhere, and the query is stripped
    without losing the path or the other parameters."""
    response = guarded.get(
        f"/api/levels?k={TOKEN}&keep=this",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "http://testserver/api/levels?keep=this"
