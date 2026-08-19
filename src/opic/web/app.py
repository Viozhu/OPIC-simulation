"""HTTP only: validate, delegate to `session/`, answer JSON.

No exam logic lives here. Anything that decides what happens next belongs in
`opic.session`, which is why these handlers read as plumbing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from opic.core.survey import (
    GROUP_LABELS_KO,
    GROUP_MINIMUMS,
    HOUSING_LABELS_KO,
    MIN_TOTAL_ITEMS,
    OCCUPATION_LABELS_KO,
    RECENT_COURSE_LABELS_KO,
    SURVEY_ITEMS,
    Housing,
    Occupation,
    RecentCourse,
    SurveyAnswers,
    TopicGroup,
    validate_survey,
)
from opic.session import store
from opic.session.state import Step, TransitionError, advance
from opic.session.worker import Task, Worker


class SurveyPayload(BaseModel):
    occupation: str
    is_student: bool
    housing: str
    selected_item_ids: list[str]
    recent_course: str | None = None


class LevelPayload(BaseModel):
    level: int


def create_app(
    root: Path,
    worker: Worker,
    clock: Callable[[], datetime] = datetime.now,
) -> FastAPI:
    app = FastAPI(title="OPIc simulator")

    @app.exception_handler(TransitionError)
    async def transition_error_handler(request, exc: TransitionError):
        # A refresh or a double-submit is an ordinary thing for a browser to do.
        # The state machine's refusal is a client error, not a crash.
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    def session_json(state) -> dict:
        payload = store.to_json(state)
        payload["questions_ready"] = state.questions_ready
        # The browser fetches audio through its own route; the host's directory
        # layout is not its business.
        for question in payload["questions"]:
            question["audio_ready"] = question.pop("audio_path") is not None
        return payload

    def load_or_404(session_id: str):
        try:
            return store.load(root, session_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="session not found") from None

    @app.post("/api/sessions", status_code=201)
    def create_session() -> dict:
        state = store.create(root, seed=int(clock().timestamp()), now=clock())
        return session_json(state)

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str) -> dict:
        return session_json(load_or_404(session_id))

    @app.get("/api/survey")
    def survey_schema() -> dict:
        return {
            "min_total_items": MIN_TOTAL_ITEMS,
            "occupations": [
                {"id": occupation.value, "label_ko": label}
                for occupation, label in OCCUPATION_LABELS_KO.items()
            ],
            "housing": [
                {"id": housing.value, "label_ko": label}
                for housing, label in HOUSING_LABELS_KO.items()
            ],
            "recent_courses": [
                {"id": course.value, "label_ko": label}
                for course, label in RECENT_COURSE_LABELS_KO.items()
            ],
            "groups": [
                {
                    "id": group.value,
                    "label_ko": GROUP_LABELS_KO[group],
                    "minimum": GROUP_MINIMUMS[group],
                    "items": [
                        {"id": item.id, "label_ko": item.label_ko}
                        for item in SURVEY_ITEMS
                        if item.group is group
                    ],
                }
                for group in TopicGroup
            ],
        }

    @app.put("/api/sessions/{session_id}/survey")
    def put_survey(session_id: str, payload: SurveyPayload):
        load_or_404(session_id)
        try:
            answers = SurveyAnswers(
                occupation=Occupation(payload.occupation),
                is_student=payload.is_student,
                housing=Housing(payload.housing),
                selected_item_ids=tuple(payload.selected_item_ids),
                recent_course=(
                    RecentCourse(payload.recent_course) if payload.recent_course else None
                ),
            )
        except ValueError as error:
            return JSONResponse(
                status_code=422,
                content={"issues": [{"error": "unknown_value", "detail": str(error)}]},
            )

        issues = validate_survey(answers)
        if issues:
            return JSONResponse(
                status_code=422,
                content={
                    "issues": [
                        {"error": issue.error.value, "detail": issue.detail}
                        for issue in issues
                    ]
                },
            )

        state = worker.update(
            session_id, lambda s: advance(s.with_survey(answers), Step.LEVEL)
        )
        return session_json(state)

    @app.put("/api/sessions/{session_id}/level")
    def put_level(session_id: str, payload: LevelPayload):
        state = load_or_404(session_id)
        if state.step is not Step.LEVEL:
            raise HTTPException(
                status_code=409,
                detail=f"expected step level, session is at {state.step.value}",
            )
        if payload.level not in range(1, 7):
            return JSONResponse(
                status_code=422,
                content={"issues": [{"error": "bad_level", "detail": str(payload.level)}]},
            )

        state = worker.update(
            session_id, lambda s: advance(s.with_level(payload.level), Step.SETUP)
        )
        worker.submit(Task("generate", session_id))
        return session_json(state)

    @app.get("/api/sessions/{session_id}/questions/{index}/audio")
    def question_audio(session_id: str, index: int):
        state = load_or_404(session_id)
        record = next((q for q in state.questions if q.index == index), None)
        if record is None or not record.audio_path:
            raise HTTPException(status_code=404, detail="audio not ready")
        path = Path(record.audio_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="audio not ready")
        return FileResponse(path, media_type="audio/wav")

    return app
