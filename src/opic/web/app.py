"""HTTP only: validate, delegate to `session/`, answer JSON.

No exam logic lives here. Anything that decides what happens next belongs in
`opic.session`, which is why these handlers read as plumbing.
"""

from __future__ import annotations

import asyncio
import json
import math
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from opic.core.candidate import (
    Candidate,
    describe_candidate_error_ko,
    validate_candidate,
)
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
from opic.session.state import AnswerRecord, AnswerState, Feedback, Step, TransitionError, advance
from opic.session.worker import Task, Worker
from opic.web.shutdown import IdleWatch, watch_and_stop


class SurveyPayload(BaseModel):
    occupation: str
    is_student: bool
    housing: str
    selected_item_ids: list[str]
    recent_course: str | None = None


class LevelPayload(BaseModel):
    level: int


class IdentityPayload(BaseModel):
    name: str
    email: str


class StepPayload(BaseModel):
    step: str


class FeedbackPayload(BaseModel):
    rating: int
    comment: str = ""


# Un comentario más largo que esto no es una opinión, es un accidente (o un
# intento de llenar el disco). Se recorta en vez de rechazarse: el candidato ya
# terminó el examen y no va a volver a escribirlo.
MAX_COMMENT = 2000


# The browser's filename picks the suffix, and the browser is not trusted: it
# could send a filename that is absurdly long or has no recognisable audio
# extension at all. Rather than propagate that into a filesystem call (where a
# too-long name turns into an unhandled OSError), fall back to `.webm` for
# anything that is not one of the extensions the two supported browsers send.
ALLOWED_AUDIO_SUFFIXES = frozenset({".webm", ".mp4", ".m4a", ".ogg", ".wav"})


def _safe_audio_suffix(filename: str | None) -> str:
    suffix = Path(filename or "answer.webm").suffix.lower()
    return suffix if suffix in ALLOWED_AUDIO_SUFFIXES else ".webm"


async def _read_capped(upload: UploadFile, limit: int) -> bytes | None:
    """Leer la subida sin dejar que su tamaño lo decida el cliente.

    `await upload.read()` a secas se traga lo que llegue, y con una sola cola un
    fichero enorme la bloquea entera. `None` significa que se pasó.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


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
        # El chequeo de salud queda fuera del secreto a propósito: un vigilante
        # externo no tiene el token, y lo único que aprende es `ok`.
        if request.url.path == "/healthz":
            return await call_next(request)
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


class _RateLimiter:
    """Cuántas veces se ha hecho algo por origen, en una ventana móvil.

    En memoria y por proceso: hay un solo proceso por diseño (`serve.py`), y
    reiniciar el servidor perdona a todo el mundo, que es aceptable para lo que
    esto defiende — que un enlace filtrado no genere mil exámenes a tu cuenta
    de Anthropic mientras duermes.
    """

    def __init__(self, limit: int, window: timedelta, clock: Callable[[], datetime]) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._seen: dict[str, list[datetime]] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        cutoff = now - self._window
        recent = [when for when in self._seen.get(key, []) if when > cutoff]
        if len(recent) >= self._limit:
            self._seen[key] = recent
            return False
        recent.append(now)
        self._seen[key] = recent
        return True


def _caller(request: Request) -> str:
    """Quién pregunta, visto desde detrás del túnel.

    cloudflared habla con este proceso desde 127.0.0.1, así que sin la cabecera
    todos los invitados serían el mismo origen. `cf-connecting-ip` es fiable
    aquí sólo porque el puerto no es alcanzable de otra forma: la pone
    Cloudflare y nadie más llega a este proceso.
    """
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_app(
    root: Path,
    worker: Worker,
    clock: Callable[[], datetime] = datetime.now,
    share_token: str | None = None,
    # Unos diez minutos de Opus a 64 kbps. Una respuesta de OPIc dura minuto y
    # medio; esto es holgura, no un objetivo.
    max_answer_bytes: int = 40 * 1024 * 1024,
    creates_per_hour: int = 20,
    # Veinte minutos después del último examen terminado, y con nadie más
    # dentro, el proceso se apaga solo: ver `web/shutdown.py`. `None` lo
    # desactiva, que es lo que quiere un test y lo que querría un servidor que
    # alguien decida dejar encendido.
    shutdown_after: timedelta | None = timedelta(minutes=20),
) -> FastAPI:
    def step_on_disk(session_id: str) -> Step | None:
        try:
            return store.load(root, session_id).step
        except (FileNotFoundError, OSError, ValueError, KeyError):
            # Una sesión ilegible no puede decidir nada; se queda como se vio
            # por última vez y el reloj de abandono acaba con ella.
            return None

    watch = (
        IdleWatch(shutdown_after, clock=clock, step_of=step_on_disk, busy=lambda: worker.busy)
        if shutdown_after is not None
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if watch is None:
            yield
            return
        # Nace con el servidor y muere con él. `cancel` sin esperar: la tarea no
        # tiene nada que cerrar, y esto corre dentro del apagado que ella misma
        # pudo haber pedido.
        task = asyncio.create_task(watch_and_stop(watch))
        try:
            yield
        finally:
            task.cancel()
            # Esperarla, no sólo cancelarla: si el bucle se queda pendiente
            # cuando el loop se cierra, asyncio escribe un `Task was destroyed
            # but it is pending!` en el log de errores — justo el sitio donde
            # `docs/deploy.md` manda mirar para distinguir un apagado limpio de
            # un fallo.
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="OPIc simulator", lifespan=lifespan)
    app.state.root = root
    app.state.idle_watch = watch

    if share_token:
        _install_share_gate(app, share_token)

    creations = _RateLimiter(creates_per_hour, timedelta(hours=1), clock)

    here = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=here / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (here / "templates" / "index.html").read_text(encoding="utf-8")

    @app.get("/healthz")
    def healthz():
        if not worker.alive:
            return JSONResponse(status_code=503, content={"status": "worker down"})
        return {"status": "ok"}

    @app.exception_handler(TransitionError)
    async def transition_error_handler(request, exc: TransitionError):
        # A refresh or a double-submit is an ordinary thing for a browser to do.
        # The state machine's refusal is a client error, not a crash.
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    def session_json(state) -> dict:
        # Junto con `load_or_404`, esto deja "visto por última vez" al día sin
        # un latido que alguien tenga que acordarse de mandar. Hace falta
        # además de aquél porque una sesión recién creada no se carga: se
        # crea.
        if watch is not None:
            watch.note(state.id, state.step)
        payload = store.to_json(state)
        payload["questions_ready"] = state.questions_ready
        # The browser fetches audio through its own route; the host's directory
        # layout is not its business.
        for question in payload["questions"]:
            question["audio_ready"] = question.pop("audio_path") is not None
        return payload

    def load_or_404(session_id: str):
        try:
            state = store.load(root, session_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="session not found") from None
        # Aquí y no sólo en `session_json`: durante la corrección el navegador
        # sólo pide `/progress`, que devuelve un recuento y no el estado. Una
        # sesión que pasa media hora corrigiéndose parecería abandonada, y el
        # apagado automático la contaría como tal.
        if watch is not None:
            watch.note(state.id, state.step)
        return state

    @app.post("/api/sessions", status_code=201)
    def create_session(request: Request) -> dict:
        if not creations.allow(_caller(request)):
            raise HTTPException(
                status_code=429,
                detail={
                    "detail": "too many sessions from this address",
                    "reason": "too_many_sessions",
                },
            )
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

    @app.put("/api/sessions/{session_id}/identity")
    def put_identity(session_id: str, payload: IdentityPayload):
        state = load_or_404(session_id)
        if state.step is not Step.IDENTITY:
            raise HTTPException(
                status_code=409,
                detail=f"expected step identity, session is at {state.step.value}",
            )
        name = payload.name.strip()
        email = payload.email.strip()
        issues = validate_candidate(name, email)
        if issues:
            return JSONResponse(
                status_code=422,
                content={
                    "issues": [
                        {
                            "error": issue.value,
                            "detail": "",
                            "message_ko": describe_candidate_error_ko(issue),
                        }
                        for issue in issues
                    ]
                },
            )
        state = worker.update(
            session_id,
            lambda s: advance(s.with_candidate(Candidate(name, email)), Step.SURVEY),
        )
        return session_json(state)

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

        body = await _read_capped(audio, max_answer_bytes)
        if body is None:
            raise HTTPException(
                status_code=413,
                detail={
                    "detail": f"the answer is larger than {max_answer_bytes} bytes",
                    "reason": "answer_too_large",
                },
            )

        # Write to a unique temporary file first, and only publish it at the
        # final path once the claim below succeeds. Two uploads racing for the
        # same index would otherwise both pass the PENDING check above (it was
        # read outside any lock) and both write the same final path, silently
        # discarding whichever recording lost the write.
        temporary = target.with_name(f"{target.name}.{uuid4().hex}.part")
        temporary.write_bytes(body)

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
    def report_page(session_id: str) -> HTMLResponse:
        """The report as `core/page.py` renders it — the same document the
        candidate can keep, framed by the done screen.

        Two statuses, because there are two pages. `200` is the written one,
        narrative and all. `202` is the same report rendered on the spot
        without it: the worker writes `result.json` first and pays for the
        narrative afterwards, so for about a minute after grading ends this is
        the only page that exists — and a candidate who reads it then would
        otherwise keep the poorer document forever, since nothing asks again.
        The status is what lets the browser wait for the better one instead of
        framing this. It is still a whole page, so a direct visit shows a
        report rather than an error.

        `/report` next to this one is the JSON the older screen was built on
        and stays where it is: it is what the fallback path reads when this
        route has nothing to give.
        """
        load_or_404(session_id)
        final = pages.written(root, session_id)
        if final is not None:
            return HTMLResponse(final)
        provisional = pages.render_now(root, session_id)
        if provisional is None:
            raise HTTPException(status_code=404, detail="not scored yet")
        return HTMLResponse(provisional, status_code=202)

    @app.post("/api/sessions/{session_id}/feedback", status_code=202)
    def post_feedback(session_id: str, payload: FeedbackPayload) -> dict:
        """Guardar la opinión del candidato, y sólo después intentar la hoja.

        El orden es lo importante: `worker.update` deja el feedback en
        `session.json` antes de que Google entre en la historia, así que el
        envío del candidato no espera a la red y no falla por ella.

        Una vez publicada, la fila ya salió hacia la hoja: sobrescribir el
        feedback aquí no la corregiría, sólo añadiría una segunda. Mientras
        sigue pendiente, en cambio, no hay fila que duplicar todavía, así que
        un reenvío se limita a sobrescribir su propia fila pendiente.
        """
        state = load_or_404(session_id)
        if state.feedback is not None and state.feedback.published:
            return JSONResponse(
                status_code=409,
                content={
                    "issues": [
                        {
                            "error": "feedback_already_sent",
                            "detail": "",
                            "message_ko": "이미 의견을 보내주셨습니다. 감사합니다.",
                        }
                    ]
                },
            )
        if payload.rating not in range(1, 6):
            return JSONResponse(
                status_code=422,
                content={
                    "issues": [
                        {
                            "error": "bad_rating",
                            "detail": str(payload.rating),
                            "message_ko": "1점부터 5점 사이로 선택해 주세요.",
                        }
                    ]
                },
            )
        comment = payload.comment.strip()[:MAX_COMMENT]
        worker.update(
            session_id,
            lambda s: s.with_feedback(Feedback(rating=payload.rating, comment=comment)),
        )
        worker.submit(Task("publish", session_id))
        return {"ok": True}

    return app
