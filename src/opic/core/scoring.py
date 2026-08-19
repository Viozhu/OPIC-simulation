from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.transcript import Transcript
from opic.core.rubric import DIMENSION_WEIGHTS, ActflLevel, Dimension

WEAK_DIMENSION_GAP = 3


@dataclass(frozen=True, slots=True)
class Evidence:
    quote: str
    issue_ko: str
    correction_en: str


@dataclass(frozen=True, slots=True)
class DimensionScore:
    dimension: Dimension
    level: ActflLevel
    comment_ko: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerAssessment:
    """One answer, judged — together with what was asked and what was said.

    The report quotes the question, and every piece of evidence has to be
    checkable against the transcript it came from. Holding both here is what
    keeps the result object self-contained instead of something the caller has
    to carry side tables for.
    """

    question: Question
    transcript: Transcript
    dimension_scores: tuple[DimensionScore, ...]
    metrics: AnswerMetrics

    @property
    def question_index(self) -> int:
        return self.question.slot.index

    def level_for(self, dimension: Dimension) -> ActflLevel:
        for score in self.dimension_scores:
            if score.dimension is dimension:
                return score.level
        raise ValueError(
            f"answer {self.question_index} has no score for {dimension.value}"
        )


@dataclass(frozen=True, slots=True)
class PronunciationProxy:
    """A rough signal, never a band.

    Whisper does not measure pronunciation. Transcription confidence correlates
    with it loosely, so it is reported as a hint and labelled as such.
    """

    mean_confidence: float
    low_confidence_rate: float
    indicative: bool = True


@dataclass(frozen=True, slots=True)
class ExamResult:
    final_level: ActflLevel
    dimension_levels: tuple[tuple[Dimension, ActflLevel], ...]
    by_type: tuple[tuple[QuestionType, ActflLevel], ...]
    by_topic: tuple[tuple[str, ActflLevel], ...]
    pronunciation: PronunciationProxy
    assessments: tuple[AnswerAssessment, ...]

    def level_for(self, dimension: Dimension) -> ActflLevel:
        for dim, level in self.dimension_levels:
            if dim is dimension:
                return level
        raise ValueError(f"no level recorded for {dimension.value}")


def _median_level(levels: Sequence[ActflLevel]) -> ActflLevel:
    """The median band; even counts take the lower of the two middles."""
    ranks = sorted(level.rank for level in levels)
    if not ranks:
        raise ValueError("cannot take a median of no levels")
    return ActflLevel.from_rank(ranks[(len(ranks) - 1) // 2])


def dimension_level(
    assessments: Sequence[AnswerAssessment],
    dimension: Dimension,
) -> ActflLevel:
    """The median band for one dimension across every answer."""
    return _median_level([a.level_for(dimension) for a in assessments])


def _weighted_rank(assessments: Sequence[AnswerAssessment]) -> int:
    """The floored weighted mean of the per-dimension medians."""
    return math.floor(
        sum(
            dimension_level(assessments, dimension).rank * weight
            for dimension, weight in DIMENSION_WEIGHTS.items()
        )
    )


def _capped(rank: int, assessments: Sequence[AnswerAssessment]) -> int:
    """Drop one band when any dimension sits WEAK_DIMENSION_GAP or more below.

    A serious weakness in one axis caps the result rather than being averaged
    away, so this is applied last — after any raise, never before one.
    """
    weakest = min(dimension_level(assessments, d).rank for d in Dimension)
    return rank - 1 if rank - weakest >= WEAK_DIMENSION_GAP else rank


def _level_for_answers(assessments: Sequence[AnswerAssessment]) -> ActflLevel:
    """The band a subset of answers earns, under the same rule as the whole exam."""
    return ActflLevel.from_rank(_capped(_weighted_rank(assessments), assessments))


def aggregate(
    blueprint: Sequence[QuestionSlot],
    assessments: Sequence[AnswerAssessment],
) -> ExamResult:
    """Collapse per-answer judgements into one level with a fixed rule.

    The blueprint is required because the score depends on what each answer was
    asked: the report breaks down by topic and question type, and the advanced
    combo probes above the declared level.
    """
    if not assessments:
        raise ValueError("cannot aggregate an empty set of assessments")

    slots = {slot.index: slot for slot in blueprint}
    indices = [a.question_index for a in assessments]
    if len(set(indices)) != len(indices):
        raise ValueError("two assessments share a question_index")
    if set(indices) != set(slots):
        missing = sorted(set(slots) - set(indices))
        extra = sorted(set(indices) - set(slots))
        raise ValueError(
            f"assessments do not match the blueprint (missing {missing}, extra {extra})"
        )

    levels = tuple(
        (dimension, dimension_level(assessments, dimension)) for dimension in Dimension
    )

    rank = _weighted_rank(assessments)

    advanced = [a for a in assessments if slots[a.question_index].advanced]
    if advanced:
        stretch = _level_for_answers(advanced)
        if stretch.rank > rank:
            rank = min(rank + 1, stretch.rank)

    rank = _capped(rank, assessments)

    by_type: list[tuple[QuestionType, ActflLevel]] = []
    for qtype in QuestionType:
        group = [a for a in assessments if slots[a.question_index].qtype is qtype]
        if group:
            by_type.append((qtype, _level_for_answers(group)))

    by_topic: list[tuple[str, ActflLevel]] = []
    for topic_id in dict.fromkeys(slot.topic_id for slot in blueprint):
        if topic_id is None:
            continue
        group = [a for a in assessments if slots[a.question_index].topic_id == topic_id]
        by_topic.append((topic_id, _level_for_answers(group)))

    count = len(assessments)
    pronunciation = PronunciationProxy(
        mean_confidence=sum(a.metrics.mean_confidence for a in assessments) / count,
        low_confidence_rate=sum(a.metrics.low_confidence_rate for a in assessments)
        / count,
        indicative=True,
    )

    return ExamResult(
        final_level=ActflLevel.from_rank(rank),
        dimension_levels=levels,
        by_type=tuple(by_type),
        by_topic=tuple(by_topic),
        pronunciation=pronunciation,
        assessments=tuple(assessments),
    )
