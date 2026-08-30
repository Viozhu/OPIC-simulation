from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from opic.core.questions import EXAM_LENGTH
from opic.session import assessments as answers_on_disk
from opic.session import store
from opic.session.state import AnswerRecord, AnswerState, Step, advance
from opic.session.worker import Task, Worker

from doubles import ExplodingQuestionWriter, ExplodingRater


def a_session(root: Path, survey, level: int = 4):
    state = store.create(root, seed=7, now=datetime(2026, 8, 19, 14, 30, 52))
    state = state.with_survey(survey).with_level(level)
    store.save(root, state)
    return state


def a_worker(root: Path, ports, **kwargs) -> Worker:
    return Worker(root=root, sleeper=lambda _: None, **ports, **kwargs)


def recorded(root: Path, worker: Worker, session_id: str, index: int) -> None:
    """Pretend the browser uploaded an answer for this question."""
    path = store.answer_audio_path(root, session_id, index, ".webm")
    path.write_bytes(b"webm")
    worker.update(
        session_id,
        lambda s: s.with_answer(AnswerRecord(index, AnswerState.RECORDED, path.name)),
    )


def test_generating_writes_every_question_and_queues_its_audio(tmp_path, ports, survey):
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)

    worker.submit(Task("generate", state.id))
    worker.drain()

    loaded = store.load(tmp_path, state.id)
    assert len(loaded.questions) == EXAM_LENGTH
    assert loaded.questions[0].text_en == "Question 0."
    assert loaded.questions_ready is True
    assert len(ports["tts"].calls) == EXAM_LENGTH


def test_the_audio_path_points_at_the_tts_cache_not_the_session(tmp_path, ports, survey):
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()

    audio = Path(store.load(tmp_path, state.id).questions[0].audio_path)
    assert audio.exists()
    assert store.session_dir(tmp_path, state.id) not in audio.parents


def test_evaluating_one_answer_writes_its_file_and_marks_it_scored(tmp_path, ports, survey):
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    recorded(tmp_path, worker, state.id, 0)

    worker.submit(Task("evaluate", state.id, 0))
    worker.drain()

    loaded = store.load(tmp_path, state.id)
    assert loaded.answers[0].state is AnswerState.SCORED
    assert (tmp_path / state.id / "answer-00.json").exists()
    assert ports["rater"].calls == [0]


def test_a_replay_is_taken_out_of_the_answering_window(tmp_path, ports, survey):
    """The candidate replayed the question over the first half of the recording.

    The double transcribes one second of audio; half of it was the question
    playing back, so what is measured is the half-second that was theirs.
    """
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    path = store.answer_audio_path(tmp_path, state.id, 0, ".webm")
    path.write_bytes(b"webm")
    worker.update(
        state.id,
        lambda s: s.with_answer(
            AnswerRecord(0, AnswerState.RECORDED, path.name, replay_spans=((0.0, 0.5),))
        ),
    )

    worker.submit(Task("evaluate", state.id, 0))
    worker.drain()

    judged = answers_on_disk.read_answer(tmp_path, state.id, 0)
    assert judged.metrics.duration_s == 0.5
    assert judged.metrics.words_per_minute == 360.0
    # The recording itself is untouched: the word timings are offsets into it.
    assert judged.transcript.duration_s == 1.0


def test_a_rater_that_fails_twice_is_retried_and_succeeds(tmp_path, ports, survey):
    ports["rater"] = ExplodingRater(failures=2)
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    recorded(tmp_path, worker, state.id, 0)

    worker.submit(Task("evaluate", state.id, 0))
    worker.drain()

    assert store.load(tmp_path, state.id).answers[0].state is AnswerState.SCORED
    assert ports["rater"].attempts == 3


def test_a_rater_that_never_works_fails_the_answer_and_says_why(tmp_path, ports, survey):
    ports["rater"] = ExplodingRater(failures=0, always=True)
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    recorded(tmp_path, worker, state.id, 0)

    worker.submit(Task("evaluate", state.id, 0))
    worker.drain()

    answer = store.load(tmp_path, state.id).answers[0]
    assert answer.state is AnswerState.FAILED
    assert "timed out" in answer.error
    assert ports["rater"].attempts == 3


def test_the_last_answer_triggers_aggregation(tmp_path, ports, survey):
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    worker.update(state.id, lambda s: advance(advance(advance(advance(advance(s, Step.LEVEL), Step.SETUP), Step.SAMPLE), Step.TEST), Step.GRADING))

    for index in range(EXAM_LENGTH):
        recorded(tmp_path, worker, state.id, index)
        worker.submit(Task("evaluate", state.id, index))
    worker.drain()

    result = json.loads((tmp_path / state.id / "result.json").read_text(encoding="utf-8"))
    assert result["scored_answers"] == EXAM_LENGTH
    assert result["expected_answers"] == EXAM_LENGTH
    assert store.load(tmp_path, state.id).step is Step.DONE


def test_an_exam_with_one_broken_answer_still_produces_a_level(tmp_path, ports, survey):
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    worker.update(state.id, lambda s: advance(advance(advance(advance(advance(s, Step.LEVEL), Step.SETUP), Step.SAMPLE), Step.TEST), Step.GRADING))

    for index in range(EXAM_LENGTH):
        recorded(tmp_path, worker, state.id, index)
    worker.update(
        state.id,
        lambda s: s.with_answer(AnswerRecord(3, AnswerState.FAILED, "answer-03.webm", "boom")),
    )
    for index in range(EXAM_LENGTH):
        if index != 3:
            worker.submit(Task("evaluate", state.id, index))
    worker.drain()

    result = json.loads((tmp_path / state.id / "result.json").read_text(encoding="utf-8"))
    assert result["scored_answers"] == EXAM_LENGTH - 1
    assert result["expected_answers"] == EXAM_LENGTH


def test_no_answers_at_all_writes_no_result(tmp_path, ports, survey):
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()

    for index in range(EXAM_LENGTH):
        worker.update(
            state.id,
            lambda s, i=index: s.with_answer(AnswerRecord(i, AnswerState.FAILED, None, "boom")),
        )
    worker.submit(Task("aggregate", state.id))
    worker.drain()

    assert not (tmp_path / state.id / "result.json").exists()


def test_resume_requeues_what_a_restart_left_behind(tmp_path, ports, survey):
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    recorded(tmp_path, worker, state.id, 0)
    recorded(tmp_path, worker, state.id, 1)
    worker.submit(Task("evaluate", state.id, 0))
    worker.drain()

    fresh = a_worker(tmp_path, ports)
    fresh.resume()
    fresh.drain()

    loaded = store.load(tmp_path, state.id)
    assert loaded.answers[1].state is AnswerState.SCORED
    assert loaded.answers[0].state is AnswerState.SCORED


def test_resume_finishes_a_session_whose_questions_never_got_audio(tmp_path, ports, survey):
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.run_one(Task("generate", state.id))

    fresh = a_worker(tmp_path, ports)
    fresh.resume()
    fresh.drain()

    assert store.load(tmp_path, state.id).questions_ready is True


# --- fix round 1 (review findings A-E) -------------------------------------


def test_stop_that_times_out_does_not_let_start_spawn_a_second_thread(tmp_path, ports, survey):
    """FINDING A: `stop()` after an in-flight, un-joinable task, then `start()`.

    A real model call can run to the client's own ceiling, so the `join` inside
    `stop()` can legitimately time out with the loop thread still alive. If
    `stop()` cleared `_thread` anyway, a later `start()` would see `_thread is
    None` and spawn a second thread onto the same queue — the exact
    concurrency the single-queue design exists to prevent.
    """
    entered = threading.Event()
    release = threading.Event()

    class BlockingTextToSpeech:
        def __init__(self, cache: Path) -> None:
            self.cache = cache

        def synthesize(self, text: str) -> Path:
            entered.set()
            release.wait(timeout=5)
            path = self.cache / "blocked.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"RIFF")
            return path

    ports["tts"] = BlockingTextToSpeech(tmp_path / "tts_cache")
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports, join_timeout=0.05)

    worker.submit(Task("generate", state.id))
    worker.start()
    try:
        assert entered.wait(timeout=5), "the worker thread never reached synthesize()"
        in_flight_thread = worker._thread

        worker.stop()  # the join times out: synthesize() is still blocked

        worker.start()  # must be a no-op — the loop thread is still running

        alive = [
            t for t in threading.enumerate() if t.name == "opic-worker" and t.is_alive()
        ]
        assert len(alive) == 1
        assert alive[0] is in_flight_thread
    finally:
        release.set()
        worker._thread.join(timeout=5)


def test_resume_queues_aggregate_for_a_settled_session_missing_its_result(
    tmp_path, ports, survey, monkeypatch
):
    """FINDING B (cases 1 and 2): every answer settled, but nothing ever queued
    AGGREGATE — e.g. a restart landed between the last `_evaluate` settling and
    the `AGGREGATE` task it would have queued.
    """
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()

    monkeypatch.setattr(worker, "_maybe_aggregate", lambda session_id: None)
    for index in range(EXAM_LENGTH):
        recorded(tmp_path, worker, state.id, index)
        worker.submit(Task("evaluate", state.id, index))
    worker.drain()

    result_path = tmp_path / state.id / "result.json"
    assert not result_path.exists()
    assert all(
        a.state is AnswerState.SCORED for a in store.load(tmp_path, state.id).answers
    )

    fresh = a_worker(tmp_path, ports)
    fresh.resume()
    fresh.drain()

    assert result_path.exists()


def test_maybe_aggregate_does_not_requeue_once_a_result_exists(tmp_path, ports, survey):
    """FINDING B: the missing-result check, not the step, is what `resume()`
    (via `_maybe_aggregate`) keys on — a session that already has a
    `result.json` must not be re-aggregated.
    """
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    for index in range(EXAM_LENGTH):
        recorded(tmp_path, worker, state.id, index)
        worker.submit(Task("evaluate", state.id, index))
    worker.drain()

    result_path = tmp_path / state.id / "result.json"
    assert result_path.exists()
    before = result_path.read_text(encoding="utf-8")

    worker._maybe_aggregate(state.id)
    worker.drain()

    assert result_path.read_text(encoding="utf-8") == before


def test_evaluate_leaves_the_record_alone_when_the_audio_changed_under_it(
    tmp_path, ports, survey
):
    """FINDING C: `_evaluate` must not clobber a newer recording back to the
    stale one it started judging.
    """
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    recorded(tmp_path, worker, state.id, 0)
    assert store.load(tmp_path, state.id).answers[0].audio_path == "answer-00.webm"

    real_stt = worker._stt

    class SwapAudioMidTranscribe:
        def transcribe(self, audio):
            # A newer recording lands (a different suffix, so its path
            # differs from the one `_evaluate` captured) while this answer is
            # still being judged.
            fresh_path = store.answer_audio_path(tmp_path, state.id, 0, ".wav")
            fresh_path.write_bytes(b"wav-v2")
            worker.update(
                state.id,
                lambda s: s.with_answer(
                    AnswerRecord(0, AnswerState.RECORDED, fresh_path.name)
                ),
            )
            return real_stt.transcribe(audio)

    worker._stt = SwapAudioMidTranscribe()

    worker.submit(Task("evaluate", state.id, 0))
    worker.drain()

    answer = store.load(tmp_path, state.id).answers[0]
    assert answer.state is AnswerState.RECORDED
    assert answer.audio_path == "answer-00.wav"


def test_a_second_generate_does_not_reset_recorded_answers(tmp_path, ports, survey):
    """FINDING D: `with_questions` resets every answer to PENDING, so a second
    `_generate` on a live session must be a no-op once questions already exist.
    """
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    recorded(tmp_path, worker, state.id, 0)
    recorded(tmp_path, worker, state.id, 1)
    recorded(tmp_path, worker, state.id, 2)

    worker.submit(Task("generate", state.id))
    worker.drain()

    answers = store.load(tmp_path, state.id).answers
    assert [a.state for a in answers[:3]] == [AnswerState.RECORDED] * 3


def test_a_recorded_answer_with_no_audio_path_fails_with_a_reason(tmp_path, ports, survey):
    """FINDING E: a RECORDED answer with `audio_path=None` must settle as
    FAILED with a legible reason, not raise and stay RECORDED forever.
    """
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    worker.update(
        state.id,
        lambda s: s.with_answer(AnswerRecord(0, AnswerState.RECORDED, None)),
    )

    worker.submit(Task("evaluate", state.id, 0))
    worker.drain()

    answer = store.load(tmp_path, state.id).answers[0]
    assert answer.state is AnswerState.FAILED
    assert answer.error


# --- fix round 1, task 11 (browser-review findings A-E) --------------------


def test_a_generate_that_fails_twice_is_retried_and_succeeds(tmp_path, ports, survey):
    """FINDING D: `_generate` never retried the writer call at all — one
    throw left `questions_ready` false forever, with nothing left to requeue
    it. It must now go through `self._attempt`, exactly like `_evaluate`
    already does for the rater and the transcriber.
    """
    ports["writer"] = ExplodingQuestionWriter(failures=2)
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)

    worker.submit(Task("generate", state.id))
    worker.drain()

    loaded = store.load(tmp_path, state.id)
    assert loaded.questions_ready is True
    assert ports["writer"].attempts == 3


# --- fix round 2, task 12 (browser-review: TEST -> DONE never happened) ----


def test_aggregation_finishing_while_still_on_test_still_reaches_done(
    tmp_path, ports, survey
):
    """The candidate's real bug: the last EVALUATE can settle and trigger
    aggregation before the browser's own POST has moved the session
    TEST -> GRADING. `_aggregate` used to advance only `if state.step is
    Step.GRADING`, so a session caught at TEST here got stuck there forever —
    `list_unfinished` filters on `result.json` existing, so `resume()` would
    never touch it again either. Aggregation must walk every remaining step
    to DONE, not assume the step is already GRADING.
    """
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    worker.update(
        state.id,
        lambda s: advance(advance(advance(s, Step.LEVEL), Step.SETUP), Step.SAMPLE),
    )
    worker.update(state.id, lambda s: advance(s, Step.TEST))

    for index in range(EXAM_LENGTH):
        recorded(tmp_path, worker, state.id, index)
        worker.submit(Task("evaluate", state.id, index))
    worker.drain()

    result = json.loads((tmp_path / state.id / "result.json").read_text(encoding="utf-8"))
    assert result["scored_answers"] == EXAM_LENGTH
    loaded = store.load(tmp_path, state.id)
    assert loaded.step is Step.DONE


# --- fix round 3 (whole-branch review, FINDING 1) ---------------------------


def test_aggregate_ignores_answer_files_left_by_a_previous_run_in_this_directory(
    tmp_path, ports, survey
):
    """A second exam into the same session directory overwrites `session.json`
    but leaves the previous run's `answer-NN.json` files on disk. `_aggregate`
    has to go by the CURRENT session state (SCORED), not by whichever files
    happen to exist — otherwise a rater that fails every call in THIS run
    would still make the exam report the PREVIOUS run's level.
    """
    from opic.core.metrics import AnswerMetrics
    from opic.core.rubric import ActflLevel, Dimension
    from opic.core.scoring import AnswerAssessment, DimensionScore
    from opic.core.transcript import Span, Transcript, Word
    from opic.session import assessments

    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    state = store.load(tmp_path, state.id)

    def a_previous_runs_assessment(index: int) -> AnswerAssessment:
        return AnswerAssessment(
            question=assessments.question_from_record(state.questions[index]),
            transcript=Transcript(
                text="previous exam's answer",
                words=(Word("previous", 0.0, 0.3, 0.9),),
                speech_spans=(Span(0.0, 0.3),),
                duration_s=1.0,
            ),
            dimension_scores=tuple(
                DimensionScore(dimension=d, level=ActflLevel.IM1, comment_ko="이전 답변입니다.")
                for d in Dimension
            ),
            metrics=AnswerMetrics(
                duration_s=1.0,
                word_count=1,
                words_per_minute=60.0,
                pause_ratio=0.0,
                type_token_ratio=1.0,
                mean_utterance_length=1.0,
                mean_confidence=0.9,
                low_confidence_rate=0.0,
            ),
        )

    # Leftover files from a previous run: every answer already has a judged
    # file on disk...
    for index in range(EXAM_LENGTH):
        assessments.write_answer(tmp_path, state.id, a_previous_runs_assessment(index))

    # ...but THIS run's session state says every one of them FAILED.
    for index in range(EXAM_LENGTH):
        worker.update(
            state.id,
            lambda s, i=index: s.with_answer(
                AnswerRecord(i, AnswerState.FAILED, None, "boom")
            ),
        )

    worker.submit(Task("aggregate", state.id))
    worker.drain()

    assert not (tmp_path / state.id / "result.json").exists()


def test_a_second_aggregate_on_a_session_already_done_does_not_raise(
    tmp_path, ports, survey
):
    """A restart (or a stray duplicate task) can queue AGGREGATE again after
    the session already reached DONE. Walking to DONE must be a no-op there,
    not a `TransitionError` from asking `advance` to leave the last step.
    """
    state = a_session(tmp_path, survey)
    worker = a_worker(tmp_path, ports)
    worker.submit(Task("generate", state.id))
    worker.drain()
    worker.update(
        state.id,
        lambda s: advance(advance(advance(advance(advance(s, Step.LEVEL), Step.SETUP), Step.SAMPLE), Step.TEST), Step.GRADING),
    )
    for index in range(EXAM_LENGTH):
        recorded(tmp_path, worker, state.id, index)
        worker.submit(Task("evaluate", state.id, index))
    worker.drain()
    assert store.load(tmp_path, state.id).step is Step.DONE

    worker.submit(Task("aggregate", state.id))
    worker.drain()  # must not raise

    assert store.load(tmp_path, state.id).step is Step.DONE
