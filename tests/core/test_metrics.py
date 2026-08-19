from __future__ import annotations

import pytest

from opic.core.metrics import Word, compute_metrics


def speech(texts: list[str], step: float = 0.5, probability: float = 0.9) -> list[Word]:
    return [
        Word(text=text, start=i * step, end=i * step + step / 2, probability=probability)
        for i, text in enumerate(texts)
    ]


def test_empty_speech_yields_zeroed_metrics():
    metrics = compute_metrics([], duration_s=10.0)
    assert metrics.word_count == 0
    assert metrics.words_per_minute == 0.0
    assert metrics.type_token_ratio == 0.0
    assert metrics.pause_ratio == 0.0
    assert metrics.mean_utterance_length == 0.0


def test_words_per_minute_counts_words_over_the_recording_length():
    words = speech(["one"] * 30)
    metrics = compute_metrics(words, duration_s=60.0)
    assert metrics.words_per_minute == pytest.approx(30.0)


def test_pause_ratio_measures_silence_between_words():
    words = [
        Word("hello", 0.0, 1.0, 0.9),
        Word("world", 4.0, 5.0, 0.9),
    ]
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.pause_ratio == pytest.approx(0.3)


def test_short_gaps_are_not_pauses():
    words = [
        Word("hello", 0.0, 1.0, 0.9),
        Word("world", 1.2, 2.0, 0.9),
    ]
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.pause_ratio == 0.0


def test_fillers_are_counted_case_insensitively_and_without_punctuation():
    words = speech(["Um,", "I", "uh", "think", "so"])
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.filler_count == 2
    assert metrics.filler_rate == pytest.approx(2 / 5)


def test_common_words_that_are_not_hesitations_are_not_fillers():
    words = speech(["I", "like", "it", "so", "well"])
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.filler_count == 0


def test_type_token_ratio_measures_lexical_variety():
    words = speech(["cat", "cat", "dog", "bird"])
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.type_token_ratio == pytest.approx(0.75)


def test_mean_utterance_length_splits_the_answer_on_pauses():
    words = [
        Word("I", 0.0, 0.3, 0.9),
        Word("think", 0.4, 0.8, 0.9),
        Word("so", 3.0, 3.4, 0.9),
    ]
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.mean_utterance_length == pytest.approx(1.5)


def test_confidence_metrics_flag_doubtful_words():
    words = [
        Word("clear", 0.0, 0.5, 0.95),
        Word("mumbled", 1.0, 1.5, 0.25),
    ]
    metrics = compute_metrics(words, duration_s=5.0)
    assert metrics.mean_confidence == pytest.approx(0.6)
    assert metrics.low_confidence_rate == pytest.approx(0.5)


def test_a_non_positive_duration_is_refused():
    with pytest.raises(ValueError):
        compute_metrics(speech(["hello"]), duration_s=0.0)
