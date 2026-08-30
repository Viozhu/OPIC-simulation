from __future__ import annotations

import hashlib
import re
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


# Where a question breaks. Measured over the 105 questions in `data/sessions`:
# only 22 have a second sentence, but 23 use an em-dash for the same setup /
# question beat, and the remaining 62 are one sentence of up to 28 words whose
# sub-questions are separated by commas. Pausing at sentences alone would reach
# a fifth of them, so all three are cuts here.
#
# Both patterns match the whitespace *after* the mark and leave the mark itself
# in the text. An earlier version cut the em-dash out and put a silence in its
# place; that measured the same length, but it threw away whatever intonation
# the voice does at a dash to buy back a pause it had just deleted. Keeping the
# mark cannot be worse and is the flatness this is trying to fix. The silence
# that follows is governed by the 200ms floor documented in adapters/config.py.
_AFTER_FULL_BREAK = re.compile(r"(?<=[.?!;:\u2014\u2013])\s+|(?<=\s-)\s+")
_AFTER_CLAUSE = re.compile(r"(?<=,)\s+")


def with_prosody(
    text: str,
    lead_in_ms: int = config.TTS_LEAD_IN_MS,
    sentence_pause_ms: int = config.TTS_SENTENCE_PAUSE_MS,
    clause_pause_ms: int = config.TTS_CLAUSE_PAUSE_MS,
) -> str:
    """The wording as `say` will actually receive it, silences included.

    A lead-in so the question does not start on the same instant as the audio,
    a longer stop where the setup ends and the question begins, and a shorter
    one between sub-questions, because a candidate hears this once and has to
    hold all three parts of "what did you do, where did you go, and what made
    it memorable" at the same time.

    A pause of 0 inserts nothing rather than a `[[slnc 0]]`: the marker is part
    of the cache key, so an inaudible one would resynthesise every question to
    produce identical audio.

    A literal `[[` in the source text would be read as an embedded speech
    command and swallowed, so it is broken up rather than passed through: a
    question is written by a model and nothing guarantees it never contains
    one.
    """
    spoken = text.replace("[[", "[ [").strip()
    if sentence_pause_ms > 0:
        spoken = _AFTER_FULL_BREAK.sub(f" [[slnc {sentence_pause_ms}]] ", spoken)
    if clause_pause_ms > 0:
        spoken = _AFTER_CLAUSE.sub(f" [[slnc {clause_pause_ms}]] ", spoken)
    if lead_in_ms > 0:
        spoken = f"[[slnc {lead_in_ms}]] {spoken}"
    return spoken


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
        lead_in_ms: int = config.TTS_LEAD_IN_MS,
        sentence_pause_ms: int = config.TTS_SENTENCE_PAUSE_MS,
        clause_pause_ms: int = config.TTS_CLAUSE_PAUSE_MS,
    ) -> None:
        self._cache_dir = cache_dir
        self._voice = voice
        self._rate = rate
        self._run = runner
        self._lead_in_ms = lead_in_ms
        self._sentence_pause_ms = sentence_pause_ms
        self._clause_pause_ms = clause_pause_ms

    def synthesize(self, text: str) -> Path:
        if not text.strip():
            raise ValueError("cannot synthesise empty text")

        # Keyed on the marked-up wording, not the raw question: the silences
        # change the audio, so they have to change the cache entry too, or a
        # question already spoken keeps playing without them.
        spoken = with_prosody(
            text, self._lead_in_ms, self._sentence_pause_ms, self._clause_pause_ms
        )
        target = cache_path(spoken, self._voice, self._rate, self._cache_dir)
        if target.exists():
            return target

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        raw = target.with_name(target.name + ".aiff")
        pending = target.with_name(target.name + ".part")
        try:
            self._run(
                [
                    "say", "-v", self._voice, "-r", str(self._rate),
                    "-o", str(raw), spoken,
                ]
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
