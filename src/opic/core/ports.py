from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from opic.core.metrics import AnswerMetrics
from opic.core.narrative import Narrative
from opic.core.questions import Question, QuestionSlot
from opic.core.report import Report
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


@runtime_checkable
class NarrativeWriter(Protocol):
    """Reads a finished report and writes the parts no template can.

    Called once, after the exam is graded and `result.json` is on disk, so a
    slow or failed call costs a section of a page and never an answer.
    """

    def write_narrative(self, report: Report) -> Narrative: ...


@runtime_checkable
class SheetSink(Protocol):
    """Dónde va a parar una fila de resultados. Una hoja de cálculo, o nada."""

    def append(self, row: dict[str, str]) -> None: ...
