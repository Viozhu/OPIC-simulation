from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from opic.core.questions import EXAM_LENGTH
from opic.session import store
from opic.session.state import AnswerRecord, AnswerState, Step, advance
from opic.session.worker import Task, Worker

from doubles import ExplodingRater


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
