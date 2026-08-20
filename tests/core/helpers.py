from __future__ import annotations

from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import AnswerAssessment, DimensionScore
from opic.core.transcript import Span, Transcript, Word


def slot(index: int, qtype: QuestionType, topic_id: str | None, advanced: bool = False):
    return QuestionSlot(
        index=index,
        qtype=qtype,
        topic_id=topic_id,
        combo_id=None if topic_id is None else 0,
        advanced=advanced,
        target=ActflLevel.IM2,
    )


def blueprint_of(n: int) -> tuple[QuestionSlot, ...]:
    return tuple(slot(i, QuestionType.DESCRIPTION, "movies") for i in range(n))


def metrics(mean_confidence: float = 0.9, low_rate: float = 0.1) -> AnswerMetrics:
    return AnswerMetrics(
        duration_s=60.0,
        word_count=120,
        words_per_minute=120.0,
        pause_ratio=0.1,
        type_token_ratio=0.6,
        mean_utterance_length=8.0,
        mean_confidence=mean_confidence,
        low_confidence_rate=low_rate,
    )


def transcript_for(text: str = "I usually go to the beach on weekends") -> Transcript:
    spoken = text.split()
    return Transcript(
        text=text,
        words=tuple(
            Word(w, i * 0.4, i * 0.4 + 0.3, 0.9) for i, w in enumerate(spoken)
        ),
        speech_spans=(Span(0.0, len(spoken) * 0.4),),
        duration_s=60.0,
    )


def assessment(
    index: int,
    levels: dict[Dimension, ActflLevel],
    mean_confidence: float = 0.9,
    low_rate: float = 0.1,
) -> AnswerAssessment:
    return AnswerAssessment(
        question=Question(
            slot=slot(index, QuestionType.DESCRIPTION, "movies"),
            text_en="Tell me about the last movie you saw.",
        ),
        transcript=transcript_for(),
        dimension_scores=tuple(
            DimensionScore(
                dimension=dimension,
                level=levels[dimension],
                comment_ko="설명",
                evidence=(),
            )
            for dimension in Dimension
        ),
        metrics=metrics(mean_confidence, low_rate),
    )


def flat(level: ActflLevel) -> dict[Dimension, ActflLevel]:
    return {dimension: level for dimension in Dimension}
