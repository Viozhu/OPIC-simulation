from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from opic.core.transcript import Span, Transcript, Word

PAUSE_THRESHOLD_S = 0.5
LOW_CONFIDENCE_THRESHOLD = 0.6

_STRIP = ".,!?;:\"'()[]…-"


@dataclass(frozen=True, slots=True)
class AnswerMetrics:
    # The time the candidate had to answer in, which is not the length of the
    # recording: the microphone keeps running while the question is replayed,
    # and `compute_metrics` takes those stretches back out. Everything derived
    # from time here — speed, silence — is measured against this window, so a
    # candidate who used their one replay is not reported as slower for it.
    duration_s: float
    word_count: int
    words_per_minute: float
    pause_ratio: float
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


def clip_spans(spans: Sequence[Span], start: float, end: float) -> tuple[Span, ...]:
    """The parts of `spans` that fall inside [start, end), overlaps merged.

    Merging first is what makes `total_duration` of the result a length rather
    than a sum: two spans covering the same second must count that second once.
    """
    inside = []
    for span in merge_spans(spans, threshold=0.0):
        low, high = max(span.start, start), min(span.end, end)
        if high > low:
            inside.append(Span(low, high))
    return tuple(inside)


def total_duration(spans: Sequence[Span]) -> float:
    return sum(span.duration for span in spans)


def compute_metrics(
    transcript: Transcript,
    replayed: Sequence[Span] = (),
) -> AnswerMetrics:
    """Derive the objective half of the score.

    Everything here is arithmetic, which is exactly why it does not go to the
    model: a local LLM will happily invent a words-per-minute figure.

    Pauses come from voice activity spans rather than from gaps between word
    timings. Whisper aligns words continuously, so those gaps stay near zero
    however long the speaker actually hesitated.

    The spans must come from a detector tuned to split on ordinary hesitation:
    silences of roughly a quarter second, with no padding added around speech.
    faster-whisper's defaults (min_silence_duration_ms=2000, speech_pad_ms=400)
    are far too coarse — under them no gap below about 1.2s can exist, the
    merge threshold never fires, and these metrics collapse back to the values
    that made them useless in the first place.

    `replayed` is when the question audio was playing back over the live
    microphone, in seconds from the start of the recording, as reported by the
    browser. The candidate is not answering during those stretches, so they
    come out of the answering window before speed and silence are measured;
    `transcript.duration_s` keeps the real length of the file, because the word
    and span timings are offsets into it.
    """
    words = transcript.words
    count = len(words)

    dead = clip_spans(replayed, 0.0, transcript.duration_s)
    duration_s = transcript.duration_s - total_duration(dead)
    if duration_s <= 0:
        # A recording that is nothing but replay cannot also hold an answer, so
        # the reported spans are wrong. Fall back to the file's own length
        # rather than divide a word count by a window of zero seconds.
        dead = ()
        duration_s = transcript.duration_s

    if count == 0:
        return AnswerMetrics(
            duration_s=duration_s,
            word_count=0,
            words_per_minute=0.0,
            pause_ratio=0.0,
            type_token_ratio=0.0,
            mean_utterance_length=0.0,
            mean_confidence=0.0,
            low_confidence_rate=0.0,
        )

    utterances = merge_spans(transcript.speech_spans)
    if utterances:
        first, last = utterances[0].start, utterances[-1].end
        # A replay taken mid-answer leaves a silence between two utterances
        # that the candidate did not choose; counting it would report them as
        # hesitant for having used the button the real exam also gives them.
        window = last - first - total_duration(clip_spans(dead, first, last))
        paused = sum(
            (later.start - earlier.end)
            - total_duration(clip_spans(dead, earlier.end, later.start))
            for earlier, later in zip(utterances, utterances[1:], strict=False)
        )
        pause_ratio = min(1.0, paused / window) if window > 0 else 0.0
        mean_utterance_length = count / len(utterances)
    else:
        raise ValueError(
            "transcript has words but no speech_spans; pause and utterance "
            "metrics require voice activity detection"
        )

    tokens = [_normalise(word.text) for word in words]
    spoken = [token for token in tokens if token]
    confidences = [word.probability for word in words]
    doubtful = sum(1 for value in confidences if value < LOW_CONFIDENCE_THRESHOLD)

    return AnswerMetrics(
        duration_s=duration_s,
        word_count=count,
        words_per_minute=count / duration_s * 60.0,
        pause_ratio=pause_ratio,
        type_token_ratio=len(set(spoken)) / len(spoken) if spoken else 0.0,
        mean_utterance_length=mean_utterance_length,
        mean_confidence=sum(confidences) / count,
        low_confidence_rate=doubtful / count,
    )
