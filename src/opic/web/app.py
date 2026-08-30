"""HTTP only: validate, delegate to `session/`, answer JSON.

No exam logic lives here. Anything that decides what happens next belongs in
`opic.session`, which is why these handlers read as plumbing.
"""

from __future__ import annotations

import json
import math
import secrets
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from opic.core.report import build_report
from opic.core.selfassess import SELF_ASSESS_OPTIONS
from opic.core.survey import (
    GROUP_LABELS_KO,
    GROUP_MINIMUMS,
    HOUSING_LABELS_KO,
    MIN_TOTAL_ITEMS,
    OCCUPATION_LABELS_KO,
    QUESTION_LABELS_KO,
    RECENT_COURSE_LABELS_KO,
    SURVEY_ITEMS,
    YES_NO_LABELS_KO,
    Housing,
    Occupation,
    RecentCourse,
    SurveyAnswers,
    TopicGroup,
    describe_issue_ko,
    validate_survey,
)
from opic.session import assessments as answers_on_disk
from opic.session import pages
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


# The real exam allows one replay per question, and the client enforces that.
# A handful is still accepted here so a client bug shows up as odd metrics
# rather than a refused upload — but not an unbounded list, which would let a
# forged POST push arbitrarily much into `session.json`.
MAX_REPLAY_SPANS = 8


def _replay_spans(raw: str) -> tuple[tuple[float, float], ...]:
    """Parse the browser's replay timings, or refuse the upload.

    These arrive as JSON in a form field because they belong to the recording
    and must land with it — an answer is judged as soon as it is uploaded, so
    there is no later request to carry them. The browser is not trusted: this
    is the boundary where a malformed or hostile list stops.
    """
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="replay_spans is not JSON") from None
    if not isinstance(parsed, list) or len(parsed) > MAX_REPLAY_SPANS:
        raise HTTPException(status_code=422, detail="replay_spans must be a short list")

    spans = []
    for pair in parsed:
        if not isinstance(pair, list | tuple) or len(pair) != 2:
            raise HTTPException(status_code=422, detail="replay_spans holds a non-pair")
        start, end = pair
        # `bool` is an `int`, and `math.isfinite` accepts NaN's type happily —
        # both are rejected here so nothing but a real number reaches metrics.
        if any(isinstance(v, bool) or not isinstance(v, int | float) for v in pair):
            raise HTTPException(status_code=422, detail="replay_spans is not numeric")
        if not (math.isfinite(start) and math.isfinite(end)):
            raise HTTPException(status_code=422, detail="replay_spans is not finite")
        if start < 0 or end < start:
            raise HTTPException(status_code=422, detail="replay_spans is not ordered")
        spans.append((float(start), float(end)))
    return tuple(spans)


SHARE_COOKIE = "opic_share"
SHARE_KEY_PARAM = "k"
SHARE_COOKIE_MAX_AGE = 12 * 60 * 60


def _install_share_gate(app: FastAPI, token: str) -> None:
    """Put the whole app behind one secret carried in the link.

    This exists for the one case where the server runs on a laptop and a tunnel
    makes it reachable by one other person. It is not authentication: there is
    one secret, everybody who has the link holds it, and nothing here checks
    who owns which session. It only ensures that a stranger who finds the
    hostname — tunnel hostnames are not private, and they get scanned — sees a
    404 instead of somebody's exam.

    The key is accepted on a GET, which is how a browser opens a shared link.
    Every other method needs the cookie the GET leaves behind, so a token that
    leaked into a log cannot be replayed as a bare POST.
    """

    @app.middleware("http")
    async def gate(request, call_next):
        if secrets.compare_digest(request.cookies.get(SHARE_COOKIE, ""), token):
            return await call_next(request)

        offered = request.query_params.get(SHARE_KEY_PARAM, "")
        if request.method in ("GET", "HEAD") and secrets.compare_digest(offered, token):
            # Send the browser back to the same place without the key. It has
            # the cookie now, and the token has no business staying in the
            # address bar, in history, in a bookmark or in a Referer header.
            destination = request.url.remove_query_params(SHARE_KEY_PARAM)
            response = RedirectResponse(str(destination), status_code=303)
            response.set_cookie(
                SHARE_COOKIE,
                token,
                max_age=SHARE_COOKIE_MAX_AGE,
                httponly=True,
                samesite="lax",
                # cloudflared speaks plain HTTP to this process and reports the
                # real scheme in a header. Marking the cookie Secure on a plain
                # HTTP run would mean the browser never sends it back.
                secure=request.headers.get("x-forwarded-proto", request.url.scheme)
                == "https",
            )
            return response

        # 404 and not 401: an authentication challenge would confirm that
        # something is here worth guessing at.
        return JSONResponse(status_code=404, content={"detail": "not found"})


def create_app(
    root: Path,
    worker: Worker,
    clock: Callable[[], datetime] = datetime.now,
    share_token: str | None = None,
) -> FastAPI:
    app = FastAPI(title="OPIc simulator")
    app.state.root = root

    if share_token:
        _install_share_gate(app, share_token)

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
            "question_labels": QUESTION_LABELS_KO,
            "yes_no": [
                {"id": "yes", "label_ko": YES_NO_LABELS_KO[True]},
                {"id": "no", "label_ko": YES_NO_LABELS_KO[False]},
            ],
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
                content={
                    "issues": [
                        {
                            "error": "unknown_value",
                            "detail": str(error),
                            "message_ko": "입력한 값 중 알 수 없는 값이 있습니다. 다시 선택해 주세요.",
                        }
                    ]
                },
            )

        issues = validate_survey(answers)
        if issues:
            return JSONResponse(
                status_code=422,
                content={
                    "issues": [
                        {
                            "error": issue.error.value,
                            "detail": issue.detail,
                            "message_ko": describe_issue_ko(issue),
                        }
                        for issue in issues
                    ]
                },
            )

        state = worker.update(
            session_id, lambda s: advance(s.with_survey(answers), Step.LEVEL)
        )
        return session_json(state)

    @app.get("/api/levels")
    def levels() -> dict:
        return {
            "options": [
                {
                    "level": option.level,
                    "description_ko": option.description_ko,
                    "sample_audio_id": option.sample_audio_id,
                }
                for option in SELF_ASSESS_OPTIONS
            ]
        }

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
                content={
                    "issues": [
                        {
                            "error": "bad_level",
                            "detail": str(payload.level),
                            "message_ko": "1부터 6 사이의 레벨을 선택해 주세요.",
                        }
                    ]
                },
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
    async def post_answer(
        session_id: str,
        index: int,
        audio: UploadFile = File(...),
        # Defaulted, so a client that does not send it — the sample step, an
        # older cached page — still uploads, and simply measures as if the
        # question had never been replayed.
        replay_spans: str = Form("[]"),
    ):
        state = load_or_404(session_id)
        replayed = _replay_spans(replay_spans)
        if state.step is not Step.TEST:
            # `reason` is what the browser is meant to branch on; the sentence
            # in `detail` is only for whoever is reading devtools. Keeping
            # them separate means a future rewording of the sentence can never
            # silently flip which 409 case the client thinks it got.
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": f"answers are only accepted during the test, not at {state.step.value}",
                    "reason": "not_in_test_step",
                },
            )
        record = next((a for a in state.answers if a.index == index), None)
        if record is None:
            raise HTTPException(status_code=404, detail="no such question")
        if record.state is not AnswerState.PENDING:
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": f"answer {index} is already {record.state.value}",
                    "reason": "answer_already_recorded",
                },
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
                    status_code=409,
                    detail={
                        "detail": f"answer {index} is already {label}",
                        "reason": "answer_already_recorded",
                    },
                )
            return s.with_answer(
                AnswerRecord(
                    index,
                    AnswerState.RECORDED,
                    target.name,
                    replay_spans=replayed,
                )
            )

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

    @app.get("/api/sessions/{session_id}/report")
    def report(session_id: str):
        state = load_or_404(session_id)
        if not store.result_path(root, session_id).exists():
            raise HTTPException(status_code=404, detail="not scored yet")
        judged, broken = answers_on_disk.read_answers_tolerantly(root, session_id, state)
        if not judged:
            raise HTTPException(status_code=404, detail="not scored yet")
        exam = answers_on_disk.aggregate_available(state.questions, judged)
        questions = [answers_on_disk.question_from_record(r) for r in state.questions]
        built = build_report(exam, questions, unreadable=broken)
        return JSONResponse(content=answers_on_disk.report_json(built))

    @app.get("/api/sessions/{session_id}/page", response_class=HTMLResponse)
    def report_page(session_id: str) -> str:
        """The report as `core/page.py` renders it — the same document the
        candidate can keep, framed by the done screen.

        `/report` next to this one is the JSON the older screen was built on
        and stays where it is: it is what the fallback path reads when this
        route has nothing to give.
        """
        load_or_404(session_id)
        html = pages.html_for(root, session_id)
        if html is None:
            raise HTTPException(status_code=404, detail="not scored yet")
        return html

    return app
