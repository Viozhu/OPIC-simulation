from __future__ import annotations

import json
import urllib.error
from contextlib import contextmanager

import pytest

from opic.adapters.sheets import (
    AppsScriptSheet,
    NullSheet,
    SheetError,
    make_sheet_sink,
)


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


def recording_opener(status: int = 200):
    """Un doble de `urlopen`: guarda la petición y no toca la red."""
    seen = []

    @contextmanager
    def opener(request, timeout=None):
        seen.append((request, timeout))
        yield FakeResponse(status)

    opener.seen = seen
    return opener


def test_it_posts_the_row_as_json():
    opener = recording_opener()
    AppsScriptSheet("https://script.google.com/macros/s/xyz/exec", opener=opener).append(
        {"email": "minjun@example.com", "rating": "5"}
    )
    request, timeout = opener.seen[0]
    assert request.method == "POST"
    assert request.full_url == "https://script.google.com/macros/s/xyz/exec"
    assert request.headers["Content-type"] == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "email": "minjun@example.com",
        "rating": "5",
    }
    assert timeout == 20.0


def test_a_refusal_raises_so_the_worker_retries():
    opener = recording_opener(status=500)
    with pytest.raises(SheetError):
        AppsScriptSheet("https://example.com/hook", opener=opener).append({"a": "b"})


def test_an_http_error_is_reported_with_status_code():
    def opener_that_raises_http_error(request, timeout=None):
        raise urllib.error.HTTPError("https://example.com", 500, "Server Error", {}, None)

    with pytest.raises(SheetError, match="answered 500"):
        AppsScriptSheet("https://example.com/hook", opener=opener_that_raises_http_error).append({"a": "b"})

    # Also verify the error message doesn't contain the transport failure wording
    try:
        AppsScriptSheet("https://example.com/hook", opener=opener_that_raises_http_error).append({"a": "b"})
    except SheetError as e:
        assert "did not answer" not in str(e)


def test_the_null_sink_swallows_everything():
    assert NullSheet().append({"a": "b"}) is None


def test_no_url_means_the_null_sink(monkeypatch):
    monkeypatch.delenv("OPIC_SHEET_URL", raising=False)
    assert isinstance(make_sheet_sink(), NullSheet)


def test_a_blank_url_means_the_null_sink(monkeypatch):
    monkeypatch.setenv("OPIC_SHEET_URL", "   ")
    assert isinstance(make_sheet_sink(), NullSheet)


def test_a_url_in_the_environment_is_used(monkeypatch):
    monkeypatch.setenv("OPIC_SHEET_URL", "https://example.com/hook")
    assert isinstance(make_sheet_sink(), AppsScriptSheet)
