"""The real server: real adapters, one worker, one uvicorn process.

`uv run uvicorn --factory opic.web.serve:app` is the supported way to start it.
Two uvicorn workers would be two queues over one sessions folder — and, on the
local backend, over one model as well — so the process count is not a tuning
knob here.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from opic.adapters import make_llm_client
from opic.adapters.sheets import make_sheet_sink
from opic.adapters.stt import WhisperSpeechToText
from opic.adapters.tts import SayTextToSpeech
from opic.session import retention
from opic.session.worker import Worker
from opic.web.app import create_app

SESSIONS = Path("data/sessions")
TTS_CACHE = Path("data/tts_cache")

LOCK_NAME = ".server.lock"

logger = logging.getLogger(__name__)


class LockedError(RuntimeError):
    """Another server already owns this sessions folder."""


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def claim_the_lock(root: Path, pid: int | None = None, is_running=_is_running) -> None:
    root.mkdir(parents=True, exist_ok=True)
    lock = root / LOCK_NAME
    if lock.exists():
        try:
            held = lock.read_text(encoding="utf-8").strip()
        except OSError:
            # An unreadable lock file is not evidence that a server is
            # running — take it over the same as a stale or garbage one.
            held = ""
        if held.isdigit() and is_running(int(held)):
            raise LockedError(
                f"a server is already running on {root} (pid {held}); "
                "evaluation must not run twice over the same sessions"
            )
    lock.write_text(str(pid or os.getpid()), encoding="utf-8")


def apply_retention(root: Path, now: datetime | None = None) -> retention.Swept:
    """Enforce the issue #16 deadlines, once, as the server comes up.

    Who runs the sweep was the last open question, and startup wins because of
    how this process lives: launchd brings it up when somebody arrives and it
    switches itself off twenty minutes after the last exam ends, so on this
    machine "the server started" is the closest thing to a cron there is, and
    it fires on every day the thing is used at all. A console command only
    deletes on the days somebody remembers to type it, and a deadline that
    depends on a person remembering is not a deadline — `opic --purge-expired`
    exists for the operator, not for the policy. The idle-shutdown loop does
    not repeat it either: thirty days never pass between one start and the
    next, so a second call would only be a second chance to delete something.

    A failure here must not stop the server. A candidate who cannot sit the
    exam because a stale folder would not delete is a worse outcome than a
    folder that lives one boot longer.
    """
    try:
        swept = retention.sweep(root, now or datetime.now())
    except OSError:
        logger.exception("retention sweep failed; leaving %s alone", root)
        return retention.Swept((), ())
    if swept.expired:
        logger.info("retention: deleted %d expired session(s)", len(swept.expired))
    if swept.purged:
        logger.info("retention: discarded the audio of %d session(s)", len(swept.purged))
    return swept


def app(local: bool = False):
    """Build the real app. `local=True` is the CLI's `--serve`, bound to
    `127.0.0.1` and reached only from this machine; everything else — the
    uvicorn factory path, which is what a tunnel or a launchd agent runs — is
    reachable by whoever finds the hostname, so it refuses to start without
    the share gate rather than come up silently public. A `.env.deploy` that
    goes missing or fails to `source` (a renamed file, a launchd restart with
    a stale environment) must not turn into an ungated server that keeps
    answering `/healthz` with `ok`; it has to fail loudly instead.
    """
    token = os.environ.get("OPIC_SHARE_TOKEN", "").strip()
    if not local and not token:
        raise RuntimeError(
            "OPIC_SHARE_TOKEN is not set; refusing to start without the share "
            "gate, since this server would otherwise be publicly readable. "
            "Set OPIC_SHARE_TOKEN in .env.deploy."
        )
    claim_the_lock(SESSIONS)
    # After the lock and before the worker: nothing else is writing to the
    # folder yet, so no sweep can ever race a grading in progress.
    apply_retention(SESSIONS)
    client = make_llm_client()
    worker = Worker(
        root=SESSIONS,
        tts=SayTextToSpeech(cache_dir=TTS_CACHE),
        stt=WhisperSpeechToText(),
        writer=client,
        rater=client,
        # The same client, when it can also write the report's prose. The
        # local backend cannot, and gets the derived page.
        narrator=client if hasattr(client, "write_narrative") else None,
        sheet=make_sheet_sink(),
        # El servidor no puede saber bajo qué nombre lo ven desde fuera; sin
        # esto la fila va a la hoja sin enlace al informe, que es peor pero no
        # es un fallo.
        public_url=os.environ.get("OPIC_PUBLIC_URL", "").strip(),
    )
    worker.resume()
    worker.start()
    # Set when the server is about to be reachable by somebody else, which on
    # this machine means a tunnel. Unset for a local run, and then the gate is
    # not installed at all. See `_install_share_gate` for what it is and is not.
    return create_app(
        root=SESSIONS,
        worker=worker,
        share_token=token or None,
    )
