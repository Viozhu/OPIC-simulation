"""The exam result as something a candidate can read.

Everything here is derived — no score is computed, no rule is re-decided. The
browser and the CLI both render this model, so what the candidate is shown is
decided exactly once.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from opic.core.metrics import LOW_CONFIDENCE_THRESHOLD, _normalise
from opic.core.questions import QUESTION_TYPE_LABELS_KO, Question, QuestionType
from opic.core.rubric import (
    DIMENSION_LABELS_KO,
    DIMENSION_WEIGHTS,
    ActflLevel,
    Dimension,
)
from opic.core.scoring import (
    WEAK_DIMENSION_GAP,
    Evidence,
    ExamResult,
    GradeTrace,
    grade_trace,
    limiting_dimension,
)
from opic.core.transcript import Word
from opic.core.survey import ITEMS_BY_ID

CONTEXT_WORDS = 5
EXAM_EVIDENCE_PER_DIMENSION = 3
UNCLEAR_WORDS_SHOWN = 10

STATE_LABELS_KO: dict[str, str] = {
    "unreadable": "읽을 수 없는 파일",
    "not_scored": "채점하지 못한 답변",
}

# §7.7 — the five `MetricSummary` fields shown, each against the exam
# average. One table, so the label and its formatting live in exactly one
# place instead of being retyped inline by every renderer that needs them.
METRIC_LABELS_KO: dict[str, str] = {
    "duration_s": "답변 길이",
    "word_count": "단어 수",
    "words_per_minute": "말하기 속도",
    "pause_ratio": "침묵 비율",
    "mean_utterance_length": "평균 발화 길이",
}

METRIC_FORMATTERS: dict[str, Callable[[float], str]] = {
    "duration_s": lambda v: f"{v:.0f}초",
    "word_count": lambda v: f"{v:.0f}개",
    "words_per_minute": lambda v: f"{v:.0f}단어/분",
    "pause_ratio": lambda v: f"{v:.0%}",
    "mean_utterance_length": lambda v: f"{v:.1f}단어",
}


def format_metrics(metrics: MetricSummary) -> dict[str, str]:
    """Every field of a `MetricSummary`, already formatted for display.

    This is the one place either renderer needs for "what does this number
    look like" — `render_text` calls it directly, and `report_json`
    serialises its result, so `done.js` prints these strings instead of
    deciding its own formatting. Two formatting tables (one in Python, one
    in JS) is exactly how the CLI and the browser drifted apart before.
    """
    return {
        field: METRIC_FORMATTERS[field](getattr(metrics, field))
        for field in METRIC_LABELS_KO
    }


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
    state_label_ko: str
    transcript_text: str
    # Every word with its timing and the recogniser's confidence, so a renderer
    # can mark the doubtful ones inside the sentence they were said in.
    # `Report.unclear` answers a different question — which words the recogniser
    # doubts across the whole exam, deduplicated and capped — and neither
    # replaces the other.
    transcript_words: tuple[Word, ...]
    metrics: MetricSummary | None
    scores: tuple[DimensionDetail, ...]


@dataclass(frozen=True, slots=True)
class LimitingDimension:
    dimension: Dimension
    label_ko: str
    level: ActflLevel
    without_cap: ActflLevel


@dataclass(frozen=True, slots=True)
class GradeStep:
    """One step of the grading rule, already written out.

    The steps are the same three `scoring.py` applies, in the same order, and
    they are always all present: "no dimension was far enough behind to cost a
    band" is as much a part of the explanation as the cap firing would have
    been. A reader who can only see the steps that changed something cannot
    tell a rule that did not fire from a rule that does not exist.
    """

    label_ko: str
    detail_ko: str


@dataclass(frozen=True, slots=True)
class Closing:
    """What the report found, and how the band was arrived at.

    Last section of the document, and the only one that recaps. Everything in
    it is derived — `highlights` restates numbers printed further up, `steps`
    restates the arithmetic — so it survives an exam graded with no model at
    all, which is exactly when a candidate most needs to be told why the letter
    at the top is the letter it is.
    """

    final_level: ActflLevel
    highlights: tuple[str, ...]
    steps: tuple[GradeStep, ...]


@dataclass(frozen=True, slots=True)
class ScaleRung:
    """One band of the ACTFL scale, and who landed on it.

    Every band is present, including the ones nobody reached: a scale with the
    empty rungs removed is a list of results, not a reference, and "IM2" tells
    a candidate nothing unless they can see it sits fifth of nine.
    """

    level: ActflLevel
    is_final: bool
    dimensions: tuple[str, ...]


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
    scale: tuple[ScaleRung, ...]
    closing: Closing


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
    dimensions = tuple(
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
    )
    by_type = tuple(
        (qtype, QUESTION_TYPE_LABELS_KO[qtype], level)
        for qtype, level in result.by_type
    )
    by_topic = tuple(
        (topic_id, _topic_label(topic_id) or topic_id, level)
        for topic_id, level in result.by_topic
    )
    answers = _answers(result, questions, unreadable)
    unclear = _unclear_words(result)
    averages = _averages(result)
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
        dimensions=dimensions,
        unclear=unclear,
        by_type=by_type,
        by_topic=by_topic,
        averages=averages,
        answers=answers,
        scale=_scale(result.final_level, dimensions),
        closing=_closing(
            trace=grade_trace(blueprint, result.assessments),
            dimensions=dimensions,
            by_type=by_type,
            by_topic=by_topic,
            answers=answers,
            unclear=unclear,
            averages=averages,
            expected_answers=len(questions),
            scored_answers=len(result.assessments),
        ),
    )


def _extremes(
    rows: Sequence[tuple[object, str, ActflLevel]],
) -> tuple[tuple[str, ActflLevel], tuple[str, ActflLevel]] | None:
    """The best and worst row of a breakdown, or nothing when it says nothing.

    A table where every row carries the same band has no best and no worst, and
    a sentence naming one anyway would be picking a winner out of a tie.
    """
    if len(rows) < 2:
        return None
    best = max(rows, key=lambda row: row[2].rank)
    worst = min(rows, key=lambda row: row[2].rank)
    if best[2] is worst[2]:
        return None
    return (best[1], best[2]), (worst[1], worst[2])


def _closing(
    *,
    trace: GradeTrace,
    dimensions: tuple[DimensionSummary, ...],
    by_type: tuple[tuple[QuestionType, str, ActflLevel], ...],
    by_topic: tuple[tuple[str, str, ActflLevel], ...],
    answers: tuple[AnswerReport, ...],
    unclear: tuple[UnclearWord, ...],
    averages: MetricSummary | None,
    expected_answers: int,
    scored_answers: int,
) -> Closing:
    """The recap, written from what the rest of the report already holds.

    Nothing is recomputed here — the bands come from `trace`, which walked
    `scoring.py`'s own rules, and every count is of something printed further
    up. The Korean is written around the band names rather than after them:
    "IM2" takes a different particle depending on how a reader pronounces it,
    so the sentences here end in the label and let a colon carry the join.
    """
    strongest_dimension, strongest_level = trace.strongest
    weakest_dimension, weakest_level = trace.weakest

    highlights = [f"{expected_answers}개 문항 중 {scored_answers}개가 채점되었습니다."]

    # A spread only exists when the two ends differ. On a real exam every
    # dimension came out at IH, and naming a highest and a lowest anyway
    # printed the same dimension twice — a sentence that reads as a finding
    # and says nothing.
    if strongest_level is weakest_level:
        highlights.append(f"다섯 영역이 모두 같은 등급입니다 — {strongest_level.name}")
    else:
        highlights.append(
            f"영역별 최고 — {DIMENSION_LABELS_KO[strongest_dimension]} "
            f"{strongest_level.name} · 최저 — "
            f"{DIMENSION_LABELS_KO[weakest_dimension]} {weakest_level.name}"
        )

    types = _extremes(by_type)
    if types is not None:
        (best_label, best_level), (worst_label, worst_level) = types
        highlights.append(
            f"문항 유형별 최고 — {best_label} {best_level.name} · "
            f"최저 — {worst_label} {worst_level.name}"
        )

    topics = _extremes(by_topic)
    if topics is not None:
        (best_label, best_level), (worst_label, worst_level) = topics
        highlights.append(
            f"주제별 최고 — {best_label} {best_level.name} · "
            f"최저 — {worst_label} {worst_level.name}"
        )

    corrections = sum(
        len(score.evidence) for answer in answers for score in answer.scores
    )
    if corrections:
        highlights.append(f"고쳐야 할 문장으로 {corrections}개가 인용되었습니다.")
    if unclear:
        highlights.append(
            f"음성 인식기가 또렷하게 잡지 못한 단어는 {len(unclear)}개입니다."
        )
    if averages is not None:
        display = format_metrics(averages)
        highlights.append(
            f"답변 평균 — 길이 {display['duration_s']} · "
            f"속도 {display['words_per_minute']} · "
            f"침묵 {display['pause_ratio']}"
        )

    medians = " · ".join(f"{d.label_ko} {d.level.name}" for d in dimensions)
    weights = " · ".join(f"{d.label_ko} {d.weight:.0%}" for d in dimensions)

    steps = [
        GradeStep(
            label_ko="1. 영역별 중앙값",
            detail_ko=f"문항마다 매긴 등급의 중앙값입니다 — {medians}",
        ),
        GradeStep(
            label_ko="2. 가중 평균",
            detail_ko=(
                f"가중치({weights})를 적용한 평균 {trace.weighted_mean:.2f} — "
                f"가장 가까운 등급 {trace.weighted_level.name}"
            ),
        ),
    ]

    if trace.stretch_level is None:
        stretch_detail = "이 시험에는 상위 난이도로 출제된 문항이 없었습니다."
    elif trace.raised:
        stretch_detail = (
            f"자기 평가보다 한 단계 높게 출제된 문항들이 받은 등급 "
            f"{trace.stretch_level.name} — 한 단계 올려 {trace.pre_cap_level.name}"
        )
    else:
        stretch_detail = (
            f"자기 평가보다 한 단계 높게 출제된 문항들이 받은 등급 "
            f"{trace.stretch_level.name} — 가중 평균을 넘지 못해 상승은 없습니다."
        )
    steps.append(GradeStep(label_ko="3. 상위 난이도 문항", detail_ko=stretch_detail))

    if trace.capped:
        cap_detail = (
            f"{DIMENSION_LABELS_KO[weakest_dimension]} {weakest_level.name}이 "
            f"{WEAK_DIMENSION_GAP}단계 이상 뒤처져 한 단계 내려갔습니다 — "
            f"이 상한이 없었다면 {trace.pre_cap_level.name}"
        )
    elif strongest_level is weakest_level:
        cap_detail = (
            f"다섯 영역이 모두 같은 등급이라 깎일 여지가 없습니다 — "
            f"{weakest_level.name}"
        )
    else:
        cap_detail = (
            f"{WEAK_DIMENSION_GAP}단계 이상 뒤처진 영역이 없어 깎이지 않았습니다 — "
            f"가장 낮은 영역은 {DIMENSION_LABELS_KO[weakest_dimension]} "
            f"{weakest_level.name}"
        )
    steps.append(GradeStep(label_ko="4. 약점 상한", detail_ko=cap_detail))

    steps.append(
        GradeStep(
            label_ko="5. 최종 등급",
            detail_ko=f"위의 네 단계를 거쳐 나온 등급 — {trace.final_level.name}",
        )
    )

    return Closing(
        final_level=trace.final_level,
        highlights=tuple(highlights),
        steps=tuple(steps),
    )


def _scale(final: ActflLevel, dimensions: tuple[DimensionSummary, ...]) -> tuple[ScaleRung, ...]:
    """The whole ladder, highest band first.

    Highest first so both renderers iterate in reading order and neither has to
    reverse — a scale drawn upside down in one of the two would be a bug nobody
    notices until someone compares them.
    """
    return tuple(
        ScaleRung(
            level=level,
            is_final=level is final,
            dimensions=tuple(d.label_ko for d in dimensions if d.level is level),
        )
        for level in sorted(ActflLevel, key=lambda band: -band.rank)
    )


def _unclear_words(result: ExamResult) -> tuple[UnclearWord, ...]:
    """Words the recogniser gave low confidence to, one entry per word.

    Context is the five words before and five after in the raw word stream —
    not a sentence: word timings do not mark sentence boundaries, and a mumble
    at the edge of an utterance still needs neighbours to be legible.

    A real 15-question exam produced 87 below-threshold appearances but only
    12 distinct words: the same uncertain word recurs answer after answer, and
    listing every appearance turned the section into a wall of `and`/`an`/
    `but`/`it`. This keeps one entry per word — normalised the same way
    `metrics.py` already does for its own matching, so there is only one
    normalisation in the codebase — the lowest-probability appearance of it
    (the recogniser's worst guess is the most telling one), ordered
    worst-first, capped at UNCLEAR_WORDS_SHOWN.
    """
    best: dict[str, UnclearWord] = {}
    for assessment in result.assessments:
        words = assessment.transcript.words
        for position, word in enumerate(words):
            if word.probability >= LOW_CONFIDENCE_THRESHOLD:
                continue
            key = _normalise(word.text)
            start = max(0, position - CONTEXT_WORDS)
            end = min(len(words), position + CONTEXT_WORDS + 1)
            candidate = UnclearWord(
                text=word.text,
                probability=word.probability,
                context=" ".join(w.text for w in words[start:end]),
                answer_index=assessment.question_index,
            )
            existing = best.get(key)
            if existing is None or candidate.probability < existing.probability:
                best[key] = candidate

    ordered = sorted(best.values(), key=lambda w: w.probability)
    return tuple(ordered[:UNCLEAR_WORDS_SHOWN])


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
            state = "unreadable" if index in broken else "not_scored"
            reports.append(
                AnswerReport(
                    index=index,
                    question_en=question.text_en,
                    qtype_label_ko=QUESTION_TYPE_LABELS_KO[question.slot.qtype],
                    topic_label_ko=_topic_label(question.slot.topic_id),
                    state=state,
                    state_label_ko=STATE_LABELS_KO[state],
                    transcript_text="",
                    transcript_words=(),
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
                state_label_ko="",
                transcript_text=assessment.transcript.text,
                transcript_words=assessment.transcript.words,
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
    lines.append("등급 척도")
    for rung in report.scale:
        marker = "◀" if rung.is_final else " "
        who = f"   {' · '.join(rung.dimensions)}" if rung.dimensions else ""
        lines.append(f"  {marker} {rung.level.name:<4}{who}".rstrip())

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
            lines.append(f"  질문 {answer.index + 1} — {answer.state_label_ko}")
            continue
        heading = answer.qtype_label_ko
        if answer.topic_label_ko:
            heading += f" · {answer.topic_label_ko}"
        lines.append(f"  질문 {answer.index + 1} ({heading})")
        lines.append(f"    {answer.question_en}")
        lines.append(f"    {answer.transcript_text}")
        if answer.metrics is not None and report.averages is not None:
            answer_display = format_metrics(answer.metrics)
            average_display = format_metrics(report.averages)
            for field, label in METRIC_LABELS_KO.items():
                lines.append(
                    f"    {label}: {answer_display[field]} (평균 {average_display[field]})"
                )
        for score in answer.scores:
            lines.append(f"    {score.label_ko}: {score.level.name} — {score.comment_ko}")
            for item in score.evidence:
                lines.append(f"      \"{item.quote}\"")
                lines.append(f"        {item.issue_ko}")
                lines.append(f"        → {item.correction_en}")

    lines.append("")
    lines.append("리포트 요약")
    for highlight in report.closing.highlights:
        lines.append(f"  {highlight}")

    lines.append("")
    lines.append(f"이 등급이 나온 과정 — 최종 {report.closing.final_level.name}")
    for step in report.closing.steps:
        lines.append(f"  {step.label_ko}: {step.detail_ko}")

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
