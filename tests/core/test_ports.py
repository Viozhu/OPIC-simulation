from __future__ import annotations

from pathlib import Path

from opic.core.metrics import AnswerMetrics
from opic.core.ports import QuestionWriter, Rater, SpeechToText, TextToSpeech
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.rubric import ActflLevel
from opic.core.survey import SurveyAnswers
from opic.core.transcript import Transcript


class FakeTts:
    def synthesize(self, text: str) -> Path:
        return Path("/tmp/fake.wav")


class FakeStt:
    def transcribe(self, audio: Path) -> Transcript:
        return Transcript(text="", words=(), speech_spans=(), duration_s=1.0)


class FakeWriter:
    def write(
        self, answers: SurveyAnswers, blueprint: tuple[QuestionSlot, ...]
    ) -> tuple[Question, ...]:
        return ()


class FakeRater:
    def rate(
        self,
        question: Question,
        transcript: Transcript,
        metrics: AnswerMetrics,
    ) -> tuple:
        return ()


class NotATts:
    def speak(self, text: str) -> Path:
        return Path("/tmp/nope.wav")


def test_a_conforming_object_satisfies_its_port():
    assert isinstance(FakeTts(), TextToSpeech)
    assert isinstance(FakeStt(), SpeechToText)
    assert isinstance(FakeWriter(), QuestionWriter)
    assert isinstance(FakeRater(), Rater)


def test_an_object_with_the_wrong_method_does_not():
    assert not isinstance(NotATts(), TextToSpeech)


def test_the_ports_module_imports_nothing_from_the_adapters():
    import opic.core.ports as ports

    source = Path(ports.__file__).read_text(encoding="utf-8")
    assert "opic.adapters" not in source
