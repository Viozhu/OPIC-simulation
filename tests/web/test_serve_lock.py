from __future__ import annotations

import os
from pathlib import Path

import pytest

from opic.web.serve import LockedError, claim_the_lock


def test_the_first_process_takes_the_lock(tmp_path: Path):
    claim_the_lock(tmp_path)
    assert (tmp_path / ".server.lock").read_text(encoding="utf-8") == str(os.getpid())


def test_a_second_live_process_is_refused(tmp_path: Path):
    claim_the_lock(tmp_path)
    with pytest.raises(LockedError) as excinfo:
        claim_the_lock(tmp_path, is_running=lambda _: True)
    assert "already running" in str(excinfo.value)


def test_a_stale_lock_from_a_dead_process_is_taken_over(tmp_path: Path):
    (tmp_path / ".server.lock").write_text("999999", encoding="utf-8")
    claim_the_lock(tmp_path, is_running=lambda _: False)
    assert (tmp_path / ".server.lock").read_text(encoding="utf-8") == str(os.getpid())


def test_an_unreadable_lock_file_is_taken_over(tmp_path: Path, monkeypatch):
    """A permission error reading the lock is not evidence a server is live.

    There is no portable, sandbox-safe way to actually strip read permission
    from a file here (root and CI sandboxes routinely ignore chmod), so this
    monkeypatches `Path.read_text` to raise `PermissionError` instead, which
    exercises exactly the branch a real unreadable file would hit.
    """
    lock = tmp_path / ".server.lock"
    lock.write_text("123", encoding="utf-8")
    original_read_text = Path.read_text

    def broken_read_text(self, *args, **kwargs):
        if self == lock:
            raise PermissionError("permission denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", broken_read_text)

    claim_the_lock(tmp_path, is_running=lambda _: True)

    monkeypatch.undo()
    assert lock.read_text(encoding="utf-8") == str(os.getpid())
