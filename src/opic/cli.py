from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from opic.adapters import config
from opic.adapters.llm import OllamaClient
from opic.adapters.stt import WhisperSpeechToText
from opic.adapters.tts import SayTextToSpeech
from opic.core.metrics import compute_metrics
from opic.core.questions import build_blueprint
from opic.core.scoring import AnswerAssessment, ExamResult, aggregate
from opic.core.survey import (
    Housing,
    Occupation,
    RecentCourse,
    SurveyAnswers,
    validate_survey,
)

ANSWER_SECONDS = 90


def record_answer(
    path: Path,
    seconds: int = ANSWER_SECONDS,
    device: str = ":0",
) -> Path:
    """Capture one spoken answer from the microphone via ffmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "avfoundation", "-i", device,
            "-t", str(seconds),
            "-ar", "16000", "-ac", "1",
            str(path),
        ],
        check=True,
    )
    return path


def play(path: Path) -> None:
    subprocess.run(["afplay", str(path)], check=True)


def run_exam(
    answers: SurveyAnswers,
    self_assess_level: int,
    seed: int,
    session_dir: Path,
    tts,
    stt,
    writer,
    rater,
    recorder: Callable[[Path, int], Path] = record_answer,
    player: Callable[[Path], None] = play,
) -> ExamResult:
    """Run a whole exam: ask, record, transcribe, judge, aggregate, save.

    Every collaborator is an argument so the flow can be exercised without a
    microphone or a model.
    """
    issues = validate_survey(answers)
    if issues:
        detail = ", ".join(f"{i.error.value}({i.detail})" for i in issues)
        raise ValueError(f"invalid survey: {detail}")

    session_dir.mkdir(parents=True, exist_ok=True)
    blueprint = build_blueprint(answers, self_assess_level, seed)
    questions = writer.write(answers, blueprint)

    recordings: list[Path] = []
    for question in questions:
        player(tts.synthesize(question.text_en))
        recordings.append(
            recorder(session_dir / f"answer-{question.slot.index:02d}.wav", ANSWER_SECONDS)
        )

    assessments: list[AnswerAssessment] = []
    for question, recording in zip(questions, recordings, strict=True):
        transcript = stt.transcribe(recording)
        metrics = compute_metrics(transcript)
        assessments.append(
            AnswerAssessment(
                question=question,
                transcript=transcript,
                dimension_scores=rater.rate(question, transcript, metrics),
                metrics=metrics,
            )
        )

    result = aggregate(blueprint, assessments)
    (session_dir / "result.json").write_text(
        json.dumps(_as_json(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _as_json(result: ExamResult) -> dict:
    return {
        "final_level": result.final_level.name,
        "dimensions": {d.value: level.name for d, level in result.dimension_levels},
        "by_type": {t.value: level.name for t, level in result.by_type},
        "by_topic": {topic: level.name for topic, level in result.by_topic},
        "pronunciation": {
            "mean_confidence": result.pronunciation.mean_confidence,
            "low_confidence_rate": result.pronunciation.low_confidence_rate,
            "indicative": result.pronunciation.indicative,
        },
        "answers": [
            {
                "index": a.question_index,
                "question_en": a.question.text_en,
                "transcript": a.transcript.text,
                "words_per_minute": a.metrics.words_per_minute,
                "pause_ratio": a.metrics.pause_ratio,
                "scores": [
                    {
                        "dimension": s.dimension.value,
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
                    for s in a.dimension_scores
                ],
            }
            for a in result.assessments
        ],
    }


REQUIRED_SURVEY_FIELDS = ("occupation", "is_student", "housing", "selected_item_ids")


def load_survey(path: Path) -> SurveyAnswers:
    """Read survey answers from JSON, failing with something a person can act on.

    Everything here happens before `run_exam` gets a chance to validate, so a
    bare KeyError from this point would be the last thing the user ever sees.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc

    missing = [field for field in REQUIRED_SURVEY_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"{path} is missing: {', '.join(missing)}")

    def choose(enum, value, field):
        try:
            return enum(value)
        except ValueError as exc:
            allowed = ", ".join(member.value for member in enum)
            raise ValueError(
                f"{field} is {value!r}; expected one of: {allowed}"
            ) from exc

    course = raw.get("recent_course")
    return SurveyAnswers(
        occupation=choose(Occupation, raw["occupation"], "occupation"),
        is_student=bool(raw["is_student"]),
        housing=choose(Housing, raw["housing"], "housing"),
        selected_item_ids=tuple(raw["selected_item_ids"]),
        recent_course=choose(RecentCourse, course, "recent_course") if course else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opic", description="Run a local OPIc mock exam")
    parser.add_argument("--survey", type=Path, required=True, help="survey answers as JSON")
    parser.add_argument("--level", type=int, required=True, choices=range(1, 7))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--session", type=Path, default=Path("data/sessions/latest"))
    args = parser.parse_args(argv)

    try:
        answers = load_survey(args.survey)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    client = OllamaClient()
    result = run_exam(
        answers=answers,
        self_assess_level=args.level,
        seed=args.seed,
        session_dir=args.session,
        tts=SayTextToSpeech(cache_dir=Path("data/tts_cache")),
        stt=WhisperSpeechToText(),
        writer=client,
        rater=client,
    )
    print(f"\n최종 등급: {result.final_level.name}")
    print(f"결과 파일: {args.session / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
