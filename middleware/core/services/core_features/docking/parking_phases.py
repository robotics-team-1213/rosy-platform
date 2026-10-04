"""core_features.docking.parking_phases — 주차형 도크(`approach="pose"`)의 단계.

`DockingManager` 가 기종 설정으로 갈라 쓰는 주차형 경로다 (차선망 미션 3단계):
스테이징 대신 진입 회전(TURNING), 태그가 보일 때까지 주차점 쪽으로
크리프(ACQUIRING), 도크 좌표계 정렬 접근(APPROACHING), 제자리 방위 정렬(ALIGNING),
포즈 정착(SETTLING). 실패 뒤 후진은 거리로 끝나고, 언도킹은 후진 뒤 회전이다.

**상태와 락은 매니저의 것이다.** 이 객체는 자기 락도, 자기 상태도 없다 — 단계
상태(`_tracker`, `_turn_target` …)는 매니저 필드이고, 매니저가 만들고 되돌린다.
모든 진입점은 매니저의 락(RLock) 안에서, 매니저의 틱·명령 경로에서만 불린다.
그래서 호출 순서(estop 먼저, `take_mode` 가 상태 변경보다 먼저, 락 안의 모드
해제)는 매니저 한 곳에서 읽힌다. 순수 법칙과 추정기는 `parking.py` 에 있다.

ROS 무의존. 설계: docs/plans/2026-09-23-lane-network-parking-design.md
"""

from __future__ import annotations

import math
from typing import Any, Optional, Protocol

from core_features.docking.model import DockPhase
from core_features.docking.parking import (
    DockPoseTracker,
    ParkingGains,
    approach_twist,
    reverse_twist,
    robot_in_dock_frame,
    turn_twist,
    wrap,
)


class ParkingHost(Protocol):
    """주차형 단계가 매니저에서 쓰는 전부. `DockingManager` 가 구현한다."""

    executor: Any
    _cfg: Any
    _pose_provider: Any
    _dock: Any
    _detector: Any
    _phase_since: float
    _last_seen_at: Optional[float]
    _next_phase_after_backoff: Any
    # 주차형 단계 상태 — 매니저가 소유한다
    _tracker: Optional[DockPoseTracker]
    _turn_target: Optional[float]
    _after_turn: Optional[str]
    _creep_from: Optional[tuple]
    _creep_done_at: Optional[float]
    _backoff_from: Optional[tuple]

    def _type(self) -> Any: ...
    def _parking(self) -> bool: ...
    def _enter(self, phase: Any) -> None: ...
    def _fail(self, reason: str) -> None: ...
    def _retry(self, reason: str) -> None: ...
    def _reseat(self, reason: str) -> None: ...
    def _begin_acquiring(self) -> None: ...
    def _begin_settling(self) -> None: ...
    def _begin_staging(self) -> None: ...
    def _finish_undock(self) -> None: ...
    def _stop_detector(self) -> None: ...
    def _mark_docked(self) -> None: ...


class ParkingPhases:
    """주차형 단계의 전략. 매니저가 위임하고, 이 객체는 매니저를 통해서만 쓴다."""

    def __init__(self, host: ParkingHost, gains: Optional[ParkingGains] = None) -> None:
        self._h = host
        self.gains = gains or ParkingGains()

    # --- 도구 -----------------------------------------------------------------

    def odometry(self) -> Optional[tuple]:
        source = getattr(self._h.executor, "odometry_pose", None)
        pose = source() if callable(source) else None
        return None if pose is None else tuple(float(v) for v in pose)

    def _drive(self, linear: float, angular: float) -> None:
        if self._h.executor is not None:
            self._h.executor.drive(linear, angular)

    def _stop(self) -> None:
        if self._h.executor is not None:
            self._h.executor.stop()

    def _aim(self) -> float:
        """주차점을 겨누는 맵 방위. 가까우면 도크 yaw — 맵은 대략까지다."""
        h = self._h
        pose = h._pose_provider()
        if pose is None:
            return h._dock.yaw
        dx, dy = h._dock.x - float(pose[0]), h._dock.y - float(pose[1])
        if math.hypot(dx, dy) <= h._cfg.aim_min_m:
            return h._dock.yaw
        return math.atan2(dy, dx)

    def _near_spot(self, pose) -> bool:
        """맵 포즈가 도크 축 위에서 주차점 aim_min_m 앞까지 왔는가."""
        if pose is None:
            return False
        dock = self._h._dock
        along = ((dock.x - float(pose[0])) * math.cos(dock.yaw)
                 + (dock.y - float(pose[1])) * math.sin(dock.yaw))
        return along <= self._h._cfg.aim_min_m

    def _observe(self, now: float) -> bool:
        """오도메트리를 기록하고, 새 관측이면 추정기를 다시 고정한다. True 는 새 고정뿐이다 —
        같은 프레임이 반복되면 도크를 "다시 본" 것이 아니다 (_last_seen_at 이 갱신되면
        관측이 끊겨도 유예가 끝나지 않는다)."""
        h = self._h
        h._tracker.record_odometry(now, self.odometry())
        observation = h._detector.relative_pose() if h._detector else None
        if observation is None:
            return False
        return h._tracker.observe(observation)

    # --- 회전 (진입, 언도킹 뒤) --------------------------------------------------

    def begin_entry_turn(self) -> None:
        self.begin_turn(self._aim(), "acquire")

    def begin_turn(self, target_map_yaw: float, after: str) -> None:
        """맵 방위 `target_map_yaw` 로 제자리 회전. 상대각은 맵 포즈로 한 번 재고,
        수행은 오도메트리로 한다 — 회전 중 맵 포즈가 튀어도 흔들리지 않는다."""
        h = self._h
        h._after_turn = after
        pose, odom = h._pose_provider(), self.odometry()
        if pose is None or odom is None:
            h._fail("no pose for the turn")
            return
        relative = wrap(target_map_yaw - float(pose[2]))
        h._turn_target = wrap(odom[2] + relative)
        if h._tracker is None and h._parking():
            h._tracker = DockPoseTracker(h._type().tag_offset_m)
        h._enter(DockPhase.TURNING)
        if abs(relative) <= self.gains.turn_tolerance_rad:
            self._finish_turn()

    def begin_undock_turn(self) -> bool:
        """후진을 마친 주차형이면 차선 방향으로 돈다 (도크 yaw + undock_turn_rad)."""
        dock_type = self._h._type()
        if dock_type is None or not dock_type.undock_turn_rad:
            return False
        self.begin_turn(self._h._dock.yaw + dock_type.undock_turn_rad, "undocked")
        return True

    def tick_turning(self, now: float) -> None:
        h = self._h
        odom = self.odometry()
        if odom is None:
            h._fail("odometry lost during the turn")
            return
        if h._tracker is not None:
            # 회전 끝에 찍힌 프레임이 짝지을 오도메트리를 갖도록 기록한다.
            h._tracker.record_odometry(now, odom)
        angular, done = turn_twist(wrap(h._turn_target - odom[2]), self.gains)
        if done:
            self._stop()
            self._finish_turn()
            return
        if now - h._phase_since > h._cfg.turn_timeout_s:
            h._fail("turn timed out")
            return
        self._drive(0.0, angular)

    def _finish_turn(self) -> None:
        if self._h._after_turn == "undocked":
            self._h._finish_undock()
        else:
            self._h._begin_acquiring()

    # --- 획득·접근·정렬·정착 -----------------------------------------------------

    def begin_acquiring(self) -> None:
        h = self._h
        if h._tracker is None:
            h._tracker = DockPoseTracker(h._type().tag_offset_m)
        h._tracker.reset()
        h._creep_from = self.odometry()
        h._creep_done_at = None

    def tick_acquiring(self, now: float) -> None:
        h = self._h
        if self._observe(now) and h._tracker.anchored_at is not None:
            h._enter(DockPhase.APPROACHING)
            h._last_seen_at = now
            if h.executor is not None:
                h.executor.set_collision_exemption(True)
            return
        if now - h._phase_since > h._cfg.acquire_timeout_s:
            h._retry("dock not acquired")
            return
        creep = h._type().acquire_creep_m
        odom = self.odometry()
        travelled = (math.dist(odom[:2], h._creep_from[:2])
                     if odom is not None and h._creep_from is not None else creep)
        if now - h._phase_since < h._cfg.acquire_look_s:
            self._stop()
            return
        pose = h._pose_provider()
        if travelled < creep and not self._near_spot(pose):
            # 태그가 아직 시야 밖이다 (진입점에서는 태그 윗단이 잘린다). 주차점을
            # 겨누고 기어간다 — 맵 포즈가 없으면 방위를 유지한다. 재시도가 거듭돼도
            # 맵 위의 주차점을 넘어가며 기지는 않는다.
            error = 0.0 if pose is None else wrap(self._aim() - float(pose[2]))
            limit = self.gains.max_angular
            self._drive(self.gains.creep_speed,
                        max(-limit, min(limit, self.gains.gain_heading * error)))
            return
        self._stop()
        if h._creep_done_at is None:
            h._creep_done_at = now
        elif now - h._creep_done_at > h._cfg.creep_exhausted_s:
            h._retry("dock not acquired")

    def tick_approaching(self, now: float) -> None:
        h = self._h
        if self._observe(now):
            h._last_seen_at = now
        if h._last_seen_at is None or \
                now - h._last_seen_at > h._cfg.detector_lost_grace_s:
            h._retry("dock lost during approach")
            return
        if now - h._phase_since > h._cfg.approach_timeout_s:
            h._retry("approach timed out")
            return
        pose = h._tracker.pose(self.odometry())
        if pose is None:
            h._retry("odometry lost during approach")
            return
        linear, angular, arrived = approach_twist(pose, self.gains)
        if arrived:
            self._stop()
            h._enter(DockPhase.ALIGNING)
            return
        self._drive(linear, angular)

    def tick_aligning(self, now: float) -> None:
        h = self._h
        self._observe(now)
        pose = h._tracker.pose(self.odometry())
        if pose is None or now - h._phase_since > h._cfg.align_timeout_s:
            h._reseat("heading not aligned at the spot")
            return
        angular, done = turn_twist(-pose[2], self.gains)
        if done:
            h._begin_settling()
            return
        self._drive(0.0, angular)

    def tick_settling(self, now: float, dock_type) -> None:
        h = self._h
        self._stop()
        h._tracker.record_odometry(now, self.odometry())
        if now - h._phase_since < h._cfg.settle_still_s:
            return
        observation = h._detector.relative_pose() if h._detector else None
        if observation is not None and \
                observation.at >= h._phase_since + h._cfg.settle_still_s / 2.0:
            ex, ey, heading = robot_in_dock_frame(
                observation.x, observation.y, observation.yaw, dock_type.tag_offset_m)
            if (abs(ex) <= dock_type.pose_tolerance_m
                    and abs(ey) <= dock_type.pose_tolerance_m
                    and abs(heading) <= dock_type.pose_tolerance_rad):
                h._stop_detector()
                h._mark_docked()
                return
            h._tracker.observe(observation)
            h._reseat(f"parked out of tolerance (ex={ex:+.3f} ey={ey:+.3f} "
                      f"heading={math.degrees(heading):+.1f} deg)")
            return
        if now - h._phase_since > h._cfg.settle_timeout_s:
            h._reseat("no tag at the spot")

    # --- 후진 -----------------------------------------------------------------

    def tick_backoff(self, now: float, distance: float) -> None:
        """거리로 끝나는 후진. 벽 앞 주차면은 시간 기준 후진(0.16 m)이 벽에 닿을 수
        있다. 추정이 있으면 횡오차를 줄이는 쪽으로 조향한다."""
        h = self._h
        odom = self.odometry()
        travelled = (math.dist(odom[:2], h._backoff_from[:2])
                     if odom is not None and h._backoff_from is not None else distance)
        if travelled < distance and now - h._phase_since < h._cfg.backoff_timeout_s:
            pose = None
            if h._tracker is not None:
                h._tracker.record_odometry(now, odom)
                pose = h._tracker.pose(odom)
            if pose is not None:
                self._drive(*reverse_twist(pose, self.gains))
            else:
                self._drive(-self.gains.reverse_speed, 0.0)
            return
        self._stop()
        if h._next_phase_after_backoff is DockPhase.ACQUIRING:
            h._begin_acquiring()
        else:
            h._begin_staging()
