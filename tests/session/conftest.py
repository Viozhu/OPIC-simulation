from __future__ import annotations

from pathlib import Path

import pytest

from doubles import (
    FakeQuestionWriter,
    FakeRater,
    FakeSpeechToText,
    FakeTextToSpeech,
    a_survey,
)


@pytest.fixture
def survey():
    return a_survey()


@pytest.fixture
def ports(tmp_path: Path):
    return {
        "tts": FakeTextToSpeech(tmp_path / "tts_cache"),
        "stt": FakeSpeechToText(),
        "writer": FakeQuestionWriter(),
        "rater": FakeRater(),
    }
