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
EXAM_EVIDENCE_PER_DIMENSION = 3


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


def render_text(report: Report) -> str:
    """The same report the browser shows, for a terminal."""
    lines: list[str] = []
    lines.append(f"최종 등급: {report.final_level.name}")
    lines.append(
        f"{report.expected_answers}개 중 {report.scored_answers}개의 답변으로 산출되었습니다."
    )
    lines.append("이 등급은 공식 점수가 아니며 실제 시험 결과를 예측하지 않습니다.")

    lines.append("")
    lines.append("왜 이 등급인가")
    if report.limiting is not None:
        lines.append(
            f"  최종 등급은 {report.limiting.label_ko}에 의해 한 단계 낮아졌습니다. "
            f"그 제한이 없었다면 {report.limiting.without_cap.name}입니다."
        )
    for dimension in report.dimensions:
        lines.append(
            f"  {dimension.label_ko} ({dimension.weight:.0%}): {dimension.level.name}"
        )
        for item in dimension.evidence:
            lines.append(f"    \"{item.quote}\" (질문 {item.answer_index + 1})")
            lines.append(f"      {item.issue_ko}")
            lines.append(f"      → {item.correction_en}")

    lines.append("")
    lines.append("또렷하게 인식되지 않은 단어")
    if not report.unclear:
        lines.append("  또렷하게 인식되지 않은 단어는 없습니다.")
    for word in report.unclear:
        lines.append(f"  {word.text} (질문 {word.answer_index + 1}): …{word.context}…")

    lines.append("")
    lines.append("유형별 · 주제별")
    for _, label_ko, level in report.by_type:
        lines.append(f"  {label_ko}: {level.name}")
    for _, label_ko, level in report.by_topic:
        lines.append(f"  {label_ko}: {level.name}")

    lines.append("")
    lines.append("답변별 상세")
    for answer in report.answers:
        if answer.state != "scored":
            note = "읽을 수 없는 파일" if answer.state == "unreadable" else "채점하지 못한 답변"
            lines.append(f"  질문 {answer.index + 1} — {note}")
            continue
        lines.append(f"  질문 {answer.index + 1} ({answer.qtype_label_ko})")
        lines.append(f"    {answer.question_en}")
        lines.append(f"    {answer.transcript_text}")
        if answer.metrics is not None and report.averages is not None:
            lines.append(
                f"    말하기 속도 {answer.metrics.words_per_minute:.0f}"
                f" (평균 {report.averages.words_per_minute:.0f}) · "
                f"침묵 비율 {answer.metrics.pause_ratio:.0%}"
                f" (평균 {report.averages.pause_ratio:.0%})"
            )
        for score in answer.scores:
            lines.append(f"    {score.label_ko}: {score.level.name} — {score.comment_ko}")

    return "\n".join(lines)


def _evidence_for(result: ExamResult, dimension: Dimension) -> tuple[EvidenceRef, ...]:
    """The exam-level quotes for one dimension, capped and spread out.

    A real 15-question exam produced ~15 quotes per dimension on this
    screen alone; the per-answer detail (§7.5) already keeps every quote, so
    this summary caps at EXAM_EVIDENCE_PER_DIMENSION. The cap is filled by
    taking at most one quote per answer first, walking answers in ascending
    index order, so the summary is spread across answers rather than
    dominated by whichever answer happened to collect the most evidence.
    Only if the cap is still unfilled after that pass does a second quote
    from an already-used answer get taken.
    """
    by_answer: dict[int, list[Evidence]] = {}
    for assessment in result.assessments:
        for score in assessment.dimension_scores:
            if score.dimension is not dimension:
                continue
            by_answer.setdefault(assessment.question_index, []).extend(score.evidence)

    def ref(answer_index: int, item: Evidence) -> EvidenceRef:
        return EvidenceRef(
            quote=item.quote,
            issue_ko=item.issue_ko,
            correction_en=item.correction_en,
            answer_index=answer_index,
        )

    order = sorted(by_answer)
    found: list[EvidenceRef] = []

    for answer_index in order:
        if len(found) >= EXAM_EVIDENCE_PER_DIMENSION:
            break
        items = by_answer[answer_index]
        if items:
            found.append(ref(answer_index, items[0]))

    if len(found) < EXAM_EVIDENCE_PER_DIMENSION:
        for answer_index in order:
            for item in by_answer[answer_index][1:]:
                if len(found) >= EXAM_EVIDENCE_PER_DIMENSION:
                    break
                found.append(ref(answer_index, item))
            if len(found) >= EXAM_EVIDENCE_PER_DIMENSION:
                break

    return tuple(found)
