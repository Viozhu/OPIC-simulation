"""The session on disk: one folder, one `session.json`, written by rename.

`session.json` is the source of truth. It is written whole to a temporary file
and published with `Path.replace`, so a crash mid-write leaves the previous
version intact rather than a truncated one.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from opic.core.survey import Housing, Occupation, RecentCourse, SurveyAnswers
from opic.session.state import (
    AnswerRecord,
    AnswerState,
    QuestionRecord,
    SessionState,
    Step,
)

SESSION_FILE = "session.json"
RESULT_FILE = "result.json"


def new_session_id(now: datetime) -> str:
    """Readable and sortable, with no new dependency."""
    return now.strftime("%Y%m%d-%H%M%S")


def session_dir(root: Path, session_id: str) -> Path:
    return root / session_id


def answer_audio_path(root: Path, session_id: str, index: int, suffix: str) -> Path:
    """Where one recorded answer lives. The suffix comes from the browser."""
    return session_dir(root, session_id) / f"answer-{index:02d}{suffix}"


def answer_result_path(root: Path, session_id: str, index: int) -> Path:
    return session_dir(root, session_id) / f"answer-{index:02d}.json"


def page_path(root: Path, session_id: str) -> Path:
    """The standalone report page, next to the result it was rendered from.

    Korean, like every other thing the candidate reads, so the name says so:
    a future English or Spanish page is a different file, not a different
    version of this one.
    """
    return session_dir(root, session_id) / "report-ko.html"


def result_path(root: Path, session_id: str) -> Path:
    return session_dir(root, session_id) / RESULT_FILE


def create(root: Path, seed: int, now: datetime) -> SessionState:
    state = SessionState.new(new_session_id(now), seed)
    session_dir(root, state.id).mkdir(parents=True, exist_ok=True)
    save(root, state)
    return state


def save(root: Path, state: SessionState) -> None:
    directory = session_dir(root, state.id)
    directory.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(to_json(state), ensure_ascii=False, indent=2)
    temporary = directory / f"{SESSION_FILE}.tmp"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(directory / SESSION_FILE)


def load(root: Path, session_id: str) -> SessionState:
    path = session_dir(root, session_id) / SESSION_FILE
    if not path.exists():
        raise FileNotFoundError(f"no session {session_id!r} under {root}")
    return from_json(json.loads(path.read_text(encoding="utf-8")))


def list_unfinished(root: Path) -> tuple[str, ...]:
    """Sessions with a `session.json` and no `result.json`, oldest first."""
    if not root.exists():
        return ()
    return tuple(
        sorted(
            directory.name
            for directory in root.iterdir()
            if (directory / SESSION_FILE).exists()
            and not (directory / RESULT_FILE).exists()
        )
    )


def to_json(state: SessionState) -> dict:
    return {
        "id": state.id,
        "step": state.step.value,
        "seed": state.seed,
        "self_assess_level": state.self_assess_level,
        "survey": _survey_json(state.survey),
        "questions": [
            {
                "index": q.index,
                "qtype": q.qtype,
                "topic_id": q.topic_id,
                "combo_id": q.combo_id,
                "advanced": q.advanced,
                "target": q.target,
                "text_en": q.text_en,
                "audio_path": q.audio_path,
            }
            for q in state.questions
        ],
        "answers": [
            {
                "index": a.index,
                "state": a.state.value,
                "audio_path": a.audio_path,
                "error": a.error,
            }
            for a in state.answers
        ],
    }


def from_json(payload: dict) -> SessionState:
    return SessionState(
        id=payload["id"],
        step=Step(payload["step"]),
        seed=payload["seed"],
        survey=_survey_from_json(payload["survey"]),
        self_assess_level=payload["self_assess_level"],
        questions=tuple(
            QuestionRecord(
                index=q["index"],
                qtype=q["qtype"],
                topic_id=q["topic_id"],
                combo_id=q["combo_id"],
                advanced=q["advanced"],
                target=q["target"],
                text_en=q["text_en"],
                audio_path=q["audio_path"],
            )
            for q in payload["questions"]
        ),
        answers=tuple(
            AnswerRecord(
                index=a["index"],
                state=AnswerState(a["state"]),
                audio_path=a["audio_path"],
                error=a["error"],
            )
            for a in payload["answers"]
        ),
    )


def _survey_json(survey: SurveyAnswers | None) -> dict | None:
    if survey is None:
        return None
    return {
        "occupation": survey.occupation.value,
        "is_student": survey.is_student,
        "housing": survey.housing.value,
        "selected_item_ids": list(survey.selected_item_ids),
        "recent_course": survey.recent_course.value if survey.recent_course else None,
    }


def _survey_from_json(payload: dict | None) -> SurveyAnswers | None:
    if payload is None:
        return None
    course = payload["recent_course"]
    return SurveyAnswers(
        occupation=Occupation(payload["occupation"]),
        is_student=payload["is_student"],
        housing=Housing(payload["housing"]),
        selected_item_ids=tuple(payload["selected_item_ids"]),
        recent_course=RecentCourse(course) if course else None,
    )
