"""Writing the standalone report page for a session on disk.

The one place that knows both halves: `core/page.py` renders, `store.py` says
where, and this reads a graded session back off disk and puts the two together.
Called from the grading worker when an exam finishes and from `opic report` for
any session that already has a `result.json`.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from opic.core.narrative import Narrative
from opic.core.page import Meta, render_html
from opic.core.ports import NarrativeWriter
from opic.core.report import Report, build_report
from opic.session import assessments as answers_on_disk
from opic.session import store
from opic.session.state import SessionState


def build(root: Path, session_id: str) -> tuple[Report, Meta] | None:
    """The report and its masthead facts, read back from a graded session.

    `None` when there is nothing to report on yet — no `result.json`, or every
    answer file unreadable. Tolerant of a single corrupt answer for the same
    reason the web endpoint is: fourteen answers still make a report.
    """
    state = store.load(root, session_id)
    if not store.result_path(root, session_id).exists():
        return None
    judged, broken = answers_on_disk.read_answers_tolerantly(root, session_id, state)
    if not judged:
        return None
    exam = answers_on_disk.aggregate_available(state.questions, judged)
    questions = [answers_on_disk.question_from_record(r) for r in state.questions]
    report = build_report(exam, questions, unreadable=broken)
    return report, _meta(state)


def html_for(root: Path, session_id: str) -> str | None:
    """The report page for a session: the written file, or one rendered now.

    The file on disk is the better answer whenever it is there — it is the one
    the worker rendered with a narrative, and that narrative cost a model call
    that a page view has no business paying again. Rendering on demand covers
    the session graded before this file existed and the one whose narrative
    call failed: the same page, minus the judged sections.

    `None` when there is nothing to render at all — no `result.json`, or not
    one readable answer file. The web layer turns that into a 404.

    Reading never writes. A GET that leaves a file behind is a GET that can
    fail in ways a reader cannot see.
    """
    written = store.page_path(root, session_id)
    if written.exists():
        try:
            return written.read_text(encoding="utf-8")
        except OSError:
            # An unreadable page is not a reason to have no page: everything
            # it was built from is still sitting next to it.
            traceback.print_exc()
    built = build(root, session_id)
    if built is None:
        return None
    report, meta = built
    return render_html(report, meta, None)


def _meta(state: SessionState) -> Meta:
    targets = {record.target for record in state.questions}
    return Meta(
        session_id=state.id,
        seed=state.seed,
        self_assessed_ko=(
            f"{state.self_assess_level}단계"
            if state.self_assess_level is not None
            else None
        ),
        target_level=targets.pop() if len(targets) == 1 else None,
    )


def write(
    root: Path,
    session_id: str,
    report: Report,
    meta: Meta,
    narrative: Narrative | None = None,
) -> Path:
    """Render the page and put it next to `result.json`, atomically.

    Same `.tmp` then `replace` as every other write in this layer: a reader
    that opens the file while it is being rewritten sees the old page or the
    new one, never half of either.
    """
    target = store.page_path(root, session_id)
    temporary = target.with_suffix(".html.tmp")
    temporary.write_text(render_html(report, meta, narrative), encoding="utf-8")
    temporary.replace(target)
    return target


def write_for(
    root: Path, session_id: str, narrative: Narrative | None = None
) -> Path | None:
    """Build and write in one call, or return `None` if there is nothing to write."""
    built = build(root, session_id)
    if built is None:
        return None
    report, meta = built
    return write(root, session_id, report, meta, narrative)


def write_with_narrator(
    root: Path, session_id: str, narrator: NarrativeWriter | None = None
) -> Path | None:
    """Build, ask for a narrative, render, write — and never raise.

    This runs after the exam is graded and `result.json` is safely on disk, so
    everything it can go wrong at costs a page and not a result. An exception
    escaping here would take the worker's aggregate task down with it and make
    a finished exam look unfinished, so the traceback goes to stderr for the
    operator and the candidate keeps their result.

    A narrator that fails is not the same as no narrator: the page is still
    written, with the judged sections absent. That is the whole reason
    `render_html` treats the narrative as optional.
    """
    try:
        built = build(root, session_id)
        if built is None:
            return None
        report, meta = built
        return write(root, session_id, report, meta, _ask(narrator, report))
    except Exception:  # noqa: BLE001 - the result is already safe; never lose it
        traceback.print_exc()
        return None


def _ask(narrator: NarrativeWriter | None, report: Report) -> Narrative | None:
    if narrator is None:
        return None
    try:
        return narrator.write_narrative(report)
    except Exception:  # noqa: BLE001 - a page without prose beats no page
        traceback.print_exc()
        return None
