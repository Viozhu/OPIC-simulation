"""Writing the standalone report page for a session on disk.

The page is written after the exam is already graded and safe, so the property
that matters most here is that nothing in this path can take a finished exam
down with it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from opic.core.narrative import AnswerRewrite, Narrative
from opic.core.questions import EXAM_LENGTH
from opic.session import pages, store
from opic.session.state import AnswerRecord, AnswerState, Step, advance
from opic.session.worker import Task, Worker


def a_session(root: Path, survey, level: int = 4):
    state = store.create(root, seed=7, now=datetime(2026, 8, 19, 14, 30, 52))
    state = state.with_survey(survey).with_level(level)
    store.save(root, state)
    return state


def a_graded_session(root: Path, ports, survey, **kwargs) -> str:
    """Run a whole fake exam through the worker and return its id."""
    state = a_session(root, survey)
    worker = Worker(root=root, sleeper=lambda _: None, **ports, **kwargs)
    worker.submit(Task("generate", state.id))
    worker.drain()
    worker.update(
        state.id,
        lambda s: advance(
            advance(advance(advance(advance(s, Step.LEVEL), Step.SETUP), Step.SAMPLE), Step.TEST),
            Step.GRADING,
        ),
    )
    for index in range(EXAM_LENGTH):
        path = store.answer_audio_path(root, state.id, index, ".webm")
        path.write_bytes(b"webm")
        worker.update(
            state.id,
            lambda s, i=index, p=path: s.with_answer(
                AnswerRecord(i, AnswerState.RECORDED, p.name)
            ),
        )
        worker.submit(Task("evaluate", state.id, index))
    worker.drain()
    return state.id


class Narrator:
    def __init__(self, narrative=None, boom: bool = False) -> None:
        self.narrative = narrative
        self.boom = boom
        self.calls = 0

    def write_narrative(self, report):
        self.calls += 1
        if self.boom:
            raise RuntimeError("the model refused")
        return self.narrative


def test_a_finished_exam_writes_its_page(tmp_path, ports, survey):
    session_id = a_graded_session(tmp_path, ports, survey)

    page = store.page_path(tmp_path, session_id)
    assert page.exists()
    text = page.read_text(encoding="utf-8")
    assert text.startswith("<title>OPIc ")
    assert "OPIc 모의고사 결과" in text


def test_the_page_is_written_after_the_result_and_never_instead_of_it(
    tmp_path, ports, survey
):
    """A narrator that explodes costs the prose, not the exam."""
    narrator = Narrator(boom=True)

    session_id = a_graded_session(tmp_path, ports, survey, narrator=narrator)

    assert narrator.calls == 1
    assert store.result_path(tmp_path, session_id).exists()
    assert store.load(tmp_path, session_id).step is Step.DONE
    assert store.page_path(tmp_path, session_id).exists()
    assert "AL 목표 답변" not in store.page_path(tmp_path, session_id).read_text(
        encoding="utf-8"
    )


def test_a_narrative_reaches_the_page(tmp_path, ports, survey):
    narrator = Narrator(
        Narrative(
            analysis=None,
            rewrites=(
                AnswerRewrite(
                    answer_index=0,
                    text_en="A far better answer.",
                    why_ko="이유",
                    invented=False,
                ),
            ),
        )
    )

    session_id = a_graded_session(tmp_path, ports, survey, narrator=narrator)

    text = store.page_path(tmp_path, session_id).read_text(encoding="utf-8")
    assert "A far better answer." in text
    assert "AL 목표 답변" in text


def test_a_session_with_no_result_writes_nothing(tmp_path, ports, survey):
    state = a_session(tmp_path, survey)

    assert pages.write_with_narrator(tmp_path, state.id) is None
    assert not store.page_path(tmp_path, state.id).exists()


def test_writing_twice_replaces_the_page_and_leaves_no_temporary(
    tmp_path, ports, survey
):
    session_id = a_graded_session(tmp_path, ports, survey)
    page = store.page_path(tmp_path, session_id)
    first = page.read_text(encoding="utf-8")

    pages.write_with_narrator(tmp_path, session_id)

    assert page.read_text(encoding="utf-8") == first
    assert list(page.parent.glob("*.tmp")) == []


def test_a_broken_session_does_not_raise(tmp_path, ports, survey):
    """`write_with_narrator` is called from the worker; it may never throw."""
    assert pages.write_with_narrator(tmp_path, "20990101-000000") is None
