from __future__ import annotations

import pytest

from opic.core.metrics import compute_metrics, merge_spans
from opic.core.transcript import Span, Transcript, Word


def make(
    texts: list[str],
    *,
    spans: list[tuple[float, float]] | None = None,
    step: float = 0.5,
    probability: float = 0.9,
    duration_s: float = 10.0,
    probabilities: list[float] | None = None,
) -> Transcript:
    words = tuple(
        Word(
            text=text,
            start=i * step,
            end=i * step + step / 2,
            probability=probabilities[i] if probabilities else probability,
        )
        for i, text in enumerate(texts)
    )
    if spans is None:
        spans = [(0.0, max(step, len(texts) * step))]
    return Transcript(
        text=" ".join(texts),
        words=words,
        speech_spans=tuple(Span(a, b) for a, b in spans),
        duration_s=duration_s,
    )


def test_merge_spans_joins_spans_closer_than_the_threshold():
    merged = merge_spans((Span(0.0, 1.0), Span(1.2, 2.0)))
    assert merged == (Span(0.0, 2.0),)


def test_merge_spans_keeps_spans_further_apart_than_the_threshold():
    spans = (Span(0.0, 1.0), Span(4.0, 5.0))
    assert merge_spans(spans) == spans


def test_merge_spans_handles_an_empty_input():
    assert merge_spans(()) == ()


def test_empty_speech_yields_zeroed_metrics():
    t = Transcript(text="", words=(), speech_spans=(), duration_s=10.0)
    m = compute_metrics(t)
    assert m.word_count == 0
    assert m.words_per_minute == 0.0
    assert m.type_token_ratio == 0.0
    assert m.pause_ratio == 0.0
    assert m.mean_utterance_length == 0.0


def test_words_per_minute_counts_words_over_the_recording_length():
    m = compute_metrics(make(["one"] * 30, duration_s=60.0))
    assert m.words_per_minute == pytest.approx(30.0)


def test_pause_ratio_measures_silence_between_utterances():
    m = compute_metrics(make(["a", "b"], spans=[(0.0, 1.0), (4.0, 5.0)], duration_s=10.0))
    assert m.pause_ratio == pytest.approx(0.6)


def test_leading_and_trailing_silence_is_not_a_pause():
    early = compute_metrics(make(["a", "b"], spans=[(0.0, 1.0), (4.0, 5.0)], duration_s=10.0))
    late = compute_metrics(make(["a", "b"], spans=[(2.0, 3.0), (6.0, 7.0)], duration_s=20.0))
    assert late.pause_ratio == pytest.approx(early.pause_ratio)


def test_a_short_gap_is_not_a_pause():
    m = compute_metrics(make(["a", "b"], spans=[(0.0, 1.0), (1.2, 2.0)], duration_s=10.0))
    assert m.pause_ratio == 0.0


def test_mean_utterance_length_divides_words_by_utterances():
    m = compute_metrics(make(["a", "b", "c"], spans=[(0.0, 1.0), (4.0, 5.0)], duration_s=10.0))
    assert m.mean_utterance_length == pytest.approx(1.5)


def test_words_without_speech_spans_are_refused():
    t = Transcript(
        text="a b c",
        words=tuple(Word(x, 0.0, 0.1, 0.9) for x in ("a", "b", "c")),
        speech_spans=(),
        duration_s=10.0,
    )
    with pytest.raises(ValueError):
        compute_metrics(t)


def test_type_token_ratio_measures_lexical_variety():
    m = compute_metrics(make(["cat", "cat", "dog", "bird"]))
    assert m.type_token_ratio == pytest.approx(0.75)


def test_confidence_metrics_flag_doubtful_words():
    m = compute_metrics(make(["clear", "mumbled"], probabilities=[0.95, 0.25]))
    assert m.mean_confidence == pytest.approx(0.6)
    assert m.low_confidence_rate == pytest.approx(0.5)
