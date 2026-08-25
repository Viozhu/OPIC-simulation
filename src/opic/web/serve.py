"""The real server: real adapters, one worker, one uvicorn process.

`uv run uvicorn --factory opic.web.serve:app` is the supported way to start it.
Two uvicorn workers would be two queues over one sessions folder — and, on the
local backend, over one model as well — so the process count is not a tuning
knob here.
"""

from __future__ import annotations

import os
from pathlib import Path

from opic.adapters import make_llm_client
from opic.adapters.stt import WhisperSpeechToText
from opic.adapters.tts import SayTextToSpeech
from opic.session.worker import Worker
from opic.web.app import create_app

SESSIONS = Path("data/sessions")
TTS_CACHE = Path("data/tts_cache")

LOCK_NAME = ".server.lock"


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


def app():
    claim_the_lock(SESSIONS)
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
    )
    worker.resume()
    worker.start()
    # Set when the server is about to be reachable by somebody else, which on
    # this machine means a tunnel. Unset for a local run, and then the gate is
    # not installed at all. See `_install_share_gate` for what it is and is not.
    return create_app(
        root=SESSIONS,
        worker=worker,
        share_token=os.environ.get("OPIC_SHARE_TOKEN", "").strip() or None,
    )
