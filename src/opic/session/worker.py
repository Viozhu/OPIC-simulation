"""One queue, one thread, four kinds of task.

Sharing a queue between question generation and answer evaluation is not
laziness: it is what guarantees that two requests never hit Ollama at once. The
rater measurement in `docs/superpowers/notes/2026-08-19-rater-model.md` shows
what concurrent pressure on a local model costs — four timeouts out of five.

Nothing here is kept in memory that is not also on disk, so `resume()` after a
restart needs no state beyond what the session folder already says.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from opic.adapters.sheets import NullSheet
from opic.core.metrics import compute_metrics
from opic.core.ports import (
    NarrativeWriter,
    QuestionWriter,
    Rater,
    SheetSink,
    SpeechToText,
    TextToSpeech,
)
from opic.core.questions import build_blueprint
from opic.core.scoring import AnswerAssessment
from opic.core.transcript import Span
from opic.session import assessments as answers_on_disk
from opic.session import pages
from opic.session import retention
from opic.session import store
from opic.session.publish import sheet_row
from opic.session.state import (
    ORDER,
    AnswerState,
    Feedback,
    QuestionRecord,
    SessionState,
    Step,
    advance,
)

GENERATE = "generate"
SYNTHESIZE = "synthesize"
EVALUATE = "evaluate"
AGGREGATE = "aggregate"
PUBLISH = "publish"


@dataclass(frozen=True, slots=True)
class Task:
    kind: str
    session_id: str
    index: int | None = None


class Worker:
    def __init__(
        self,
        root: Path,
        tts: TextToSpeech,
        stt: SpeechToText,
        writer: QuestionWriter,
        rater: Rater,
        narrator: NarrativeWriter | None = None,
        sheet: SheetSink | None = None,
        public_url: str = "",
        retries: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        join_timeout: float = 5.0,
    ) -> None:
        self._root = root
        self._tts = tts
        self._stt = stt
        self._writer = writer
        self._rater = rater
        self._narrator = narrator
        self._sheet = sheet or NullSheet()
        self._public_url = public_url
        self._retries = retries
        self._sleep = sleeper
        self._join_timeout = join_timeout
        self._queue: queue.Queue[Task | None] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        # Si hay una tarea corriendo *ahora*. La cola vacía no significa nada
        # por sí sola: durante los cinco minutos que tarda una evaluación la
        # cola está vacía y el worker está trabajando. Lo lee el apagado
        # automático, que sin esto puede matar el proceso a mitad de una
        # corrección. Un `bool` basta: lo escribe sólo el hilo del worker.
        self._running = False

    # --- state access -----------------------------------------------------

    def update(
        self, session_id: str, change: Callable[[SessionState], SessionState]
    ) -> SessionState:
        """Read, change and write a session under the lock.

        Both the HTTP thread and the worker thread mutate sessions, and every
        write rewrites the whole file. Serialising them here is what stops one
        from overwriting the other's change.
        """
        with self._lock:
            state = change(store.load(self._root, session_id))
            store.save(self._root, state)
            return state

    # --- queue ------------------------------------------------------------

    def submit(self, task: Task) -> None:
        self._queue.put(task)

    def drain(self) -> None:
        """Run every queued task in this thread, synchronously.

        Used by tests (and by the CLI exam, which drives the worker without a
        background thread); `resume()` only re-`submit`s tasks onto the queue,
        it never calls this itself — whoever starts the worker afterwards
        (`start()` or a test's own `drain()`) is what actually runs them.
        """
        while True:
            try:
                task = self._queue.get_nowait()
            except queue.Empty:
                return
            if task is not None:
                self._running = True
                try:
                    self.run_one(task)
                finally:
                    self._running = False

    @property
    def busy(self) -> bool:
        """Si queda trabajo por hacer o hay algo corriendo.

        Existe para el apagado automático (`opic/web/shutdown.py`): el hilo es
        `daemon`, así que un proceso que sale con una evaluación a medias se la
        lleva por delante y el candidato se queda sin nota.
        """
        return self._running or not self._queue.empty()

    @property
    def alive(self) -> bool:
        """Si el hilo, habiendo arrancado, sigue en pie.

        Un worker que nunca se arrancó cuenta como vivo: la CLI y las pruebas
        conducen la cola con `drain()` y no tienen hilo. Lo que esto detecta es
        el fallo silencioso que sí importa en el servidor — el hilo murió y
        FastAPI sigue contestando, así que el candidato hace el examen entero y
        no se transcribe nada.
        """
        return self._thread is None or self._thread.is_alive()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="opic-worker")
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._queue.put(None)
        self._thread.join(timeout=self._join_timeout)
        if not self._thread.is_alive():
            self._thread = None
        # else: the join timed out — a real model call can run to the client's
        # own ceiling — so the thread is still out there. Leaving `_thread` set
        # is what stops a later `start()` from spawning a second one on the
        # same queue, which is exactly the concurrency this design exists to
        # prevent.

    def _loop(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return
            self._running = True
            try:
                self.run_one(task)
            except Exception:  # noqa: BLE001 - a dead worker is worse than a logged failure
                traceback.print_exc()
            finally:
                self._running = False

    # --- tasks ------------------------------------------------------------

    def run_one(self, task: Task) -> None:
        if task.kind == GENERATE:
            self._generate(task.session_id)
        elif task.kind == SYNTHESIZE:
            self._synthesize(task.session_id, task.index)
        elif task.kind == EVALUATE:
            self._evaluate(task.session_id, task.index)
        elif task.kind == AGGREGATE:
            self._aggregate(task.session_id)
        elif task.kind == PUBLISH:
            self._publish(task.session_id)
        else:
            raise ValueError(f"unknown task kind {task.kind!r}")

    def _generate(self, session_id: str) -> None:
        state = store.load(self._root, session_id)
        if state.questions:
            # Already generated. `with_questions` resets every answer to
            # PENDING, so re-running this on a live session would throw away
            # whatever the candidate has already recorded.
            return
        blueprint = build_blueprint(state.survey, state.self_assess_level, state.seed)
        written = self._attempt(lambda: self._writer.write(state.survey, blueprint))
        records = tuple(
            QuestionRecord(
                index=question.slot.index,
                qtype=question.slot.qtype.value,
                topic_id=question.slot.topic_id,
                combo_id=question.slot.combo_id,
                advanced=question.slot.advanced,
                target=question.slot.target.name,
                text_en=question.text_en,
                audio_path=None,
            )
            for question in written
        )
        self.update(session_id, lambda s: s.with_questions(records))
        for record in records:
            self.submit(Task(SYNTHESIZE, session_id, record.index))

    def _synthesize(self, session_id: str, index: int) -> None:
        state = store.load(self._root, session_id)
        record = state.questions[index]
        if record.audio_path:
            return
        audio = self._attempt(lambda: self._tts.synthesize(record.text_en))
        self.update(session_id, lambda s: s.with_question_audio(index, str(audio)))

    def _evaluate(self, session_id: str, index: int) -> None:
        state = store.load(self._root, session_id)
        record = state.answers[index]
        if record.state in (AnswerState.SCORED, AnswerState.FAILED):
            return

        if record.audio_path is None:
            # A RECORDED answer with no audio path can never be judged; fail it
            # explicitly so it settles instead of sitting RECORDED forever and
            # blocking aggregation.
            self.update(
                session_id,
                lambda s: self._settle(
                    s, index, record.audio_path, AnswerState.FAILED, "no recorded audio"
                ),
            )
            self._maybe_aggregate(session_id)
            return

        try:
            audio = store.session_dir(self._root, session_id) / record.audio_path
            assessment = self._judge(state, index, audio)
        except Exception as error:  # noqa: BLE001 - one bad answer must not end the exam
            reason = f"{type(error).__name__}: {error}"
            self.update(
                session_id,
                lambda s: self._settle(
                    s, index, record.audio_path, AnswerState.FAILED, reason
                ),
            )
        else:
            answers_on_disk.write_answer(self._root, session_id, assessment)
            self.update(
                session_id,
                lambda s: self._settle(
                    s, index, record.audio_path, AnswerState.SCORED, None
                ),
            )

        self._maybe_aggregate(session_id)

    def _settle(
        self,
        s: SessionState,
        index: int,
        expected_audio_path: str | None,
        state: AnswerState,
        error: str | None,
    ) -> SessionState:
        """Write a judged outcome only if the recording hasn't changed under us.

        `record` (and so `expected_audio_path`) was read outside the lock,
        possibly a long model call ago. If a newer recording landed for this
        answer in the meantime, `s.answers[index].audio_path` will no longer
        match — in that case the outcome we are about to write is stale, so we
        leave the current record untouched and let the newer recording get
        evaluated on its own task instead of being clobbered back to SCORED
        with the old audio.
        """
        current = s.answers[index]
        if current.audio_path != expected_audio_path:
            return s
        return s.with_answer(replace(current, state=state, error=error))

    def _maybe_aggregate(self, session_id: str) -> None:
        state = store.load(self._root, session_id)
        if not state.questions:
            return
        settled = all(
            a.state in (AnswerState.SCORED, AnswerState.FAILED) for a in state.answers
        )
        if settled and not store.result_path(self._root, session_id).exists():
            self.submit(Task(AGGREGATE, session_id))

    def _judge(self, state: SessionState, index: int, audio: Path) -> AnswerAssessment:
        question = answers_on_disk.question_from_record(state.questions[index])
        transcript = self._attempt(lambda: self._stt.transcribe(audio))
        replayed = tuple(
            Span(start, end) for start, end in state.answers[index].replay_spans
        )
        metrics = compute_metrics(transcript, replayed)
        scores = self._attempt(lambda: self._rater.rate(question, transcript, metrics))
        return AnswerAssessment(
            question=question,
            transcript=transcript,
            dimension_scores=scores,
            metrics=metrics,
        )

    def _attempt(self, call):
        """Retry a model call, backing off, before giving up on this answer."""
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                return call()
            except Exception as error:  # noqa: BLE001 - retried, then surfaced
                last = error
                self._sleep(2**attempt)
        raise last

    def _aggregate(self, session_id: str) -> None:
        state = store.load(self._root, session_id)
        judged = answers_on_disk.read_all_answers(self._root, session_id, state)
        if not judged:
            return
        result = answers_on_disk.aggregate_available(state.questions, judged)
        payload = answers_on_disk.result_json(result, expected=len(state.questions))
        target = store.result_path(self._root, session_id)
        temporary = target.with_suffix(".json.tmp")

        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(target)
        # A result now exists, so the exam is over regardless of which step
        # the session happened to be sitting in when the last answer
        # settled. That is usually GRADING, but the last EVALUATE can settle
        # (and so trigger this) before the browser's own POST moves the
        # session TEST -> GRADING; advancing only from GRADING left that
        # session stuck at TEST forever, since `advance` permits exactly one
        # step at a time and nothing else ever nudges it again. Walk every
        # remaining step instead of assuming which one it is; a session
        # already at DONE (e.g. a second AGGREGATE task racing a restart)
        # is left untouched rather than raising.
        self.update(session_id, self._advance_to_done)
        # The exam is over and safe on disk. The report page is written after
        # that line and never before it: it is the one step here that calls a
        # language model for something the candidate can already live without,
        # and `write_with_narrator` swallows every failure for that reason.
        pages.write_with_narrator(self._root, session_id, self._narrator)
        # With the page written, the recordings have no reader left, and they
        # are the most personal thing the folder holds. `discard_audio` checks
        # for the page itself, so a `write_with_narrator` that gave up leaves
        # the audio exactly where it is. See `session/retention.py`.
        retention.discard_audio(self._root, session_id)

    def _publish(self, session_id: str) -> None:
        """Mandar la fila del examen a la hoja, una sola vez.

        El feedback ya está en `session.json` cuando esto corre: el endpoint lo
        guarda antes de encolar la tarea. Si la hoja no contesta, `_attempt`
        acaba lanzando, el bucle del worker lo registra, y el feedback se queda
        en disco con `published: False` — que es lo que `--publish` reenvía.
        """
        state = store.load(self._root, session_id)
        if state.feedback is None or state.feedback.published:
            return
        # Capturado antes de la llamada a la hoja, que puede tardar más de un
        # minuto entre reintentos: si un segundo POST llega mientras tanto,
        # sobrescribe el feedback en disco y encola su propia publicación.
        # Marcar `published` sobre lo que haya entonces confundiría la fila
        # que sí se mandó (la primera) con la que quedó pendiente (la
        # segunda). Comparar por valor — `Feedback` es un dataclass congelado
        # — es lo que distingue "sigue siendo lo que mandé" de "ya no lo es".
        sent = state.feedback
        result = None
        path = store.result_path(self._root, session_id)
        if path.exists():
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                result = None
        row = sheet_row(state, result, self._public_url)
        self._attempt(lambda: self._sheet.append(row))
        self.update(session_id, lambda s: self._mark_sent(s, sent))

    def _mark_sent(self, s: SessionState, sent: Feedback) -> SessionState:
        if s.feedback != sent:
            # Otro POST llegó y sobrescribió el feedback mientras la hoja
            # respondía. Lo que hay en disco ahora nunca salió: se deja tal
            # cual, pendiente, para que la tarea de publicación que ese POST
            # ya encoló sea quien lo mande.
            return s
        return s.with_feedback(replace(sent, published=True))

    def _advance_to_done(self, s: SessionState) -> SessionState:
        while s.step is not Step.DONE:
            s = advance(s, ORDER[ORDER.index(s.step) + 1])
        return s

    # --- restart ----------------------------------------------------------

    def resume(self) -> None:
        """Requeue whatever every unfinished session still owes."""
        for session_id in store.list_unfinished(self._root):
            state = store.load(self._root, session_id)
            if state.self_assess_level is None:
                continue
            if not state.questions:
                self.submit(Task(GENERATE, session_id))
                continue
            for question in state.questions:
                if not question.audio_path:
                    self.submit(Task(SYNTHESIZE, session_id, question.index))
            for answer in state.answers:
                if answer.state is AnswerState.RECORDED:
                    self.submit(Task(EVALUATE, session_id, answer.index))
            # A restart can land after the last `_evaluate` settled its answer
            # but before the AGGREGATE it queued ran (or was even queued, if
            # the settling happened by some path other than `_evaluate`). Since
            # aggregation is otherwise only triggered from inside `_evaluate`,
            # a stranded session like that would sit in GRADING forever without
            # this check.
            self._maybe_aggregate(session_id)
