"""D-507 6: one motion admission for D-468 return/retrace, D-476 bridge and D-495 junction motion.

(a) enforce: the D-400 worker proof (bind_return_motion), unchanged; the only basis while live.
(b) site: the D-507 9 floor declaration, a fresh calibrated IR verdict this kind may run on, path
mode with the URDF body, a fresh scan and the D-422 sweep of the very twist above its restart gap.
(c) Reverse on (b) only for the D-468 retrace (limits stay in lane_return.py): no IR sees the rear
floor, the declaration covers it and the rear sweep is the space evidence. Under the manager lock.
"""
from core_features.line_follow.clearance import body_path_gap

#: IR guard verdicts (manager._ir_guard) each kind may move on; 'stale' never. Bridge: D-476
#: rev 1; approach/turn/advance: D-498 (not on the line); return/retrace: D-468 starts on it.
_OFF_LINE, _ANY = frozenset({'clear', 'left', 'right'}), frozenset({'clear', 'left', 'right', 'centre'})
IR_ALLOWED = {'bridge': frozenset({'clear'}), 'approach': _OFF_LINE, 'turn': _OFF_LINE,
              'advance': _OFF_LINE, 'return': _ANY, 'retrace': _ANY}


class MotionAdmitMixin:
    def _enforce_basis(self):
        """The D-400 proof is bound and its floor proof live (unreadable: live, fail closed),
        unless it says it cannot admit at all; then the site basis may hold."""
        if self._return_motion is None:
            return False
        try:
            live = self._floor_proof_live is None or self._floor_proof_live() is not False
        except Exception:  # noqa: BLE001 - unreadable liveness: the proof is required
            live = True
        try:
            return live and (self._return_proof_configured is None
                             or self._return_proof_configured() is True)
        except Exception:  # noqa: BLE001 - an unreadable proof admits nothing
            return False

    def _motion_basis(self, now, kind, map_id=None):
        """'enforce', 'site' (its standing part holds for `kind`) or None."""
        if self._enforce_basis():
            return 'enforce'
        c, at = self._config, self._clearance_at
        site = (c.site_floor_map_id is not None and map_id in (None, c.site_floor_map_id)
                and c.ir_guard_enabled and self._ir_guard(now) in IR_ALLOWED[kind]
                and c.obstacle_mode == 'path' and c.body_stop_known and self._scan_points is not None
                and at is not None and 0 <= now-at <= c.clearance_stale_s)
        return 'site' if site else None

    def motion_admitted(self, now, linear, angular, kind, map_id=None):
        """May this (linear, angular) of `kind` go out? map_id: the opening instruction's SiteMap."""
        if kind not in IR_ALLOWED:
            raise ValueError(f"unknown motion kind {kind!r}")
        with self._lock:
            basis = self._motion_basis(now, kind, map_id)
            if basis == 'enforce':
                return self._return_probe(now, linear, angular)
            if basis is None or (linear < 0 and kind != 'retrace'):
                return False
            return not (linear or angular) or self._sweep_clear(now, linear, angular)

    def _sweep_clear(self, now, linear, angular):
        """D-422 body sweep of this twist (not the follow intent) above its restart gap."""
        if linear < 0:
            return self._rear_sweep_clear(-linear, angular)
        saved = self._intended, self._gap_status, self._gap_resume
        self._intended = (linear, angular)
        try:
            gap, _, _, resume = self._body_clearance(now)
        finally:
            self._intended, self._gap_status, self._gap_resume = saved
        return gap is None or gap > resume

    def _rear_sweep_clear(self, speed, angular):
        """Reverse: the outline swept backwards over the 360 deg scan and the points remembered
        under range_min, turned half a turn so reverse is forward. Restart gap as forward, never
        below the rear LiDAR blind band (no rear ultrasonic)."""
        c, envelope = self._config, self._envelope()
        if envelope is None or self._odometry_hold:
            return False
        speed, angular = min(speed, envelope[0]), max(-envelope[1], min(envelope[1], angular))
        stop = c.derived_stop_gap_m(speed)
        resume = stop + c.obstacle_resume_hysteresis_m
        if self._range_min is not None:
            resume += max(0., self._range_min - (c.body_lidar_x_m - c.body_rear_x_m) - stop)
        points = [(-(x + c.body_lidar_x_m), -y) for x, y in self._scan_points]
        points += [(-x, -y) for x, y in self._remembered_points()]
        gap = points and body_path_gap(
            points, linear=speed, angular=angular, horizon_m=c.obstacle_path_horizon_m,
            min_travel_m=resume, front_x_m=-c.body_rear_x_m, rear_x_m=-c.body_front_x_m,
            half_width_m=c.body_half_width_m, rotation_radius_m=c.body_rotation_radius_m)
        return not points or gap is None or gap > resume
