from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from opic.core.transcript import Span, Transcript, Word

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


def merge_spans(
    spans: Sequence[Span],
    threshold: float = PAUSE_THRESHOLD_S,
) -> tuple[Span, ...]:
    """Join speech spans separated by less than the pause threshold.

    Voice activity detection splits on breath and micro-gaps. Merging first means
    an utterance is what a listener would call one, not what the detector emitted.
    """
    if not spans:
        return ()

    ordered = sorted(spans, key=lambda span: span.start)
    merged = [ordered[0]]
    for span in ordered[1:]:
        last = merged[-1]
        if span.start - last.end < threshold:
            merged[-1] = Span(last.start, max(last.end, span.end))
        else:
            merged.append(span)
    return tuple(merged)


def compute_metrics(transcript: Transcript) -> AnswerMetrics:
    """Derive the objective half of the score.

    Everything here is arithmetic, which is exactly why it does not go to the
    model: a local LLM will happily invent a words-per-minute figure.

    Pauses come from voice activity spans rather than from gaps between word
    timings. Whisper aligns words continuously, so those gaps stay near zero
    however long the speaker actually hesitated.
    """
    words = transcript.words
    duration_s = transcript.duration_s
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

    utterances = merge_spans(transcript.speech_spans)
    if utterances:
        window = utterances[-1].end - utterances[0].start
        paused = sum(
            later.start - earlier.end
            for earlier, later in zip(utterances, utterances[1:], strict=False)
        )
        pause_ratio = min(1.0, paused / window) if window > 0 else 0.0
        mean_utterance_length = count / len(utterances)
    else:
        pause_ratio = 0.0
        mean_utterance_length = float(count)

    tokens = [_normalise(word.text) for word in words]
    spoken = [token for token in tokens if token]
    fillers = sum(1 for token in spoken if token in FILLERS)
    confidences = [word.probability for word in words]
    doubtful = sum(1 for value in confidences if value < LOW_CONFIDENCE_THRESHOLD)

    return AnswerMetrics(
        duration_s=duration_s,
        word_count=count,
        words_per_minute=count / duration_s * 60.0,
        pause_ratio=pause_ratio,
        filler_count=fillers,
        filler_rate=fillers / count,
        type_token_ratio=len(set(spoken)) / len(spoken) if spoken else 0.0,
        mean_utterance_length=mean_utterance_length,
        mean_confidence=sum(confidences) / count,
        low_confidence_rate=doubtful / count,
    )
