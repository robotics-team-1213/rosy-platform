"""core_features.docking.bay_phases — 충전 칸 분홍 유도선 접안(`approach="line"`, D-1013).
순서: Nav2 스테이징(교차점, 도크를 정면으로 본다) → TURNING 제자리 180°(오도메트리 상대,
뒤가 칸으로) → ACQUIRING(선 관측 획득 + 캐스터 정착 크립 + 두 번 일치) → ALIGNING(선
가운데·평행 유지하며 후진, 코스트·스캔·점프 게이트, 접촉 3중 판정) → SETTLING(전압 1소스,
D-941 숫자) → DOCKED. 실패는 전진 백오프 뒤 스테이징부터, `max_retries` 뒤 DOCK_FAILED.

선 관측은 선을 가상 도크로 본다(`DockObservation`): x·y = 칸 중심선 멈춤면 가운데의
base_link 상대 위치, yaw = 칸 안쪽 축. `rear_errors` 와 같은 분해(along·lateral·heading)를
쓴다. 소스는 CAMERA_LINE(`bay_line_observer_node`, 다음 단계)이 `dock/observation` 에 싣는다.

끊김은 예측(오도메트리)이 메운다: 프레임은 게이트를 통과할 때만 증거다(점프 게이트 ±2 cm·
5 deg), 무효 프레임은 코스트 예산(0.5–1 s) 안 제어량 유지, 넘으면 정지 후 ±5° 스캔(게이트
우회 재동기화), 실패는 전진 백오프 재시도. 접촉은 진행 멈춤 + 거리 상한 + 진행 발산(오도메트리는
가는데 선 모양이 그대로면 슬립·정지) 3중으로 본다 — 마지막 구간은 발산 검출이 포화해 거리
상한이 유일한 방어다(bay_pit_sim 발견). 캐스터는 180° 회전 뒤 뒤집혀 몸을 비튼다(2026-11-03
조사) — ACQUIRING 의 정착 크립(전진)이 몸통 축으로 정렬해 없앤다(킥 6° 에 0.8 mm → 0.1 mm).

락은 매니저의 것이고 이 단계만의 상태는 여기 둔다(매니저 크기 래칫, D-766). ROS 무의존.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from core_common.protocol.schemas import NavigationState
from core_features.docking.bay_align import BayAlignMixin
from core_features.docking.bay_guards import BayGuardsMixin, entry_ok, heading_gate, rear_blocked, reverse_twist
from core_features.docking.bay_zone import map_offsets
from core_features.docking.bay_lidar_steer import BayLidarSteerMixin
from core_features.docking.bay_centre import BayCentreMixin
from core_features.docking.bay_reseat import BayReseatMixin
from core_features.docking.bay_turn_watch import BayTurnMixin
from core_features.docking.bay_zone_checks import BayZoneChecksMixin
from core_features.docking.bay_zone_phases import BayZoneMixin
from core_features.docking.charging import PackChargeConfirmation
from core_features.docking.model import DockPhase
from core_features.docking.parking import ParkingGains
from core_features.docking.rear_phases import rear_errors

_TURN_GAINS = ParkingGains()
_LOG = logging.getLogger(__name__)


class BayPhases(BayZoneChecksMixin, BayZoneMixin, BayGuardsMixin, BayAlignMixin, BayTurnMixin, BayLidarSteerMixin, BayReseatMixin, BayCentreMixin):
    """The pink guide-line charge bay, under the manager's lock (D-1013)."""

    def __init__(self, host: Any) -> None:
        self._h = host
        # 전압 1소스(D-941 숫자: 20 s 창) — D-27 억제 입력이 아니다.
        self._charging = PackChargeConfirmation(clock=host._clock, window_s=host._cfg.bay_charge_confirm_s)
        self._est: Optional[tuple[float, float]] = None   # (횡, 방위) 추정 — 예측이 메운다
        self._no_obs_s = 0.0
        self._scan_s: Optional[float] = None
        self._resync = False
        self._turn_target: Optional[float] = None
        self._site_verified, self._site_refusal = False, None      # CORE's judgement of the dock command's site_pose_evidence (Nav2 staging allowed only when accepted)
        self._pitin = False                        # this dock run turned at the junction on the LiDAR pose (bay_zone.junction_geometry)
        self._stage_bad: Optional[float] = None           # first tick the arrival heading looked wrong
        self._turn_dir = -1.0                             # fixed turn sense: tray swings downstream
        self._creep_from: Optional[float] = None          # 정착 크립 시작 travelled
        self._crept = False
        self._match: Optional[tuple[float, float]] = None  # 크립 전 관측(두 번 일치용)
        self._travel_cap_m: Optional[float] = None        # 거리 상한 = 진입 잔여 + 여유
        self._progress: Optional[tuple[float, float]] = None
        self._slip: Optional[tuple[float, float]] = None   # (travelled, along) 창 시작
        self._backoff = False
        self._last_tick: Optional[float] = None
        self._fleet_cue: Optional[tuple[float, dict]] = None
        # 칸 줄 안 시작(bay_zone.py): None | "check"(선 관측 기다려 판정) | "exit"(곧은 전진)
        self._zone: Optional[str] = None
        self._zone_checked = False      # "out" 판정 직후 한 번은 Nav2 스테이징으로 보낸다
        self._exit_m = 0.0
        self._init_scan()                              # LiDAR bay pose requests (bay_zone_phases.py)
        # 몸 스캔(짐칸 포함 회전 판정, 앞 여유): (rotation_block, front_gap, rear_gap, at)
        self._body: Optional[tuple] = None
        self._init_guards()
        self._init_align()
        self._init_tw()
        self._init_ls()
        self._init_reseat()
        self._init_centre()
        self._facing_bay = False                   # the last LiDAR pose had the nose toward the bay: a retry back-off stays still

    # --- 매니저가 부르는 자리 ---------------------------------------------------

    def active(self) -> bool:
        dock_type = self._h._type()
        return dock_type is not None and dock_type.approach == "line"

    def observe_fleet_docking(self, cue: Optional[dict], now: Optional[float] = None) -> bool:
        """관제(Fleet)가 추출한 충전소 서브픽셀 중심선 평가(offset_m, yaw_err_deg, to_end_m, verdict) 수신."""
        with self._h._lock:
            if cue is None or not isinstance(cue, dict) or not self.active():
                return False
            at = self._h.now() if now is None else float(now)
            self._fleet_cue = (at, dict(cue))
            return True

    def docked_confirm(self, status, voltage, now):
        """DOCKED 유지 중 충전 확인: 칸은 여기 전압 1소스, 나머지는 후진형 규칙에 위임."""
        if status is not None:
            return self._h._charging.update(status, voltage, now=now), self._h._charging
        if self.active():
            return self._charging.observe(self._h._battery, now=now), self._charging
        return self._h._rear_phases.docked_confirm(status, voltage, now)

    def note_body_scan(self, rotation_block: Optional[str], front_gap_m: Optional[float],
                       rear_gap_m: Optional[float], at: float) -> None:
        """CORE 가 LiDAR 한 장마다 넣는다: 짐칸 포함 제자리 회전 판정(None = 비어 있음)과 앞뒤 여유."""
        self._body = (rotation_block, front_gap_m, rear_gap_m, float(at))

    def _body_fresh(self, now: float) -> Optional[tuple]:
        if self._body is None or now - self._body[3] > self._h._cfg.bay_scan_fresh_s:
            return None
        return self._body

    def _forward_block(self, now: float, since: float, step: Optional[float] = None, facing_ok: bool = False) -> Optional[str]:
        """곧은 전진(칸 줄 나가기·재시도 후퇴·정착 크립) 전 앞 확인: None = 가도 된다, "wait" = 아직
        판정 없음(멈춰 기다림), 그 밖 = 실패 사유. 점이 없거나 앞 빔이 무응답이면 비어 있는 것이 아니다."""
        if not facing_ok and self._facing_recent(now):
            return "the last LiDAR bay pose has the nose toward the bay: no forward move in the row"      # settle creep / retry back-off / lane exit drive at the bay
        body = self._body_fresh(now)
        if body is not None and body[3] < since:
            body = None
        if body is None:
            return "wait" if now - since <= self._h._cfg.bay_scan_wait_s else "no fresh body scan"
        if body[0] in ("empty", "unknown"):
            return "LiDAR cannot vouch for the way ahead (%s)" % body[0]
        if body[1] is not None and body[1] < self._h._cfg.bay_exit_front_gap_m:
            return "something ahead within %.2f m" % self._h._cfg.bay_exit_front_gap_m
        return self._row_forward_reason(step, now, since)

    def zone_entry(self) -> bool:
        """스테이징 전에 칸 줄 안인지 본다(시작·재시도 모두). 판정을 맡으면 True."""
        if not self.active():
            return False
        if self._zone_checked:
            self._zone_checked = False
            return False
        h = self._h
        self._reset_line_state()
        self._row_pose = None if h._retries == 0 and h._reseats == 0 else self._row_pose      # a fresh dock starts without an old pose
        if h._retries == 0 and h._reseats == 0:
            self._pitin = False
            self._cen_n = 0
            self._facing_bay = False
        if h._detector is None and h._detector_factory is not None and h._dock is not None:
            h._detector = h._detector_factory(h._dock, h._type())
        if h._detector is not None:
            h._detector.start(h._dock)        # a retry's backoff stopped it
        if h.executor is not None:
            h.executor.stop()
        self._zone = "check"
        self._req_open = None                          # close the open request before the next ask is allowed
        self._scan_asked, self._scan_match, self._scan_error, self._bay_lateral = False, None, None, None
        h._enter(DockPhase.BACKOFF)
        return True

    def leave_sign(self) -> float:
        """칸 언도킹은 전진(도크가 뒤에 있다). 나머지는 후진형 규칙에 위임."""
        return 1.0 if self.active() else self._h._rear_phases.leave_sign()

    def tick(self, phase, now: float) -> bool:
        """칸형이면 이 단계를 맡고 True."""
        if not self.active():
            return False
        if phase is DockPhase.BACKOFF and self._zone is not None:
            self._tick_zone(now)
        elif phase is DockPhase.STAGING:
            self._tick_staging(now)
        elif phase is DockPhase.TURNING:
            self._tick_turning(now)
        elif phase is DockPhase.ACQUIRING:
            self._tick_acquiring(now)
        elif phase is DockPhase.ALIGNING:
            self._tick_aligning(now)
        elif phase is DockPhase.SETTLING:
            self._tick_settling(now)
        elif phase is DockPhase.BACKOFF:
            self._tick_backoff(now)
        self._last_tick = now
        return True

    # --- 단계 -----------------------------------------------------------------

    def _drive(self, linear: float, angular: float) -> None:
        self._omega = angular
        if self._h.executor is not None:
            self._h.executor.drive(linear, angular)

    def _stop(self) -> None:
        self._omega = 0.0
        if self._h.executor is not None:
            self._h.executor.stop()

    def _observation(self):
        obs = self._h._detector.relative_pose() if self._h._detector is not None else None
        if obs is None or obs.lateral_measured:
            return obs
        # Only the corridor line was seen: heading and along are measured, the lateral is not. Fill it from
        # the running estimate, else from the map pose; never from the payload's placeholder (2026-11-18).
        lateral = self._est[0] if self._est is not None else self._bay_lateral
        if lateral is None:
            pose = self._h._pose_provider()
            if pose is None or self._h._dock is None:
                return None
            lateral = self._bay_lateral if self._bay_lateral is not None else map_offsets(pose, self._h._dock)[1]
        along, _, _ = rear_errors(obs)
        ax, ay = math.cos(obs.yaw), math.sin(obs.yaw)
        return obs.model_copy(update={"x": along * ax + lateral * ay, "y": along * ay - lateral * ax})

    def _tick_staging(self, now: float) -> None:
        """스테이징(교차점) 도착 → 선반 180° 회전부터. Nav2 실패는 후진형과 같은 재시도."""
        h = self._h
        if h._nav_state is not NavigationState.ARRIVED:
            h._tick_staging(now)
            return
        pose = self._odometry()
        if pose is None:
            h._fail("bay odometry unavailable")
            return
        self._stop()
        mp = h._pose_provider()
        # The staging goal faces the bay: a nose far off that axis is a wrong-way arrival, and the
        # line observer would read it as normal (it forces the axis to -x), so refuse before turning.
        if mp is None or self._stage_heading_bad(mp):
            # One noisy or missing pose must not end a first try: stand still and look again for a while.
            self._stage_bad = now if self._stage_bad is None else self._stage_bad
            if now - self._stage_bad >= h._cfg.bay_stage_recheck_s:
                self._stage_bad = None
                h._fail("bay staging arrival heading off the bay axis")
            return
        self._stage_bad = None
        self._start_staging_turn(now, pose)

    def _start_staging_turn(self, now: float, pose, bay_heading=None) -> None:
        """The 180 turn at the staging point (also used by a pit-in arrival at the junction, which has no Nav2 leg); the turn is watched by bay_turn_watch."""
        h = self._h
        self._reset_line_state()
        if h._retries == 0 and h._reseats == 0:
            self._seen.clear()           # a fresh dock; a guard failure always counts a retry or reseat
            self._align_n = 0
            self._tw_flipped = False       # a fresh dock may flip its staging turn once again
        self._turn_dir = -math.copysign(1.0, h._cfg.bay_downstream_sign) if h._cfg.bay_downstream_sign else 0.0
        if h._cfg.bay_turn_first_dir:
            self._turn_dir = math.copysign(1.0, h._cfg.bay_turn_first_dir)       # per-robot config: +1 ccw, -1 cw (0: the downstream rule)
        elif self._turn_bad_dir and self._turn_dir == self._turn_bad_dir:
            self._turn_dir = -self._turn_dir                                      # learned: this robot's body did not follow that sense
        self._facing_bay = False                   # after the turn the rear is toward the bay
        self._last_lidar = None                    # the turn changes the heading: the old facing-bay memory no longer holds
        ang = math.pi
        if bay_heading is not None:
            self._pitin = True
            # pit-in: turn to the LiDAR bay heading 0 (rear to the bay), not a fixed 180 (b8xy: it stood 13.5 deg short of 180 and ended -13 deg); at most 180, the rest is
            # left to the in-place heading align the strict pit-in entry window triggers
            ang = min(math.pi, (-(self._turn_dir or 1.0) * bay_heading) % math.tau)
        self._turn_target = pose[2] + (self._turn_dir or 1.0) * ang
        self._tw_start(pose[2], now, want=ang)
        h._enter(DockPhase.TURNING)

    def _tick_acquiring(self, now: float) -> None:
        """선 포획 + 캐스터 정착 크립 + 두 번 일치. 크립 없이는 후진 첫 cm 에 킥이 온다."""
        h, cfg = self._h, self._h._cfg
        if self._align is not None:
            self._tick_heading_align(now)
            return
        along, lateral, heading = self._line_errors()
        seen = (along, lateral, heading) != (None, None, None)
        if not self._crept and self._find_step(now, seen):
            return
        if self._crept:
            if (along, lateral, heading) == (None, None, None):
                if h._last_seen_at is None or now - h._last_seen_at > cfg.detector_lost_grace_s:
                    self._stop()
                    h._retry("bay line lost after the settle creep")
                return
            # a reference-scan dock judges lateral and heading by the LiDAR pose (entry window below): the camera heading is wrong at this site
            # (-20 deg on a straight body), so the pre/post-creep camera comparison is not a jump check there; the camera still has to SEE the line
            if self._match is not None and not self._has_reference() and (
                    abs(lateral - self._match[0]) > cfg.bay_gate_jump_m
                    or abs(heading - self._match[1]) > cfg.bay_gate_jump_rad):
                # A frame that does not match the one before the creep is not evidence (the camera line can alternate between
                # the corridor line and a spurious fit): stand still and wait for a matching one; retry only past the grace.
                self._stop()
                if h._last_seen_at is None or now - h._last_seen_at > cfg.detector_lost_grace_s:
                    h._retry("bay line observation jumped after the creep (lat %.0f mm, head %.1f deg vs %.0f mm, %.1f deg)"
                             % (lateral * 1000.0, math.degrees(heading), self._match[0] * 1000.0, math.degrees(self._match[1])))
                return
            h._last_seen_at = now
            camera_lateral = lateral
            got = self._entry_values(now, lateral, heading)
            if got == "stop":
                return
            lateral, heading = got
            if not entry_ok(cfg, lateral, heading) or (self._pitin and abs(heading) > cfg.bay_pitin_entry_heading_rad):
                if self._try_heading_align(now, lateral, heading):
                    return
                # Too far off to converge: never reverse into it. A straight back-off keeps the bearing, so start over.
                self._guard_fail("entry", "entry error outside the window (lat %.0f mm, head %.0f deg)"
                                 % (lateral * 1000.0, math.degrees(heading)), h._fail if self._pitin else h._retry)       # pit-in: no Nav2 staging to retry from
                return
            if self._entrance_blocked(now, along, camera_lateral):
                return
            self._est = (lateral, heading)
            self._no_obs_s = 0.0
            self._blind_s = self._blind_m = 0.0
            self._blind_budget_m = max(0.0, along - cfg.bay_line_view_m) + cfg.bay_blind_margin_m
            if h.executor is not None:
                h.executor.reset_odometry_mark()
                h.executor.set_collision_exemption(True)
            # An unmeasured along is a stand-in, not a distance: no cap until a measured frame sets it.
            self._travel_cap_m = along + cfg.bay_travel_margin_m if self._along_m is not None else None
            self._progress = None
            self._slip = None
            self._gap_hist, self._along_last = [], None
            self._reset_ls()
            h._enter(DockPhase.ALIGNING)
            return
        if (along, lateral, heading) == (None, None, None):
            if now - h._phase_since > cfg.acquire_timeout_s:
                h._retry("bay line not acquired")
            return
        # 첫 포획: 정착 크립 — 전진해 캐스터를 몸통 축으로 정렬하고 다시 본다.
        self._match = (lateral, heading)
        if h.executor is None:
            h._fail("bay executor unavailable")
            return
        if self._creep_from is None:
            h.executor.reset_odometry_mark()
            self._creep_from = 0.0
        if abs(h.executor.travelled_m()) < cfg.bay_settle_creep_m:
            block = self._forward_block(now, h._phase_since, cfg.bay_settle_creep_m)
            if block is not None:
                self._stop()
                if block != "wait":
                    h._fail("bay settle creep: " + block)
                return
            self._drive(h._cfg.undock_speed, 0.0)
            return
        self._stop()
        self._crept = True
        h._last_seen_at = now

    def _tick_aligning(self, now: float) -> None:
        """선 가운데·평행 유지하며 후진. 관측은 게이트를 통과할 때만 증거다."""
        h, cfg = self._h, self._h._cfg
        if h.executor is None:
            h._fail("bay executor unavailable")
            return
        dt = now - self._last_tick if self._last_tick is not None else 0.0
        self._note_rear_gap(now)
        self._ingest_observation(dt)
        if self._apply_fleet_evaluation(now) is not None:
            return
        speed = cfg.bay_reverse_speed
        steer = self._lidar_steer(now)
        if steer == "stop":
            return
        if steer == "use":
            self._scan_s, self._no_obs_s, self._resync = None, 0.0, False      # the camera line is not what steers here
            if self._rail_judge(now):
                return
        if self._scan_s is not None:
            # 스캔은 정지 상태에서 천천히 ±bay_scan_rad — 회전 중 병진이 흐르면 눈감고 접촉한다.
            # 주기: +폭 0.25 s → 정지 → −2×폭 0.25 s → 정지(대칭 복귀), 2.5 s 주기.
            self._scan_s += dt
            self._stop()
            phase_t = self._scan_s % 2.5
            rate = cfg.bay_scan_rad / 0.25
            if phase_t < 0.25:
                self._drive(0.0, rate)
            elif 1.25 <= phase_t < 1.5:
                self._drive(0.0, -2.0 * rate)
            if self._est is not None and self._no_obs_s == 0.0:
                self._scan_s = None
            elif self._scan_s > cfg.bay_scan_s:
                self._scan_s = None
                h._retry("bay line lost during alignment")
            return
        if self._no_obs_s > cfg.bay_coast_stop_s:
            self._scan_s = 0.0
            self._resync = True
            return
        if cfg.bay_coast_slow_s < self._no_obs_s:
            speed = 0.02
        if steer != "use" and self._blind_lateral(dt, speed):
            return
        body = self._body_fresh(now)
        if body is not None and rear_blocked(cfg, body[2], self._rear_along if steer == "use" else self._along_m):
            self._guard_fail("rear", "LiDAR sees something in the bay before the stop face", h._retry)
            return
        if self._lidar_seated(now):
            self._begin_settling()               # the LiDAR puts the rear at the stored seated gap: the real stop
            return
        lateral, heading = self._est
        angular = reverse_twist(cfg, lateral * (cfg.bay_lidar_lateral_gain_mult if steer == "use" else 1.0), heading)
        if steer == "use":
            angular = max(-cfg.bay_rail_max_angular, min(cfg.bay_rail_max_angular, angular))
        if steer == "use" and self._lidar_stalled(now):
            self._stop()
            h._retry("bay reverse stalled in the rails (LiDAR rear gap unchanged over %.1f s while reversing): held" % cfg.bay_lidar_stall_s)
            return
        self._drive(-speed, angular)
        # 추정은 오도메트리 명령으로 전파(프레임 사이를 메운다)
        self._est = (lateral + speed * math.sin(heading) * dt,
                     _wrap(heading + angular * dt))
        travelled = abs(h.executor.travelled_m())
        if self._contact(travelled, now):
            return
        if self._travel_cap_m is not None and travelled > self._travel_cap_m + 0.10:
            self._stop()
            h._retry("bay alignment overran the travel cap")
            return

    def _ingest_observation(self, dt: float) -> None:
        """게이트가 증거를 판다: 점프는 이웃 칸 선이나 잡음, 통과만 관측이다."""
        h, cfg = self._h, self._h._cfg
        along, lateral, heading = self._line_errors()
        if self._obs_age > cfg.bay_obs_max_age_s:
            along = lateral = heading = None       # too old to steer by, and not worth widening the gate for
        if (along, lateral, heading) != (None, None, None):
            if (not self._resync and self._est is not None and (
                    abs(lateral - self._est[0]) > cfg.bay_gate_jump_m
                    or abs(heading - self._est[1]) > heading_gate(cfg, self._omega, self._obs_age))):
                self._no_obs_s += dt          # 물리적으로 불가능한 점프: 무관측
            else:
                self._est, self._no_obs_s, self._resync = (lateral, heading), 0.0, False
                h._last_seen_at = h.now()
                if self._along_m is None:
                    self._slip = None            # a stand-in along never moves: not slip evidence
                    return
                travelled = abs(h.executor.travelled_m()) if h.executor is not None else None
                if travelled is not None and self._travel_cap_m is None:
                    self._travel_cap_m = travelled + along + cfg.bay_travel_margin_m   # first measured along
                if self._slip is not None and travelled is not None:
                    t0, along0 = self._slip
                    # 창은 선 모양이 움직일 때만 재앵커 — 정지한 그림에서 오도메트리가
                    # 3 cm 넘게 쌓이면 슬립·정지다(시뮬의 고정 가장자리 회귀와 같은 근거).
                    if abs(along0 - along) >= 0.01:
                        self._slip = (travelled, along)
                    elif travelled - t0 > 0.03:
                        self._slip = ("contact", 0.0)
                        return
                elif travelled is not None:
                    self._slip = (travelled, along)
        else:
            self._no_obs_s += dt

    def _contact(self, travelled: float, now: float) -> bool:
        """접촉 3중 판정: 진행 멈춤 · 슬립 발산 · 거리 상한."""
        h, cfg = self._h, self._h._cfg
        if self._slip is not None and self._slip[0] == "contact":
            if self._lidar_moving(now):
                self._slip = None                  # the line's shape stood still but the LiDAR sees the body going back
            else:
                self._begin_settling()
                return True
        last, since = self._progress or (travelled, now)
        if travelled - last >= cfg.contact_progress_m:
            self._progress = (travelled, now)
        elif now - since >= cfg.contact_stall_s:
            self._begin_settling()
            return True
        if self._travel_cap_m is not None and travelled >= self._travel_cap_m and not self._lidar_moving(now):
            self._begin_settling()
            return True
        return False

    def _begin_settling(self) -> None:
        h = self._h
        if self._contact_off_axis():
            return
        self._stop()
        if h.executor is not None:
            h.executor.set_collision_exemption(False)
        self._charging.begin_settling(h._battery)
        self._req_open = None
        self._seat_asked, self._seat_match, self._seat_tries = False, None, 0
        h._enter(DockPhase.SETTLING)

    def _tick_settling(self, now: float) -> None:
        """전압 1소스(D-941): 멈춘 뒤 2 s 기준, 20 s 안 +0.05 V 상승."""
        h, cfg = self._h, self._h._cfg
        cue = self._fresh_fleet_cue(now)
        if cue is not None and cue.get("verdict") == "RETRY_FROM_P":
            h._retry("fleet bay contact misaligned")
            return
        if self._seat_blocked(now):
            return
        if self._charging.observe(h._battery, now=now, since_settled=now - h._phase_since,
                                  baseline_delay_s=cfg.bay_settle_baseline_s, rise_v=cfg.bay_charge_rise_v):
            h._mark_docked()
            return
        if now - h._phase_since > cfg.settle_timeout_s + cfg.bay_charge_confirm_s:
            if self._settle_unconfirmed():
                return
            h._retry("no charge after bay contact")

    # --- 보조 -----------------------------------------------------------------

    def _fresh_fleet_cue(self, now: float) -> Optional[dict]:
        if self._fleet_cue is None:
            return None
        at, cue = self._fleet_cue
        if not (0.0 <= now - at <= self._h._cfg.detector_lost_grace_s):
            return None
        return cue

    def _apply_fleet_evaluation(self, now: float) -> Optional[str]:
        """관제 중심선 평가 반영: RETRY_FROM_P 재시도, CONTACT_STOP 정지, BACKING_* 실시간 조향 보정."""
        cue = self._fresh_fleet_cue(now)
        if cue is None:
            return None
        verdict = cue.get("verdict")
        if verdict == "RETRY_FROM_P":
            self._stop()
            self._h._retry("fleet bay centerline misaligned")
            return "retry"
        if verdict == "CONTACT_STOP":
            self._begin_settling()
            return "contact"
        if verdict in ("BACKING_ALIGNED", "BACKING_DRIFT"):
            f_lat = float(cue.get("offset_m", 0.0))
            f_head = math.radians(float(cue.get("yaw_err_deg", 0.0)))
            w = self._h._cfg.bay_fleet_eval_weight
            if self._est is not None and self._no_obs_s == 0.0:
                lat, head = self._est
                self._est = ((1.0 - w) * lat + w * f_lat, _wrap(head + w * _wrap(f_head - head)))
            else:
                self._est = (f_lat, f_head)
                self._no_obs_s = 0.0
                self._scan_s = None
                self._resync = False
                self._h._last_seen_at = now
        return None

    def _reset_line_state(self) -> None:
        self._est = None
        self._no_obs_s = 0.0
        self._scan_s = None
        self._resync = False
        self._creep_from = None
        self._crept = False
        self._match = None
        self._travel_cap_m = None
        self._progress = None
        self._slip = None
        self._backoff = False
        self._turn_target = None
        self._align = None
        self._find_on, self._find_seen_m = False, None
        self._fleet_cue = None
        self._zone = None
        self._exit_m = 0.0
        self._entry_since, self._entry_asked, self._entry_match = None, False, None
        self._reset_find()
        self._reseat_active = False
        self._reset_ls()                              # the LiDAR-steer state of an earlier attempt must not outlive its ALIGNING
        self._blind_s = self._blind_m = 0.0

    def _odometry(self):
        pose = getattr(self._h.executor, "odometry_pose", None) if self._h.executor else None
        return pose() if callable(pose) else None

    def _line_errors(self):
        observation = self._observation()
        if observation is None:
            self._along_m = None
            return None, None, None
        errors = rear_errors(observation)
        self._along_m = errors[0] if observation.along_measured else None
        self._note_along()
        self._obs_age = max(0.0, self._h.now() - observation.at)
        return errors


def _wrap(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle
