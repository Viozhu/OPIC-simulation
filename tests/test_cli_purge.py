"""`opic --purge-expired`: the operator's hand on the retention deadlines.

The policy runs at server startup; this command is what applies it without
starting one. Every test works inside `tmp_path` — the real `data/sessions` is
never the root of anything here.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from opic.cli import purge_expired
from opic.session import store

NOW = datetime(2026, 9, 1, 12, 0)


def _a_session(root: Path, days: int) -> str:
    when = NOW - timedelta(days=days)
    state = store.create(root, seed=1, now=when)
    directory = store.session_dir(root, state.id)
    stamp = when.timestamp()
    for path in [*directory.iterdir(), directory]:
        os.utime(path, (stamp, stamp))
    return state.id


def test_it_deletes_what_is_past_the_deadline_and_says_so(tmp_path: Path):
    old = _a_session(tmp_path, days=31)
    young = _a_session(tmp_path, days=1)
    lines: list[str] = []

    assert purge_expired(tmp_path, NOW, out=lines.append) == 0

    printed = "\n".join(lines)
    assert old in printed
    assert young not in printed
    assert not store.session_dir(tmp_path, old).exists()
    assert store.session_dir(tmp_path, young).exists()


def test_it_reports_the_audio_it_discarded(tmp_path: Path):
    session_id = _a_session(tmp_path, days=2)
    audio = store.answer_audio_path(tmp_path, session_id, 0, ".webm")
    audio.write_bytes(b"webm")
    store.page_path(tmp_path, session_id).write_text("<html>", encoding="utf-8")
    lines: list[str] = []

    assert purge_expired(tmp_path, NOW, out=lines.append) == 0

    assert not audio.exists()
    assert any(session_id in line and "audio" in line for line in lines)


def test_nothing_to_delete_is_not_an_error(tmp_path: Path):
    _a_session(tmp_path, days=1)
    lines: list[str] = []

    assert purge_expired(tmp_path, NOW, out=lines.append) == 0

    assert any("0 caducada" in line for line in lines)
