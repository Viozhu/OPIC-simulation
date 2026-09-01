"""The server is what applies the retention deadlines, once, as it comes up.

`tmp_path` throughout: `apply_retention` takes its root, and the point of it
taking one is that no test ever has to name the real `data/sessions`.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from opic.session import store
from opic.web.serve import apply_retention

NOW = datetime(2026, 9, 1, 12, 0)


def _a_session(root: Path, days: int) -> str:
    when = NOW - timedelta(days=days)
    state = store.create(root, seed=1, now=when)
    directory = store.session_dir(root, state.id)
    stamp = when.timestamp()
    for path in [*directory.iterdir(), directory]:
        os.utime(path, (stamp, stamp))
    return state.id


def test_starting_the_server_deletes_what_expired_while_it_was_off(tmp_path: Path):
    old = _a_session(tmp_path, days=31)
    young = _a_session(tmp_path, days=3)

    swept = apply_retention(tmp_path, NOW)

    assert swept.expired == (old,)
    assert store.session_dir(tmp_path, young).exists()


def test_a_sweep_that_fails_does_not_stop_the_server_coming_up(tmp_path: Path):
    """A candidate locked out by a folder that will not delete is the worse bug."""
    not_a_folder = tmp_path / "sessions"
    not_a_folder.write_text("", encoding="utf-8")

    assert apply_retention(not_a_folder, NOW).expired == ()
