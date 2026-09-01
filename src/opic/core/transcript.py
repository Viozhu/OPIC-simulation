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

    def clipped(self, seconds: float) -> Transcript:
        """The first `seconds` of this transcript, or itself if it is shorter.

        Every timing here is an offset into the recording, so cutting is a
        matter of dropping what starts past the mark and shortening whatever
        straddles it. A word is kept whole or not at all: half a word is not a
        word, and everything downstream counts words.
        """
        if seconds <= 0:
            raise ValueError(f"seconds must be positive, got {seconds!r}")
        if self.duration_s <= seconds:
            return self
        words = tuple(word for word in self.words if word.end <= seconds)
        return Transcript(
            # Rebuilt from the words that survived rather than cut out of
            # `text`: the text has no timings in it, so there is no honest way
            # to find the mark inside it.
            text=" ".join(word.text.strip() for word in words).strip(),
            words=words,
            speech_spans=tuple(
                Span(span.start, min(span.end, seconds))
                for span in self.speech_spans
                if span.start < seconds
            ),
            duration_s=seconds,
        )
