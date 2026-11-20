"""core_features.docking.bay_zone_phases — 칸 줄 안에서 시작한 도킹(D-1013 2026-11-18)과 LiDAR 칸 자세 요청.
스테이징·제자리 회전 없이 선 관측을 보고 곧게 전진해 나온 뒤 선 포획부터 한다. `BayPhases` 의 믹스인
(bay_phases.py 크기 한도로 분리; 상태와 락은 `BayPhases`·매니저의 것). 기준 스캔으로 칸 자세를 묻는 요청(칸 줄 판정, 정착
크리프 뒤 진입 가드, SETTLING 안착 확인)과 진입 가드의 횡 목록도 여기다. ROS 무의존.
"""

from __future__ import annotations

import dataclasses
import logging
import math
from typing import Optional

from core_features.docking.bay_zone import (DISAGREE, NO_LINE, classify as classify_zone, map_offsets, scan_diagnosis,
                                            lane_edge, lane_extent, pose_gate, scan_fit_pose, scan_geometry)
from core_features.docking.model import DockPhase
from core_features.docking.rear_phases import rear_errors

_LOG = logging.getLogger(__name__)


class BayZoneMixin:
    def _map_frame_mismatch(self, pose) -> Optional[str]:
        """A Nav2 start (the map pose says "outside the row") with a good LiDAR scan pose of the bay that puts the robot elsewhere than the map
        does: the SLAM map restarted or drifted since the dock was taught (its origin is the robot's start pose; scan matching runs only after
        0.5 m / 0.5 rad of travel, so inside a bay the map is dead reckoning). Refuse with the numbers instead of driving by it."""
        h, cfg = self._h, self._h._cfg
        m = self._scan_match[0] if self._scan_match is not None else None
        if (pose is None or m is None or m.inliers < cfg.bay_scan_inlier_min or m.margin < cfg.bay_scan_margin_min
                or abs(m.heading) > cfg.bay_scan_heading_max_rad):
            return None
        along, lateral, _ = map_offsets(pose, h._dock)
        gap = math.hypot(along - m.x, lateral + m.y)
        if gap <= cfg.bay_map_scan_tol_m:
            return None
        return ("map frame does not match the LiDAR: the dock's map pose puts the robot %.2f m from where the scan sees the bay "
                "(the SLAM map restarted or drifted since the dock was taught): teach the dock again" % gap)

    def _row_forward_reason(self, step: Optional[float] = None, now: Optional[float] = None, since: float = 0.0) -> Optional[str]:
        """In the row (case I: re-dock from inside the lane) with a reference scan, a forward motion (creep 0.04, retry back-off 0.15) must not carry the
        robot past the bay line in front (bay_line_x_m): the last LiDAR bay pose's x plus the planned step stays inside it, and the lateral stays in the lane."""
        h, cfg = self._h, self._h._cfg
        rp = self._row_pose
        if not ((self._in_row or self._reseat_active) and self._has_reference()):
            return None
        if rp is None or (now is not None and now - rp[3] > cfg.bay_row_pose_fresh_s):
            # R2: no forward motion in the row on a map/camera "acquire" alone: a LiDAR bay pose no older than bay_row_pose_fresh_s must back it
            if now is not None and now - since <= cfg.bay_scan_pose_wait_s + cfg.bay_scan_wait_s:
                return "wait"
            return "no fresh LiDAR bay pose (<= %.1f s) for a forward move in the row" % cfg.bay_row_pose_fresh_s
        if rp is None:
            return None
        if lane_extent(cfg, rp[1], rp[2]) > lane_edge(cfg, h._dock):
            h._last_event = "lane keeping: the body overlaps a neighbour lane (lateral %.0f mm, heading %.0f deg)" % (rp[1] * 1000.0, math.degrees(rp[2]))
            return "left the lane (body footprint beyond %.0f mm: lateral %.0f mm, heading %.0f deg)" % (
                lane_edge(cfg, h._dock) * 1000.0, rp[1] * 1000.0, math.degrees(rp[2]))
        step = cfg.bay_backoff_m if step is None else step
        if rp[0] + step > cfg.bay_line_x_m - 0.02:
            h._last_event = "lane keeping: a forward move of %.2f m would pass the bay line (x %.2f m, line %.2f m)" % (step, rp[0], cfg.bay_line_x_m)
            return "a forward move of %.2f m from x %.2f m would pass the bay line (%.2f m)" % (step, rp[0], cfg.bay_line_x_m)
        return None

    def _init_scan(self) -> None:
        self._seat_tries, self._seat_ask_at, self._req_t, self._req_lat = 0, -1e9, 0.0, None
        self._row_pose = None                        # (x, lateral, heading, at): the newest good LiDAR bay pose, for the lane-keeping guards
        # LiDAR bay pose (bay_scan_pose.py): one ask per check; request ids drop late answers
        self._scan_asked, self._scan_match, self._scan_error = False, None, None
        self._seat_asked, self._seat_match = False, None            # SETTLING: the seated check asks once
        self._req_seq, self._req_open, self._req_kind = 0, None, ""
        self._req_track, self._ans_track, self._track_why = False, False, None
        self.bay_identity = "confirmed"                 # "unconfirmed" after a weak first acquisition (no stamp, no re-teach from it)
        self._entry_since, self._entry_asked, self._entry_match = None, False, None   # entrance guard: fresh pose after the creep
        self._bay_lateral: Optional[float] = None                  # LiDAR lateral: fills in when the line gives none
        self._along_last: Optional[tuple] = None   # (last measured along, odometry travel then): the along while the camera cannot measure it
        self._in_row = False         # the last zone verdict started it inside the bay row (no Nav2 round trip, no drive-out retry)

    def _entry_lidar(self, now: float):
        """Reference-scan dock after the settle creep, stopped: the fresh LiDAR pose's (lateral, heading) for the entry window. "wait" while
        the pose is being measured (bay_scan_pose_wait_s); None = no reference scan or no good pose."""
        h, cfg = self._h, self._h._cfg
        if not self._has_reference():
            return None
        if self._entry_since is None:
            self._entry_since = now
        if self._entry_match is None:
            return "wait" if now - self._entry_since < cfg.bay_scan_pose_wait_s else None
        fit = scan_fit_pose(self._entry_match[0], cfg)
        if fit is None:
            return None
        if abs(fit[1]) > cfg.bay_lane_half_m:
            # round 23: lateral 191 mm, heading 23 deg right after a good turn while the robot was on the axis: one bay pitch (0.19-0.22) off is an
            # alias of the neighbouring bay, not a pose. This window (outside the row) has no staging gate, so the lane gate applies here.
            self._h._last_event = "entry LiDAR pose rejected: lateral %.0f mm is outside this bay's lane (alias of a neighbour bay?)" % (fit[1] * 1000.0)
            return None
        return (fit[1], fit[2], fit[0])

    def _entry_values(self, now: float, lateral: float, heading: float):
        """The (lateral, heading) the entry window judges after the settle creep, or "wait"/"stop" (handled this tick).
        Reference-scan dock: the LiDAR pose's; no good pose and a map-filled camera lateral = not evidence (one retry, then stop);
        LiDAR vs camera crossbar heading apart by more than bay_entry_heading_cross_rad outside the rails = a false fit, stop."""
        h, cfg = self._h, self._h._cfg
        entry = self._entry_lidar(now)
        if entry == "wait":
            return "stop"
        if entry is not None:
            cam_heading = heading
            lat, head, entry_x = entry
            apart = (cam_heading is not None and entry_x > cfg.bay_entry_outside_rails_x_m
                     and abs(math.remainder(head - cam_heading, math.tau)) > cfg.bay_entry_heading_cross_rad)
            m = self._entry_match[0]
            if (cam_heading is not None and entry_x > cfg.bay_entry_outside_rails_x_m
                    and abs(math.remainder(head - cam_heading, math.tau)) > cfg.bay_entry_heading_hard_rad):
                self._stop()                                  # even a strong fit: 40 deg apart is not a 20-deg camera bias, one of them is lost
                h._fail("bay entry heading: LiDAR %.0f deg vs camera %.0f deg are over %.0f deg apart: stopped"
                        % (math.degrees(head), math.degrees(cam_heading), math.degrees(cfg.bay_entry_heading_hard_rad)))
                return "stop"
            if apart and m.inliers >= cfg.bay_entry_strong_inliers and m.margin >= cfg.bay_entry_strong_margin:
                # a strong LiDAR fit outweighs the camera crossbar heading (wrong by ~20 deg at this site, round 22): note it, go on
                h._last_event = "entry: camera heading %.0f deg ignored, strong LiDAR fit %.0f deg (inliers %.2f margin %.2f)" % (
                    math.degrees(cam_heading), math.degrees(head), m.inliers, m.margin)
                apart = False
            if apart:
                self._stop()
                h._fail("bay entry heading: LiDAR %.0f deg vs camera %.0f deg disagree (false fit?): stopped"
                        % (math.degrees(head), math.degrees(cam_heading)))
                return "stop"
            return lat, head
        if self._has_reference():
            raw = h._detector.relative_pose() if h._detector is not None else None
            if raw is None or not raw.lateral_measured:
                self._guard_fail("entry-lidar", "no LiDAR pose at the entry window and no measured camera lateral", h._retry)
                return "stop"
        return lateral, heading

    def _rail_judge(self, now: float) -> bool:
        """Reference-scan dock, LiDAR steering: right before the wheels reach the rails' entrance (LiDAR x <= bay_rail_judge_x_m) the mean of the last
        bay_rail_judge_n LiDAR laterals must be within bay_entrance_lateral_m (the 9.45 mm a side clearance); until then the reverse itself corrects the
        lateral on the LiDAR pose. Too few poses: stand still and wait (fail after the pose grace). True = handled this tick (stopped or failed)."""
        h, cfg = self._h, self._h._cfg
        if self._rail_judged or self._x_now is None or self._x_now > cfg.bay_rail_judge_x_m:
            return False
        recent = self._lp_hist[-cfg.bay_rail_judge_n:]
        if len(recent) < cfg.bay_rail_judge_n:
            self._stop()
            self._gap_hist = []
            self._judge_wait = now if self._judge_wait is None else self._judge_wait
            if now - self._judge_wait > cfg.bay_lidar_pose_grace_s + 1.0:
                h._fail("bay rail entrance: fewer than %d LiDAR poses to judge the lateral: stopped" % cfg.bay_rail_judge_n)
            return True
        mean = sum(recent) / len(recent)
        if abs(mean) > cfg.bay_entrance_lateral_m:
            self._stop()
            h._retry("bay rail entrance lateral %.3f m (mean of %d LiDAR poses, limit %.3f m)" % (mean, len(recent), cfg.bay_entrance_lateral_m))
            return True
        self._rail_judged = True
        return False

    def _entrance_blocked(self, now: float, along: float, lateral: float) -> bool:
        """Before the reverse into the rails (main's entry window has passed): True = handled (still waiting for the fresh
        scan pose, or stopped with "centre the robot first"). The rails' entrance leaves ~9 mm a side and the wheels meet it
        7.5 cm before the stop face (y8xs 2026-11-20, 22 mm off, stopped short); with the steering runway of a normal
        staging flow the line correction still centres it."""
        h, cfg = self._h, self._h._cfg
        if self._has_reference() and self._entry_match is not None:
            fit = scan_fit_pose(self._entry_match[0], cfg)
            if fit is not None and fit[0] > cfg.bay_rail_judge_x_m + 0.08:
                return False           # outside the rails with runway: the reverse corrects the lateral and _rail_judge judges at the rails
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

    def _seat_geo(self):
        """(x out of the stop face, lateral, heading) from the stopped robot's LiDAR seat check, or None (no reference / no good fit)."""
        seat = self._seat_match[0] if self._seat_match is not None else None
        return scan_geometry(seat, self._h._type().staging_offset_m, self._h._cfg) if seat is not None else None

    def _note_along(self) -> None:
        if self._along_m is not None and self._h.executor is not None:
            self._along_last = (self._along_m, abs(self._h.executor.travelled_m()))

    def _along_now(self) -> Optional[float]:
        """The along to the stop face: measured, else the last measured one minus the odometry travel since (a reverse only closes it)."""
        if self._along_m is not None:
            return self._along_m
        if self._along_last is None or self._h.executor is None:
            return None
        last, at = self._along_last
        return last - max(0.0, abs(self._h.executor.travelled_m()) - at)

    def drive_out_refusal(self, origin=None) -> Optional[str]:
        """Why a retry from SETTLING must not drive out of the rails: the dock has a reference scan but the seat could not be
        measured, or it is skewed (round 16: a forward back-off pivoted a skewed robot 77 deg). None = allowed (also without a reference)."""
        h, cfg = self._h, self._h._cfg
        if origin is DockPhase.ALIGNING and self._has_reference():
            return None                                   # the reverse is judged by the LiDAR pose every tick; a reseat corrects it in the lane
        if origin is DockPhase.ALIGNING:
            # No seat check in ALIGNING: inside the rails (x < 0.1) a retry with a skewed line heading must not drive out either.
            est, along = self._est, self._along_now()
            if est is not None and along is not None and along < cfg.bay_inrow_along_m and abs(est[1]) > cfg.bay_inrow_retry_heading_rad:
                return "bay retry from ALIGNING inside the rails with a %.0f deg line heading: not driving out" % math.degrees(est[1])
            return None
        if not isinstance(getattr(h._dock, "metadata", {}).get("reference_scan"), dict):
            return None
        geo = self._seat_geo()
        if geo is None:
            return "bay seat not measurable by LiDAR (no good scan pose): not driving out of the rails"
        return None                                       # a skewed seat is corrected by a lane reseat (bay_reseat.py), not refused

    def _settle_unconfirmed(self) -> bool:
        """SETTLING timed out with no charge evidence. A LiDAR-confirmed straight seat stays (user rule 2026-11-21: keep the parking lines, never drive out of
        a straight seat): DOCKED, not CHARGING, the pack voltage watched (a fall warns), the state said in status.last_event. True = docked."""
        h, cfg = self._h, self._h._cfg
        geo = self._seat_geo()
        if geo is None or abs(geo[2]) > cfg.bay_seat_heading_max_rad or not -0.05 <= geo[0] <= cfg.bay_seat_tol_m:
            return False
        pct = getattr(h._battery, "percent", None)
        h._last_event = "docked, charge NOT confirmed: LiDAR-confirmed straight seat (%.3f m out, %.1f deg), battery %s: staying in the lane" % (
            geo[0], math.degrees(geo[2]), "%.0f %%" % pct if pct is not None else "unknown")
        h._uncharged_v0 = getattr(h._battery, "voltage", None)
        h._charge_unconfirmed = True
        h._mark_docked()
        if pct is not None and pct < cfg.bay_person_call_percent:
            h._call_person("battery %.0f %% and no charge evidence" % pct)
        return True

    def _seat_blocked(self, now: float) -> bool:
        """SETTLING, from the LiDAR seat check of the stopped robot: True = handled (failed, retried, or docked)."""
        h, cfg = self._h, self._h._cfg
        geo = self._seat_geo()
        if geo is None:
            return False
        if abs(geo[2]) > cfg.bay_seat_heading_max_rad:
            h._retry("bay seated skewed %.1f deg at x %.2f m (limit %.1f deg)" % (math.degrees(geo[2]), geo[0], math.degrees(cfg.bay_seat_heading_max_rad)))
            return True
        if geo[0] > cfg.bay_seat_tol_m:
            # the LiDAR puts the stopped robot well short of the stop face: the body is held, no charge will come
            h._retry("bay blocked short of the stop face (%.3f m out, seated within %.3f m)" % (geo[0], cfg.bay_seat_tol_m))
            return True
        percent = getattr(h._battery, "percent", None)
        if percent is not None and percent >= cfg.bay_full_battery_percent:
            # A full pack does not rise in voltage: the LiDAR-confirmed straight seat is the evidence.
            h._last_event = "docked without charge evidence: LiDAR-confirmed seat (%.3f m out, %.1f deg), battery %.0f %%" % (
                geo[0], math.degrees(geo[2]), percent)
            h._uncharged_v0 = getattr(h._battery, "voltage", None)         # watched while DOCKED: a falling pack warns
            h._charge_unconfirmed = True
            h._mark_docked()
            return True
        return False

    def _corridor_view(self) -> bool:
        raw = self._h._detector.relative_pose() if self._h._detector is not None else None
        return raw is not None and not raw.lateral_measured

    def scan_request(self) -> Optional[tuple]:
        """CORE 가 LiDAR 콜백에서 묻는다(락 없음): 기준 스캔을 가진 칸이 자세를 기다리면 (요청 번호, 스캔)을 한 번 내준다.
        세 때: 칸 줄 판정, 정착 크리프 뒤 진입 가드(정지 중 새로 잰다), SETTLING 안착 확인."""
        h = self._h
        if self._req_open is not None and h.now() - self._req_t > h._cfg.bay_req_timeout_s:
            # an open request that never got an answer (a matching thread that died or starved) must not block every later one
            h._last_event = "LiDAR request %s (%s) timed out after %.1f s: asking again" % (self._req_open, self._req_kind, h.now() - self._req_t)
            self._req_open = None
        if (h.phase is DockPhase.ACQUIRING and self._align is not None and self._has_reference() and self._req_open is None
                and h.now() - self._ap_ask_at >= h._cfg.bay_lidar_ask_s):
            self._ap_ask_at = h.now()
            return self._open_request(getattr(h._dock, "metadata", {}).get("reference_scan"), "alignpose",
                                      self._near(self._row_pose))
        if (((h.phase is DockPhase.ACQUIRING and not self._crept) or h.phase is DockPhase.BACKOFF) and self._in_row and self._has_reference()
                and self._req_open is None
                and (self._row_pose is None or h.now() - self._row_pose[3] > h._cfg.bay_row_pose_fresh_s / 2)
                and h.now() - self._ap_ask_at >= h._cfg.bay_lidar_ask_s):
            self._ap_ask_at = h.now()                        # a fresh bay pose before the creep (the answer feeds _row_pose)
            return self._open_request(getattr(h._dock, "metadata", {}).get("reference_scan"), "rowpose", self._near(self._row_pose))
        if self.ls_ask(h.now()):
            ref = getattr(h._dock, "metadata", {}).get("reference_scan")
            return self._open_request(ref, "align", self._near(self._row_pose))
        turn = self._tw_ask(h.now())                       # an in-place turn being watched (no reference scan needed)
        if turn is not None:
            return turn
        dock = h._dock
        ref = getattr(dock, "metadata", {}).get("reference_scan") if dock is not None else None
        if not isinstance(ref, dict):
            return None
        if h.phase is DockPhase.SETTLING and not self._seat_asked:
            # stopped for a while: where is the robot against the stop face (the stored seated scan)?
            if h.now() - h._phase_since < h._cfg.bay_seat_check_delay_s or h.now() - self._seat_ask_at < 1.0:
                return None
            self._seat_asked, self._seat_ask_at = True, h.now()
            self._seat_tries += 1
            return self._open_request(ref, "seat", self._near(self._row_pose) or (0.0, 0.0, 0.0))     # seated: close to the reference itself
        if h.phase is DockPhase.ACQUIRING and self._find_since is not None and not self._find_asked:
            if self._fh_verify and h.now() - self._find_since < h._cfg.bay_seat_check_delay_s:
                return None                      # after the turn: stand still first, the scan must not catch it moving
            self._find_asked = True
            return self._open_request(ref, "find")
        if h.phase is DockPhase.ACQUIRING and self._entry_since is not None and not self._entry_asked:
            if h.now() - self._entry_since < h._cfg.bay_seat_check_delay_s:
                return None                  # stopped after the creep first: the scan must not catch the body moving
            self._entry_asked = True
            return self._open_request(ref, "entry")
        if self._zone != "check" or self._scan_asked:
            return None
        self._scan_asked = True
        return self._open_request(ref, "zone")

    def tracking(self) -> bool:
        """Inside the row the pose is TRACKED from the last accepted pose; lost after bay_track_lost_s without one (back to first acquisition)."""
        rp = self._row_pose
        return rp is not None and self._h.now() - rp[3] <= self._h._cfg.bay_track_lost_s

    def _track_seed(self):
        """The last accepted pose carried by the odometry travel since (reverse in ALIGNING, forward in a reseat), bay frame (x, y, heading)."""
        rp, h = self._row_pose, self._h
        travel = max(0.0, abs(h.executor.travelled_m()) - rp[4]) if h.executor is not None and len(rp) > 4 else 0.0
        sign = -1.0 if h.phase is DockPhase.ALIGNING else 1.0 if h.phase is DockPhase.BACKOFF else 0.0
        return rp[0] + sign * travel, -rp[1], rp[2]

    def _open_request(self, ref: dict, kind: str, near=None) -> tuple:
        self._req_seq += 1
        self._req_kind, self._req_open, self._req_t, self._req_track = kind, self._req_seq, self._h.now(), False
        if kind in ("align", "alignpose", "rowpose", "seat") and self.tracking():
            self._req_track = True                   # local ICP from the carried pose, no alias seeds, no margin gate
            return self._req_seq, ref, "track", self._track_seed()
        if near is not None:                         # seed the ICP at the last good pose: a few runs instead of 36 (the main thread can be 85 % busy)
            return self._req_seq, ref, "near", near
        return self._req_seq, ref

    def _near(self, pose):
        """(x, y, heading) of a stored (x, lateral, heading, ...) pose for the ICP seed, or None."""
        return None if pose is None else (pose[0], -pose[1], pose[2])

    def note_scan_match(self, match, at: float, error: Optional[str] = None, request_id: Optional[int] = None) -> None:
        """scan_request 의 답(BayScanPose 또는 None = 못 맞춤). 열린 요청 번호와 다르면(늦은 답) 버린다."""
        if request_id is None or request_id != self._req_open:
            if request_id is not None:
                self._h._last_event = "LiDAR answer dropped: request %s is not the open one (%s): late" % (request_id, self._req_open)
            return
        self._req_lat = float(at) - self._req_t
        self._track_why, self._ans_track = None, self._req_track
        if self._req_track:
            why = self._track_gate(match)
            if why is not None:
                self._track_why = "tracked pose: " + why
                self._h._last_event = "LiDAR pose dropped (tracked): " + why
                match = None
        if (not self._req_track and match is not None and self._req_kind in ("zone", "entry", "find", "rowpose", "alignpose", "seat")
                and math.isfinite(match.margin) and match.margin < self._h._cfg.bay_scan_margin_min):
            # case I first acquisition (x <= 0.20): the global margin is ~0.2 in the row of self-similar bays; the rear gap and the window decide instead
            if self._first_acquisition(match, float(at)) is None:
                match = dataclasses.replace(match, margin=1.0)
        fit = scan_fit_pose(match, self._h._cfg)
        if fit is not None:
            travel = abs(self._h.executor.travelled_m()) if self._h.executor is not None else 0.0
            self._row_pose = (fit[0], fit[1], fit[2], float(at), travel)      # + the odometry travel then (a forward move since is added by the reseat)
        kind, self._req_open = self._req_kind, None
        if kind == "seat":
            self._seat_match = (match, float(at))
            why = pose_gate(match, self._h._cfg, self._h._type().staging_offset_m)
            if why is not None:
                self._h._last_event = "seat LiDAR pose dropped: %s (try %d)" % (why, self._seat_tries)
                if self._seat_tries < self._h._cfg.bay_seat_tries:
                    self._seat_asked = False                 # ask again: one dropped pose must not leave the seat unmeasured
        elif kind == "entry":
            self._entry_match = (match, float(at))
        elif kind == "find":
            self._find_match = (match, float(at))
        elif kind == "alignpose":
            fit = scan_fit_pose(match, self._h._cfg)
            prev = self._align_lp
            if fit is not None and prev is not None and abs(fit[2] - prev[0]) > 0.0873 + 0.3 * max(0.0, float(at) - prev[2]):
                fit = None                  # consecutive align poses may not jump more than 5 deg + the turn rate: not evidence
            if fit is not None:
                self._align_lp = (fit[2], fit[1], float(at))
        elif kind == "align":
            self.ls_note(match, float(at))
        elif kind == "turn":
            self._tw_note(match, float(at), request_id)
        else:
            self._scan_error = error
            self._scan_match = (match, float(at))

    def _track_gate(self, match) -> Optional[str]:
        """Gates of a TRACKED pose (no margin): inliers, heading, and inside the rails the lateral; the jump, lane and rear-gap gates follow in ls_note."""
        cfg = self._h._cfg
        if match is None or not all(math.isfinite(v) for v in (match.x, match.y, match.heading, match.inliers)):
            return "no fit"
        if match.inliers < cfg.bay_track_inlier_min:
            return "inliers %.2f < %.2f" % (match.inliers, cfg.bay_track_inlier_min)
        if abs(match.heading) > cfg.bay_scan_heading_max_rad:
            return "heading %.0f deg" % math.degrees(match.heading)
        if match.x <= cfg.bay_track_rail_x_m and abs(match.y) > cfg.bay_track_rail_lateral_m:
            return "lateral %.0f mm inside the rails (limit %.0f mm)" % (abs(match.y) * 1000.0, cfg.bay_track_rail_lateral_m * 1000.0)
        return None

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
            if verdict.kind == "exit":
                # User rule 2026-11-21: the dock KEEPS the parking lines. The way out (staging 0.32+) passes the bay line in front, and a 180 turn there leaves
                # the lane: a robot in its lane that is skewed or off-centre cannot acquire in place -> stop and say so, never go out to staging.
                verdict = verdict.__class__("manual", "in the lane but not straight/centred enough to reverse in; leaving the lane to stage is not allowed: centre it by hand")
                h._last_event = "lane keeping: " + verdict.reason
            stale = self._map_frame_mismatch(pose) if verdict.kind == "out" else None
            if stale:
                verdict = verdict.__class__("manual", stale)
            self._in_row = verdict.kind in ("acquire", "exit")
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