from __future__ import annotations

from enum import Enum


class ActflLevel(Enum):
    """The OPIc proficiency scale, ordered from lowest to highest."""

    NL = 0
    NM = 1
    NH = 2
    IL = 3
    IM1 = 4
    IM2 = 5
    IM3 = 6
    IH = 7
    AL = 8

    @property
    def rank(self) -> int:
        return self.value

    @classmethod
    def from_rank(cls, rank: int) -> ActflLevel:
        lowest = min(level.value for level in cls)
        highest = max(level.value for level in cls)
        return cls(max(lowest, min(highest, rank)))


class Dimension(Enum):
    """What the evaluator judges, one axis at a time."""

    FLUENCY = "fluency"
    GRAMMAR = "grammar"
    VOCABULARY = "vocabulary"
    COHERENCE = "coherence"
    RELEVANCE = "relevance"


DIMENSION_WEIGHTS: dict[Dimension, float] = {
    Dimension.FLUENCY: 0.25,
    Dimension.GRAMMAR: 0.20,
    Dimension.VOCABULARY: 0.20,
    Dimension.COHERENCE: 0.20,
    Dimension.RELEVANCE: 0.15,
}

DIMENSION_LABELS_KO: dict[Dimension, str] = {
    Dimension.FLUENCY: "유창성",
    Dimension.GRAMMAR: "문법",
    Dimension.VOCABULARY: "어휘",
    Dimension.COHERENCE: "구성력",
    Dimension.RELEVANCE: "질문 적합성",
}
