from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path

from opic.adapters import config


def cache_path(text: str, voice: str, rate: int, cache_dir: Path) -> Path:
    """Where this exact wording, in this voice, at this speed, is cached.

    Content addressed, so a question repeated across sessions is synthesised
    once and never again.

    `rate` is part of the key and is required rather than defaulted, because a
    caller that omits it gets silence rather than an error: every question
    already spoken stays cached under the old key and keeps playing at the old
    speed, which is indistinguishable from a speed setting that does nothing.
    """
    digest = hashlib.sha256(f"{voice}\n{rate}\n{text}".encode()).hexdigest()
    return cache_dir / f"{digest}.wav"


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)


class SayTextToSpeech:
    """Speaks a question using macOS `say`, resampled by ffmpeg.

    The cache path is written by rename, so an interrupted conversion cannot
    leave a corrupt entry that later runs would trust as valid.

    `runner` exists so tests can prove the cache short-circuits synthesis
    without shelling out.
    """

    def __init__(
        self,
        cache_dir: Path,
        voice: str = config.SAY_VOICE,
        rate: int = config.SAY_RATE,
        runner: Callable[[list[str]], None] = _run,
    ) -> None:
        self._cache_dir = cache_dir
        self._voice = voice
        self._rate = rate
        self._run = runner

    def synthesize(self, text: str) -> Path:
        if not text.strip():
            raise ValueError("cannot synthesise empty text")

        target = cache_path(text, self._voice, self._rate, self._cache_dir)
        if target.exists():
            return target

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        raw = target.with_name(target.name + ".aiff")
        pending = target.with_name(target.name + ".part")
        try:
            self._run(
                ["say", "-v", self._voice, "-r", str(self._rate), "-o", str(raw), text]
            )
            self._run(
                [
                    "ffmpeg", "-v", "error", "-y",
                    "-i", str(raw),
                    "-ar", str(config.TTS_SAMPLE_RATE),
                    "-ac", "1",
                    "-f", "wav",
                    str(pending),
                ]
            )
            pending.replace(target)
        finally:
            raw.unlink(missing_ok=True)
            pending.unlink(missing_ok=True)
        return target
