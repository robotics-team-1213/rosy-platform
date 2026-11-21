"""core_features.docking.bay_reseat — a problem inside the lane is corrected inside the lane, like a robot vacuum docking (user 2026-11-21).

For a dock with a reference scan, a retry that comes from the reverse or the seat (skewed seat, blocked short, stalled reverse, off-centre at the rail
entrance) no longer goes out to staging: it pulls forward STRAIGHT inside the lane on the LiDAR pose, correcting lateral and heading with a steered
forward arc (no in-place turn: the tray corner's circle is wider than the lane), to a point short of the bay line, then re-acquires and reverses in again.
Every tick needs a fresh LiDAR pose and the body footprint inside the lane edge; without a pose it stops, and after bay_lidar_pose_grace_s it fails where it
stands. The tries are bay_reseat_tries; each is logged in status.last_event ("reseat 2/4: ..."). A BayPhases mixin; ROS-free.
"""

from __future__ import annotations

import math
from typing import Optional

from core_features.docking.bay_guards import forward_twist
from core_features.docking.bay_zone import lane_edge, lane_extent
from core_features.docking.model import DockPhase


class BayReseatMixin:
    def _init_reseat(self) -> None:
        self._reseat_active = False
        self._rs_target = 0.0
        self._rs_lost: Optional[float] = None
        self._rs_ext0 = 0.0

    def _over_edge_ok(self, ext_worst: float, ext_nominal: float, x: float, now: float) -> bool:
        """Inside the bay line the footprint guard holds. One narrow allowance: a reseat that STARTED over the edge may go on while the footprint is not worse than at
        its start and stays within bay_reseat_over_edge_m of the edge (the forward arc is what takes the heading out; the tray corner is still ~4 cm from a parked
        neighbour). Anything worse stops it."""
        cfg = self._h._cfg
        edge = lane_edge(cfg, self._h._dock)
        body = self._body_fresh(now)
        # pit-in only, from base x >= 0.18 out (the tray corner must clear the neighbour's tip), the side clear (no rotation block / near return), and the cap holds
        # on the worst case over the pose age while "not worse than at the start" is judged on the measured pose (an age of 0.2 s must not switch it off)
        return (cfg.bay_reseat_over_edge_m > 0.0 and self._reseat_active and self._pitin and x >= cfg.bay_pitin_overedge_min_x_m and body is not None and body[0] != "near"
                and self._rs_ext0 > edge and ext_worst <= edge + cfg.bay_reseat_over_edge_m and ext_nominal <= self._rs_ext0 + 0.002)

    def in_lane_dead_end(self, phase) -> bool:
        """A failure of a reference-scan dock that leaves the robot standing in the lane (a start inside the row, or the acquire/align/seat/reseat phases)."""
        return self._has_reference() and (self._in_row or self._pitin or self._facing_bay or self._zone == "centre"
                                          or phase in (DockPhase.ACQUIRING, DockPhase.ALIGNING, DockPhase.SETTLING, DockPhase.BACKOFF, DockPhase.TURNING))

    def reseat_limit(self, limit: int, phase) -> int:
        """The retry limit: a reference dock retrying from the reverse or the seat has bay_reseat_tries."""
        if self._has_reference() and phase in (DockPhase.SETTLING, DockPhase.ALIGNING):
            return max(limit, self._h._cfg.bay_reseat_tries)
        return limit

    def reseat_begin(self, origin) -> bool:
        """BACKOFF is entered from `origin`: True = it runs as a lane reseat (forward on the LiDAR pose, then ACQUIRING)."""
        h, cfg = self._h, self._h._cfg
        if not (self._has_reference() and origin in (DockPhase.SETTLING, DockPhase.ALIGNING)):
            self._row_pose = None                           # BACKOFF to staging: the track is lost, the next pose is a first acquisition
            return False
        pose = self._row_pose
        if pose is None and self._lp is not None:
            pose = (self._lp[0], self._lp[1], self._lp[2], 0.0)
        x0 = pose[0] if pose is not None else 0.0
        base = x0 + cfg.bay_reseat_out_m + 0.03 * max(0, h._retries - 1)
        cap = cfg.bay_line_x_m - 0.03 - cfg.bay_settle_creep_m
        if self._pitin:
            cap = max(cap, cfg.bay_turn_x_target_m)          # a pit-in dock may go forward to the turn point (the user accepts the turn there), no further
        self._rs_target = max(0.0, min(cap, base))
        if pose is not None and len(pose) > 2 and lane_extent(cfg, pose[1], pose[2]) > lane_edge(cfg, h._dock):
            # it starts over the lane edge (skewed at the mouth): pull forward at least this far so the arc can take the heading out, never past the line unless pit-in
            self._rs_target = max(self._rs_target, min(max(cap, cfg.bay_line_x_m) if self._pitin else cfg.bay_line_x_m, x0 + cfg.bay_reseat_min_arc_m))
        self._rs_ext0 = lane_extent(cfg, pose[1], pose[2]) if pose is not None and len(pose) > 2 else 0.0
        self._reseat_active, self._rs_lost = True, None
        why = (h._last_event or "").split(": ", 1)[-1]
        h._last_event = "reseat %d/%d: %s; at x %.2f out to %.2f" % (h._retries, cfg.bay_reseat_tries, why, x0, self._rs_target)
        return True

    def _tick_reseat(self, now: float) -> None:
        h, cfg = self._h, self._h._cfg
        if not self._backoff:
            h.executor.reset_odometry_mark()
            self._backoff, self._bo_gap0 = True, None
        if now - h._phase_since > cfg.backoff_timeout_s * 2:
            self._stop()
            h._fail("bay reseat: the move out did not finish in time: stopped in the lane")
            return
        rp = self._row_pose
        if rp is None or now - rp[3] > cfg.bay_row_pose_fresh_s:
            self._stop()                                   # stand; the rowpose request keeps asking; fail only after the grace
            self._rs_lost = now if self._rs_lost is None else self._rs_lost
            if now - self._rs_lost > cfg.bay_lidar_pose_grace_s:
                h._fail("bay reseat: no fresh LiDAR pose for %.0f s: stopped in the lane" % cfg.bay_lidar_pose_grace_s)
            return
        self._rs_lost = None
        x, lateral, heading = rp[0], rp[1], rp[2]
        dh = cfg.bay_rail_max_angular * max(0.0, now - rp[3])           # the heading may have changed this much since the pose: take the worse side
        ext = max(lane_extent(cfg, lateral, heading - dh), lane_extent(cfg, lateral, heading + dh))
        edge = lane_edge(cfg, h._dock)
        if x <= cfg.bay_line_x_m and ext > edge and not self._over_edge_ok(ext, lane_extent(cfg, lateral, heading), x, now):
            self._stop()
            h._fail("bay reseat: the body footprint reaches past the lane edge (lateral %.0f mm, heading %.0f deg): stopped in the lane"
                    % (lateral * 1000.0, math.degrees(heading)))
            return
        x += max(0.0, abs(h.executor.travelled_m()) - rp[4]) if len(rp) > 4 and self._backoff else 0.0      # the pose is up to a second old: add the travel since
        if x >= self._rs_target - 0.005:
            self._stop()
            self._reset_line_state()
            h._begin_acquiring()                           # out far enough and straightened: acquire again and reverse in
            return
        if self._backoff_stuck(now, abs(h.executor.travelled_m())):
            return
        block = self._forward_block(now, h._phase_since, 0.0)
        if block is not None:
            self._stop()
            if block != "wait":
                h._fail("bay reseat: " + block)
            return
        self._drive(cfg.bay_backoff_speed, max(-cfg.bay_rail_max_angular, min(cfg.bay_rail_max_angular, forward_twist(cfg, lateral, heading))))

    def _tick_backoff(self, now: float) -> None:
        """재시도: 교차점 쪽으로 전진한 뒤 스테이징부터. A lane reseat (reference dock, from the reverse or the seat) runs _tick_reseat."""
        h, cfg = self._h, self._h._cfg
        if h.executor is None:
            h._fail("bay executor unavailable")
            return
        if self._reseat_active:
            self._tick_reseat(now)
            return
        if not self._backoff:
            h.executor.reset_odometry_mark()
            self._backoff, self._bo_gap0 = True, None
        # A retry from ACQUIRING that began inside the bay row stays put (round 15: backing out to x 0.34 lost the line).
        in_place = getattr(h, "_backoff_from_phase", None) is DockPhase.ACQUIRING and self._in_row
        back_m = 0.0 if in_place or self._facing_bay else cfg.bay_backoff_m       # facing the bay a forward back-off drives AT the bay: it stays still
        if abs(h.executor.travelled_m()) < back_m:
            if self._backoff_stuck(now, abs(h.executor.travelled_m())):
                return
            if now - h._phase_since > cfg.backoff_timeout_s:
                self._stop()
                h._fail("bay backoff blocked")
                return
            block = self._forward_block(now, h._phase_since)
            if block is not None:
                self._stop()
                if block != "wait":
                    h._fail("bay backoff: " + block)
                return
            self._drive(cfg.bay_backoff_speed, 0.0)
            return
        self._stop()
        self._reset_line_state()
        if getattr(h, "_next_phase_after_backoff", None) is DockPhase.ACQUIRING:
            h._begin_acquiring()             # a reseat: the line is in view, no Nav2 round trip
        else:
            h._begin_staging()
