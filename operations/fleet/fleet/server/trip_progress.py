"""D-494 5 progress predicates of the trip loop (``trip_runner``): where the robot is on its plan,
whether CORE carried out an instruction, arrival and stall. Moved out of ``trip_runner`` unchanged
(2026-10-10 seam, docs/plans/2026-10-07-fleet-site-map-web-server-seam.md); ``TripRunner`` mixes it in.
"""

from __future__ import annotations

from typing import Optional

from fleet.localization.map_pose import MapPose
from fleet.routing.cost import STOP
from fleet.server.trip_laps import hold_back_m
from fleet.server.trip_ports import LiveTrip

#: D-495 1: CORE is executing a junction manoeuvre; a new instruction would abort it. CORE's own
#: ``recovery/junction/gate.py`` ``MANEUVER`` (incl. D-507 4 ``approaching``); test_trip_runner pins both.
MANOEUVRE = ("approaching", "turning", "advancing", "reacquiring", "bending")


class TripProgress:
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

    def _arrived(self, live: LiveTrip, index: int, remaining: float, lane: bool) -> bool:
        """Free: within the D-463 ``DONE_M``. Lane: our stop for this place was accepted, and the
        robot is within ``arrive_lane_m``, or CORE holds that stop within ``pass_window_m``."""
        if not lane:
            return remaining <= self.config.arrive_free_m
        sent = live.sent
        if sent is None or (sent["index"], sent["action"]) != (index, STOP):
            return False
        holding = live.junction.get("seq") == sent["seq"] and live.junction.get("state") == "executing"
        remaining -= hold_back_m(self.traffic, live.segments[index]) or 0.0  # D-517 3: it stops short of a zone
        return remaining <= self.config.arrive_lane_m or (holding and remaining <= self.config.pass_window_m)

    def _stalled(self, live: LiveTrip, index: int, s: float) -> bool:
        now = self._clock()
        progress = live.progress(index, s)
        if (live.progress_at is None or progress >= live.best_progress + self.config.stall_m
                or live.view["hold"] is not None or live.junction.get("state") in MANOEUVRE
                or (live.traffic or {}).get("waiting_for")  # D-517 4: waiting for a block is no stall
                or (live.authority or {}).get("state") == "HOLDING"):  # nor at the authority's end
            live.best_progress = max(live.best_progress, progress)
            live.progress_at = now
            return False
        return now - live.progress_at >= self.config.stall_s
