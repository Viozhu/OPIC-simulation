"""The rule that lets the server switch itself off after an exam.

The policy is a pure function over what this process has seen, so every case
below is a table row and not a wall-clock wait. The loop that acts on it is
tested separately, with a stub watch, for the one thing it owns: that it calls
`stop` exactly once and then gives up its own task.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opic.session.state import Step
from opic.web.app import create_app
from opic.web.shutdown import IdleWatch, Seen, due_to_stop, watch_and_stop

AFTER = timedelta(minutes=20)
NOW = datetime(2026, 9, 1, 18, 0, 0)


def ago(minutes: float) -> datetime:
    return NOW - timedelta(minutes=minutes)


def test_a_server_that_has_seen_nothing_stays_up():
    assert not due_to_stop(NOW, {}, AFTER)


def test_a_session_still_taking_the_exam_is_not_a_reason_to_stop():
    seen = {"a": Seen(Step.TEST, ago(1))}
    assert not due_to_stop(NOW, seen, AFTER)


def test_a_finished_exam_stays_up_until_the_delay_is_over():
    seen = {"a": Seen(Step.DONE, ago(19))}
    assert not due_to_stop(NOW, seen, AFTER)


def test_a_finished_exam_stops_the_server_once_the_delay_is_over():
    seen = {"a": Seen(Step.DONE, ago(20))}
    assert due_to_stop(NOW, seen, AFTER)


def test_a_second_exam_in_progress_keeps_the_server_up():
    """The reason this is not just a timer: on the shared link, one candidate
    finishing must not pull the server out from under another one."""
    seen = {"a": Seen(Step.DONE, ago(40)), "b": Seen(Step.TEST, ago(2))}
    assert not due_to_stop(NOW, seen, AFTER)


def test_an_abandoned_session_stops_blocking_once_it_is_as_stale_as_the_delay():
    """Somebody who opened the page and walked away would otherwise hold the
    server open forever — nothing ever moves that session to `done`."""
    seen = {"a": Seen(Step.DONE, ago(30)), "b": Seen(Step.IDENTITY, ago(25))}
    assert due_to_stop(NOW, seen, AFTER)


def test_the_delay_runs_from_the_most_recent_finish():
    seen = {"a": Seen(Step.DONE, ago(90)), "b": Seen(Step.DONE, ago(3))}
    assert not due_to_stop(NOW, seen, AFTER)


def test_the_watch_remembers_the_last_step_a_session_was_seen_at():
    clock = iter([ago(50), ago(0)])
    watch = IdleWatch(AFTER, clock=lambda: next(clock))
    watch.note("a", Step.TEST)
    assert not watch.due(NOW)
    watch.note("a", Step.DONE)
    assert not watch.due(NOW)
    assert watch.due(NOW + AFTER)


def test_the_loop_stops_the_process_once_the_watch_says_so():
    class Stub:
        def __init__(self) -> None:
            self.asked = 0

        def due(self) -> bool:
            self.asked += 1
            return self.asked >= 3

    watch, stopped = Stub(), []
    asyncio.run(watch_and_stop(watch, stop=lambda: stopped.append(True), every=0))
    assert stopped == [True]
    assert watch.asked == 3


@pytest.fixture
def client(sessions_root, worker) -> TestClient:
    """The same app the other web tests get, but with the delay set to zero, so
    the wiring test below asserts on wiring and never on a wait."""
    return TestClient(
        create_app(root=sessions_root, worker=worker, shutdown_after=timedelta(0))
    )


def test_the_watch_picks_up_a_finish_that_never_came_through_http():
    """The worker walks a session to `done` on its own. Without this, a
    candidate who closes the tab as the report is written leaves the watch
    remembering `grading`, and the server never switches off."""
    steps = iter([Step.GRADING, Step.DONE])
    watch = IdleWatch(AFTER, clock=lambda: ago(30), step_of=lambda _: next(steps))
    watch.note("a", Step.GRADING)
    assert not watch.due(NOW)  # sigue en grading en disco
    assert watch.due(NOW)  # el worker lo terminó; se ve sin que nadie pregunte


def test_a_session_that_has_not_moved_keeps_the_timestamp_it_had():
    """Re-reading the step must not look like activity, or a finished exam on
    an idle server would push its own deadline back every thirty seconds."""
    watch = IdleWatch(AFTER, clock=lambda: ago(21), step_of=lambda _: Step.DONE)
    watch.note("a", Step.DONE)
    assert watch.due(NOW)


def test_the_app_arms_the_watch_when_a_session_reaches_done(client: TestClient, scored_session):
    """Wiring, not policy: with no delay at all, a graded session is enough."""
    app = client.app
    assert app.state.idle_watch is not None
    assert app.state.idle_watch.due()


def test_a_server_built_without_a_delay_has_no_watch(sessions_root, worker):
    app = create_app(root=sessions_root, worker=worker, shutdown_after=None)
    assert app.state.idle_watch is None


def test_the_launchd_agent_does_not_undo_the_shutdown_it_was_given():
    """The plist is where this feature is easiest to break by accident.

    uvicorn re-raises the signal after shutting down, so a self-shutdown always
    leaves exit code 143 — which launchd reads as a failure and restarts. The
    template has to turn that into a 0, and `KeepAlive` has to be conditional
    rather than `<true/>`, or the server comes straight back up.
    """
    template = (
        Path(__file__).resolve().parents[2]
        / "tools" / "deploy" / "com.opic.server.plist.template"
    ).read_text(encoding="utf-8")
    assert "143" in template, "el plist ya no traduce el 143 de uvicorn"
    assert "SuccessfulExit" in template
    assert "<key>KeepAlive</key>\n  <true/>" not in template


def test_a_busy_worker_outranks_the_clock():
    """Grading one exam takes longer than the delay, and the session sits at
    `grading` untouched the whole time. Without this, an earlier finished exam
    would switch the server off mid-correction — and the worker thread is a
    daemon, so that correction dies with the process."""
    watch = IdleWatch(AFTER, clock=lambda: ago(40), busy=lambda: True)
    watch.note("a", Step.DONE)
    assert not watch.due(NOW)


def test_an_idle_worker_does_not_hold_the_server_open():
    watch = IdleWatch(AFTER, clock=lambda: ago(40), busy=lambda: False)
    watch.note("a", Step.DONE)
    assert watch.due(NOW)


def test_the_loop_survives_a_check_that_raises():
    """This task is the only thing that can switch the server off. If one bad
    read killed it, the process would stay up forever and look exactly like a
    server nobody had used."""

    class Stub:
        def __init__(self) -> None:
            self.asked = 0

        def due(self) -> bool:
            self.asked += 1
            if self.asked == 1:
                raise OSError("session.json is unreadable")
            return self.asked >= 2

    watch, stopped = Stub(), []
    asyncio.run(watch_and_stop(watch, stop=lambda: stopped.append(True), every=0))
    assert stopped == [True]


def test_polling_progress_counts_as_being_alive(client: TestClient, session_id: str):
    """`/progress` is the only request the browser makes while an exam is being
    graded, and it does not return session state — so noting activity had to
    happen on the load, not on the serialisation."""
    watch = client.app.state.idle_watch
    watch._seen.clear()
    client.get(f"/api/sessions/{session_id}/progress")
    assert session_id in watch._seen
