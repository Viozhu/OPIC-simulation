from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot
from opic.core.scoring import DimensionScore
from opic.core.survey import SurveyAnswers
from opic.core.transcript import Transcript


@runtime_checkable
class TextToSpeech(Protocol):
    """Turns a question's English text into an audio file."""

    def synthesize(self, text: str) -> Path: ...


@runtime_checkable
class SpeechToText(Protocol):
    """Turns a recorded answer into a transcript with timings and speech spans."""

    def transcribe(self, audio: Path) -> Transcript: ...


@runtime_checkable
class QuestionWriter(Protocol):
    """Writes the English wording for every slot in a blueprint.

    The whole set is produced before the exam begins, so no question ever waits
    on a language model while the candidate is sitting in front of it.
    """

    def write(
        self, answers: SurveyAnswers, blueprint: tuple[QuestionSlot, ...]
    ) -> tuple[Question, ...]: ...


@runtime_checkable
class Rater(Protocol):
    """Judges one answer along every scoring dimension."""

    def rate(
        self,
        question: Question,
        transcript: Transcript,
        metrics: AnswerMetrics,
    ) -> tuple[DimensionScore, ...]: ...
