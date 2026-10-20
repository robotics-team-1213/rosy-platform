"""core_api_web.api.command_activity — which REST calls are a D-24 "command".

D-24 amendment (2026-10-04): the inactivity timer that puts a robot to sleep is
reset only by a *command* — a request that asks the robot to do something and
was accepted. Reads (GET), telemetry and WS subscriptions never count, so a
dashboard left open does not keep a robot awake forever.

The table below is the one place that says what a command is. A route that is
not listed does not reset the timer. The hook runs **after** the handler has
answered and only for a 2xx answer: a refused command is not one, and the
power policy is an observer that never sits in front of a command (E-stop,
watchdog and the cmd_vel mux are untouched).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)

#: (method, path regex, source). Source names land in `power.wake` events.
COMMAND_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("POST", r"/api/v1/arm/(actions|stop)", "arm"),
    ("POST", r"/api/v1/teleop", "teleop"),
    ("POST", r"/api/v1/mode", "mode"),
    ("POST", r"/api/v1/navigation/(goal|home|cancel)", "navigation"),
    ("POST", r"/api/v1/localization/initialpose", "navigation"),
    ("POST", r"/api/v1/motion/rotate_to", "navigation"),
    ("POST", r"/api/v1/localization/(mission|decision|suspect)", "mission"),
    ("POST", r"/api/v1/docking/(dock|undock|cancel|station-dock|station-undock|station-stop)", "docking"),
    ("PUT", r"/api/v1/line-follow/mode", "line_follow"),
    ("POST", r"/api/v1/line-follow/(hold|stuck/decision)", "line_follow"),
    ("POST", r"/api/v1/swarm/(follow|cancel)", "fleet_task"),
    ("POST", r"/api/v1/do", "intent"),
    ("POST", r"/api/v1/safety/(stop|release)", "safety"),
)

_COMPILED = tuple((method, re.compile(pattern), source) for method, pattern, source in COMMAND_ROUTES)


def command_source(method: str, path: str) -> Optional[str]:
    """The command source for a request, or None when it is not a command."""
    upper = method.upper()
    for route_method, pattern, source in _COMPILED:
        if upper == route_method and pattern.fullmatch(path.rstrip("/") or "/"):
            return source
    return None


class CommandActivityMiddleware:
    """Pure ASGI middleware: after a 2xx command answer, call `on_command(source)`."""

    def __init__(self, app: Any, power: Callable[[], Any]) -> None:
        self.app = app
        self._power = power

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        source = command_source(scope.get("method", ""), scope.get("path", ""))
        if source is None:
            await self.app(scope, receive, send)
            return

        status = {"code": 0}

        async def capture(message):
            if message.get("type") == "http.response.start":
                status["code"] = int(message.get("status", 0))
            await send(message)

        await self.app(scope, receive, capture)
        if 200 <= status["code"] < 300:
            try:
                power = self._power()
                if power is not None:
                    power.on_command(source)
            except Exception:  # noqa: BLE001 - the answer is already sent; an observer never fails a command
                _log.exception("power on_command hook failed")
