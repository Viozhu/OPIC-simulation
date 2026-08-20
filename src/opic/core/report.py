"""The exam result as something a candidate can read.

Everything here is derived — no score is computed, no rule is re-decided. The
browser and the CLI both render this model, so what the candidate is shown is
decided exactly once.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from opic.core.metrics import LOW_CONFIDENCE_THRESHOLD
from opic.core.questions import QUESTION_TYPE_LABELS_KO, Question, QuestionType
from opic.core.rubric import (
    DIMENSION_LABELS_KO,
    DIMENSION_WEIGHTS,
    ActflLevel,
    Dimension,
)
from opic.core.scoring import Evidence, ExamResult, limiting_dimension
from opic.core.survey import ITEMS_BY_ID

CONTEXT_WORDS = 5


@dataclass(frozen=True, slots=True)
class MetricSummary:
    duration_s: float
    word_count: float
    words_per_minute: float
    pause_ratio: float
    mean_utterance_length: float


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    quote: str
    issue_ko: str
    correction_en: str
    answer_index: int


@dataclass(frozen=True, slots=True)
class DimensionSummary:
    dimension: Dimension
    label_ko: str
    weight: float
    level: ActflLevel
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class DimensionDetail:
    dimension: Dimension
    label_ko: str
    level: ActflLevel
    comment_ko: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class UnclearWord:
    text: str
    probability: float
    context: str
    answer_index: int


@dataclass(frozen=True, slots=True)
class AnswerReport:
    index: int
    question_en: str
    qtype_label_ko: str
    topic_label_ko: str | None
    state: str
    transcript_text: str
    metrics: MetricSummary | None
    scores: tuple[DimensionDetail, ...]


@dataclass(frozen=True, slots=True)
class LimitingDimension:
    dimension: Dimension
    label_ko: str
    level: ActflLevel
    without_cap: ActflLevel


@dataclass(frozen=True, slots=True)
class Report:
    final_level: ActflLevel
    scored_answers: int
    expected_answers: int
    limiting: LimitingDimension | None
    dimensions: tuple[DimensionSummary, ...]
    unclear: tuple[UnclearWord, ...]
    by_type: tuple[tuple[QuestionType, str, ActflLevel], ...]
    by_topic: tuple[tuple[str, str, ActflLevel], ...]
    averages: MetricSummary | None
    answers: tuple[AnswerReport, ...]


def build_report(
    result: ExamResult,
    questions: Sequence[Question],
    unreadable: Sequence[int] = (),
) -> Report:
    levels = dict(result.dimension_levels)
    blueprint = tuple(q.slot for q in questions if q.slot.index in {
        a.question_index for a in result.assessments
    })
    limiting = limiting_dimension(blueprint, result.assessments)
    return Report(
        final_level=result.final_level,
        scored_answers=len(result.assessments),
        expected_answers=len(questions),
        limiting=(
            LimitingDimension(
                dimension=limiting[0],
                label_ko=DIMENSION_LABELS_KO[limiting[0]],
                level=levels[limiting[0]],
                without_cap=limiting[1],
            )
            if limiting is not None
            else None
        ),
        dimensions=tuple(
            DimensionSummary(
                dimension=dimension,
                label_ko=DIMENSION_LABELS_KO[dimension],
                weight=weight,
                level=levels[dimension],
                evidence=_evidence_for(result, dimension),
            )
            for dimension, weight in sorted(
                DIMENSION_WEIGHTS.items(), key=lambda pair: -pair[1]
            )
        ),
        unclear=_unclear_words(result),
        by_type=tuple(
            (qtype, QUESTION_TYPE_LABELS_KO[qtype], level)
            for qtype, level in result.by_type
        ),
        by_topic=tuple(
            (topic_id, _topic_label(topic_id) or topic_id, level)
            for topic_id, level in result.by_topic
        ),
        averages=_averages(result),
        answers=_answers(result, questions, unreadable),
    )


def _unclear_words(result: ExamResult) -> tuple[UnclearWord, ...]:
    """Words the recogniser gave low confidence to, with surrounding context.

    Context is the five words before and five after in the raw word stream —
    not a sentence: word timings do not mark sentence boundaries, and a mumble
    at the edge of an utterance still needs neighbours to be legible.
    """
    found = []
    for assessment in result.assessments:
        words = assessment.transcript.words
        for position, word in enumerate(words):
            if word.probability >= LOW_CONFIDENCE_THRESHOLD:
                continue
            start = max(0, position - CONTEXT_WORDS)
            end = min(len(words), position + CONTEXT_WORDS + 1)
            found.append(
                UnclearWord(
                    text=word.text,
                    probability=word.probability,
                    context=" ".join(w.text for w in words[start:end]),
                    answer_index=assessment.question_index,
                )
            )
    return tuple(found)


def _topic_label(topic_id: str | None) -> str | None:
    if topic_id is None:
        return None
    item = ITEMS_BY_ID.get(topic_id)
    return item.label_ko if item is not None else topic_id


def _averages(result: ExamResult) -> MetricSummary | None:
    if not result.assessments:
        return None
    count = len(result.assessments)
    take = lambda field: sum(  # noqa: E731
        getattr(a.metrics, field) for a in result.assessments
    ) / count
    return MetricSummary(
        duration_s=take("duration_s"),
        word_count=take("word_count"),
        words_per_minute=take("words_per_minute"),
        pause_ratio=take("pause_ratio"),
        mean_utterance_length=take("mean_utterance_length"),
    )


def _answers(
    result: ExamResult,
    questions: Sequence[Question],
    unreadable: Sequence[int],
) -> tuple[AnswerReport, ...]:
    judged = {a.question_index: a for a in result.assessments}
    broken = set(unreadable)
    reports = []
    for question in questions:
        index = question.slot.index
        assessment = judged.get(index)
        if assessment is None:
            reports.append(
                AnswerReport(
                    index=index,
                    question_en=question.text_en,
                    qtype_label_ko=QUESTION_TYPE_LABELS_KO[question.slot.qtype],
                    topic_label_ko=_topic_label(question.slot.topic_id),
                    state="unreadable" if index in broken else "not_scored",
                    transcript_text="",
                    metrics=None,
                    scores=(),
                )
            )
            continue
        m = assessment.metrics
        reports.append(
            AnswerReport(
                index=index,
                question_en=question.text_en,
                qtype_label_ko=QUESTION_TYPE_LABELS_KO[question.slot.qtype],
                topic_label_ko=_topic_label(question.slot.topic_id),
                state="scored",
                transcript_text=assessment.transcript.text,
                metrics=MetricSummary(
                    duration_s=m.duration_s,
                    word_count=m.word_count,
                    words_per_minute=m.words_per_minute,
                    pause_ratio=m.pause_ratio,
                    mean_utterance_length=m.mean_utterance_length,
                ),
                scores=tuple(
                    DimensionDetail(
                        dimension=score.dimension,
                        label_ko=DIMENSION_LABELS_KO[score.dimension],
                        level=score.level,
                        comment_ko=score.comment_ko,
                        evidence=score.evidence,
                    )
                    for score in assessment.dimension_scores
                ),
            )
        )
    return tuple(reports)


def _evidence_for(result: ExamResult, dimension: Dimension) -> tuple[EvidenceRef, ...]:
    found = []
    for assessment in result.assessments:
        for score in assessment.dimension_scores:
            if score.dimension is not dimension:
                continue
            for item in score.evidence:
                found.append(
                    EvidenceRef(
                        quote=item.quote,
                        issue_ko=item.issue_ko,
                        correction_en=item.correction_en,
                        answer_index=assessment.question_index,
                    )
                )
    return tuple(found)
