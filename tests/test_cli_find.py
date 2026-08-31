from __future__ import annotations

from datetime import datetime
from pathlib import Path

from opic.cli import find_sessions
from opic.core.candidate import Candidate
from opic.session import store


def _a_session(root: Path, name: str, email: str, when: datetime) -> str:
    state = store.create(root, seed=1, now=when)
    store.save(root, state.with_candidate(Candidate(name, email)))
    return state.id


def test_it_finds_by_email(tmp_path: Path):
    wanted = _a_session(tmp_path, "김민준", "minjun@example.com", datetime(2026, 8, 31, 9, 0))
    _a_session(tmp_path, "이서연", "seoyeon@example.com", datetime(2026, 8, 31, 10, 0))
    lines: list[str] = []
    assert find_sessions(tmp_path, "minjun", out=lines.append) == 0
    printed = "\n".join(lines)
    assert wanted in printed
    assert "seoyeon" not in printed


def test_it_finds_by_name_and_ignores_case(tmp_path: Path):
    wanted = _a_session(tmp_path, "Minjun Kim", "m@example.com", datetime(2026, 8, 31, 9, 0))
    lines: list[str] = []
    find_sessions(tmp_path, "MINJUN", out=lines.append)
    assert wanted in "\n".join(lines)


def test_nothing_found_is_not_an_error(tmp_path: Path):
    _a_session(tmp_path, "김민준", "minjun@example.com", datetime(2026, 8, 31, 9, 0))
    lines: list[str] = []
    assert find_sessions(tmp_path, "nobody", out=lines.append) == 0
    assert any("0" in line for line in lines)


def test_a_session_with_no_candidate_does_not_crash_it(tmp_path: Path):
    store.create(tmp_path, seed=1, now=datetime(2026, 8, 31, 9, 0))
    lines: list[str] = []
    assert find_sessions(tmp_path, "minjun", out=lines.append) == 0


def test_a_malformed_result_json_does_not_crash_it(tmp_path: Path):
    wanted = _a_session(tmp_path, "김민준", "minjun@example.com", datetime(2026, 8, 31, 9, 0))
    result = store.result_path(tmp_path, wanted)
    result.write_text("[1, 2, 3]", encoding="utf-8")
    lines: list[str] = []
    assert find_sessions(tmp_path, "minjun", out=lines.append) == 0
    printed = "\n".join(lines)
    assert wanted in printed
    assert "?" in printed
