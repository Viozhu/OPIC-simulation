"""One judged answer on disk, and the aggregation of whatever survived.

`answer-NN.json` holds everything needed to rebuild an `AnswerAssessment`:
words with their timings, the voice-activity spans, the metrics and the
dimension scores. That is what makes a restart able to aggregate without
re-running a single model.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Sequence
from pathlib import Path

from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.report import METRIC_LABELS_KO, Report
from opic.core.rubric import DIMENSION_LABELS_KO, ActflLevel, Dimension
from opic.core.scoring import AnswerAssessment, DimensionScore, Evidence, ExamResult, aggregate
from opic.core.transcript import Span, Transcript, Word
from opic.session.state import QuestionRecord, SessionState
from opic.session.store import answer_result_path


def question_from_record(record: QuestionRecord) -> Question:
    return Question(
        slot=QuestionSlot(
            index=record.index,
            qtype=QuestionType(record.qtype),
            topic_id=record.topic_id,
            combo_id=record.combo_id,
            advanced=record.advanced,
            target=ActflLevel[record.target],
        ),
        text_en=record.text_en,
    )


def write_answer(root: Path, session_id: str, assessment: AnswerAssessment) -> Path:
    path = answer_result_path(root, session_id, assessment.question_index)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(_answer_json(assessment), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def read_answer(root: Path, session_id: str, index: int) -> AnswerAssessment:
    path = answer_result_path(root, session_id, index)
    return _answer_from_json(json.loads(path.read_text(encoding="utf-8")))


def read_all_answers(
    root: Path, session_id: str, state: SessionState
) -> tuple[AnswerAssessment, ...]:
    """Every answer whose CURRENT state is SCORED, in question order.

    `session.json` — `state` here — is the source of truth for what this run
    judged, not which `answer-NN.json` files happen to sit on disk. A second
    exam run into the same directory overwrites `session.json` but leaves the
    previous run's answer files behind; selecting by file existence would
    silently mix those stale answers into a fresh exam's result. Going by
    `state.scored_indices()` instead means an answer only counts if THIS run's
    state says it was scored.
    """
    scored = set(state.scored_indices())
    found = []
    for record in state.questions:
        if record.index in scored:
            found.append(read_answer(root, session_id, record.index))
    return tuple(found)


def aggregate_available(
    questions: Sequence[QuestionRecord],
    assessments: Sequence[AnswerAssessment],
) -> ExamResult:
    """Aggregate over the answers that exist.

    `core.aggregate` requires the assessments to match the blueprint exactly, so
    a failed answer would make it raise. Passing only the slots that were judged
    keeps that check meaningful — it still catches a mismatch — while letting an
    exam with a broken answer produce a level.
    """
    judged = {a.question_index for a in assessments}
    blueprint = tuple(
        question_from_record(record).slot
        for record in questions
        if record.index in judged
    )
    return aggregate(blueprint, list(assessments))


def result_json(result: ExamResult, expected: int) -> dict:
    return {
        "final_level": result.final_level.name,
        "scored_answers": len(result.assessments),
        "expected_answers": expected,
        "dimensions": {
            d.value: {"label_ko": DIMENSION_LABELS_KO[d], "level": level.name}
            for d, level in result.dimension_levels
        },
        "by_type": {t.value: level.name for t, level in result.by_type},
        "by_topic": {topic: level.name for topic, level in result.by_topic},
        "pronunciation": {
            "mean_confidence": result.pronunciation.mean_confidence,
            "low_confidence_rate": result.pronunciation.low_confidence_rate,
            "indicative": result.pronunciation.indicative,
        },
        "answers": [_answer_json(a) for a in result.assessments],
    }


def report_json(report: Report) -> dict:
    return {
        "final_level": report.final_level.name,
        "scored_answers": report.scored_answers,
        "expected_answers": report.expected_answers,
        "limiting": (
            {
                "dimension": report.limiting.dimension.value,
                "label_ko": report.limiting.label_ko,
                "level": report.limiting.level.name,
                "without_cap": report.limiting.without_cap.name,
            }
            if report.limiting is not None
            else None
        ),
        "dimensions": [
            {
                "dimension": d.dimension.value,
                "label_ko": d.label_ko,
                "weight": d.weight,
                "level": d.level.name,
                "evidence": [
                    {
                        "quote": e.quote,
                        "issue_ko": e.issue_ko,
                        "correction_en": e.correction_en,
                        "answer_index": e.answer_index,
                    }
                    for e in d.evidence
                ],
            }
            for d in report.dimensions
        ],
        "unclear": [
            {
                "text": w.text,
                "probability": w.probability,
                "context": w.context,
                "answer_index": w.answer_index,
            }
            for w in report.unclear
        ],
        "by_type": [
            {"id": t.value, "label_ko": label, "level": level.name}
            for t, label, level in report.by_type
        ],
        "by_topic": [
            {"id": topic, "label_ko": label, "level": level.name}
            for topic, label, level in report.by_topic
        ],
        "metric_labels_ko": dict(METRIC_LABELS_KO),
        "averages": _metrics_json(report.averages),
        "answers": [
            {
                "index": a.index,
                "question_en": a.question_en,
                "qtype_label_ko": a.qtype_label_ko,
                "topic_label_ko": a.topic_label_ko,
                "state": a.state,
                "state_label_ko": a.state_label_ko,
                "transcript_text": a.transcript_text,
                "metrics": _metrics_json(a.metrics),
                "scores": [
                    {
                        "dimension": s.dimension.value,
                        "label_ko": s.label_ko,
                        "level": s.level.name,
                        "comment_ko": s.comment_ko,
                        "evidence": [
                            {
                                "quote": e.quote,
                                "issue_ko": e.issue_ko,
                                "correction_en": e.correction_en,
                            }
                            for e in s.evidence
                        ],
                    }
                    for s in a.scores
                ],
            }
            for a in report.answers
        ],
    }


def _metrics_json(metrics) -> dict | None:
    if metrics is None:
        return None
    return {
        "duration_s": metrics.duration_s,
        "word_count": metrics.word_count,
        "words_per_minute": metrics.words_per_minute,
        "pause_ratio": metrics.pause_ratio,
        "mean_utterance_length": metrics.mean_utterance_length,
    }


def read_answers_tolerantly(
    root: Path, session_id: str, state: SessionState
) -> tuple[tuple[AnswerAssessment, ...], tuple[int, ...]]:
    """Every answer that could be read, and the indices of the ones that could not.

    A single corrupt `answer-NN.json` must not cost the candidate the other
    fourteen, so this reports the damage instead of raising.

    `_answer_from_json` also raises `KeyError` on a field an older schema
    never wrote, `KeyError`/`ValueError` on an enum value the current code no
    longer recognises, and `TypeError` when `AnswerMetrics(**metrics)` is
    missing one of its keyword arguments — `mean_utterance_length` postdates
    phase 3, so that is the plausible real case. All of those are a
    syntactically valid file that is still the wrong shape, and are caught
    here too, alongside the read/parse failures, so a schema mismatch
    degrades the same way a truncated file does. The failure is not
    swallowed silently: it is a real bug (a stale or hand-edited answer
    file) and the operator needs to see it, so the full traceback goes to
    stderr the same way `Worker._loop` already surfaces a dead task — the
    candidate keeps their other answers, the operator sees what broke.
    """
    scored = set(state.scored_indices())
    found = []
    broken = []
    for record in state.questions:
        if record.index not in scored:
            continue
        try:
            found.append(read_answer(root, session_id, record.index))
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
            broken.append(record.index)
            traceback.print_exc()
    return tuple(found), tuple(broken)


def _answer_json(assessment: AnswerAssessment) -> dict:
    metrics = assessment.metrics
    return {
        "index": assessment.question_index,
        "question_en": assessment.question.text_en,
        "slot": {
            "qtype": assessment.question.slot.qtype.value,
            "topic_id": assessment.question.slot.topic_id,
            "combo_id": assessment.question.slot.combo_id,
            "advanced": assessment.question.slot.advanced,
            "target": assessment.question.slot.target.name,
        },
        "transcript": {
            "text": assessment.transcript.text,
            "duration_s": assessment.transcript.duration_s,
            "words": [
                {"text": w.text, "start": w.start, "end": w.end, "probability": w.probability}
                for w in assessment.transcript.words
            ],
            "speech_spans": [
                {"start": s.start, "end": s.end} for s in assessment.transcript.speech_spans
            ],
        },
        "metrics": {
            "duration_s": metrics.duration_s,
            "word_count": metrics.word_count,
            "words_per_minute": metrics.words_per_minute,
            "pause_ratio": metrics.pause_ratio,
            "type_token_ratio": metrics.type_token_ratio,
            "mean_utterance_length": metrics.mean_utterance_length,
            "mean_confidence": metrics.mean_confidence,
            "low_confidence_rate": metrics.low_confidence_rate,
        },
        "scores": [
            {
                "dimension": s.dimension.value,
                "level": s.level.name,
                "comment_ko": s.comment_ko,
                "evidence": [
                    {"quote": e.quote, "issue_ko": e.issue_ko, "correction_en": e.correction_en}
                    for e in s.evidence
                ],
            }
            for s in assessment.dimension_scores
        ],
    }


def _answer_from_json(payload: dict) -> AnswerAssessment:
    slot = payload["slot"]
    transcript = payload["transcript"]
    metrics = payload["metrics"]
    return AnswerAssessment(
        question=Question(
            slot=QuestionSlot(
                index=payload["index"],
                qtype=QuestionType(slot["qtype"]),
                topic_id=slot["topic_id"],
                combo_id=slot["combo_id"],
                advanced=slot["advanced"],
                target=ActflLevel[slot["target"]],
            ),
            text_en=payload["question_en"],
        ),
        transcript=Transcript(
            text=transcript["text"],
            words=tuple(
                Word(w["text"], w["start"], w["end"], w["probability"])
                for w in transcript["words"]
            ),
            speech_spans=tuple(
                Span(s["start"], s["end"]) for s in transcript["speech_spans"]
            ),
            duration_s=transcript["duration_s"],
        ),
        dimension_scores=tuple(
            DimensionScore(
                dimension=Dimension(s["dimension"]),
                level=ActflLevel[s["level"]],
                comment_ko=s["comment_ko"],
                evidence=tuple(
                    Evidence(e["quote"], e["issue_ko"], e["correction_en"])
                    for e in s["evidence"]
                ),
            )
            for s in payload["scores"]
        ),
        metrics=AnswerMetrics(**metrics),
    )
