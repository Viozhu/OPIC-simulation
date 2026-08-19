from __future__ import annotations

import wave
from pathlib import Path

import pytest

from opic.adapters import config
from opic.adapters.tts import SayTextToSpeech, cache_path
from opic.core.ports import TextToSpeech


def test_the_adapter_satisfies_the_port(tmp_path):
    assert isinstance(SayTextToSpeech(cache_dir=tmp_path), TextToSpeech)


def test_the_cache_path_is_content_addressed(tmp_path):
    a = cache_path("hello there", "Samantha", tmp_path)
    b = cache_path("hello there", "Samantha", tmp_path)
    c = cache_path("hello THERE", "Samantha", tmp_path)
    assert a == b
    assert a != c
    assert a.suffix == ".wav"
    assert a.parent == tmp_path


def test_a_different_voice_is_a_different_cache_entry(tmp_path):
    assert cache_path("hello", "Samantha", tmp_path) != cache_path(
        "hello", "Alex", tmp_path
    )


def test_a_cached_file_is_returned_without_synthesising(tmp_path):
    voice = "Samantha"
    text = "already here"
    target = cache_path(text, voice, tmp_path)
    target.write_bytes(b"not really a wav")

    calls: list[str] = []

    def explode(*args, **kwargs):
        calls.append("ran")
        raise AssertionError("synthesis must not run for a cached entry")

    tts = SayTextToSpeech(cache_dir=tmp_path, voice=voice, runner=explode)
    assert tts.synthesize(text) == target
    assert calls == []


def test_an_empty_text_is_refused(tmp_path):
    with pytest.raises(ValueError):
        SayTextToSpeech(cache_dir=tmp_path).synthesize("   ")


@pytest.mark.models
def test_real_synthesis_produces_mono_16k_audio(tmp_path):
    out = SayTextToSpeech(cache_dir=tmp_path).synthesize(
        "Tell me about a memorable trip you took."
    )
    assert out.exists()
    with wave.open(str(out)) as wf:
        assert wf.getframerate() == config.TTS_SAMPLE_RATE
        assert wf.getnchannels() == 1
        assert wf.getnframes() / wf.getframerate() > 1.0
