"""D-1051: send a REQUESTED cell repark to the robot's CORE and close it with the measured result.

The request store and its close call belong to `fleet.server.sitemap.pipeline_repark` (cell reach fix);
this module only drives one request: site shift -> robot body shift (by the robot's map yaw), CORE
`POST /api/v1/motion/repark`, poll `GET`, then `close(state, request_id, body)`. CORE owns the motion
and every limit (0.06 m sideways, 0.10 m fore-aft, 0.023 m/s, 0.09 rad/s); Fleet never publishes a twist.
A request it cannot send (no site delta, no pose, CORE refused) is closed FAILED with a reason, never
retried here: the cell task goes to a person.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

_LOG = logging.getLogger(__name__)
OPERATOR = "fleet-repark"
Close = Callable[[str, str, dict], Awaitable[None]]  # (state, request_id, body)


def site_to_body(need_site_dxdy, yaw: float) -> tuple[float, float]:
    """Site (dx, dy) metres -> robot body (forward, left) for a robot facing `yaw` in the site frame."""
    dx, dy = ((need_site_dxdy.get("x"), need_site_dxdy.get("y")) if isinstance(need_site_dxdy, Mapping)
              else tuple(need_site_dxdy))
    c, s = math.cos(yaw), math.sin(yaw)
    return c * dx + s * dy, -s * dx + c * dy


class ReparkExecutor:
    def __init__(self, clients: Callable[[], Mapping[str, Any]], yaw_of: Callable[[str], Awaitable[Optional[float]]],
                 close: Close, *, poll_s: float = 0.5, timeout_s: float = 60.0) -> None:
        self._clients, self._yaw_of, self._close = clients, yaw_of, close
        self._poll_s, self._timeout_s = poll_s, timeout_s
        self._busy: set[str] = set()   # robot ids: one repark per robot

    async def tick(self, requests: Iterable[Mapping[str, Any]]) -> None:
        """Start every REQUESTED request whose robot is not already being re-parked (call at ~1 Hz)."""
        for req in requests:
            if req.get("state") != "REQUESTED" or req.get("robot_id") in self._busy:
                continue
            self._busy.add(req.get("robot_id"))
            asyncio.get_running_loop().create_task(self._run_guarded(dict(req)))

    async def _run_guarded(self, req: dict) -> None:
        try:
            await self._close(*await self.execute(req))
        except Exception:  # noqa: BLE001 - a closing failure must not kill the loop; the request stays REQUESTED
            _LOG.exception("repark %s could not be closed", req.get("request_id"))
        finally:
            self._busy.discard(req.get("robot_id"))

    async def execute(self, req: Mapping[str, Any]) -> tuple[str, str, dict]:
        """(state, request_id, body) for one request. Never raises for a robot-side failure."""
        rid, robot = req["request_id"], req.get("robot_id")
        fail = lambda why, moved=None: ("FAILED", rid, {"state": "FAILED", "reason": why,  # noqa: E731
                                                       **({"moved_robot_dxdy_m": moved} if moved else {})})
        need = req.get("need_site_dxdy_m")
        if need is None:
            return fail("no_site_delta")
        client = self._clients().get(robot)
        if client is None:
            return fail("unknown_robot")
        yaw = await self._yaw_of(robot)
        if yaw is None:
            return fail("no_pose")
        try:
            forward, left = site_to_body(need, yaw)
            await client.repark(round(forward, 4), round(left, 4), OPERATOR)
        except ValueError:
            return fail("bad_site_delta")
        except Exception as exc:  # noqa: BLE001 - CORE refusal (409/400/...) or transport: nothing moved
            return fail(f"core_refused: {getattr(exc, 'code', None) or type(exc).__name__}")
        deadline = asyncio.get_running_loop().time() + self._timeout_s
        status: dict = {}
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(self._poll_s)
            try:
                status = await client.repark_status()
            except Exception:  # noqa: BLE001 - keep polling until the deadline
                continue
            if status.get("state") in ("done", "aborted"):
                break
        else:
            try:
                await client.repark_stop()
            except Exception:  # noqa: BLE001
                _LOG.exception("repark stop for %s failed", robot)
            return fail("timeout", status.get("moved_robot_dxdy_m"))
        moved = status.get("moved_robot_dxdy_m")
        if status["state"] == "done":
            return "DONE", rid, {"state": "DONE", **({"moved_robot_dxdy_m": moved} if moved else {})}
        return fail(f"core_aborted: {status.get('reason')}", moved)
