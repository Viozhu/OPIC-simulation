"""The session on disk: one folder, one `session.json`, written by rename.

`session.json` is the source of truth. It is written whole to a temporary file
and published with `Path.replace`, so a crash mid-write leaves the previous
version intact rather than a truncated one.
"""

from __future__ import annotations

import json
import re
import secrets
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


# El id es la única cosa que separa el examen de un candidato del de otro:
# `GET /api/sessions/{id}` no comprueba quién pregunta. Mientras el nombre de
# máquina moría con cada túnel, una marca de tiempo era tolerable. Con un
# nombre permanente se recorre a mano, así que el id pasa a ser un secreto.
def new_session_id() -> str:
    return secrets.token_urlsafe(16)


# El formato de los ids anteriores a ese cambio. Sus carpetas no se renombran,
# así que hay que seguir sabiendo leerlas.
_LEGACY_ID = re.compile(r"^\d{8}-\d{6}$")


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
    state = SessionState.new(new_session_id(), seed, now)
    # `exist_ok=False`: una colisión con 128 bits es imposible en la práctica,
    # y si ocurriera preferimos el error a dos exámenes en la misma carpeta.
    session_dir(root, state.id).mkdir(parents=True, exist_ok=False)
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
    # La fecha de modificación es el último recurso para una sesión anterior a
    # `created_at` cuyo nombre de carpeta tampoco es una marca de tiempo.
    fallback = datetime.fromtimestamp(path.stat().st_mtime)
    return from_json(json.loads(path.read_text(encoding="utf-8")), fallback)


def list_unfinished(root: Path) -> tuple[str, ...]:
    """Sesiones con `session.json` y sin `result.json`, la más antigua primero.

    Ordenar por nombre dejó de servir cuando el id dejó de ser una marca de
    tiempo, así que esto lee cada sesión. Con miles de carpetas seguiría siendo
    trivial; si algún día no lo fuera, la fecha ya está en el JSON.
    """
    if not root.exists():
        return ()
    unfinished = []
    for directory in root.iterdir():
        if not (directory / SESSION_FILE).exists():
            continue
        if (directory / RESULT_FILE).exists():
            continue
        try:
            state = load(root, directory.name)
        except (OSError, ValueError, KeyError):
            continue
        unfinished.append((state.created_at, state.id))
    return tuple(session_id for _, session_id in sorted(unfinished))


def to_json(state: SessionState) -> dict:
    return {
        "id": state.id,
        "created_at": state.created_at.isoformat(),
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
                "replay_spans": [[start, end] for start, end in a.replay_spans],
            }
            for a in state.answers
        ],
    }


def from_json(payload: dict, fallback: datetime | None = None) -> SessionState:
    return SessionState(
        id=payload["id"],
        created_at=_created_at(payload, fallback),
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
                # `.get`, unlike every other field here, because a session that
                # was already in progress when replay timing landed has answers
                # on disk without the key; those answers still have to load.
                replay_spans=tuple(
                    (start, end) for start, end in a.get("replay_spans", ())
                ),
            )
            for a in payload["answers"]
        ),
    )


def _created_at(payload: dict, fallback: datetime | None) -> datetime:
    raw = payload.get("created_at")
    if raw:
        return datetime.fromisoformat(raw)
    if _LEGACY_ID.match(payload["id"]):
        return datetime.strptime(payload["id"], "%Y%m%d-%H%M%S")
    return fallback or datetime.min


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
