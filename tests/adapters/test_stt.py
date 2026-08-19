from __future__ import annotations

import json
from pathlib import Path

import pytest

from opic.adapters import config
from opic.adapters.stt import WhisperSpeechToText, spans_from_timestamps
from opic.core.metrics import compute_metrics, merge_spans
from opic.core.ports import SpeechToText
from opic.core.transcript import Span, Transcript, Word

FIXTURE_AUDIO = Path("evidence/sample-answer.wav")
FIXTURE_JSON = Path("evidence/sample-transcript.json")


def test_the_adapter_satisfies_the_port():
    assert isinstance(WhisperSpeechToText(), SpeechToText)


def test_timestamps_in_samples_become_spans_in_seconds():
    spans = spans_from_timestamps(
        [{"start": 0, "end": 16000}, {"start": 32000, "end": 48000}],
        sampling_rate=16000,
    )
    assert spans == (Span(0.0, 1.0), Span(2.0, 3.0))


def test_no_speech_detected_gives_no_spans():
    assert spans_from_timestamps([], sampling_rate=16000) == ()


def test_the_vad_contract_is_pinned_to_the_measured_values():
    assert config.VAD_MIN_SILENCE_MS == 250
    assert config.VAD_SPEECH_PAD_MS == 0


@pytest.mark.models
def test_the_contract_produces_usable_metrics_on_real_speech():
    """The defaults give pause_ratio 0.0235 and mean_utterance_length 75.0 on this
    recording — the broken numbers. The contract gives 0.23 and 6.8."""
    from faster_whisper import vad
    from faster_whisper.audio import decode_audio

    pcm = decode_audio(str(FIXTURE_AUDIO), sampling_rate=16000)
    options = vad.VadOptions(
        min_silence_duration_ms=config.VAD_MIN_SILENCE_MS,
        speech_pad_ms=config.VAD_SPEECH_PAD_MS,
    )
    spans = spans_from_timestamps(
        vad.get_speech_timestamps(pcm, options, sampling_rate=16000),
        sampling_rate=16000,
    )
    assert len(spans) > 10
    assert len(merge_spans(spans)) > 10

    words = tuple(
        Word(w["text"], w["start"], w["end"], w["probability"])
        for w in json.loads(FIXTURE_JSON.read_text())["configs"]["mitigated"]["words"]
    )
    m = compute_metrics(
        Transcript(
            text="",
            words=words,
            speech_spans=spans,
            duration_s=len(pcm) / 16000,
        )
    )
    assert 0.15 < m.pause_ratio < 0.35
    assert 4.0 < m.mean_utterance_length < 12.0


@pytest.mark.models
def test_real_transcription_preserves_the_speakers_errors():
    result = WhisperSpeechToText().transcribe(FIXTURE_AUDIO)
    assert result.words
    assert result.speech_spans
    assert result.duration_s == pytest.approx(90.0, abs=1.0)
    lowered = result.text.lower()
    assert "a island" in lowered or "we take a bath" in lowered


@pytest.mark.models
def test_the_adapter_itself_produces_many_speech_spans():
    """With faster-whisper's default VadOptions this recording yields 2 spans and
    mean_utterance_length 75 — the numbers an earlier phase existed to remove."""
    result = WhisperSpeechToText().transcribe(FIXTURE_AUDIO)
    assert len(result.speech_spans) > 10
