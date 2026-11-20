"""core_features.docking.bay_zone_phases — 칸 줄 안에서 시작한 도킹(D-1013 2026-11-18)과 LiDAR 칸 자세 요청.
스테이징·제자리 회전 없이 선 관측을 보고 곧게 전진해 나온 뒤 선 포획부터 한다. `BayPhases` 의 믹스인
(bay_phases.py 크기 한도로 분리; 상태와 락은 `BayPhases`·매니저의 것). 기준 스캔으로 칸 자세를 묻는 요청(칸 줄 판정, 정착
크리프 뒤 진입 가드, SETTLING 안착 확인)과 진입 가드의 횡 목록도 여기다. ROS 무의존.
"""

from __future__ import annotations

import logging
from typing import Optional

from core_features.docking.bay_zone import DISAGREE, NO_LINE, classify as classify_zone, scan_diagnosis, scan_geometry
from core_features.docking.model import DockPhase
from core_features.docking.rear_phases import rear_errors

_LOG = logging.getLogger(__name__)


class BayZoneMixin:
    def _init_scan(self) -> None:
        # LiDAR bay pose (bay_scan_pose.py): one ask per check; request ids drop late answers
        self._scan_asked, self._scan_match, self._scan_error = False, None, None
        self._seat_asked, self._seat_match = False, None            # SETTLING: the seated check asks once
        self._req_seq, self._req_open, self._req_kind = 0, None, ""
        self._entry_since, self._entry_asked, self._entry_match = None, False, None   # entrance guard: fresh pose after the creep
        self._bay_lateral: Optional[float] = None                  # LiDAR lateral: fills in when the line gives none

    def _entrance_blocked(self, now: float, along: float, lateral: float) -> bool:
        """Before the reverse into the rails (main's entry window has passed): True = handled (still waiting for the fresh
        scan pose, or stopped with "centre the robot first"). The rails' entrance leaves ~9 mm a side and the wheels meet it
        7.5 cm before the stop face (y8xs 2026-11-20, 22 mm off, stopped short); with the steering runway of a normal
        staging flow the line correction still centres it."""
        h, cfg = self._h, self._h._cfg
        if self._along_m is None:
            return False               # along unmeasured = the stop face is out of the camera's range: a long runway
        if self._along_m - cfg.bay_rail_entry_along_m >= cfg.bay_entrance_runway_m:
            return False
        if isinstance(getattr(h._dock, "metadata", {}).get("reference_scan"), dict):
            if self._entry_since is None:
                self._entry_since = now                 # stopped after the creep: measure the pose again, fresh
            if self._entry_match is None and now - self._entry_since < cfg.bay_scan_pose_wait_s:
                return True
        worst = max((abs(v) for v in self._entrance_laterals(lateral)), default=None)
        if worst is None or worst > cfg.bay_entrance_lateral_m:
            self._stop()
            h._fail("bay entrance lateral %s (limit %.3f m): centre the robot first"
                    % ("unmeasured" if worst is None else "%.3f m" % worst, cfg.bay_entrance_lateral_m))
            return True
        return False

    def _seat_blocked(self) -> bool:
        """SETTLING: the LiDAR puts the stopped robot well short of the stop face: the body is held, no charge will come."""
        h, cfg = self._h, self._h._cfg
        seat = self._seat_match[0] if self._seat_match is not None else None
        geo = scan_geometry(seat, h._type().staging_offset_m, cfg) if seat is not None else None
        if geo is None or geo[0] <= cfg.bay_seat_tol_m:
            return False
        h._retry("bay blocked short of the stop face (%.3f m out, seated within %.3f m)" % (geo[0], cfg.bay_seat_tol_m))
        return True

    def _corridor_view(self) -> bool:
        raw = self._h._detector.relative_pose() if self._h._detector is not None else None
        return raw is not None and not raw.lateral_measured

    def scan_request(self) -> Optional[tuple]:
        """CORE 가 LiDAR 콜백에서 묻는다(락 없음): 기준 스캔을 가진 칸이 자세를 기다리면 (요청 번호, 스캔)을 한 번 내준다.
        세 때: 칸 줄 판정, 정착 크리프 뒤 진입 가드(정지 중 새로 잰다), SETTLING 안착 확인."""
        h = self._h
        dock = h._dock
        ref = getattr(dock, "metadata", {}).get("reference_scan") if dock is not None else None
        if not isinstance(ref, dict):
            return None
        if h.phase is DockPhase.SETTLING and not self._seat_asked:
            # stopped for a while: where is the robot against the stop face (the stored seated scan)?
            if h.now() - h._phase_since < h._cfg.bay_seat_check_delay_s:
                return None
            self._seat_asked = True
            return self._open_request(ref, "seat")
        if h.phase is DockPhase.ACQUIRING and self._entry_since is not None and not self._entry_asked:
            if h.now() - self._entry_since < h._cfg.bay_seat_check_delay_s:
                return None                  # stopped after the creep first: the scan must not catch the body moving
            self._entry_asked = True
            return self._open_request(ref, "entry")
        if self._zone != "check" or self._scan_asked:
            return None
        self._scan_asked = True
        return self._open_request(ref, "zone")

    def _open_request(self, ref: dict, kind: str) -> tuple:
        self._req_seq += 1
        self._req_kind, self._req_open = kind, self._req_seq
        return self._req_seq, ref

    def note_scan_match(self, match, at: float, error: Optional[str] = None, request_id: Optional[int] = None) -> None:
        """scan_request 의 답(BayScanPose 또는 None = 못 맞춤). 열린 요청 번호와 다르면(늦은 답) 버린다."""
        if request_id is None or request_id != self._req_open:
            return
        kind, self._req_open = self._req_kind, None
        if kind == "seat":
            self._seat_match = (match, float(at))
        elif kind == "entry":
            self._entry_match = (match, float(at))
        else:
            self._scan_error = error
            self._scan_match = (match, float(at))

    def _entrance_laterals(self, line_lateral: float) -> list:
        """Every independent MEASURED lateral (dock frame, m) for the rails' entrance: the camera line's when it measured
        one, and the fresh LiDAR scan pose's (taken while stopped after the creep). All must pass; the scan one also
        replaces the lateral CORE fills in. A lateral filled from the map or the estimate proves nothing and is not listed."""
        found = []
        raw = self._h._detector.relative_pose() if self._h._detector is not None else None
        if raw is not None and raw.lateral_measured:
            found.append(line_lateral)
        if self._entry_match is not None:
            geo = scan_geometry(self._entry_match[0], self._h._type().staging_offset_m, self._h._cfg)
            if geo is not None:
                found.append(geo[1])
                self._bay_lateral = geo[1]
        return found


    def _tick_zone(self, now: float) -> None:
        """칸 줄 안: 판정 → 곧은 전진(Nav2·제자리 회전 없음) → 뒤가 칸을 보므로 선 포획부터."""
        h, cfg = self._h, self._h._cfg
        if self._zone == "check":
            pose = h._pose_provider()
            if pose is None and now - h._phase_since < cfg.bay_stage_recheck_s:
                return                       # standing still: one missing pose must not end a first try
            scan, scan_note = None, ""
            if isinstance(getattr(h._dock, "metadata", {}).get("reference_scan"), dict):
                if self._scan_match is None and now - h._phase_since < cfg.bay_scan_pose_wait_s:
                    return                   # the match runs off the scan thread; the map path takes over after the wait
                if self._scan_match is not None:
                    scan = scan_geometry(self._scan_match[0], h._type().staging_offset_m, cfg)
                scan_note = scan_diagnosis(self._scan_asked, self._scan_match, self._scan_error, scan, cfg)
            verdict = classify_zone(pose, h._dock, h._type().staging_offset_m,
                                    self._observation(), cfg, scan)
            if scan is not None and verdict.kind in ("acquire", "exit"):
                self._bay_lateral = scan[1]
            if verdict.reason == NO_LINE and now - h._phase_since < cfg.bay_zone_look_s:
                return                       # a frame may still be on its way (5 Hz)
            if verdict.reason.startswith(DISAGREE) and now - h._phase_since < cfg.bay_zone_look_s:
                # The camera can alternate between the corridor line and a spurious fit frame by frame (y8xs
                # 2026-11-20); standing still, look again. A frame is accepted only when it meets the same
                # agreement gate, so nothing is weakened: the refusal after the look time is unchanged.
                return
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
                _LOG.warning("bay zone refused: %s %s", verdict.reason, scan_note)    # WARNING reaches the journal; INFO does not
                h._fail("bay zone: " + verdict.reason + (" " + scan_note if scan_note and scan is None else ""))
            elif h.executor is None:
                h._fail("bay executor unavailable")
            elif verdict.kind == "acquire" or self._corridor_view():
                # Straight in the lane, or only the corridor line is in view: the nose is at the bay mouth, and driving out to the
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
