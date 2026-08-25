from __future__ import annotations

import os
from pathlib import Path

# Text to speech. macOS `say`, because it ships with the system and everything
# else here already runs locally on this machine.
#
# An earlier note in this file blamed piper-tts for baking the build machine's
# data path into its espeak-ng binary. The path is baked in, but that is not
# why it failed. espeak-ng holds the data directory in a 160-character buffer:
# a longer path is truncated, the compiled-in default is used instead, and the
# process exits when `phontab` is not there. Measured with piper-tts 1.7.0 on
# macOS arm64 — 67, 101, 131 and 151 characters synthesise; 161 and 171 die.
# It is piper1-gpl issue #272, still open, with PR #281 unmerged.
#
# So Piper is viable on both Linux and macOS, and is what a container would
# use. Whatever installs it has to keep the path to `piper/espeak-ng-data`
# under 160 characters, and prove it with a test — moving the project to a
# deeper directory is enough to break synthesis with an error that points
# somewhere else entirely.
SAY_VOICE = "Samantha"

# Words per minute for `say`. The default delivery was too fast to sit an exam
# against — a candidate hears each question once, twice at most, and has to
# parse it before the recording starts.
#
# `say` quantises this: measured against a real fifteen-question exam, 115-140
# all produce one duration, 85-105 the next, 60-75 the next. So there are three
# steps below the default, worth +10%, +20% and +30% of speaking time. This is
# the middle one, chosen by listening to all four.
SAY_RATE = 95
TTS_SAMPLE_RATE = 16000

# Speech to text.
WHISPER_MODEL = "medium"
WHISPER_COMPUTE_TYPE = "int8"

# The voice-activity contract. faster-whisper's defaults are 2000 and 400, under
# which no silence below about 1.2s can exist, the 0.5s merge threshold in
# core/metrics.py never fires, and pause_ratio collapses to 0.02 with
# mean_utterance_length at 75 — the exact numbers that made those metrics
# useless. Measured on evidence/sample-answer.wav; with the values below the
# same recording yields pause_ratio 0.23 and mean_utterance_length 6.8.
VAD_MIN_SILENCE_MS = 250
VAD_SPEECH_PAD_MS = 0

# The rater. Measured against evidence/sample-transcript.json (see
# docs/superpowers/notes/2026-08-19-rater-model.md): qwen3:8b failed 4 of 5
# rating calls with a timeout at OLLAMA_TIMEOUT_S, and its one completed call
# duplicated one rubric dimension while omitting another. qwen3:14b passed 5/5
# with all five dimensions distinct and zero evidence discarded, so it is
# pinned here despite being the slower model per raw tokens/second.
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3:14b"
OLLAMA_TIMEOUT_S = 600


# ---------------------------------------------------------------- the backend

# Which language model writes the questions and rates the answers. The two
# adapters implement the same two ports, so this is the only place that decides.
#
# `anthropic` is the default: the local rater returned the same level (IH) for
# all fifteen answers of a real exam, which is not a grade but a constant, and
# grading took about 75 minutes of machine time. `ollama` keeps the offline path
# alive — it needs no key and no network, and it is the baseline the rater bench
# compares against.
LLM_BACKENDS = ("anthropic", "ollama")


def backend() -> str:
    chosen = os.environ.get("OPIC_LLM", "anthropic").strip().lower()
    if chosen not in LLM_BACKENDS:
        raise ValueError(
            f"OPIC_LLM={chosen!r} is not one of {LLM_BACKENDS}"
        )
    return chosen


# Haiku 4.5 rejects `output_config.effort` outright, so nothing here sends it.
# It is the cheapest model the rater bench was able to run end to end against
# the product's own schema.
ANTHROPIC_MODEL = "claude-haiku-4-5"
ANTHROPIC_MAX_TOKENS = 16000
ANTHROPIC_TIMEOUT_S = 300

# The key is read from the environment under either name: `API_KEY_ANTHROPIC`,
# which is what this project's `.env` uses, or `ANTHROPIC_API_KEY`, which is
# what the SDK and every other Anthropic tool use. Neither being set is not an
# error — the SDK also accepts an `ant auth login` profile, so the client is
# left to resolve credentials itself in that case.
API_KEY_NAMES = ("API_KEY_ANTHROPIC", "ANTHROPIC_API_KEY")


def anthropic_api_key() -> str | None:
    for name in API_KEY_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def find_env_file(start: Path | None = None) -> Path | None:
    """The project's `.env`, looked for from `start` upward.

    `.env` sits at the project root and the process does not always start
    there: a git worktree, a `cd` into `src/`, an editor's terminal. Resolving
    it against the working directory alone meant that in any of those the file
    contributed nothing — silently, since a missing `.env` is not an error —
    and credentials fell through to whatever was exported. A stale
    `ANTHROPIC_API_KEY` then produced a 401 while the good key sat unread at
    the root.

    The walk stops at the project root rather than continuing to the
    filesystem root, so an unrelated `.env` in a parent or home directory can
    never hand credentials to this project. `pyproject.toml` marks the root.
    """
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / ".env"
        if candidate.exists():
            return candidate
        if (directory / "pyproject.toml").exists():
            # A linked worktree is the same project, and `.env` is git-ignored,
            # so it is never copied into one. Stopping here would stop one
            # directory short of the only `.env` there is.
            main = _main_checkout_of_worktree(directory)
            return find_env_file(main) if main is not None else None
    return None


def _main_checkout_of_worktree(directory: Path) -> Path | None:
    """Where a linked worktree's main checkout lives, or `None` if this is not one.

    In a linked worktree `.git` is a file holding `gitdir: <repo>/.git/worktrees/<name>`,
    so the main checkout is that path with the last three components removed.
    """
    marker = directory / ".git"
    if not marker.is_file():
        return None
    try:
        line = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = Path(line.partition(":")[2].strip())
    if gitdir.parent.name != "worktrees" or gitdir.parent.parent.name != ".git":
        return None
    return gitdir.parent.parent.parent


def load_env_file(path: Path | None = None) -> None:
    """Read `.env` into the environment, without overwriting what is already set.

    Written by hand rather than pulled in as a dependency: the file holds one
    key and the format needed is `NAME=value`. A real shell parser is not worth
    a package here.

    An exported variable always wins over the file, so a key given for one run
    is not silently overridden by a stale `.env`.
    """
    target = path or find_env_file()
    if target is None:
        return
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip("'\"")
        if name and name not in os.environ:
            os.environ[name] = value
