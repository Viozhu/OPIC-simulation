from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from opic.core.transcript import Span, Transcript, Word


def test_span_reports_its_duration():
    assert Span(1.5, 4.0).duration == pytest.approx(2.5)


def test_a_transcript_holds_words_and_speech_spans():
    words = (Word("hello", 0.0, 0.5, 0.9),)
    spans = (Span(0.0, 0.5),)
    t = Transcript(text="hello", words=words, speech_spans=spans, duration_s=3.0)
    assert t.words == words
    assert t.speech_spans == spans
    assert t.duration_s == 3.0


@pytest.mark.parametrize("duration", [0.0, -1.0])
def test_a_non_positive_duration_is_refused(duration):
    with pytest.raises(ValueError):
        Transcript(text="", words=(), speech_spans=(), duration_s=duration)


def test_a_transcript_is_frozen():
    t = Transcript(text="hi", words=(), speech_spans=(), duration_s=1.0)
    with pytest.raises(FrozenInstanceError):
        t.text = "bye"
