from __future__ import annotations

import ast
import pathlib

FORBIDDEN = {
    "fastapi",
    "uvicorn",
    "httpx",
    "requests",
    "ollama",
    "faster_whisper",
    "piper",
    "sqlite3",
}

CORE = pathlib.Path(__file__).resolve().parents[1] / "src" / "opic" / "core"


def imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_never_imports_infrastructure():
    offenders: dict[str, set[str]] = {}
    for path in sorted(CORE.rglob("*.py")):
        bad = imported_roots(path) & FORBIDDEN
        if bad:
            offenders[path.name] = bad
    assert offenders == {}


def test_the_purity_guard_actually_reads_the_core_modules():
    modules = {path.name for path in CORE.rglob("*.py")}
    assert {
        "rubric.py",
        "survey.py",
        "selfassess.py",
        "questions.py",
        "metrics.py",
        "scoring.py",
        "transcript.py",
        "ports.py",
    } <= modules


def test_core_never_imports_the_adapters():
    offenders = [
        path.name
        for path in sorted(CORE.rglob("*.py"))
        if "opic.adapters" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
