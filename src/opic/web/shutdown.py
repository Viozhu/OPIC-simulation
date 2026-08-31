"""When a server that has finished its work is allowed to switch itself off.

An exam ends and the machine keeps a uvicorn process, a Whisper model and a
tunnel alive for nobody. This decides when that is over, and it decides it from
what *this process* has seen rather than from what is on disk: a sessions
folder full of abandoned exams from last month must not have a vote, and it
would have one — none of those sessions will ever reach `done`.

The policy is pure and the loop that acts on it is four lines, because the
interesting failure here is not a bug in the timer. It is stopping a server
while somebody is still speaking into it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from opic.session.state import Step

# How often the loop asks. The delay is measured in tens of minutes, so this
# only decides how far past it the exit can land.
CHECK_EVERY_S = 30.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Seen:
    """A session as this process last saw it: which step, and when."""

    step: Step
    at: datetime


def due_to_stop(now: datetime, seen: Mapping[str, Seen], after: timedelta) -> bool:
    """Has every exam this server saw ended, long enough ago to switch off?

    Three conditions, and the last two are what keep this from being a plain
    timer:

    - something must have finished. A server nobody used stays up.
    - `after` must have passed since the *most recent* finish, so a second exam
      taken on the same server restarts the clock.
    - no session may still be live. A candidate at question three does not lose
      the server because somebody else just finished. An abandoned session —
      one nothing has touched for as long as the delay itself — stops counting,
      or a browser tab left open on the first screen would hold the process
      open forever.
    """
    finishes = [s.at for s in seen.values() if s.step is Step.DONE]
    if not finishes:
        return False
    if now - max(finishes) < after:
        return False
    return all(now - s.at >= after for s in seen.values() if s.step is not Step.DONE)


class IdleWatch:
    """What has been seen, and whether that adds up to a shutdown yet."""

    def __init__(
        self,
        after: timedelta,
        clock: Callable[[], datetime] = datetime.now,
        # Cómo averiguar en qué paso está una sesión ahora mismo, o `None` para
        # no mirar más allá de lo que pasó por HTTP. Ver `_catch_up`.
        step_of: Callable[[str], Step | None] | None = None,
        # Si hay trabajo en curso ahora mismo. Ver `due`.
        busy: Callable[[], bool] | None = None,
    ) -> None:
        self._after = after
        self._clock = clock
        self._step_of = step_of
        self._busy = busy
        self._seen: dict[str, Seen] = {}

    def note(self, session_id: str, step: Step) -> None:
        """Record that this session is at this step, right now.

        Called wherever a session's state is handed to the browser, which is
        every route that moves an exam forward — so "last seen" is activity,
        not a heartbeat somebody has to remember to send.
        """
        self._seen[session_id] = Seen(step, self._clock())

    def _catch_up(self) -> None:
        """Pick up the steps nobody asked for over HTTP.

        The last transition of an exam is not a request: the worker finishes
        grading and walks the session to `done` itself. A candidate who closes
        the tab at that moment leaves this watch remembering `grading` forever
        — no finish, so no shutdown, so the server stays up for nobody, which
        is the exact case this whole module exists for. Only a *changed* step
        is noted, so a session sitting still keeps the timestamp it had.
        """
        if self._step_of is None:
            return
        for session_id, seen in list(self._seen.items()):
            # `done` es definitivo: ni cambia ni hace falta volver a leerlo del
            # disco cada treinta segundos.
            if seen.step is Step.DONE:
                continue
            current = self._step_of(session_id)
            if current is not None and current is not seen.step:
                self.note(session_id, current)

    def due(self, now: datetime | None = None) -> bool:
        # Un worker ocupado manda sobre cualquier reloj. Corregir un examen
        # tarda más de lo que dura este plazo, y durante todo ese rato la
        # sesión se queda quieta en `grading` sin que nadie la toque: sin esta
        # comprobación, un examen anterior ya terminado bastaría para apagar el
        # proceso a mitad de la corrección de otro — y el hilo del worker es
        # `daemon`, así que esa corrección se pierde entera.
        if self._busy is not None and self._busy():
            return False
        self._catch_up()
        return due_to_stop(now or self._clock(), self._seen, self._after)


def terminate_this_process() -> None:
    """Ask uvicorn to shut down the way Ctrl-C does.

    SIGTERM and not `sys.exit`: the exit has to happen in uvicorn's signal
    handler so it drains connections and runs the lifespan's shutdown, rather
    than raising inside one background task that nothing is watching.
    """
    os.kill(os.getpid(), signal.SIGTERM)


async def watch_and_stop(
    watch,
    stop: Callable[[], None] = terminate_this_process,
    every: float = CHECK_EVERY_S,
) -> None:
    while True:
        await asyncio.sleep(every)
        try:
            due = watch.due()
        except Exception:  # noqa: BLE001
            # Una sesión ilegible, un disco lleno: esta tarea es la única que
            # puede apagar el servidor, y si muere no vuelve — el proceso se
            # queda en pie para siempre y desde fuera eso es idéntico a "nadie
            # terminó un examen". Se registra y se reintenta al siguiente
            # ciclo. `CancelledError` no hereda de `Exception` y sigue de largo,
            # que es lo que deja cerrar el servidor.
            logger.exception("idle watch check failed")
            continue
        if due:
            stop()
            return
