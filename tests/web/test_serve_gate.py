"""FINDING: `serve.app()` used to come up ungated whenever `OPIC_SHARE_TOKEN`
was empty or missing, silently — the deployment path (the uvicorn factory a
tunnel or a launchd agent runs) must instead refuse to start, so a `.env.deploy`
that goes missing or fails to `source` cannot bring the app back up public.
`local=True` (the CLI's `--serve`, bound to 127.0.0.1) is the one exception.

Everything below `app()`'s gate check touches real adapters and a real lock
file, so the "does not raise" cases replace them with doubles before calling
`app()` — none of these tests should construct a real LLM client, load a real
Whisper model, or write `.server.lock` anywhere but a `tmp_path`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opic.web import serve


class _DummyWorker:
    def __init__(self, **kwargs) -> None:
        pass

    def resume(self) -> None:
        pass

    def start(self) -> None:
        pass


def _stub_out_real_adapters(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(serve, "SESSIONS", tmp_path / "sessions")
    monkeypatch.setattr(serve, "claim_the_lock", lambda root: None)
    monkeypatch.setattr(serve, "make_llm_client", lambda: object())
    monkeypatch.setattr(serve, "make_sheet_sink", lambda: None)
    monkeypatch.setattr(serve, "SayTextToSpeech", lambda cache_dir: object())
    monkeypatch.setattr(serve, "WhisperSpeechToText", lambda: object())
    monkeypatch.setattr(serve, "Worker", _DummyWorker)


def test_no_token_and_not_local_refuses_to_start(monkeypatch):
    monkeypatch.delenv("OPIC_SHARE_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="OPIC_SHARE_TOKEN"):
        serve.app()


def test_a_blank_token_and_not_local_refuses_to_start(monkeypatch):
    monkeypatch.setenv("OPIC_SHARE_TOKEN", "   ")

    with pytest.raises(RuntimeError, match="OPIC_SHARE_TOKEN"):
        serve.app()


def test_no_token_and_local_starts_anyway(monkeypatch, tmp_path):
    monkeypatch.delenv("OPIC_SHARE_TOKEN", raising=False)
    _stub_out_real_adapters(monkeypatch, tmp_path)

    serve.app(local=True)  # must not raise


def test_a_token_and_not_local_starts(monkeypatch, tmp_path):
    monkeypatch.setenv("OPIC_SHARE_TOKEN", "a-real-token")
    _stub_out_real_adapters(monkeypatch, tmp_path)

    serve.app()  # must not raise
