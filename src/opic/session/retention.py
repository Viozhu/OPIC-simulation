"""How long a person's exam is allowed to stay on this disk.

Two deadlines, decided in issue #16 and told to the candidate on the screen
that asks for their name and email:

- the recordings go as soon as the session has its report written. They were
  only ever the input to the transcription; everything read afterwards — the
  page, `opic --report`, the sheet row — is built from `result.json` and the
  `answer-NN.json` files, so nothing downstream ever needs the audio again.
- everything else expires thirty days after the exam started: `session.json`
  with the name and the email in it, the transcripts inside `answer-NN.json`,
  the result and the page.

The root and the clock are arguments here and never defaults. This module
deletes other people's exams; a caller that forgets to say *where* and *when*
should get a `TypeError` rather than `data/sessions` and `datetime.now()`.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from opic.session import store

logger = logging.getLogger(__name__)

MAX_AGE = timedelta(days=30)

# What an answer recording can be called: `ALLOWED_AUDIO_SUFFIXES` in
# `web/app.py` — the set the browser is allowed to upload — plus the `.wav`
# the command-line exam records with ffmpeg. Copied rather than imported
# because the web layer imports this module and not the other way round; a
# test asserts the two sets stay in step.
AUDIO_SUFFIXES = frozenset({".webm", ".mp4", ".m4a", ".ogg", ".wav"})

# An exam lasts an hour and grading it takes minutes, so a folder somebody
# wrote to this recently is one that is still in use, whatever its `created_at`
# says. Same reasoning as the abandonment clock in `web/shutdown.py`: the
# question is never "how old is this" on its own, it is "is anybody still in
# it".
LIVE_WITHIN = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class Swept:
    """What one pass actually deleted, for the log and for the operator."""

    purged: tuple[str, ...]
    expired: tuple[str, ...]


def discard_audio(root: Path, session_id: str) -> tuple[Path, ...]:
    """Delete this session's recordings, but only once its report exists.

    `report-ko.html` and not `result.json` is the gate on purpose. The result
    lands first and the page is written after it, from a separate model call
    that can run for a minute — deleting on the result would race the last
    reader of the folder. The page on disk is the first moment at which
    nothing can want the audio again.

    Safe on a session with no page, no audio, or neither: it does nothing and
    says so with an empty tuple.
    """
    if not store.page_path(root, session_id).exists():
        return ()

    removed = []
    for path in sorted(store.session_dir(root, session_id).glob("answer-*")):
        if path.suffix not in AUDIO_SUFFIXES:
            continue
        try:
            path.unlink()
        except OSError:
            # A recording we cannot delete is worth a line in the log and
            # nothing more: the next sweep tries again, and the thirty-day
            # deadline takes the whole folder either way.
            logger.exception("could not delete %s", path)
            continue
        removed.append(path)
    return tuple(removed)


def expired(
    root: Path,
    now: datetime,
    max_age: timedelta = MAX_AGE,
    live_within: timedelta = LIVE_WITHIN,
) -> tuple[str, ...]:
    """The sessions whose deadline has passed and that nobody is still using.

    Age comes from `created_at` inside `session.json`, not from the folder's
    timestamps: writing a report, re-running `--publish` or restoring a backup
    all touch the files without making the exam any younger.

    That leaves the opposite risk — a clock that calls a live session old — so
    a folder written to within `live_within` is kept whatever its age. An
    unfinished exam from a month ago is rubbish; one being graded right now is
    not, and `created_at` alone cannot tell the two apart. `now` and the
    folder's timestamps are therefore read as coming from the same clock.

    A session that will not load is never returned. Deleting what we cannot
    read is how a bug in the parser turns into somebody's lost exam.
    """
    if not root.exists():
        return ()

    old = []
    for directory in sorted(root.iterdir()):
        if not (directory / store.SESSION_FILE).exists():
            continue
        try:
            state = store.load(root, directory.name)
        except (OSError, ValueError, KeyError):
            logger.exception("could not read %s; leaving it alone", directory)
            continue
        if now - state.created_at < max_age:
            continue
        if now - _touched_at(directory) < live_within:
            continue
        old.append((state.created_at, state.id))
    return tuple(session_id for _, session_id in sorted(old))


def sweep(
    root: Path,
    now: datetime,
    max_age: timedelta = MAX_AGE,
    live_within: timedelta = LIVE_WITHIN,
) -> Swept:
    """Apply both deadlines to a whole sessions folder.

    Expiry runs first — there is no point purging the audio of a folder that is
    about to go anyway — and the audio pass behind it is the catch-up for every
    session whose page was written before any of this existed, or whose purge
    never ran because the process died between the two writes.
    """
    gone = []
    for session_id in expired(root, now, max_age, live_within):
        try:
            shutil.rmtree(store.session_dir(root, session_id))
        except OSError:
            logger.exception("could not delete session %s", session_id)
            continue
        gone.append(session_id)

    purged = []
    for directory in sorted(root.iterdir()) if root.exists() else ():
        if not (directory / store.SESSION_FILE).exists():
            continue
        if discard_audio(root, directory.name):
            purged.append(directory.name)

    return Swept(purged=tuple(purged), expired=tuple(gone))


def _touched_at(directory: Path) -> datetime:
    """When anything in this folder was last written."""
    stamps = [directory.stat().st_mtime]
    try:
        stamps.extend(entry.stat().st_mtime for entry in directory.iterdir())
    except OSError:
        pass
    return datetime.fromtimestamp(max(stamps))
