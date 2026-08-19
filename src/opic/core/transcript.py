from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Word:
    """One transcribed word with its timing and the model's confidence in it."""

    text: str
    start: float
    end: float
    probability: float


@dataclass(frozen=True, slots=True)
class Span:
    """A stretch of detected speech, in seconds from the start of the audio."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Transcript:
    """What a speech-to-text adapter hands back.

    `speech_spans` comes from voice activity detection, not from word timings.
    Whisper aligns words continuously, so the gaps between them do not show
    where the speaker actually stopped.
    """

    text: str
    words: tuple[Word, ...]
    speech_spans: tuple[Span, ...]
    duration_s: float

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError(f"duration_s must be positive, got {self.duration_s!r}")
