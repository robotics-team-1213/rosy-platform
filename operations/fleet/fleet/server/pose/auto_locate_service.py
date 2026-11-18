"""D-989: a bounded session in which Fleet locates robots without a person pinning them.

While a session is open the camera keeps sending (the detections config's ``stream_wanted``), each
robot without a confirmed track is asked to blink (D-472, colours and refusals as in IdentityService),
and every tick feeds the fit in ``fleet.localization.auto_locate``. The only command this sends is the
lamp blink, the same one ``/identify`` sends. A robot in ``fleet.map_pose.auto_locate_robots`` also gets
the fit as a map pose anchor (D-989); every other robot stays observation only.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Iterable, Mapping, Optional

from fleet.localization import auto_locate
from fleet.localization.auto_locate import AlignmentTracker, RecoveryWindow
from fleet.server.identity_triggers import caution
from fleet.server.trip_guard import engaged

logger = logging.getLogger("fleet.auto_locate")

SESSION_S = 120.0  # D-691: the phone is awake only this long per request
RETRY_S = 10.0
#: D-989 follow-up: a robot the camera cannot see is not blinked forever.
AUTO_START_RETRY_S = 300.0


class AutoLocateService:
    def __init__(self, tracking, *, map_pose=None, console=None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.tracking = tracking
        self.map_pose = map_pose  # D-989: fed only for robots in fleet.map_pose.auto_locate_robots
        self.console = console    # D-989 follow-up: online/trip facts for auto_start; None keeps it off
        self._anchor_reason: dict[str, Optional[str]] = {}
        self._clock = clock
        self._until: dict[str, float] = {}
        self._auto_start_retry: dict[str, float] = {}
        self._asked_at: dict[str, float] = {}
        self._trackers: dict[str, AlignmentTracker] = {}

    def start(self, robot_ids: Iterable[str]) -> dict:
        """Open or extend a session; a new session forgets a DEGRADED latch."""
        now = self._clock()
        for robot_id in robot_ids:
            if now >= self._until.get(robot_id, -1.0):
                self._trackers[robot_id] = AlignmentTracker(robot_id)
                self._asked_at.pop(robot_id, None)
            self._until[robot_id] = now + SESSION_S
        return self.snapshot()

    def auto_start(self, now: Optional[float] = None) -> list[str]:
        """D-989 follow-up: open a session for every listed robot Fleet cannot yet place on
        the site map — the operator route without the press. The only command stays the
        blink ``start`` already sends; an operator-opened session is left alone."""
        if self.map_pose is None or self.console is None:
            return []
        now = self._clock() if now is None else now
        started: list[str] = []
        for robot_id in sorted(self.map_pose.config.auto_locate_robots):
            if (now < self._auto_start_retry.get(robot_id, 0.0)
                    or now < self._until.get(robot_id, -1.0)
                    or not self.map_pose.knows(robot_id)
                    or not self._auto_start_eligible(robot_id)):
                continue
            self.start([robot_id])
            self._auto_start_retry[robot_id] = now + AUTO_START_RETRY_S
            started.append(robot_id)
        if started:
            logger.info("auto locate: automatic session for %s", started)
        return started

    def _auto_start_eligible(self, robot_id: str) -> bool:
        """Online on the hub, not moving for Fleet (trip/formation), and without a driving pose."""
        record = self.console.hub.registry.find(robot_id)
        if record is None or not record.online:
            return False
        if engaged(self.console, robot_id) is not None or self.console.trip_busy(robot_id):
            return False  # the blink never interrupts a run
        pose = self.map_pose.driving_pose(robot_id)
        return pose is None or pose.state != "LOCALIZED"

    def stream_wanted(self) -> bool:
        # shortcut: any open session wakes every source; narrow per source when a site has a second camera.
        now = self._clock()
        return any(now < until for until in self._until.values())

    def lift_block(self, robot_id: str, principal_id: str) -> bool:
        """A named operator's explicit clear of a disagreement block; audited here."""
        lifted = self.map_pose is not None and self.map_pose.allow_auto_locate(robot_id)
        logger.warning("auto locate block lift: robot_id=%s lifted=%s principal_id=%s", robot_id, lifted, principal_id)
        return lifted

    def _keep_enabled_open(self, now: float) -> None:
        """Robots in auto_locate_robots keep a session open without an operator (user, 2026-11-13).
        A DEGRADED fit is never reopened here: a new session would clear that latch (D-989 3)."""
        if self.map_pose is None:
            return
        for robot_id in self._watched():
            if not self.map_pose.auto_locate_enabled(robot_id) or now < self._until.get(robot_id, -1.0):
                continue
            tracker = self._trackers.get(robot_id)
            if tracker is not None and tracker.view(now)["state"] == "DEGRADED":
                continue
            logger.info("auto locate session opened by config: robot_id=%s", robot_id)
            self.start([robot_id])

    async def tick(self) -> None:
        self._keep_enabled_open(self._clock())
        self._feed_map_pose(self._clock())  # first: the blink below can wait on a robot
        try:
            await self._sessions(self._clock())
        finally:
            self._feed_map_pose(self._clock())

    async def _sessions(self, now: float) -> None:
        identity = self.tracking.identity
        if identity is None:
            return
        open_ids = [rid for rid, until in self._until.items() if now < until]
        tracks = {rid: self._track(identity, rid) for rid in self._watched() | set(open_ids)}
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
            try:
                self._trackers[robot_id].observe(now, track, self.tracking.robot_state(robot_id), peers)
            except Exception:  # one robot's bad input must not hold the others' anchors
                logger.exception("auto locate observe failed: robot_id=%s", robot_id)
                self._trackers[robot_id].fail("OBSERVE_FAILED")
        self._feed_map_pose(now)

    @staticmethod
    def _track(identity, robot_id: str) -> dict:
        try:
            return identity.confirmed_track_pose(robot_id)
        except Exception:
            logger.exception("auto locate track failed: robot_id=%s", robot_id)
            return {"state": "UNKNOWN", "reason": "TRACK_READ_FAILED"}

    def _feed_map_pose(self, now: float) -> None:
        """Each tick, sessions over or not, each robot alone. If this stops, the feed reads DEGRADED in 3 s."""
        if self.map_pose is None:
            return
        for robot_id, tracker in self._trackers.items():
            if not self.map_pose.auto_locate_enabled(robot_id):
                continue
            try:
                sample, reason = tracker.anchor_sample(now, self.tracking.robot_state(robot_id),
                                                       self._revision(tracker.source_id))
                refused = self.map_pose.observe_auto_locate(robot_id, sample, reason)
                if sample is not None and tracker.view(now)["state"] == "ALIGNED":
                    # Keep the camera on while this robot may drive on it: re-confirmation, not session time.
                    self._until[robot_id] = max(self._until.get(robot_id, 0.0), now + SESSION_S)
            except Exception:
                logger.exception("auto locate feed failed: robot_id=%s", robot_id)
                tracker.fail("FEED_FAILED")
                refused = self.map_pose.observe_auto_locate(robot_id, None, "FEED_FAILED")
            if refused != "NOT_NEWER":
                self._anchor_reason[robot_id] = refused

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

    def recovery_window(self, robot_id: str, *, bay_bounds=None) -> Optional[RecoveryWindow]:
        """Bounded Path B SLAM recovery window from confirmed track pose or peer fallback."""
        identity = self.tracking.identity
        if identity is not None:
            track = self._track(identity, robot_id)
            if track.get("state") == "CONFIRMED":
                x, y = auto_locate._finite_float(track.get("x")), auto_locate._finite_float(track.get("y"))
                if x is not None and y is not None:
                    yaw = track.get("yaw_cam") if track.get("yaw_cam") is not None else track.get("yaw")
                    return auto_locate.recovery_window(x, y, yaw_cam=yaw, bay_bounds=bay_bounds)
        peer = self._peer_recovery_pose(robot_id)
        if peer is not None:
            return auto_locate.recovery_window(peer[0], peer[1], yaw_cam=peer[2], bay_bounds=bay_bounds)
        return None

    def _peer_recovery_pose(self, robot_id: str) -> Optional[tuple[float, float, Optional[float]]]:
        best: Optional[tuple[float, float, float, Optional[float]]] = None
        for other_id in sorted(self._watched()):
            if other_id == robot_id:
                continue
            state = self.tracking.robot_state(other_id)
            peers = state.get("peers") if isinstance(state, Mapping) else None
            if not isinstance(peers, list):
                continue
            for row in peers:
                if not isinstance(row, Mapping) or row.get("robot_id") != robot_id:
                    continue
                if row.get("localization_state") != "LOCALIZED":
                    continue
                age_s = auto_locate._finite_float(row.get("age_s", 0.0))
                if age_s is None or age_s < 0.0:
                    continue
                pose = row.get("pose")
                if not isinstance(pose, Mapping):
                    continue
                x, y = auto_locate._finite_float(pose.get("x")), auto_locate._finite_float(pose.get("y"))
                if x is None or y is None:
                    continue
                yaw = auto_locate._finite_float(pose.get("yaw"))
                if best is None or age_s < best[0]:
                    best = (age_s, x, y, yaw)
        return None if best is None else (best[1], best[2], best[3])

    def snapshot(self) -> dict:
        now = self._clock()
        identity = getattr(self.tracking, "identity", None)
        lamp_reasons = ({r.get("robot_id"): (r.get("last") or {}).get("lamp_reason")
                         for r in identity.snapshot().get("robots", [])}
                        if hasattr(identity, "snapshot") else {})
        return {"use": "observation-only",
                "robots": [tracker.view(now) | {"session_left_s": round(max(0.0, self._until[rid] - now), 1),
                                                "lamp_reason": lamp_reasons.get(rid),
                                                "anchor_enabled": (self.map_pose is not None
                                                                   and self.map_pose.auto_locate_enabled(rid)),
                                                "anchor_refused_reason": self._anchor_reason.get(rid),
                                                "anchor_blocked": (self.map_pose is not None
                                                                   and self.map_pose.auto_locate_blocked(rid))}
                           for rid, tracker in sorted(self._trackers.items())]}
