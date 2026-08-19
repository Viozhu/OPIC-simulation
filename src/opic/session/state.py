"""A session as data, and the transitions it is allowed to make.

The browser proposes the next step; this module decides whether it is legal.
Nothing here touches disk, models or HTTP, so the whole state machine is
exercised in milliseconds.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from opic.core.survey import SurveyAnswers


class Step(Enum):
    SURVEY = "survey"
    LEVEL = "level"
    SETUP = "setup"
    SAMPLE = "sample"
    TEST = "test"
    GRADING = "grading"
    DONE = "done"


class AnswerState(Enum):
    PENDING = "pending"
    RECORDED = "recorded"
    TRANSCRIBED = "transcribed"
    SCORED = "scored"
    FAILED = "failed"


ORDER: tuple[Step, ...] = (
    Step.SURVEY,
    Step.LEVEL,
    Step.SETUP,
    Step.SAMPLE,
    Step.TEST,
    Step.GRADING,
    Step.DONE,
)


class TransitionError(ValueError):
    """Raised when the browser asks for a step that does not follow this one."""


@dataclass(frozen=True, slots=True)
class QuestionRecord:
    """A question as it is persisted: the slot flattened, plus its wording.

    The slot's enums are stored by value so `session.json` survives a rename in
    the code, and `audio_path` points into the TTS cache — the session never
    owns a copy of the audio.
    """

    index: int
    qtype: str
    topic_id: str | None
    combo_id: int | None
    advanced: bool
    target: str
    text_en: str
    audio_path: str | None


@dataclass(frozen=True, slots=True)
class AnswerRecord:
    index: int
    state: AnswerState
    audio_path: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SessionState:
    id: str
    step: Step
    seed: int
    survey: SurveyAnswers | None
    self_assess_level: int | None
    questions: tuple[QuestionRecord, ...]
    answers: tuple[AnswerRecord, ...]

    @classmethod
    def new(cls, session_id: str, seed: int) -> SessionState:
        return cls(
            id=session_id,
            step=Step.SURVEY,
            seed=seed,
            survey=None,
            self_assess_level=None,
            questions=(),
            answers=(),
        )

    @property
    def questions_ready(self) -> bool:
        """Every question written and every audio synthesised."""
        return bool(self.questions) and all(q.audio_path for q in self.questions)

    def with_survey(self, survey: SurveyAnswers) -> SessionState:
        return replace(self, survey=survey)

    def with_level(self, level: int) -> SessionState:
        return replace(self, self_assess_level=level)

    def with_questions(self, questions: tuple[QuestionRecord, ...]) -> SessionState:
        answers = tuple(
            AnswerRecord(index=q.index, state=AnswerState.PENDING) for q in questions
        )
        return replace(self, questions=questions, answers=answers)

    def with_question_audio(self, index: int, audio_path: str) -> SessionState:
        questions = tuple(
            replace(q, audio_path=audio_path) if q.index == index else q
            for q in self.questions
        )
        return replace(self, questions=questions)

    def with_answer(self, answer: AnswerRecord) -> SessionState:
        answers = tuple(
            answer if existing.index == answer.index else existing
            for existing in self.answers
        )
        return replace(self, answers=answers)

    def pending_indices(self) -> tuple[int, ...]:
        return tuple(a.index for a in self.answers if a.state is AnswerState.PENDING)

    def scored_indices(self) -> tuple[int, ...]:
        return tuple(a.index for a in self.answers if a.state is AnswerState.SCORED)


def advance(state: SessionState, step: Step) -> SessionState:
    """Move to the next step, refusing anything that is not exactly next."""
    current = ORDER.index(state.step)
    if current == len(ORDER) - 1:
        raise TransitionError(f"{state.step.value} is the last step; nothing follows it")
    if ORDER.index(step) != current + 1:
        raise TransitionError(
            f"cannot go from {state.step.value} to {step.value}; "
            f"expected {ORDER[current + 1].value}"
        )
    return replace(state, step=step)
