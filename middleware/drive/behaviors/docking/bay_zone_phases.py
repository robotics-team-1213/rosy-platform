"""core_features.docking.bay_zone_phases — 칸 줄 안에서 시작한 도킹(D-1013 2026-11-18).
스테이징·제자리 회전 없이 선 관측을 보고 곧게 전진해 나온 뒤 선 포획부터 한다. `BayPhases` 의 믹스인
(bay_phases.py 크기 한도로 분리; 상태와 락은 `BayPhases`·매니저의 것). ROS 무의존.
"""

from __future__ import annotations

import logging

from core_features.docking.bay_zone import NO_LINE, classify as classify_zone
from core_features.docking.model import DockPhase
from core_features.docking.rear_phases import rear_errors

_LOG = logging.getLogger(__name__)


class BayZoneMixin:
    def _corridor_view(self) -> bool:
        raw = self._h._detector.relative_pose() if self._h._detector is not None else None
        return raw is not None and not raw.lateral_measured

    def _tick_zone(self, now: float) -> None:
        """칸 줄 안: 판정 → 곧은 전진(Nav2·제자리 회전 없음) → 뒤가 칸을 보므로 선 포획부터."""
        h, cfg = self._h, self._h._cfg
        if self._zone == "check":
            verdict = classify_zone(h._pose_provider(), h._dock, h._type().staging_offset_m,
                                    self._observation(), cfg)
            if verdict.reason == NO_LINE and now - h._phase_since < cfg.bay_zone_look_s:
                return                       # a frame may still be on its way (5 Hz)
            body = self._body_fresh(now)
            if verdict.kind == "out" and (body is None or body[3] < h._phase_since):
                if now - h._phase_since <= cfg.bay_scan_wait_s:
                    return                   # Nav2 may turn at its start: look first
                verdict = verdict.__class__("manual", "no fresh body scan before Nav2")
            elif verdict.kind == "out" and body[0] == "near":
                verdict = verdict.__class__("manual", "something within the tray sweep before Nav2")
            # a log, not an event: a manual verdict already reaches Fleet as docking.failed "bay zone: ..."
            _LOG.info("bay zone verdict %s: %s", verdict.kind, verdict.reason)
            if verdict.kind == "out":
                self._zone, self._zone_checked = None, True
                h._begin_staging()
            elif verdict.kind == "manual":
                self._stop()
                h._fail("bay zone: " + verdict.reason)
            elif h.executor is None:
                h._fail("bay executor unavailable")
            elif self._corridor_view():
                # Only the corridor line is in view: the nose is at the bay mouth, and driving out to the
                # staging distance loses that line under the nose (y8xs 2026-11-18). The rear already faces
                # the bay and the verdict said straight: acquire here.
                self._stop()
                self._reset_line_state()
                h._begin_acquiring()
            else:
                h.executor.reset_odometry_mark()
                self._zone, self._exit_m = "exit", verdict.exit_m
                self._est, h._last_seen_at = None, now
                h._enter(DockPhase.BACKOFF)
            return
        if abs(h.executor.travelled_m()) >= self._exit_m:
            self._stop()
            self._reset_line_state()
            h._begin_acquiring()
            return
        if now - h._phase_since > self._exit_m / cfg.bay_exit_speed + cfg.backoff_timeout_s:
            self._stop()
            h._fail("bay lane exit timed out")
            return
        block = self._forward_block(now, h._phase_since)
        if block is not None:
            self._stop()
            if block != "wait":
                h._fail("bay lane exit: " + block)
            return
        observation = self._observation()
        errors = rear_errors(observation) if observation is not None else None
        if errors is not None and self._est is not None and abs(errors[1] - self._est[0]) > cfg.bay_gate_jump_m:
            errors = None                    # a jump is a neighbour's line or noise, not evidence
        if errors is None:
            # Never steer or drive blind out of the row: stop, and call a person if it stays lost.
            self._stop()
            if h._last_seen_at is None or now - h._last_seen_at > cfg.detector_lost_grace_s:
                h._fail("bay lane exit lost the guide line")
            return
        _, lateral, heading = errors
        self._est, h._last_seen_at = (lateral, heading), now
        angular = 0.0
        if cfg.bay_exit_steer_head > 0.0:
            # Forward along the line: hold a heading that walks the lateral back (sign checked in sim).
            target = max(-0.15, min(0.15, cfg.bay_exit_steer_lat * lateral))
            angular = max(-0.3, min(0.3, -cfg.bay_exit_steer_head * (heading - target)))
        self._drive(cfg.bay_exit_speed, angular)
