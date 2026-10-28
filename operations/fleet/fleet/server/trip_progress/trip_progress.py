"""D-494 5 progress predicates of the trip loop (``trip_runner``): where the robot is on its plan,
whether CORE carried out an instruction, arrival, stall and D-760 4 ``link_wait``. Moved out of ``trip_runner`` unchanged
(2026-10-10 seam, docs/plans/2026-10-07-fleet-site-map-web-server-seam.md); ``TripRunner`` mixes it in.
"""

from __future__ import annotations

import math
from typing import Optional

from rosy.world.state.projections.map_pose import MapPose
from fleet.routing.cost import STOP
from fleet.server.trip_laps import hold_back_m
from fleet.server.trip_live import LiveTrip

#: D-495 1: CORE is executing a junction manoeuvre; a new instruction would abort it. CORE's own
#: ``recovery/junction/gate.py`` ``MANEUVER`` (incl. D-507 4 ``approaching``); test_trip_runner pins both.
MANOEUVRE = ("approaching", "turning", "advancing", "reacquiring", "bending")
CROSSWALK_WAIT_S = 15.0  # CORE crosswalk_report_s 10 + crosswalk_clear_s 5 (D-573 3 defaults)


def inherited_stop(live: LiveTrip) -> bool:
    """SIM r4 (D-763 7): a lane arrival leaves CORE holding that trip's ``stop`` (``executing``). A trip started there
    (a job's next step, an operator's next trip) that has sent nothing yet may replace exactly that stop: the seq and
    place this robot's last arrived trip sent (``TripRunner.held_stops``), at this trip's next place. A halt's stop
    (stall, cancel, E-stop) or anyone else's instruction has another seq and keeps the trip waiting, as before."""
    junction, held = live.junction, getattr(live, "inherited", None)  # set at the trip's start
    return (live.sent is None and held is not None and junction.get("state") == "executing"
            and junction.get("pending_action") == STOP and (junction.get("seq"), junction.get("place_id")) == held
            and held[1] == live.place(live.view["segment_index"]))


class TripProgress:
    @staticmethod
    def _core_busy(live: LiveTrip) -> bool:
        """A new instruction would abort CORE's manoeuvre, or CORE is carrying one out (only our own
        held replan stop, or the stop a trip inherits, may be replaced)."""
        state = live.junction.get("state")
        return state in MANOEUVRE or (state == "executing" and live.junction.get("seq") != live.replaceable
                                      and not inherited_stop(live))

    def _locate(self, live: LiveTrip, pose: MapPose) -> tuple[int, float, Optional[float]]:
        """``(segment index, s on it, off-lane distance or None)``; moves past finished segments."""
        index = live.view["segment_index"]
        while True:
            arc = live.arc(index)
            dist, s, _t = arc.project(pose.x, pose.y)
            if index + 1 >= len(live.segments) or live.view["hold"] is not None:
                break
            nxt, nxt_segment = live.arc(index + 1), live.segments[index + 1]
            nxt_dist, nxt_s, _t = nxt.project(pose.x, pose.y)
            onto_next = nxt_s > nxt_segment["s_from"] + self.config.advance_eps_m and nxt_dist < dist
            remaining = live.segments[index]["s_to"] - s
            if arc.drive_mode == "lane":
                # lap SIM 2 lap_12: CORE closed a straight while D-407 backed the robot 0.26 m short
                # of SE; advancing there judged the pose against ring_e (0.276 m) and stopped a robot
                # 0.07 m off ring_s. A carried-out place moves on only once the robot is on the next lane.
                done = (self._completed(live, index) and remaining <= self.config.pass_window_m
                        and nxt_dist <= nxt.width_m / 2)
            else:
                done = remaining <= self.config.advance_free_m
            if not (done or onto_next):
                break
            index += 1
        near = [dist] + ([live.arc(index + 1).project(pose.x, pose.y)[0]] if index + 1 < len(live.segments) else [])
        return index, s, (dist if min(near) > live.arc(index).width_m / 2 else None)

    def _completed(self, live: LiveTrip, index: int) -> bool:
        """CORE finished our instruction for this place: idle again, or a newer seq."""
        sent, junction = live.sent, live.junction
        if sent is None or sent["index"] != index or sent["action"] in (STOP, "bend"):
            return False
        if sent.get("done"):
            return True
        seq = junction.get("seq")
        newer = isinstance(seq, int) and isinstance(sent["seq"], int) and seq > sent["seq"]
        return bool(sent.get("carried")) and (junction.get("state") == "idle" or newer)

    def _arrived(self, live: LiveTrip, index: int, remaining: float, lane: bool, pose: MapPose) -> bool:
        """Lane arrival needs our accepted stop and the actual pose within its stop destination."""
        if not lane:
            return remaining <= self.config.arrive_free_m
        sent = live.sent
        if sent is None or (sent["index"], sent["action"]) != (index, STOP):
            return False
        segment = live.segments[index]
        stop_s = segment["s_to"] - (hold_back_m(self.traffic, segment) or 0.0)
        x, y, _ = live.arc(index).point_at(stop_s)
        return math.hypot(pose.x - x, pose.y - y) <= self.config.arrive_lane_m

    def _stalled(self, live: LiveTrip, index: Optional[int] = None, s: float = 0.0) -> bool:
        """No ``stall_m`` of progress for ``stall_s``; ``index`` None: the robot could not be located."""
        now = self._clock()
        progress = -math.inf if index is None else live.progress(index, s)
        moved = progress >= live.best_progress + self.config.stall_m
        if moved and (live.view.get("wait") or {}).get("reason") not in (None, "link_wait"):
            live.view.pop("wait")  # D-763 8: only progress ends a regulation episode, not a reason change
        if (live.progress_at is None or moved
                or live.view["hold"] is not None or live.junction.get("state") in MANOEUVRE
                or self._waiting(live, now)
                or (live.traffic or {}).get("waiting_for")  # D-517 4: waiting for a block is no stall
                or (live.authority or {}).get("state") == "HOLDING"):  # nor at the authority's end
            live.best_progress = max(live.best_progress, progress)
            live.progress_at = now
            return False
        return now - live.progress_at >= self.config.stall_s

    def _wait_bound(self, reason: Optional[str]) -> Optional[float]:
        """D-760 4 / D-517 4 / D-763 8: seconds a trip may wait for ``reason`` before the stall rule applies again;
        crosswalk = CORE report_s + clear_s defaults (D-573 3). ponytail: fixed; read CORE status if a site changes them."""
        crosswalk = dict.fromkeys(("crosswalk_look", "crosswalk_wait", "crosswalk_held"), CROSSWALK_WAIT_S)
        return {"link_wait": self.lease.ttl_s, "authority": self.lease.ttl_s, "signal": self.config.stall_s,
                **crosswalk}.get(reason)

    def _waiting(self, live: LiveTrip, now: float) -> bool:
        wait, regulation = live.view.get("wait") or {}, live.junction.get("regulation_wait")
        link = wait.get("reason") == "link_wait"
        if regulation and not link:  # D-763 8: one episode from its first reason; a new one takes its bound from there
            wait = live.view["wait"] = {"since": now, **wait, "reason": regulation}
        bound, active, live.waited = self._wait_bound(wait.get("reason")), bool(regulation or link), True
        over = active and bound is not None and now - wait.get("since", now) >= bound  # only while a wait is reported
        wait.update(bound_s=bound, over_bound=over, waiting=active and bound is not None and not over)  # v1.231: one write
        return wait["waiting"]

    def _fence(self, robot_id: str) -> None:
        """D-760 8 review: the trip's next state read starts after every read begun so far (its last step, a
        junction send, a link loss). The numbers are those of the shared read the junction port reads
        (``read_number``, app.py: MapPoseService); a junction port without them (a test fake) is not fenced."""
        number = getattr(getattr(self, "_junction", None), "read_number", None)
        if number is not None:
            self._read_after[robot_id] = number(robot_id)

    def _after(self, port, robot_id: str) -> dict:
        """``{"after": n}`` for a read on ``port`` that is the junction's numbered read, else nothing: the SIM
        pose port has its own reads, and a read number means nothing to it."""
        number = getattr(getattr(self, "_junction", None), "read_number", None)
        same = number is not None and getattr(port, "read_number", None) == number
        return {"after": self._read_after.get(robot_id, 0)} if same else {}

    async def _link_wait(self, live: LiveTrip, kind: str) -> bool:
        """D-760 4: a robot call or state read failed on a trip that holds its lease. The trip stays open in
        ``link_wait`` (no instruction, goal or extended authority; UNKNOWN in the block table, so its blocks stay
        held) until the link returns (``_link_back``) or the lease is lost. False: no lease, the trip ends as before."""
        if not live.open or (live.view.get("lease") or {}).get("state") != "held":
            return False
        self._fence(live.view["robot_id"])  # D-760 8 review: only a read that starts after the loss brings it back
        live.at, live.at_stamp = None, None
        if (live.view.get("wait") or {}).get("reason") != "link_wait":  # kept until a whole step passes
            live.view["wait"] = {"reason": "link_wait", "since": self._clock(), "lease_at": self.lease.now()}
        live.view["state"], live.view["wait"]["kind"] = "link_wait", kind
        if self._stalled(live):
            await self._stop(live, "stopped", "stall", {"stall_s": self.config.stall_s, "link_wait": kind})
        else:
            self._save(live)
        return True
