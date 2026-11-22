"""Step 3 of the stop-place alignment (docs 2026-11-19 station-align decision): a lane trip that reached a place
with a yaw (site map place.yaw) is not ARRIVED until its heading, read from a FRESH ceiling-marker sighting, is within
ALIGN_TOL_DEG; else CORE turns it in place (the start's ``_align``, tol TURN_TOL_DEG), at most MAX_TURNS times.
A refusal ends the trip through the trip's one surface (``_stop`` reason + detail): STATION_ALIGN_FAILED / _BLOCKED."""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

from fleet.routing.cost import wrap
from fleet.server.trip_ports import TripError

ALIGN_TOL_DEG = 3.0
TURN_TOL_DEG = 2.0
MAX_TURNS = 3
SIGHTING_WAIT_S = 3.0
ARM_FRESH_S = 60.0


def station_align_gate(state, zones: Optional[dict] = None, clock: Callable[[], float] = time.time):
    """``gate(place_id) -> None | reason``: a place of a cell turns only while that cell's arm is folded (fresh state)
    and neither the arm nor the cell is held. Places outside every cell have no arm to wait for."""
    if zones is None:
        from fleet.pipeline.station_zones import load_station_zones
        zones = load_station_zones()["zones_by_id"]
    by_place = {z.get("place_id"): z for z in zones.values()}

    def gate(place_id: str) -> Optional[str]:
        zone = by_place.get(place_id)
        if not zone:
            return None
        arm = zone.get("arm_id")
        if (getattr(state, "omx_cell_states", {}).get(zone.get("cell_id")) or {}).get("phase") == "HUMAN_HOLD":
            return "human_hold"
        if (getattr(state, "arm_holds", {}).get(arm) or {}).get("held"):
            return "arm_held"
        live = getattr(state, "arm_live_states", {}).get(arm) or {}
        if live.get("folded") is not True or clock() - float(live.get("updated_at") or 0.0) > ARM_FRESH_S:
            return "arm_not_folded"
        return None
    return gate


class StationAlign:
    """Mixed into ``TripRunner``; ``TripRunner(align_gate=...)`` is the safety gate (default: none)."""

    def _station_yaw(self, live) -> Optional[float]:
        goal = live.request.get("to")  # the stored plan request: {"to": place id | [x, y, yaw], "via": [...], ...}
        place = live.graph.places.get(goal) if isinstance(goal, str) else None
        arrive = live.request.get("arrive_yaw")
        return arrive if arrive is not None else getattr(place, "yaw", None)

    def _sighted(self, pose) -> bool:
        """A map-marker sighting, not odom (source ``bridged``): only that may judge the heading."""
        age = getattr(pose, "anchor_age_s", None)
        return getattr(pose, "source", None) == "sighting" and age is not None and age <= SIGHTING_WAIT_S

    async def _station_refuse(self, live, code: str, **detail) -> bool:
        await self._stop(live, "failed", code, detail)
        return False

    async def _arrival_aligned(self, live, pose) -> bool:
        """True: the trip may report ARRIVED. False: not yet (waiting) or ended (``live.open`` False)."""
        want = self._station_yaw(live)
        if want is None or live.view["detail"].get("named_stop_operation"):
            return True  # a named Nav2 stop was judged on its approved map pose (D-1051), not a marker sighting
        now = self._clock()
        if not self._sighted(pose):  # no fresh marker sighting: wait, never judge from odom
            since = live.__dict__.setdefault("align_wait_at", now)
            if now - since >= SIGHTING_WAIT_S:
                return await self._station_refuse(live, "STATION_ALIGN_FAILED", reason="no_fresh_sighting")
            return False
        live.align_wait_at = None
        err = math.degrees(wrap(pose.yaw - want))
        place, robot_id = live.request.get("to"), live.view["robot_id"]
        for turns in range(MAX_TURNS + 1):
            if abs(err) <= ALIGN_TOL_DEG:
                return True
            if turns == MAX_TURNS:
                return await self._station_refuse(live, "STATION_ALIGN_FAILED", heading_err_deg=round(err, 1), turns=turns)
            blocked = self._align_gate(place) if isinstance(place, str) else None
            if blocked:
                return await self._station_refuse(live, "STATION_ALIGN_BLOCKED", reason=blocked, heading_err_deg=round(err, 1))
            try:
                done = await self._align(robot_id, round(-err, 1), live.view.get("started_by") or "fleet",
                                         tol_deg=TURN_TOL_DEG, keep_pose=True)
            except TripError as exc:
                return await self._station_refuse(live, "STATION_ALIGN_FAILED", cause=exc.code, turns=turns, **exc.detail)
            err = math.degrees(wrap(done["pose"].yaw - want))
        return False
