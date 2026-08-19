"""HTTP only: validate, delegate to `session/`, answer JSON.

No exam logic lives here. Anything that decides what happens next belongs in
`opic.session`, which is why these handlers read as plumbing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
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
from opic.session.state import AnswerRecord, AnswerState, Step, TransitionError, advance
from opic.session.worker import Task, Worker


class SurveyPayload(BaseModel):
    occupation: str
    is_student: bool
    housing: str
    selected_item_ids: list[str]
    recent_course: str | None = None


class LevelPayload(BaseModel):
    level: int


class StepPayload(BaseModel):
    step: str


# The browser's filename picks the suffix, and the browser is not trusted: it
# could send a filename that is absurdly long or has no recognisable audio
# extension at all. Rather than propagate that into a filesystem call (where a
# too-long name turns into an unhandled OSError), fall back to `.webm` for
# anything that is not one of the extensions the two supported browsers send.
ALLOWED_AUDIO_SUFFIXES = frozenset({".webm", ".mp4", ".m4a", ".ogg", ".wav"})


def _safe_audio_suffix(filename: str | None) -> str:
    suffix = Path(filename or "answer.webm").suffix.lower()
    return suffix if suffix in ALLOWED_AUDIO_SUFFIXES else ".webm"


def create_app(
    root: Path,
    worker: Worker,
    clock: Callable[[], datetime] = datetime.now,
) -> FastAPI:
    app = FastAPI(title="OPIc simulator")
    app.state.root = root

    here = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=here / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (here / "templates" / "index.html").read_text(encoding="utf-8")

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

    @app.post("/api/sessions/{session_id}/step")
    def post_step(session_id: str, payload: StepPayload):
        load_or_404(session_id)
        try:
            target = Step(payload.step)
        except ValueError:
            raise HTTPException(status_code=422, detail="unknown step") from None
        state = worker.update(session_id, lambda s: advance(s, target))
        return session_json(state)

    @app.post("/api/sessions/{session_id}/answers/{index}", status_code=202)
    async def post_answer(session_id: str, index: int, audio: UploadFile = File(...)):
        state = load_or_404(session_id)
        if state.step is not Step.TEST:
            raise HTTPException(
                status_code=409,
                detail=f"answers are only accepted during the test, not at {state.step.value}",
            )
        record = next((a for a in state.answers if a.index == index), None)
        if record is None:
            raise HTTPException(status_code=404, detail="no such question")
        if record.state is not AnswerState.PENDING:
            raise HTTPException(
                status_code=409, detail=f"answer {index} is already {record.state.value}"
            )

        suffix = _safe_audio_suffix(audio.filename)
        target = store.answer_audio_path(root, session_id, index, suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a unique temporary file first, and only publish it at the
        # final path once the claim below succeeds. Two uploads racing for the
        # same index would otherwise both pass the PENDING check above (it was
        # read outside any lock) and both write the same final path, silently
        # discarding whichever recording lost the write.
        temporary = target.with_name(f"{target.name}.{uuid4().hex}.part")
        temporary.write_bytes(await audio.read())

        def claim(s):
            current = next((a for a in s.answers if a.index == index), None)
            if current is None or current.state is not AnswerState.PENDING:
                label = current.state.value if current is not None else "missing"
                raise HTTPException(
                    status_code=409, detail=f"answer {index} is already {label}"
                )
            return s.with_answer(AnswerRecord(index, AnswerState.RECORDED, target.name))

        try:
            # `worker.update` holds the same lock every other mutation goes
            # through, so re-checking PENDING here — not just above — is what
            # actually stops a double-click from recording twice: the loser
            # sees the winner's RECORDED state inside the lock and is refused.
            state = worker.update(session_id, claim)
        except HTTPException:
            temporary.unlink(missing_ok=True)
            raise
        temporary.replace(target)
        worker.submit(Task("evaluate", session_id, index))
        return session_json(state)

    @app.get("/api/sessions/{session_id}/progress")
    def progress(session_id: str) -> dict:
        state = load_or_404(session_id)
        counted = {value: 0 for value in ("pending", "recorded", "transcribed", "scored", "failed")}
        for answer in state.answers:
            counted[answer.state.value] += 1
        return {
            "expected": len(state.questions),
            "total": len(state.answers),
            "scored": counted["scored"],
            "failed": counted["failed"],
            "recorded": counted["recorded"],
            "done": store.result_path(root, session_id).exists(),
        }

    @app.get("/api/sessions/{session_id}/result")
    def result(session_id: str):
        load_or_404(session_id)
        path = store.result_path(root, session_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="not scored yet")
        return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))

    return app
