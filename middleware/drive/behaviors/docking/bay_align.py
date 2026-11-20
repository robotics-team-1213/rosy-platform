"""core_features.docking.bay_align — 칸 후진 파킹 전 카메라 기준 방향 맞춤과 선 찾기(실물 y8xs 2026-11-19).
지도(SLAM) 방향과 카메라 선 방향이 17~30° 어긋나면 회전이 지도 yaw 로 끝나 선과 틀어진다(진입창 방위 15° 위반
backoff 반복). 횡이 창 안이면 backoff 대신 제자리에서 카메라 방위를 0 으로 맞춘다. 선이 안 보이면(스테이징
0.32 m + Nav2 오차 = 멈춤면 0.305 m 밖) 후진 크립으로 선이 보일 때까지 다가간다. 정지 우선: 회전 판정·신선한
관측·각·횟수·시간 상한이 하나라도 깨지면 멈춘다. `BayPhases` 의 믹스인(락은 매니저의 것). ROS 무의존.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from core_features.docking.parking import ParkingGains, turn_twist
from core_features.docking.rear_phases import rear_errors

# 관측 지연(<=0.3 s)×각속도가 허용 오차(~3°)를 넘지 않게 느리게 돈다: 0.1 rad/s×0.3 s = 1.7°.
_ALIGN_GAINS = ParkingGains(max_angular=0.25, turn_gain=1.5, turn_min_angular=0.1)


def heading_alignable(cfg: Any, lateral: float, heading: float, tries_used: int) -> bool:
    """횡은 진입창 안, 방위만 창 밖(상한 안)이고 횟수가 남았다 — 후진하지 않고 제자리 회전으로 맞출 수 있다."""
    # The tray tip (overhang 0.135 behind the axle) already sits at |lateral| + overhang*sin(bearing) from the line; past the
    # lane half pitch it is beside a neighbour, and the in-place turn is not the right fix (the sim's only contacts).
    tip = abs(lateral) + cfg.bay_turn_rear_overhang_m * math.sin(abs(heading))
    return (abs(lateral) <= cfg.bay_entry_lat_m
            and cfg.bay_entry_heading_max_rad < abs(heading) <= cfg.bay_heading_align_max_rad
            and tip <= cfg.bay_lane_half_m
            and tries_used < cfg.bay_heading_align_tries)


class BayAlignMixin:
    def _init_align(self) -> None:
        self._align: Optional[tuple[float, float, float]] = None   # (시작, 시작 odom yaw, 마지막 신선 관측)
        self._align_n = 0                                          # 한 도킹의 회전 맞춤 횟수(첫 시도에서만 비운다)
        self._align_lp = None                                      # reference-scan dock: (heading, lateral, at) of the newest LiDAR pose during the align
        self._ap_ask_at = -1e9
        self._find_on = False
        self._find_seen_m: Optional[float] = None                  # 선이 처음 보인 때의 후진 거리
        self._reset_find()

    def _reset_find(self) -> None:
        # creep-start heading gate (LiDAR scan pose): asked once, the heading read once, an in-place turn outside the row
        self._find_since, self._find_asked, self._find_match = None, False, None
        self._fh_done, self._fh_turn, self._fh_verify = False, None, False

    def _find_heading_gate(self, now: float):
        """Before the find creep starts, with a reference scan: the LiDAR heading beyond bay_find_heading_max_rad is turned out in place
        when the robot is outside the row (x >= staging), else the creep does not start (the row is no place to turn). None = start
        the creep; True = handled this tick (waiting for the pose, turning, or failed)."""
        h, cfg = self._h, self._h._cfg
        if self._fh_turn is not None:
            return self._tick_find_turn(now)
        if self._fh_verify:
            return self._verify_find_turn(now)
        if self._fh_done or not isinstance(getattr(h._dock, "metadata", {}).get("reference_scan"), dict):
            return None
        self._find_since = now if self._find_since is None else self._find_since
        if self._find_match is None:
            if now - self._find_since < cfg.bay_scan_pose_wait_s:
                self._stop()
                return True
            self._fh_done = True
            return None                                   # no scan pose in time: as before
        self._fh_done = True
        m, pose = self._find_match[0], self._odometry()
        # scan_geometry refuses a pose at or beyond staging (outside the row); only the heading is wanted here, with its fit gates
        if (m is None or pose is None or m.inliers < cfg.bay_scan_inlier_min or m.margin < cfg.bay_scan_margin_min
                or abs(m.heading) > cfg.bay_scan_heading_max_rad or abs(m.heading) <= cfg.bay_find_heading_max_rad):
            return None
        if m.x < h._type().staging_offset_m:
            self._stop()
            h._fail("bay find creep: heading %.0f deg inside the row (x %.2f m): not creeping, centre the robot first"
                    % (math.degrees(m.heading), m.x))
            return True
        self._stop()
        self._fh_turn = (now, pose[2] - m.heading, pose[2], abs(m.heading))        # start, target yaw, start yaw, |heading| to turn out
        self._tw_start(pose[2], now)
        return True

    def _tick_find_turn(self, now: float):
        h, cfg = self._h, self._h._cfg
        start, target, yaw0, turn = self._fh_turn
        pose = self._odometry()
        body = self._body_fresh(now)
        if body is not None and body[3] < start:
            body = None
        if pose is None or now - start > cfg.bay_heading_align_timeout_s:
            self._fh_turn = None
            self._stop()
            h._fail("bay find heading align timed out")
            return True
        if body is None or body[0] is not None:             # the sweep must be clear every tick, as for the staging turn
            self._stop()
            if body is not None or now - start > cfg.bay_scan_wait_s:
                self._fh_turn = None
                h._fail("bay find heading align not clear: %s" % (body[0] if body else "no fresh body scan"))
            return True
        if abs(math.remainder(pose[2] - yaw0, math.tau)) > turn + 0.1:           # total rotation cap: never more than the heading + 0.1 rad
            self._fh_turn = None
            self._stop()
            h._fail("bay find heading align turned beyond its cap (%.0f deg for %.0f deg): stopped" % (
                math.degrees(abs(math.remainder(pose[2] - yaw0, math.tau))), math.degrees(turn)))
            return True
        self._tw_odo(pose[2], now)
        why = self._tw_verdict(now)
        if why:                                                  # the body does not follow the wheels (LiDAR yaw vs odometry)
            self._fh_turn, self._tw = None, None
            self._stop()
            h._fail(why)
            return True
        error = math.remainder(target - pose[2], math.tau)
        if abs(error) <= cfg.bay_heading_align_tol_rad:
            self._tw = None
            # turned: stand still, ask the scan pose again and require the heading to be out (below)
            self._fh_turn, self._fh_verify = None, True
            self._find_since, self._find_asked, self._find_match = now, False, None
            self._stop()
            return True
        self._drive(0.0, turn_twist(error, _ALIGN_GAINS)[0])
        return True

    def _verify_find_turn(self, now: float):
        h, cfg = self._h, self._h._cfg
        if self._find_match is None:
            if now - self._find_since < cfg.bay_scan_pose_wait_s + cfg.bay_seat_check_delay_s:
                self._stop()
                return True
            self._fh_verify = False
            h._fail("bay find heading align: no scan pose to verify the turn: not creeping")
            return True
        m = self._find_match[0]
        self._fh_verify = False
        if (m is None or m.inliers < cfg.bay_scan_inlier_min or m.margin < cfg.bay_scan_margin_min
                or abs(m.heading) > cfg.bay_find_heading_verify_rad):
            h._fail("bay find heading align did not bring the heading out (%s): not creeping" % (
                "no good scan pose" if m is None else "%.1f deg" % math.degrees(m.heading)))
            return True
        return None

    def _try_heading_align(self, now: float, lateral: float, heading: float) -> bool:
        """진입창 방위 위반 때: 맞출 수 있으면 멈추고 맞춤을 시작한다. True = 맡았다."""
        if self._in_row or not heading_alignable(self._h._cfg, lateral, heading, self._align_n):
            return False             # the tray corner's turning circle (0.29 m) exceeds the lane (0.21 m): no in-place turn inside the row, ever
        pose = self._odometry()
        if pose is None:
            return False
        self._stop()
        self._align_n += 1
        self._align = (now, pose[2], now)
        self._align_lp, self._ap_ask_at = None, -1e9
        return True

    def _tick_heading_align(self, now: float) -> None:
        """폐루프 제자리 회전: 신선한 몸 스캔이 회전 가능일 때만 돌고, 신선한 카메라 방위가 허용오차 안이면 끝."""
        h, cfg = self._h, self._h._cfg
        start, yaw0, seen = self._align
        pose = self._odometry()
        if pose is None:
            self._align = None
            self._stop()
            h._fail("bay odometry unavailable")
            return
        if (abs(math.remainder(pose[2] - yaw0, math.tau)) > cfg.bay_heading_align_max_rad + 0.1
                or now - start > cfg.bay_heading_align_timeout_s):
            self._align = None
            self._stop()
            h._retry("bay heading align did not converge")
            return
        body = self._body_fresh(now)
        if body is not None and body[3] < start:
            body = None          # a scan from before the align says nothing about the sweep now
        if body is None or body[0] is not None:
            self._stop()
            if body is not None or now - start > cfg.bay_scan_wait_s:
                self._align = None
                h._fail("bay heading align not clear: %s" % (body[0] if body else "no fresh body scan"))
            return
        if self._has_reference():
            # R4: closed on the LiDAR pose, never on the camera heading (wrong by ~20 deg at this site)
            lp = self._align_lp
            if lp is None or now - lp[2] > cfg.bay_scan_fresh_s + cfg.bay_lidar_ask_s:
                self._stop()
                if now - seen > cfg.detector_lost_grace_s:
                    self._align = None
                    h._fail("bay heading align: no fresh LiDAR pose (the camera heading is not used): stopped")
                return
            heading, lateral = lp[0], lp[1]
        else:
            _, lateral, heading = self._line_errors()
            if heading is None or self._obs_age > cfg.bay_obs_max_age_s:
                self._stop()
                if now - seen > cfg.detector_lost_grace_s:
                    self._align = None
                    h._retry("bay line lost during heading align")
                return
        self._align = (start, yaw0, now)
        if abs(lateral) > cfg.bay_entry_lat_m:
            self._stop()
            self._align = None       # the entry window refuses it on the next tick, as without the align
            return
        if abs(heading) <= cfg.bay_heading_align_tol_rad:
            self._stop()
            self._align = None
            self._match = (lateral, heading)
            self._entry_since, self._entry_asked, self._entry_match = None, False, None     # the entry window measures the LiDAR pose again
            return
        self._drive(0.0, turn_twist(-heading, _ALIGN_GAINS)[0])

    def _find_step(self, now: float, seen: bool) -> bool:
        """스테이징에서 선이 안 보이면 후진 크립. 처음 보인 뒤에도 정착 크립(전진) 몫만큼 더 가서 선을 안 잃게 한다.
        뒤 LiDAR 띠 여유가 작으면 멈추고 재진입. True = 이 틱을 맡았다."""
        h, cfg = self._h, self._h._cfg
        if not self._find_on:
            if seen or h.executor is None or now - h._phase_since < cfg.bay_find_wait_s:
                return False
            gate = self._find_heading_gate(now)
            if gate is not None:
                return gate
            h.executor.reset_odometry_mark()
            self._find_on, self._find_seen_m = True, None
        travelled = abs(h.executor.travelled_m())
        if seen and self._find_seen_m is None:
            self._find_seen_m = travelled
        if self._find_seen_m is not None and travelled >= self._find_seen_m + cfg.bay_find_extra_m:
            self._find_end()
            return False
        body = self._body_fresh(now)
        if body is not None and body[3] < h._phase_since:
            body = None
        if body is None:
            self._stop()
            if now - h._phase_since > cfg.bay_find_wait_s + cfg.bay_scan_wait_s:
                self._find_end()
                h._retry("bay find creep: no fresh body scan")
            return True
        if body[2] is not None and body[2] < cfg.bay_find_rear_gap_m:
            self._find_end()
            self._guard_fail("find-rear", "LiDAR sees something close behind while looking for the line", h._retry)
            return True
        seat = self._seat_gap if self._seat_gap is not None and self._seat_gap[0] == h._dock.id else None
        creep_max = cfg.bay_find_creep_max_m
        if seat is not None and body[2] is not None:
            # the stored seated gap makes the LiDAR rear gap a position: creep to where the line shows, bounded by the rails
            creep_max = cfg.bay_find_lidar_creep_max_m
            if self._find_seen_m is None and body[2] - seat[1] <= cfg.bay_find_min_x_m:
                self._find_end()
                self._guard_fail("find", "guide line not found before the rails (LiDAR x %.2f m)" % (body[2] - seat[1]), h._retry)
                return True
        if self._find_seen_m is None and travelled >= creep_max:
            self._find_end()
            self._guard_fail("find", "guide line not found within the find creep", h._retry)
            return True
        h.executor.set_collision_exemption(True)
        self._drive(-cfg.bay_find_speed, 0.0)
        return True

    def _stage_heading_bad(self, mp) -> bool:
        """Staging arrival heading check. With the camera on the bay line its (undirected) bearing decides; the SLAM yaw
        can be 17-30 deg off the line and only has to rule out a wrong-way arrival. No line in view: the map yaw as before."""
        h = self._h
        cfg = h._cfg
        map_err = abs(math.remainder(mp[2] - h._dock.yaw, math.tau))
        if h._detector is None and h._detector_factory is not None:
            h._detector = h._detector_factory(h._dock, h._type())
        if h._detector is not None:
            h._detector.start(h._dock)        # the retry back-off stopped it; the line is looked at from the staging point
        raw = h._detector.relative_pose() if h._detector is not None else None
        if raw is None:
            return map_err > cfg.bay_stage_heading_max_rad
        off = math.remainder(rear_errors(raw)[2], math.pi)     # a line has no direction: fold into +-90 deg
        return abs(off) > cfg.bay_stage_heading_max_rad or map_err > cfg.bay_stage_map_wrong_way_rad

    def _find_end(self) -> None:
        self._find_on, self._find_seen_m = False, None
        self._stop()
        if self._h.executor is not None:
            self._h.executor.set_collision_exemption(False)