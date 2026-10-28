"""D-517 4 (M2), D-760 3/5: each period, send every trip robot its movement authority from the block table.

Only with site config ``fleet.traffic.authority: true`` and robot capability ``line_follow_authority``;
other trips keep M1 (junction hold-back only, view ``traffic_authority: hold_back``). After the table:
``until_m`` = its authority end − its front ``d`` (``front_d_m``; CORE counts base odom travel),
``pose_stamp`` = the stamp of the pose ``d`` came from. A leg never gets a smaller end unasked. One send per
robot in flight, no retry before the next period: when sends stop, the robot's own expiry stops it.
D-760: every request carries ``seq``, rising per (robot, leg). The leg id is ``{trip_id}:{route_rev}:{FLEET_EPOCH}``:
a new Fleet process never reuses a leg whose highest seq CORE remembers (``stale_seq``). ``ttl_s`` is MAX_TTL_S to a
robot with ``line_follow_authority_shrink``, else LEGACY_TTL_S and never a shrink. A robot mid-step gets nothing and
rolls on its held ttl (Safety-Review MEDIUM-3: Fleet's slowness does not stop it). No extended authority goes to a robot
in ``link_wait``, before its line is on (D-760 2), or for QUARANTINE_S after this process started (D-760 5). Without
one (D-760 Context 5), a robot holding an extend gets ``shrink: true, until_m: 0`` every period until CORE confirms
it (``accepted: true``, or ``shrink_none_held``: nothing held); until then the table keeps that end's metres (``reach``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable

from core_common.protocol.line_authority import LEGACY_TTL_S, MAX_TTL_S, MAX_UNTIL_M
from fleet.traffic.trip_advice import FLEET_EPOCH
from fleet.traffic.route_guide import guide_for_authority, record_trip_guidance

_LOG = logging.getLogger(__name__)
CORE, HOLD_BACK = "core", "hold_back"
#: D-760 5: T after this process starts; every authority an earlier process sent has expired by then.
QUARANTINE_S = MAX_TTL_S


class AuthoritySender:
    record_guidance = staticmethod(record_trip_guidance)

    def __init__(self, port, enabled: bool = False, timeout_s: float = 1.5, clock=time.monotonic) -> None:
        self._port, self.enabled, self._timeout_s, self._clock = port, enabled, timeout_s, clock
        self.quiet_until = clock() + QUARANTINE_S
        self._inflight: dict[str, asyncio.Future] = {}
        #: robot id -> (leg id, end in plan metres before any lap trim) last sent
        self._sent: dict[str, tuple[str, float]] = {}
        self._seq: dict[str, tuple[str, int]] = {}  # robot id -> (leg id, last seq)
        #: robot id -> its last extend {leg, stamp, until_m, sent_at, shrunk: CORE confirmed a shrink since, closed}
        self._held: dict[str, dict] = {}
        self._count, self._failing = 0, set()

    def mode(self, caps) -> str:
        return CORE if self.enabled and getattr(caps, "line_follow_authority", False) is True else HOLD_BACK

    def busy(self) -> set:
        """Robots whose authority send is still in flight."""
        return {robot_id for robot_id, task in self._inflight.items() if not task.done()}

    def reach(self, robot_id: str) -> float:
        """Metres past its pose the robot may still drive on an extend CORE has not confirmed shrunk; after an
        unconfirmed trip end, until that extend has expired at CORE (send + MAX_TTL_S + this client's timeout)."""
        held = self._held.get(robot_id)
        if held is not None and held.get("closed") and self._clock() >= held["sent_at"] + MAX_TTL_S + self._timeout_s:
            self._held.pop(robot_id)
            held = None
        return 0.0 if held is None or held["shrunk"] else held["until_m"]

    def forget(self, robot_id: str, stopped: bool) -> None:
        """Its trip ended: a confirmed stop (line OFF) leaves no authority; else ``reach`` holds until expiry."""
        held = self._held.get(robot_id)
        if held is not None and (stopped or held["shrunk"]):
            self._held.pop(robot_id)
        elif held is not None:
            held["closed"] = True

    def _request(self, live, leg: str, **fields) -> dict:
        robot_id, last = live.view["robot_id"], self._seq.get(live.view["robot_id"])
        seq = last[1] + 1 if last is not None and last[0] == leg else 0
        self._seq[robot_id], self._count = (leg, seq), self._count + 1
        return {"authority_id": f"{live.view['trip_id']}:{self._count}", "leg_id": leg, "seq": seq, **fields}

    def body(self, live) -> dict | None:
        """The authority for this period, or None (no end, pose or stamp: nothing goes out)."""
        end, front, stamp = map((live.traffic or {}).get, ("authority_end_m", "front_d_m", "pose_stamp"))
        if end is None or front is None or stamp is None:
            return None
        robot_id, leg = live.view["robot_id"], f"{live.view['trip_id']}:{live.route_rev}:{FLEET_EPOCH}"
        absolute = end + live.trim_m  # route metres move with dropped laps; plan metres do not
        last = self._sent.get(robot_id)
        if last is not None and last[0] == leg:
            absolute = max(absolute, last[1])
        self._sent[robot_id] = (leg, absolute)
        until = round(min(MAX_UNTIL_M, max(0.0, absolute - live.trim_m - front)), 3)
        self._held[robot_id] = {"leg": leg, "stamp": stamp, "until_m": until, "shrunk": False, "sent_at": self._clock()}
        shrinks = (live.view.get("caps") or {}).get("line_follow_authority_shrink") is True
        guide = guide_for_authority(live, stamp, self._clock())
        return self._request(live, leg, pose_stamp=stamp, until_m=until, ttl_s=MAX_TTL_S if shrinks else LEGACY_TTL_S,
                             **({'route_guide': guide} if guide is not None else {}))

    def shrink(self, live) -> dict | None:
        """D-760 3: stand here, to a shrink-capable robot holding an extend not yet confirmed shrunk; the newest
        stamp Fleet has (a jumped pose's too: a refused shrink drops the held end, so the robot stands anyway)."""
        held = self._held.get(live.view["robot_id"])
        if held is None or held["shrunk"] or (live.view.get("caps") or {}).get("line_follow_authority_shrink") is not True:
            return None
        stamps = ((live.traffic or {}).get("pose_stamp"), getattr(live, "at_stamp", None), held["stamp"])
        return self._request(live, held["leg"], pose_stamp=max(s for s in stamps if s is not None), until_m=0.0,
                             ttl_s=MAX_TTL_S, shrink=True)

    def period(self, lives: Iterable, mid_step=frozenset()) -> None:
        quiet = self._clock() < self.quiet_until
        for live in lives:
            robot_id = live.view["robot_id"]
            task = self._inflight.get(robot_id)
            if (not live.open or live.view.get("traffic_authority") != CORE or (task is not None and not task.done())
                    or robot_id in mid_step):
                continue
            hold = (quiet or live.view.get("state") == "link_wait"
                    or (live.view.get("detail") or {}).get("line_follow_started") is False)
            body = (None if hold else self.body(live)) or self.shrink(live)
            if body is not None:
                self._inflight[robot_id] = asyncio.ensure_future(self._send(live, body))

    async def _send(self, live, body: dict) -> None:
        robot_id = live.view["robot_id"]
        try:
            answer = await asyncio.wait_for(self._port.send_authority(robot_id, body), self._timeout_s) or {}
            live.authority = answer.get("authority")
            # diagnostics: CORE's answers per kind, and whether the extend carried a route prior
            key = ("accepted" if answer.get("accepted") else str(answer.get("reason"))) + (
                "+guide" if "route_guide" in body else "")
            counts = live.view.setdefault("detail", {}).setdefault("authority_answers", {})
            counts[key] = counts.get(key, 0) + 1
            held = self._held.get(robot_id)
            confirmed = answer.get("accepted") is True or answer.get("reason") == "shrink_none_held"  # nothing held
            if body.get("shrink") and confirmed and held is not None and held["leg"] == body["leg_id"]:
                held["shrunk"] = True  # CORE's end is now at most where the robot stood at the stamp
            self._failing.discard(robot_id)
        except Exception as exc:  # noqa: BLE001 — the robot's expiry is the safety; next period sends again
            live.authority = None
            if robot_id not in self._failing:  # once per run of failures
                _LOG.warning("authority to %s not delivered: %r", robot_id, exc)
            self._failing.add(robot_id)
