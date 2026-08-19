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
from dataclasses import dataclass
from pathlib import Path

from opic.core.metrics import compute_metrics
from opic.core.questions import build_blueprint
from opic.core.scoring import AnswerAssessment
from opic.session import assessments as answers_on_disk
from opic.session import store
from opic.session.state import (
    AnswerRecord,
    AnswerState,
    QuestionRecord,
    SessionState,
    Step,
    advance,
)

GENERATE = "generate"
SYNTHESIZE = "synthesize"
EVALUATE = "evaluate"
AGGREGATE = "aggregate"


@dataclass(frozen=True, slots=True)
class Task:
    kind: str
    session_id: str
    index: int | None = None


class Worker:
    def __init__(
        self,
        root: Path,
        tts,
        stt,
        writer,
        rater,
        retries: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._root = root
        self._tts = tts
        self._stt = stt
        self._writer = writer
        self._rater = rater
        self._retries = retries
        self._sleep = sleeper
        self._queue: queue.Queue[Task | None] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

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
        """Run every queued task in this thread. Used by tests and by `resume`."""
        while True:
            try:
                task = self._queue.get_nowait()
            except queue.Empty:
                return
            if task is not None:
                self.run_one(task)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="opic-worker")
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._queue.put(None)
        self._thread.join(timeout=5)
        self._thread = None

    def _loop(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return
            try:
                self.run_one(task)
            except Exception:  # noqa: BLE001 - a dead worker is worse than a logged failure
                traceback.print_exc()

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
        else:
            raise ValueError(f"unknown task kind {task.kind!r}")

    def _generate(self, session_id: str) -> None:
        state = store.load(self._root, session_id)
        blueprint = build_blueprint(state.survey, state.self_assess_level, state.seed)
        written = self._writer.write(state.survey, blueprint)
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
        audio = self._tts.synthesize(record.text_en)
        self.update(session_id, lambda s: s.with_question_audio(index, str(audio)))

    def _evaluate(self, session_id: str, index: int) -> None:
        state = store.load(self._root, session_id)
        record = state.answers[index]
        if record.state in (AnswerState.SCORED, AnswerState.FAILED):
            return
        audio = store.session_dir(self._root, session_id) / record.audio_path

        try:
            assessment = self._judge(state, index, audio)
        except Exception as error:  # noqa: BLE001 - one bad answer must not end the exam
            reason = f"{type(error).__name__}: {error}"
            self.update(
                session_id,
                lambda s: s.with_answer(
                    AnswerRecord(index, AnswerState.FAILED, record.audio_path, reason)
                ),
            )
        else:
            answers_on_disk.write_answer(self._root, session_id, assessment)
            self.update(
                session_id,
                lambda s: s.with_answer(
                    AnswerRecord(index, AnswerState.SCORED, record.audio_path)
                ),
            )

        after = store.load(self._root, session_id)
        settled = sum(
            1
            for a in after.answers
            if a.state in (AnswerState.SCORED, AnswerState.FAILED)
        )
        if settled == len(after.questions):
            self.submit(Task(AGGREGATE, session_id))

    def _judge(self, state: SessionState, index: int, audio: Path) -> AnswerAssessment:
        question = answers_on_disk.question_from_record(state.questions[index])
        transcript = self._attempt(lambda: self._stt.transcribe(audio))
        metrics = compute_metrics(transcript)
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
        judged = answers_on_disk.read_all_answers(self._root, session_id, state.questions)
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
        if state.step is Step.GRADING:
            self.update(session_id, lambda s: advance(s, Step.DONE))

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
