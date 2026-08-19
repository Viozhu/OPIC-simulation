from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from opic.core.metrics import AnswerMetrics
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
    question_index: int
    dimension_scores: tuple[DimensionScore, ...]
    metrics: AnswerMetrics

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
    dimension_levels: dict[Dimension, ActflLevel]
    pronunciation: PronunciationProxy
    assessments: tuple[AnswerAssessment, ...]


def dimension_level(
    assessments: Sequence[AnswerAssessment],
    dimension: Dimension,
) -> ActflLevel:
    """The median band for one dimension; even counts take the lower middle."""
    ranks = sorted(
        assessment.level_for(dimension).rank for assessment in assessments
    )
    if not ranks:
        raise ValueError("cannot take a median of no assessments")
    return ActflLevel.from_rank(ranks[(len(ranks) - 1) // 2])


def aggregate(assessments: Sequence[AnswerAssessment]) -> ExamResult:
    """Collapse per-answer judgements into one level with a fixed rule."""
    if not assessments:
        raise ValueError("cannot aggregate an empty set of assessments")

    levels = {
        dimension: dimension_level(assessments, dimension) for dimension in Dimension
    }

    weighted = sum(
        levels[dimension].rank * weight
        for dimension, weight in DIMENSION_WEIGHTS.items()
    )
    rank = math.floor(weighted)

    weakest = min(level.rank for level in levels.values())
    if rank - weakest >= WEAK_DIMENSION_GAP:
        rank -= 1

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
        pronunciation=pronunciation,
        assessments=tuple(assessments),
    )
