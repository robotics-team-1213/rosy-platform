"""D-551 6: each period, after the authority, send every trip robot the signal ahead as advice.

Display only (D-525): CORE shows it, nothing moves on it. Only with site config
``fleet.traffic.signal_advice: true`` and robot capability ``line_follow_advice``. The body uses the
same leg id (``{trip_id}:{route_rev}``) and the same ``pose_stamp`` the block table gave the authority
this period; ``stop_m`` is ``signal_ahead``'s ``distance_m`` from that same front. Sent every period
while a signal is ahead (period 0.5 s < ``ttl_s``/2), then one ``signal: null`` once it is gone.
None goes out without a stamp, during a pose-jump hold, or while that robot's authority from an
earlier period is still in flight. One send per robot in flight, its own timeout, no retry; a
failure is logged once per run and never reaches the authority.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Iterable

_LOG = logging.getLogger(__name__)
#: Random per Fleet process; CORE orders advice only within one epoch (``AdviceStore``).
FLEET_EPOCH = uuid.uuid4().hex[:16]
TTL_S = 2.0
LAMPS = ("green", "yellow", "red")  # anything else is not sent as a lamp: ``signal: null``


def signal_advice(ahead: dict | None) -> dict | None:
    """``TrafficService.signal_ahead`` as a ``SignalAdvice``, or None (no signal or an unknown lamp)."""
    if ahead is None or ahead.get("lamp") not in LAMPS:
        return None
    return {"signal_id": ahead["signal_id"], "approach": ahead["approach"], "stop_m": ahead["distance_m"],
            "lamp": ahead["lamp"], "left_s": ahead.get("left_s"), "green_in_s": ahead.get("green_in_s"),
            "exact": ahead.get("exact") is True, "may_enter": ahead.get("may_enter") is True}


class AdviceSender:
    def __init__(self, port, traffic, enabled: bool = False, timeout_s: float = 1.0, clock=time.monotonic) -> None:
        self._port, self._traffic, self.enabled = port, traffic, enabled
        self._timeout_s, self._clock = timeout_s, clock
        self._inflight: dict[str, asyncio.Future] = {}
        self._seq: dict[str, tuple[str, int]] = {}  # robot id -> (leg id, last seq sent)
        self._shown: set[str] = set()  # robots whose last advice carried a signal
        self._outcome: dict[str, dict] = {}  # robot id -> {sent_seq, signal, accepted, reason, at}
        self._count, self._failing, self._broken = 0, set(), False

    def body(self, live) -> dict | None:
        traffic, robot_id = live.traffic or {}, live.view["robot_id"]
        stamp = traffic.get("pose_stamp")
        if stamp is None or "pose_jump" in (traffic.get("waiting_for") or ()):
            return None
        signal = signal_advice(self._traffic.signal_ahead(robot_id))
        if signal is None and robot_id not in self._shown:
            return None
        leg = f"{live.view['trip_id']}:{live.route_rev}"
        last = self._seq.get(robot_id)
        seq = last[1] + 1 if last is not None and last[0] == leg else 0
        self._seq[robot_id] = (leg, seq)
        (self._shown.add if signal else self._shown.discard)(robot_id)
        self._count += 1
        return {"advice_id": f"{FLEET_EPOCH}:{self._count}", "leg_id": leg, "seq": seq, "fleet_epoch": FLEET_EPOCH,
                "pose_stamp": stamp, "ttl_s": TTL_S, "map_version": live.view.get("map_version"),
                "route_rev": live.route_rev, "signal": signal}

    def period(self, lives: Iterable, slow: set = frozenset()) -> None:
        """Never raises: a fault here must not reach the trip loop (logged once per run)."""
        try:
            self._period(lives, slow)
            self._broken = False
        except Exception:  # noqa: BLE001
            if not self._broken:
                _LOG.exception("signal advice period failed (repeats muted until it works)")
            self._broken = True

    def _period(self, lives: Iterable, slow: set) -> None:
        for live in lives:
            robot_id = live.view["robot_id"]
            task = self._inflight.get(robot_id)
            if (not self.enabled or not live.open or robot_id in slow or (task is not None and not task.done())
                    or (live.view.get("caps") or {}).get("line_follow_advice") is not True):
                continue
            body = self.body(live)
            if body is not None:
                self._inflight[robot_id] = asyncio.ensure_future(self._send(robot_id, body))
        now = self._clock()
        for row in (self._traffic.view() or {}).get("robots", ()):
            outcome = self._outcome.get(row["robot_id"])
            if outcome is not None:
                row["advice"] = {**{k: v for k, v in outcome.items() if k != "at"},
                                 "age_s": round(now - outcome["at"], 1)}

    async def _send(self, robot_id: str, body: dict) -> None:
        outcome = {"sent_seq": body["seq"], "signal": body["signal"] is not None}
        try:
            answer = await asyncio.wait_for(self._port.send_advice(robot_id, body), self._timeout_s) or {}
            outcome.update(accepted=answer.get("accepted") is True, reason=answer.get("reason"))
            self._failing.discard(robot_id)
        except Exception as exc:  # noqa: BLE001 — advice is display only; its TTL clears it on the robot
            outcome.update(accepted=False, reason=getattr(exc, "code", None) or type(exc).__name__)
            if robot_id not in self._failing:  # once per run of failures
                _LOG.warning("signal advice to %s not delivered: %r", robot_id, exc)
            self._failing.add(robot_id)
        self._outcome[robot_id] = {**outcome, "at": self._clock()}
