"""Background-loop death watch for the vision worker.

Fleet owns its own supervision registry; this package stays ROS-free and
Fleet-independent, so the same minimal pattern lives here. A loop that ends
with an exception logs ERROR and turns ``/readyz`` to 503. Loops that finish
or are cancelled cleanly are simply forgotten — per-source status loops come
and go with camera connections, and a clean return is their normal lifecycle.
``/healthz`` keeps meaning bare process liveness (the compose healthcheck).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Optional

_LOG = logging.getLogger(__name__)

RUNNING = "running"
DEAD = "dead"


class LoopWatch:
    """Death-watch registry for this process's background loops.

    A reconnecting source re-uses its ``status:<source>`` name, so every
    supervision carries an identity token and a late callback from a replaced
    task never overwrites the current entry (review 2026-10-28).
    """

    def __init__(self, log: Optional[logging.Logger] = None) -> None:
        self._log = log or _LOG
        self._loops: dict[str, str] = {}
        self._tokens: dict[str, object] = {}

    def supervised(self, name: str, loop: Awaitable) -> asyncio.Task:
        """Run ``loop`` as a task whose *failure* is visible; clean ends are normal."""
        task: asyncio.Task = asyncio.ensure_future(loop)
        token = object()
        self._loops[name] = RUNNING
        self._tokens[name] = token

        def ended(finished: asyncio.Task) -> None:
            if self._tokens.get(name) is not token:
                return  # a newer supervision owns this name now
            if finished.cancelled():
                self._loops.pop(name, None)
                self._tokens.pop(name, None)
                return
            error = finished.exception()
            if error is None:
                # Status loops return when their camera disconnects; config sync
                # returns on its stop event. Neither is a death.
                self._loops.pop(name, None)
                self._tokens.pop(name, None)
                return
            self._loops[name] = DEAD
            self._log.error("vision loop '%s' ended: %s", name, type(error).__name__)

        task.add_done_callback(ended)
        return task

    def dead(self) -> list[str]:
        return [name for name, state in self._loops.items() if state == DEAD]

    def status(self) -> dict[str, str]:
        return dict(self._loops)


def readyz_body(watch: LoopWatch) -> tuple[int, str]:
    """The /readyz response: 503 naming dead loops, otherwise plain ok."""
    dead = watch.dead()
    if dead:
        return 503, json.dumps({"status": "not_ready", "dead": dead}) + "\n"
    return 200, '{"status":"ok"}\n'
