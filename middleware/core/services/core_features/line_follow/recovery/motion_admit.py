"""D-507 6: one motion admission for D-468 return/retrace, D-476 bridge and D-495 junction motion.

(a) enforce: the D-400 worker proof (bind_return_motion), unchanged; while its floor proof is live
or unknown it alone decides (unbound or unconfigured: refused, never the site basis).
(b) site: the D-507 9 floor declaration, a fresh calibrated IR verdict this kind may run on, path
mode with the URDF body, a fresh scan and the D-422 sweep of the very twist above its restart gap.
(c) Reverse on (b) only for the D-468 retrace (limits stay in lane_return.py): no IR sees the rear
floor, the declaration covers it and the rear sweep is the space evidence. Under the manager lock.
"""
from core_common.robot_body import RobotBody
from core_features.line_follow.clearance import body_envelope_gap, body_path_gap

#: IR guard verdicts (manager._ir_guard) each kind may move on; 'stale' never. Bridge: D-476
#: rev 1 and the bend pass (its blind arc, the same fence); approach/turn/advance: D-498 (not on
#: the line); return/retrace: D-468 starts on it.
_OFF_LINE, _ANY = frozenset({'clear', 'left', 'right'}), frozenset({'clear', 'left', 'right', 'centre'})
IR_ALLOWED = {'bridge': frozenset({'clear'}), 'bend': frozenset({'clear'}),  # bend: D-507 addendum
              'approach': _OFF_LINE, 'turn': _OFF_LINE,
              'advance': _OFF_LINE, 'return': _ANY, 'retrace': _ANY}


class MotionAdmitMixin:
    def _proof_live(self):
        """The D-400 floor proof is live or unknown (unbound or unreadable liveness)."""
        try:
            return self._floor_proof_live is None or self._floor_proof_live() is not False
        except Exception:  # noqa: BLE001 - unreadable liveness: the proof is required
            return True

    def _motion_basis(self, now, kind, map_id=None, centre_ok=False):
        """Capability basis: 'enforce' when the live (or unknown) proof is bound and configured,
        None when it is live but cannot admit (fail closed), else 'site' if its standing part
        holds for `kind` (centre_ok: see motion_admitted)."""
        if self._proof_live():
            try:
                return 'enforce' if (self._return_motion is not None
                                     and self._return_proof_configured is not None
                                     and self._return_proof_configured() is True) else None
            except Exception:  # noqa: BLE001 - an unreadable proof admits nothing
                return None
        c, at, ir = self._config, self._clearance_at, self._ir_guard(now)
        site = (c.site_floor_map_id is not None and map_id in (None, c.site_floor_map_id)
                and c.ir_guard_enabled and (ir in IR_ALLOWED[kind] or (
                    centre_ok and ir == 'centre' and kind in ('approach', 'advance')))
                and c.obstacle_mode == 'path' and c.body_stop_known and self._scan_points is not None
                and at is not None and 0 <= now-at <= c.clearance_stale_s)
        return 'site' if site else None

    def motion_admitted(self, now, linear, angular, kind, map_id=None, centre_ok=False):
        """May this (linear, angular) of `kind` go out? map_id: the opening instruction's SiteMap.
        centre_ok: IR row inside the camera's cross-line band (user 2026-10-08), approach/advance."""
        if kind not in IR_ALLOWED:
            raise ValueError(f"unknown motion kind {kind!r}")
        with self._lock:
            if self._proof_live():
                return self._return_probe(now, linear, angular)  # unbound: False
            if self._motion_basis(now, kind, map_id, centre_ok) is None or (
                    linear < 0 and kind != 'retrace'):
                return False
            return not (linear or angular) or self._sweep_clear(now, linear, angular)

    def _sweep_clear(self, now, linear, angular):
        """D-422 body sweep of this twist (not the follow intent) above its restart gap."""
        if linear < 0:
            return self._rear_sweep_clear(now, -linear, angular)
        saved = self._intended, self._gap_status, self._gap_resume
        self._intended = (linear, angular)
        try:
            gap, _, _, resume = self._body_clearance(now)
        finally:
            self._intended, self._gap_status, self._gap_resume = saved
        return gap is None or gap > resume

    def _rear_sweep_clear(self, now, speed, angular):
        """Reverse, as _body_clearance forward: the outline swept back along the (clipped) arc and
        the traffic-gate arc family over the 360 deg scan and remembered points (turned half a
        turn), the stop override moved to the body rear, never below the rear blind band. Unknown
        rear beams block (the enforce probe's rule); an unknown range_min refuses."""
        c, envelope = self._config, self._envelope()
        if envelope is None or self._odometry_hold or self._range_min is None:
            return False
        max_linear, max_angular, floor = envelope
        speed, angular = min(speed, max_linear), max(-max_angular, min(max_angular, angular))
        back = c.body_lidar_x_m - c.body_rear_x_m
        if c.obstacle_override:
            stop, resume = max(0., c.sector_stop_m - back), max(0., c.sector_resume_m - back)
        else:
            stop = c.derived_stop_gap_m(speed)
            resume = stop + c.obstacle_resume_hysteresis_m
        resume += max(0., self._range_min - back - stop)
        view = self._return_view
        if view is not None:
            outline = RobotBody(front_x_m=c.body_front_x_m, rear_x_m=c.body_rear_x_m,
                                half_width_m=c.body_half_width_m, lidar_x_m=c.body_lidar_x_m,
                                rotation_radius_m=c.body_rotation_radius_m)
            age = max(0., now - self._return_at + (self._return_source_age or 0.))
            pad = outline.sweep_pad_m + age*(c.max_linear + c.body_rotation_radius_m*c.max_angular)
            if outline.unknown_blocks(view, reverse=True, pad_m=pad):
                return False
        points = [(-(x + c.body_lidar_x_m), -y) for x, y in self._scan_points]
        points += [(-x, -y) for x, y in self._remembered_points()]
        if not points:
            return True
        body = dict(front_x_m=-c.body_rear_x_m, rear_x_m=-c.body_front_x_m,
                    half_width_m=c.body_half_width_m, rotation_radius_m=c.body_rotation_radius_m)
        gaps = [body_path_gap(points, linear=speed, angular=angular, min_travel_m=resume,
                              horizon_m=c.obstacle_path_horizon_m, **body)]
        if floor < 1. and abs(angular) > 1e-6:
            gaps.append(body_envelope_gap(points, linear=speed, angular=angular,
                                          scale_floor=floor, horizon_m=resume, **body))
        return all(gap is None or gap > resume for gap in gaps)
