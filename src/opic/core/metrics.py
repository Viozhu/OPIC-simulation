from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from opic.core.transcript import Word

PAUSE_THRESHOLD_S = 0.5
LOW_CONFIDENCE_THRESHOLD = 0.6

# Only true hesitation markers. Words like "like", "so" and "well" carry
# meaning far more often than they stall, and counting them would punish
# ordinary English.
FILLERS: frozenset[str] = frozenset(
    {"uh", "um", "umm", "erm", "er", "ah", "eh", "mm", "hmm", "mhm"}
)

_STRIP = ".,!?;:\"'()[]…-"


@dataclass(frozen=True, slots=True)
class AnswerMetrics:
    duration_s: float
    word_count: int
    words_per_minute: float
    pause_ratio: float
    filler_count: int
    filler_rate: float
    type_token_ratio: float
    mean_utterance_length: float
    mean_confidence: float
    low_confidence_rate: float


def _normalise(text: str) -> str:
    return text.strip().strip(_STRIP).lower()


def compute_metrics(words: Sequence[Word], duration_s: float) -> AnswerMetrics:
    """Derive the objective half of the score from word-level timings.

    Everything here is arithmetic, which is exactly why it does not go to the
    model: a local LLM will happily invent a words-per-minute figure.
    """
    if duration_s <= 0:
        raise ValueError(f"duration_s must be positive, got {duration_s!r}")

    count = len(words)
    if count == 0:
        return AnswerMetrics(
            duration_s=duration_s,
            word_count=0,
            words_per_minute=0.0,
            pause_ratio=0.0,
            filler_count=0,
            filler_rate=0.0,
            type_token_ratio=0.0,
            mean_utterance_length=0.0,
            mean_confidence=0.0,
            low_confidence_rate=0.0,
        )

    tokens = [_normalise(word.text) for word in words]
    spoken = [token for token in tokens if token]

    paused = 0.0
    breaks = 0
    for earlier, later in zip(words, words[1:], strict=False):
        gap = later.start - earlier.end
        if gap > PAUSE_THRESHOLD_S:
            paused += gap
            breaks += 1

    fillers = sum(1 for token in spoken if token in FILLERS)
    confidences = [word.probability for word in words]
    doubtful = sum(1 for value in confidences if value < LOW_CONFIDENCE_THRESHOLD)

    return AnswerMetrics(
        duration_s=duration_s,
        word_count=count,
        words_per_minute=count / duration_s * 60.0,
        pause_ratio=min(1.0, paused / duration_s),
        filler_count=fillers,
        filler_rate=fillers / count,
        type_token_ratio=len(set(spoken)) / len(spoken) if spoken else 0.0,
        mean_utterance_length=count / (breaks + 1),
        mean_confidence=sum(confidences) / count,
        low_confidence_rate=doubtful / count,
    )
