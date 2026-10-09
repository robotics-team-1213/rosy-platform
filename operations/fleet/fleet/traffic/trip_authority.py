"""D-517 4 (M2): each period, send every trip robot its movement authority from the block table.

Only with site config ``fleet.traffic.authority: true`` and robot capability ``line_follow_authority``;
other trips keep M1 (junction hold-back only, view ``traffic_authority: hold_back``). After the table:
``until_m`` = its authority end − its front ``d`` (``front_d_m``; CORE counts base odom travel),
``pose_stamp`` = the stamp of the pose ``d`` came from, ``ttl_s`` 2; none to a robot still mid-step.
A leg (trip id, route revision) never gets a smaller end. One send per robot in flight, no retry
before the next period: when sends stop, the robot's own expiry stops it, not Fleet.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from core_common.protocol.line_authority import MAX_TTL_S, MAX_UNTIL_M

_LOG = logging.getLogger(__name__)
CORE, HOLD_BACK = "core", "hold_back"


class AuthoritySender:
    def __init__(self, port, enabled: bool = False, timeout_s: float = 1.5) -> None:
        self._port, self.enabled, self._timeout_s = port, enabled, timeout_s
        self._inflight: dict[str, asyncio.Future] = {}
        #: robot id -> (leg id, end in plan metres before any lap trim) last sent
        self._sent: dict[str, tuple[str, float]] = {}
        self._count, self._failing = 0, set()

    def mode(self, caps) -> str:
        return CORE if self.enabled and getattr(caps, "line_follow_authority", False) is True else HOLD_BACK

    def busy(self) -> set:
        """Robots whose authority send is still in flight."""
        return {robot_id for robot_id, task in self._inflight.items() if not task.done()}

    def body(self, live) -> dict | None:
        """The authority for this period, or None (no end, pose or stamp: nothing goes out)."""
        end, front, stamp = map((live.traffic or {}).get, ("authority_end_m", "front_d_m", "pose_stamp"))
        if end is None or front is None or stamp is None:
            return None
        robot_id, leg = live.view["robot_id"], f"{live.view['trip_id']}:{live.route_rev}"
        absolute = end + live.trim_m  # route metres move with dropped laps; plan metres do not
        last = self._sent.get(robot_id)
        if last is not None and last[0] == leg:
            absolute = max(absolute, last[1])
        self._sent[robot_id] = (leg, absolute)
        self._count += 1
        return {"authority_id": f"{live.view['trip_id']}:{self._count}", "leg_id": leg, "pose_stamp": stamp,
                "until_m": round(min(MAX_UNTIL_M, max(0.0, absolute - live.trim_m - front)), 3),
                "ttl_s": MAX_TTL_S}

    def period(self, lives: Iterable) -> None:
        for live in lives:
            robot_id = live.view["robot_id"]
            task = self._inflight.get(robot_id)
            if not live.open or live.view.get("traffic_authority") != CORE or (task is not None and not task.done()):
                continue
            body = self.body(live)
            if body is not None:
                self._inflight[robot_id] = asyncio.ensure_future(self._send(live, body))

    async def _send(self, live, body: dict) -> None:
        try:
            answer = await asyncio.wait_for(self._port.send_authority(live.view["robot_id"], body), self._timeout_s)
            live.authority = (answer or {}).get("authority")
            self._failing.discard(live.view["robot_id"])
        except Exception as exc:  # noqa: BLE001 — the robot's expiry is the safety; next period sends again
            live.authority = None
            if live.view["robot_id"] not in self._failing:  # once per run of failures
                _LOG.warning("authority to %s not delivered: %r", live.view["robot_id"], exc)
            self._failing.add(live.view["robot_id"])
