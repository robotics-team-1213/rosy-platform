"""D-573 6 개정 2026-10-10: CORE's ``line_follow.crosswalk`` view, gate on or off (Safety-Review).

null only when the body and its D-407 back-off stand on ground the camera watched without a blind
gap, and no camera crosswalk zone of this odom epoch is within their reach; ``inside``/``ahead``
near one; ``unknown`` when CORE cannot know. The view keeps its own zone list: D-491 (IR rest)
drops a zone once the IR row is past it or after a turn, which is safe for the IR guard but not
for a back-off. Here a zone goes only when the whole back-off reach is past its far edge.
"""
from __future__ import annotations

import math
from typing import Optional

from core_features.line_follow.crosswalk_gate import CrosswalkGate, zone_of
from core_features.line_follow.crosswalk_zone import CORRIDOR_HALF_M, MAX_TURN_RAD, MAX_UNCERTAINTY_M, _angle

#: Distinct crosswalks one epoch may hold; more is ``unknown`` (fail closed, never a silent drop).
MAX_SEEN = 64


class CrosswalkReportMixin:
    """LineFollowManager glue (manager lock throughout)."""

    def _init_crosswalk_report(self) -> None:
        self._xwalk_seen: list = []          # Zones of this epoch, merged per crosswalk
        self._xwalk_run = None               # (epoch, image pose, start m, end m): watched run start
        self._xwalk_last = None              # the same for the latest watched frame
        self._xwalk_unadmittable = False     # the latest frame's crosswalk bound was missing or too large

    def _crosswalk_watch(self, evidence) -> None:
        """Every accepted camera frame. Its "no crosswalk here" covers the seen lane-edge span shrunk at
        both ends by the frame's crosswalk along-track bound: [x_min + u, x_max - u] ahead of its pose."""
        ev, u = self._return_evidence, evidence.crosswalk_uncertainty_m
        self._crosswalk_place(ev.epoch)   # place this frame's zone now, while the pose trail holds its stamp
        if not evidence.boundaries or evidence.uncertainty_m is None or evidence.uncertainty_m > MAX_UNCERTAINTY_M:
            return
        start = min(b.observed_x_min_m for b in evidence.boundaries) + (u or 0.0)
        end = max(b.observed_x_max_m for b in evidence.boundaries) - (u or 0.0)
        self._xwalk_unadmittable = u is None or u > self._config.crosswalk_max_uncertainty_m or start >= end
        pose = ev._image_pose(round(evidence.stamp * 1e9))
        if self._xwalk_unadmittable or pose is None:
            return
        last = self._xwalk_last
        if (last is None or last[0] != ev.epoch or last[1].frame != pose.frame
                or math.hypot(pose.x - last[1].x, pose.y - last[1].y) + start > last[3]):
            self._xwalk_run = (ev.epoch, pose, start, end)   # a gap between the two spans: start over
        self._xwalk_last = (ev.epoch, pose, start, end)

    def _crosswalk_place(self, epoch: int) -> bool:
        """Move new D-491 records into the own list (one Zone per crosswalk). False = one cannot be
        placed yet, or too many crosswalks."""
        ev, frac = self._return_evidence, self._config.crosswalk_range_error_fraction
        self._xwalk_seen = [z for z in self._xwalk_seen if z.key[0] == epoch]
        pending = []
        for record in self._crosswalks.fresh:
            if record["epoch"] != epoch:
                continue
            if record["anchor"] is None:
                record["anchor"] = ev._image_pose(record["stamp_ns"])
            if record["anchor"] is None:
                pending.append(record)
                continue
            new = zone_of(record, frac, self._config.crosswalk_max_uncertainty_m)
            if not any(self._covers(old, new) for old in self._xwalk_seen):
                self._xwalk_seen.append(new)
        self._crosswalks.fresh = pending
        return not pending and len(self._xwalk_seen) <= MAX_SEEN

    @staticmethod
    def _covers(old, new) -> bool:
        """The same crosswalk seen again: both of new's edges inside old's box (with margins)."""
        m = old.margin + new.margin
        for x_body in (new.near, new.far):
            along, across = CrosswalkGate._local(old, new, x_body)
            if not (old.near - m <= along <= old.far + m and abs(across) <= CORRIDOR_HALF_M + old.lateral + m):
                return False
        return True

    def _crosswalk_view(self, now: float) -> Optional[dict]:
        """The armed gate zone; else ``inside`` (a zone within reach of the body or its back-off, any
        heading), ``ahead`` (same road, not reached), ``unknown`` with a reason, or None (outside)."""
        c, ev = self._config, self._return_evidence
        placed = self._crosswalk_place(ev.epoch)   # every call, while the pose trail holds the frames
        zone = self._xwalk.status(now) if c.crosswalk_gate_enabled else None
        if zone is not None:
            return zone
        pose = self._fresh_pose(now)
        if pose is None:
            return dict(state="unknown", reason="pose_stale")
        if self._received_at is None or not 0.0 <= now - self._received_at <= c.stale_after_s:
            return dict(state="unknown", reason="perception_stale")
        run, last = self._xwalk_run, self._xwalk_last
        unwatched = dict(state="unknown",
                         reason="camera_crosswalk_unadmittable" if self._xwalk_unadmittable else "not_watched")
        if not c.body_stop_known or last is None or last[0] != ev.epoch or last[1].frame != pose.frame:
            return unwatched
        back = c.recovery_back_m - c.body_rear_x_m      # body rear + back-off, behind base_footprint
        # ponytail: straight-line distances, no path integral. Since the last watched frame the body may
        # move only by that frame's near span start (blind driving stays unknown); since the run start
        # the back-off rear must be on the covered span.
        if (self._xwalk_unadmittable or math.hypot(pose.x - last[1].x, pose.y - last[1].y) > last[2]
                or math.hypot(pose.x - run[1].x, pose.y - run[1].y) < run[2] + back):
            return unwatched
        if not placed:
            return dict(state="unknown", reason="zone_unplaced")
        reach = math.hypot(max(c.body_front_x_m, back), c.body_half_width_m)
        kept, out = [], None
        for z in self._xwalk_seen:
            m = z.margin + c.crosswalk_odom_error_fraction * math.hypot(pose.x - z.x, pose.y - z.y)
            along, across = CrosswalkGate._local(z, pose, 0.0)
            if along - reach > z.far + m:
                continue                      # the whole back-off reach is past it: gone for good
            kept.append(z)
            half = CORRIDOR_HALF_M + z.lateral + m
            if math.hypot(max(z.near - m - along, 0.0, along - z.far - m), max(abs(across) - half, 0.0)) <= reach:
                out = dict(state="inside")
            elif (out is None and along < z.near and abs(across) <= half
                  and abs(_angle(pose.yaw - z.yaw)) <= MAX_TURN_RAD):
                out = dict(state="ahead")
        self._xwalk_seen = kept
        return out
