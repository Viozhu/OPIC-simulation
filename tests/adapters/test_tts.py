from __future__ import annotations

import wave
from pathlib import Path

import pytest

from opic.adapters import config
from opic.adapters.tts import SayTextToSpeech, cache_path, with_prosody
from opic.core.ports import TextToSpeech

RATE = config.SAY_RATE


def test_the_adapter_satisfies_the_port(tmp_path):
    assert isinstance(SayTextToSpeech(cache_dir=tmp_path), TextToSpeech)


def test_the_cache_path_is_content_addressed(tmp_path):
    a = cache_path("hello there", "Samantha", RATE, tmp_path)
    b = cache_path("hello there", "Samantha", RATE, tmp_path)
    c = cache_path("hello THERE", "Samantha", RATE, tmp_path)
    assert a == b
    assert a != c
    assert a.suffix == ".wav"
    assert a.parent == tmp_path


def test_a_different_voice_is_a_different_cache_entry(tmp_path):
    assert cache_path("hello", "Samantha", RATE, tmp_path) != cache_path(
        "hello", "Alex", RATE, tmp_path
    )


def test_a_different_rate_is_a_different_cache_entry(tmp_path):
    """Otherwise changing the speed changes nothing anybody can hear.

    Every question already spoken stays cached under the old key and keeps
    playing at the old speed, which looks exactly like a setting that does not
    work.
    """
    assert cache_path("hello", "Samantha", 165, tmp_path) != cache_path(
        "hello", "Samantha", 95, tmp_path
    )


def test_the_rate_reaches_the_say_command(tmp_path):
    spoken: list[list[str]] = []

    def record(command: list[str]) -> None:
        if command[0] == "say":
            spoken.append(command)
            Path(command[command.index("-o") + 1]).write_bytes(b"aiff")
        else:
            Path(command[-1]).write_bytes(b"wav")

    SayTextToSpeech(cache_dir=tmp_path, rate=95, runner=record).synthesize("hi")

    assert spoken[0][spoken[0].index("-r") + 1] == "95"


def test_a_cached_file_is_returned_without_synthesising(tmp_path):
    voice = "Samantha"
    text = "already here"
    target = cache_path(with_prosody(text), voice, RATE, tmp_path)
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


def test_a_failed_conversion_leaves_no_cache_entry(tmp_path):
    def fail_on_ffmpeg(command: list[str]) -> None:
        if command[0] == "ffmpeg":
            raise RuntimeError("ffmpeg blew up")
        Path(command[command.index("-o") + 1]).write_bytes(b"aiff")

    tts = SayTextToSpeech(cache_dir=tmp_path, runner=fail_on_ffmpeg)
    with pytest.raises(RuntimeError):
        tts.synthesize("this will not convert")

    assert not cache_path(
        with_prosody("this will not convert"), config.SAY_VOICE, RATE, tmp_path
    ).exists()
    assert list(tmp_path.iterdir()) == []


def test_a_successful_synthesis_leaves_only_the_cached_wav(tmp_path):
    def fake_pipeline(command: list[str]) -> None:
        if command[0] == "say":
            Path(command[command.index("-o") + 1]).write_bytes(b"aiff")
        else:
            Path(command[-1]).write_bytes(b"wav")

    tts = SayTextToSpeech(cache_dir=tmp_path, runner=fake_pipeline)
    out = tts.synthesize("hello there")
    assert out.exists()
    assert [p.name for p in tmp_path.iterdir()] == [out.name]


def test_a_sentence_boundary_becomes_a_real_pause():
    """The setup and the question are two beats, not one contour."""
    spoken = with_prosody(
        "You said you go to cafes. Tell me about the last time you went.",
        lead_in_ms=300,
        sentence_pause_ms=600,
        clause_pause_ms=0,
    )
    assert spoken == (
        "[[slnc 300]] You said you go to cafes. "
        "[[slnc 600]] Tell me about the last time you went."
    )


def test_an_em_dash_is_the_same_beat_as_a_full_stop():
    """It is how most of these questions separate the setup from the question.

    Twenty-three of the 105 questions in `data/sessions` break this way and
    twenty-two with a full stop, so a rule that only knew about full stops
    would miss half the questions that have a beat at all.
    """
    spoken = with_prosody(
        "Describe your cooking — what dishes do you make?",
        lead_in_ms=300,
        sentence_pause_ms=600,
        clause_pause_ms=0,
    )
    assert spoken == (
        "[[slnc 300]] Describe your cooking — [[slnc 600]] what dishes do you make?"
    )


def test_the_punctuation_survives_the_pause():
    """The silence goes after the mark, never instead of it.

    Cutting the mark out to make room for the silence measures the same
    length and throws away the intonation the voice does there, which is the
    flatness this exists to fix.
    """
    for mark in (".", "?", "—", ","):
        assert mark in with_prosody(f"One{mark} two", sentence_pause_ms=600)


def test_sub_questions_are_separated_even_inside_one_sentence():
    """The majority case: one sentence, three things to remember."""
    spoken = with_prosody(
        "Tell me what you did, where you went, and what made it memorable.",
        lead_in_ms=300,
        sentence_pause_ms=600,
        clause_pause_ms=400,
    )
    assert spoken == (
        "[[slnc 300]] Tell me what you did, [[slnc 400]] where you went, "
        "[[slnc 400]] and what made it memorable."
    )


def test_a_pause_set_to_zero_leaves_no_marker():
    """Otherwise turning it off resynthesises everything to no audible effect."""
    spoken = with_prosody(
        "Tell me what you did, where you went.",
        lead_in_ms=0,
        sentence_pause_ms=600,
        clause_pause_ms=0,
    )
    assert spoken == "Tell me what you did, where you went."


def test_the_defaults_clear_the_measured_floor():
    """`say` replaces the punctuation's own pause with the marker.

    A pause set at or below that floor makes the delivery faster and flatter
    than no marker at all — a setting that reads as a fix and is a regression.
    The floor belongs to the voice: 200ms for Samantha, about 115ms for Ava
    (Premium), both measured in the note in adapters/config.py. This asserts
    against the higher of the two, so a value that passes here is audible in
    either voice.
    """
    assert config.TTS_SENTENCE_PAUSE_MS > 200
    assert config.TTS_CLAUSE_PAUSE_MS > 200


def test_every_question_gets_a_lead_in_even_with_one_sentence():
    assert with_prosody("Tell me about your job.", lead_in_ms=300) == (
        "[[slnc 300]] Tell me about your job."
    )


def test_a_bracket_in_the_question_is_not_read_as_a_command():
    """`say` swallows `[[...]]`, and the questions are written by a model.

    Left alone, a question containing one would be spoken with a hole in it
    that nothing in the pipeline would report.
    """
    spoken = with_prosody("Describe [[your]] hometown.")
    assert "[[your]]" not in spoken
    assert "[ [your]]" in spoken


def test_the_pauses_reach_the_say_command(tmp_path):
    spoken: list[list[str]] = []

    def record(command: list[str]) -> None:
        if command[0] == "say":
            spoken.append(command)
            Path(command[command.index("-o") + 1]).write_bytes(b"aiff")
        else:
            Path(command[-1]).write_bytes(b"wav")

    SayTextToSpeech(
        cache_dir=tmp_path,
        runner=record,
        lead_in_ms=300,
        sentence_pause_ms=600,
        clause_pause_ms=400,
    ).synthesize("One. Two.")

    assert spoken[0][-1] == "[[slnc 300]] One. [[slnc 600]] Two."


def test_changing_a_pause_is_a_different_cache_entry(tmp_path):
    """Otherwise the cadence setting is silent, exactly as the rate once was."""
    a = with_prosody("One. Two.", sentence_pause_ms=600)
    b = with_prosody("One. Two.", sentence_pause_ms=800)
    assert cache_path(a, "Samantha", RATE, tmp_path) != cache_path(
        b, "Samantha", RATE, tmp_path
    )
