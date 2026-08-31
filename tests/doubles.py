"""Doubles for the four ports, so the worker runs without a model in sight.

Imported as `from doubles import ...` — `tests` is on the pythonpath, which is
what lets both `tests/session` and `tests/web` share them.
"""

from __future__ import annotations

from pathlib import Path

from opic.core.questions import Question
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import DimensionScore, Evidence
from opic.core.survey import Housing, Occupation, RecentCourse, SurveyAnswers
from opic.core.transcript import Span, Transcript, Word

TWELVE_ITEMS = (
    "movies", "clubbing", "live_shows", "concerts", "museums", "parks",
    "listening_music", "cooking", "yoga", "walking", "domestic_travel", "overseas_travel",
)


def a_survey() -> SurveyAnswers:
    return SurveyAnswers(
        occupation=Occupation.BUSINESS,
        is_student=False,
        housing=Housing.ALONE,
        selected_item_ids=TWELVE_ITEMS,
        recent_course=RecentCourse.LANGUAGE,
    )


class FakeTextToSpeech:
    def __init__(self, cache: Path) -> None:
        self.cache = cache
        self.calls: list[str] = []

    def synthesize(self, text: str) -> Path:
        self.calls.append(text)
        path = self.cache / f"{abs(hash(text))}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF")
        return path


class FakeSpeechToText:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def transcribe(self, audio: Path) -> Transcript:
        self.calls.append(audio)
        return Transcript(
            text="I like films",
            words=(
                Word("I", 0.0, 0.2, 0.9),
                Word("like", 0.2, 0.5, 0.8),
                Word("films", 0.5, 0.9, 0.7),
            ),
            speech_spans=(Span(0.0, 0.9),),
            duration_s=1.0,
        )


class FakeQuestionWriter:
    def write(self, answers, blueprint) -> tuple[Question, ...]:
        return tuple(
            Question(slot=slot, text_en=f"Question {slot.index}.") for slot in blueprint
        )


class FakeRater:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def rate(self, question, transcript, metrics) -> tuple[DimensionScore, ...]:
        self.calls.append(question.slot.index)
        return tuple(
            DimensionScore(
                dimension=dimension,
                level=ActflLevel.IM1,
                comment_ko="문장이 짧습니다.",
                evidence=(Evidence("I like films", "너무 짧다", "I really enjoy films."),),
            )
            for dimension in Dimension
        )


class ExplodingQuestionWriter:
    """Fails a fixed number of times, then succeeds — mirrors `ExplodingRater`
    but for `_generate`'s call into the writer port."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.attempts = 0

    def write(self, answers, blueprint):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise TimeoutError("ollama timed out")
        return FakeQuestionWriter().write(answers, blueprint)


class ExplodingRater:
    """Fails a fixed number of times, then succeeds — or never, if `always`."""

    def __init__(self, failures: int, always: bool = False) -> None:
        self.failures = failures
        self.always = always
        self.attempts = 0

    def rate(self, question, transcript, metrics):
        self.attempts += 1
        if self.always or self.attempts <= self.failures:
            raise TimeoutError("ollama timed out")
        return FakeRater().rate(question, transcript, metrics)


class FakeSheet:
    """Guarda las filas en vez de enviarlas."""

    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    def append(self, row: dict[str, str]) -> None:
        self.rows.append(row)


class ExplodingSheet:
    """Falla siempre, para comprobar que el feedback no se pierde."""

    def __init__(self) -> None:
        self.calls = 0

    def append(self, row: dict[str, str]) -> None:
        self.calls += 1
        raise RuntimeError("the sheet is down")
