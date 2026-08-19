from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path

from opic.adapters import config


def cache_path(text: str, voice: str, cache_dir: Path) -> Path:
    """Where this exact wording, in this exact voice, is cached.

    Content addressed, so a question repeated across sessions is synthesised
    once and never again.
    """
    digest = hashlib.sha256(f"{voice}\n{text}".encode()).hexdigest()
    return cache_dir / f"{digest}.wav"


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)


class SayTextToSpeech:
    """Speaks a question using macOS `say`, resampled by ffmpeg.

    `runner` exists so tests can prove the cache short-circuits synthesis
    without shelling out.
    """

    def __init__(
        self,
        cache_dir: Path,
        voice: str = config.SAY_VOICE,
        runner: Callable[[list[str]], None] = _run,
    ) -> None:
        self._cache_dir = cache_dir
        self._voice = voice
        self._run = runner

    def synthesize(self, text: str) -> Path:
        if not text.strip():
            raise ValueError("cannot synthesise empty text")

        target = cache_path(text, self._voice, self._cache_dir)
        if target.exists():
            return target

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        raw = target.with_suffix(".aiff")
        self._run(["say", "-v", self._voice, "-o", str(raw), text])
        self._run(
            [
                "ffmpeg", "-v", "error", "-y",
                "-i", str(raw),
                "-ar", str(config.TTS_SAMPLE_RATE),
                "-ac", "1",
                str(target),
            ]
        )
        raw.unlink(missing_ok=True)
        return target
