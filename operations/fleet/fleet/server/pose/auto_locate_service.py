"""D-989: a bounded session in which Fleet locates robots without a person pinning them.

While a session is open the camera keeps sending (the detections config's ``stream_wanted``), each
robot without a confirmed track is asked to blink (D-472, colours and refusals as in IdentityService),
and every tick feeds the fit in ``fleet.localization.auto_locate``. The only command this sends is the
lamp blink, the same one ``/identify`` sends. A robot in ``fleet.map_pose.auto_locate_robots`` also gets
the fit as a map pose anchor (D-989); every other robot stays observation only.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable, Mapping, Optional

from fleet.localization.auto_locate import AlignmentTracker
from fleet.server.identity_triggers import caution

SESSION_S = 120.0  # D-691: the phone is awake only this long per request
RETRY_S = 10.0


class AutoLocateService:
    def __init__(self, tracking, *, map_pose=None, clock: Callable[[], float] = time.monotonic) -> None:
        self.tracking = tracking
        self.map_pose = map_pose  # D-989: fed only for robots in fleet.map_pose.auto_locate_robots
        self._anchor_reason: dict[str, Optional[str]] = {}
        self._clock = clock
        self._until: dict[str, float] = {}
        self._asked_at: dict[str, float] = {}
        self._trackers: dict[str, AlignmentTracker] = {}

    def start(self, robot_ids: Iterable[str]) -> dict:
        """Open or extend a session; a new session forgets a DEGRADED latch."""
        now = self._clock()
        for robot_id in robot_ids:
            if now >= self._until.get(robot_id, -1.0):
                self._trackers[robot_id] = AlignmentTracker(robot_id)
                self._asked_at.pop(robot_id, None)
                if self.map_pose is not None:
                    self.map_pose.allow_auto_locate(robot_id)
            self._until[robot_id] = now + SESSION_S
        return self.snapshot()

    def stream_wanted(self) -> bool:
        # shortcut: any open session wakes every source; narrow per source when a site has a second camera.
        now = self._clock()
        return any(now < until for until in self._until.values())

    async def tick(self) -> None:
        now = self._clock()
        identity = self.tracking.identity
        if identity is None:
            return
        open_ids = [rid for rid, until in self._until.items() if now < until]
        tracks = {rid: identity.confirmed_track_pose(rid) for rid in self._watched() | set(open_ids)}
        for robot_id in open_ids:
            track = tracks[robot_id]
            if (track["state"] != "CONFIRMED" and now - self._asked_at.get(robot_id, -RETRY_S) >= RETRY_S
                    and self._may_blink(self.tracking.robot_state(robot_id))):
                self._asked_at[robot_id] = now
                try:
                    await identity.request(robot_id, reason="auto_locate")  # not "operator": no amber, no chirp
                except Exception:  # busy colour, caution or a robot that is down: asked again after RETRY_S
                    pass
            peers = {rid: (other["x"], other["y"]) for rid, other in tracks.items()
                     if rid != robot_id and other["state"] == "CONFIRMED"
                     and other.get("map_id") == track.get("map_id")}
            self._trackers[robot_id].observe(now, track, self.tracking.robot_state(robot_id), peers)
        self._feed_map_pose(now)

    def _feed_map_pose(self, now: float) -> None:
        """Each tick, sessions over or not. If this stops, the anchor ages out at max_anchor_age_s."""
        if self.map_pose is None:
            return
        for robot_id, tracker in self._trackers.items():
            if self.map_pose.auto_locate_enabled(robot_id):
                sample, reason = tracker.anchor_sample(now, self.tracking.robot_state(robot_id),
                                                       self._revision(tracker.source_id))
                self._anchor_reason[robot_id] = self.map_pose.observe_auto_locate(robot_id, sample, reason)

    def _revision(self, source_id: Optional[str]) -> Optional[str]:
        source = next((s for s in self.tracking.sources if s.source_id == source_id), None)
        return None if source is None else self.tracking.approved_revision(source)

    @staticmethod
    def _may_blink(state) -> bool:
        """The automatic-request rule (identity_triggers): a fresh state, E-Stop exactly false, no caution."""
        return (isinstance(state, Mapping) and (state.get("safety") or {}).get("estop") is False
                and not caution(state))

    def _watched(self) -> set[str]:
        return {rid for source in self.tracking.sources for rid in source.robot_ids}

    def snapshot(self) -> dict:
        now = self._clock()
        return {"use": "observation-only",
                "robots": [tracker.view(now) | {"session_left_s": round(max(0.0, self._until[rid] - now), 1),
                                                "anchor_enabled": (self.map_pose is not None
                                                                   and self.map_pose.auto_locate_enabled(rid)),
                                                "anchor_refused_reason": self._anchor_reason.get(rid)}
                           for rid, tracker in sorted(self._trackers.items())]}
