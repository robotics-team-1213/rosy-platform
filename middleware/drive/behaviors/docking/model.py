"""core_features.docking.model — 도킹 상태머신의 단계·모션 계약·설정.

`manager` 와 `parking_phases` 가 함께 쓰는 정의다. `manager` 가 그대로 다시 내보낸다
(`from core_features.docking.manager import DockPhase, DockingConfig`).

ROS 무의존.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol

from core_features.docking.database import Pose2D


class DockPhase(str, enum.Enum):
    """`DOCKING` 안의 내부 단계.

    재시도가 *어디서* 실패했는지 알아야 하기 때문에 존재한다. 도착하지 못한
    것과 도착했는데 전류가 없는 것은 복구 방법이 다르다.
    """

    STAGING = "staging"          # Nav2 로 도크 앞까지
    ACQUIRING = "acquiring"      # 검출기가 도크를 찾는다
    APPROACHING = "approaching"  # 관측 상대 포즈에 서보
    SETTLING = "settling"        # 전류가 흐르기를 기다린다
    CHARGED_HOLD = "charged_hold"  # D-350: 만춫 확인, Fleet/운영자 지시 대기
    BACKOFF = "backoff"          # 실패 후 뒤로 빠져 재시도 준비
    TURNING = "turning"          # 주차형: 제자리 회전 (진입, 언도킹 뒤)
    ALIGNING = "aligning"        # 주차형: 주차점에서 방위만 맞춘다. 후진형: 레일 입구 밖 정렬
    REVERSING = "reversing"      # 후진형: 레일 안 곧은 후진(각속도 0), 접촉에서 멈춘다


class DockingExecutor(Protocol):
    """모션. ros_bridge 가 구현하고 이 계층은 의도만 말한다."""

    def navigate_to(self, pose: Pose2D) -> None: ...
    def cancel_navigation(self) -> None: ...
    def drive(self, linear: float, angular: float) -> None: ...
    def stop(self) -> None: ...
    def set_collision_exemption(self, enabled: bool) -> None: ...
    def travelled_m(self) -> float: ...
    def reset_odometry_mark(self) -> None: ...
    # 주차형만 쓴다 (선택, getattr 로 찾는다): 오도메트리 base 포즈
    # `odometry_pose() -> Optional[tuple[x, y, yaw]]`.
    # 선택: `odometry_available() -> bool` — 언도킹 전 오도메트리 기준점이 있는가.
    # 없으면 travelled_m 이 0.0 에 머물러 후진이 끝나지 않는다.


@dataclass
class DockingConfig:
    staging_timeout_s: float = 120.0
    acquire_timeout_s: float = 15.0
    approach_timeout_s: float = 60.0
    settle_timeout_s: float = 20.0
    backoff_s: float = 2.0
    backoff_distance_m: float = 0.25
    reseat_distance_m: float = 0.06     # 접점 재착좌 — 스테이징까지 가지 않는다
    #: D-350: 만춫 HOLD 진입/해제·재충전 히스테리시스. 팩 실측 후 조정.
    full_enter_v: float = 8.2           # 이 이상 유지 → 만춫 판정
    full_exit_v: float = 8.0            # 이 이하로 떨어지면 재충전 (CC/CV가 알아서 재개)
    #: D-350 Phase 1 (계측 없는 도크) — true 면 도크 전류 보고 없이 판정.
    instrumented: bool = True

    approach_speed: float = 0.06        # m/s — 접근은 느려야 한다
    approach_gain_yaw: float = 1.2
    max_angular: float = 0.5
    undock_speed: float = 0.08
    undock_timeout_margin_s: float = 2.0  # 후진 마감 = 2 × 거리/속도 + 이 값

    detector_lost_grace_s: float = 2.0  # 이 시간 안에 다시 보이면 실패가 아니다
    charge_confirm_s: float = 10.0      # 충전 확정 창

    # 주차형 (approach="pose")
    turn_timeout_s: float = 30.0
    align_timeout_s: float = 15.0
    settle_still_s: float = 0.6         # 멈춘 뒤 이만큼 지나 찍힌 관측으로 판정
    creep_exhausted_s: float = 1.0      # 크리프를 다 쓰고도 이만큼 안 보이면 재시도
    acquire_look_s: float = 0.5         # 기어가기 전에 먼저 본다 (5 Hz 두 프레임 + 지연)
    backoff_timeout_s: float = 10.0
    aim_min_m: float = 0.05             # 이보다 가까우면 주차점이 아니라 도크 yaw 를 겨눈다

    # 후진형 (approach="rear", D-950 후속). 레일 안에서 조향하면 벽과 다퉈 끼인다
    # (연구 dock_sim: 조향 12 ~ 27/47, 곧게 44 ~ 45/47) — 레일 안은 각속도 0 이다.
    rear_align_speed: float = 0.03      # m/s, 레일 입구 밖 후진 정렬
    rear_align_gain_lateral: float = 8.0   # rad/m — 횡 오차 → 목표 방위 (±40 mm·±6° → 0.40 m 뒤 2 mm·1°)
    rear_align_max_heading: float = 0.17   # rad, 목표 방위 상한
    rear_align_gain_yaw: float = 2.0
    rear_speed: float = 0.025           # m/s, 레일 안 곧은 후진
    contact_stall_s: float = 0.5        # 이만큼 진행이 없으면 멈춤면 접촉
    contact_progress_m: float = 0.002   # 이보다 덜 가면 진행이 없다
    rear_backoff_m: float = 0.55        # 재시도 전진 거리(레일 밖으로)
    rear_charge_rise_v: float = 0.02    # 멈춘 뒤 기준보다 이만큼 올라야 충전으로 본다(팩 실측 후 조정)

    # 칸 유도선 접근 (approach="line", D-1013). 이득·게이트·예산은 bay_pit_sim 게이트 값
    # (Rosy/docs/research/charge-bay-pink-line-2026-11-10/, 명목 36/36·시나리오 13/13).
    bay_reverse_speed: float = 0.05     # m/s, 선 가운데·평행 유지하며 후진
    bay_gain_lateral: float = 8.0       # rad/(s·m), ω = -(a·횡 + b·방위)
    bay_gain_heading: float = 1.2       # 0.6→1.2: 감쇠 ζ≈0.47→0.95, 5 cm 시작 방위 피크 20.5°→13.2°(운동학 sim, 2026-11-19)
    bay_target_heading_max_rad: float = 0.26  # 옆 오차가 요구하는 목표 방위 상한(15°; 짐칸 끝 0.135·칸 폭 0.18)
    bay_gate_jump_m: float = 0.02       # 프레임당 횡 점프 게이트(물리 가능 범위 밖 = 이웃선)
    bay_gate_jump_rad: float = 0.0873   # 5 deg/프레임
    bay_coast_slow_s: float = 0.5       # 관측 무효: 이 안은 제어량 유지(코스트)
    bay_coast_stop_s: float = 1.0       # 이 넘으면 감속 끝 정지 → 스캔
    bay_scan_rad: float = 0.0873        # 스캔 회전 폭 ±5 deg(정지 상태)
    bay_scan_s: float = 6.0
    bay_settle_creep_m: float = 0.04    # 회전 뒤 캐스터 정착 크립(전진)
    bay_travel_margin_m: float = 0.02   # 접촉 거리 상한 = 진입 잔여거리 + 이 값
    bay_backoff_m: float = 0.15         # 재시도 전진(교차점 쪽)
    # 진입 허용창(ALIGNING 시작 때): 평평한 횡·방위 한계(시뮬: 횡 ≤7 cm 는 방위 ±15°에서도 접촉 0, 밖은 거부 — sim-before-after.txt).
    # 밖이면 후진하지 않고 스테이징부터 다시(직진 후퇴로는 방위가 안 고쳐진다). Nav2 도착 허용 yaw 14° 보다 넓게 둔다.
    bay_entry_lat_m: float = 0.07
    bay_entry_heading_max_rad: float = 0.2618   # 15°
    # 접촉 때 허용창: 가이드 목 ±6 mm·방위 2°(충전 판정)의 두세 배. 넘으면 전압 20 s 를 기다리지 않고 재진입.
    bay_contact_lat_m: float = 0.015
    bay_contact_heading_rad: float = 0.0873     # 5°
    # 횡 맹목 후진(통로선만 보여 횡 실측 없음) 예산 = (진입 along - 칸 선이 보이는 거리) + 여유. 시간은 같은 비율(0.05 m/s).
    bay_line_view_m: float = 0.305              # 멈춤면 이 안에서만 칸 선이 보인다(관측기)
    bay_blind_margin_m: float = 0.05            # 관측 지연 2.5 cm + 슬립 여유
    bay_obs_max_age_s: float = 0.3              # 이보다 오래된 프레임은 게이트를 넓히지 않고 버린다(지연 0.3 s 넘으면 15° 상한이 안 지켜짐)
    bay_rear_gap_margin_m: float = 0.06         # LiDAR 뒤 여유가 남은 거리보다 이만큼 넘게 작으면 칸 안 장애
    bay_settle_baseline_s: float = 2.0  # 멈춘 뒤 기준 전압을 잡기 전 대기
    bay_charge_rise_v: float = 0.05     # D-941: 20 s 안 +0.05 V(도크 계측 없음)
    bay_charge_confirm_s: float = 20.0
    bay_fleet_eval_weight: float = 0.35  # 관제(Fleet) 서브픽셀 중심선 평가 보정 가중치
    # 칸 줄 안 시작·회전 안전(2026-11-18 옆 칸 접촉, bay_zone.py). 몸 스캔 = 짐칸 포함 회전 판정.
    bay_zone_margin_m: float = 0.0      # 스테이징 거리보다 안쪽이면 칸 줄 안(Nav2 를 부르지 않는다)
    bay_lane_half_m: float = 0.11       # 칸 간격(약 0.22 m)의 반 — 넘으면 다른 칸 줄
    bay_zone_agree_m: float = 0.05      # 맵 횡과 선 횡이 이만큼 넘게 다르면 모호
    bay_zone_agree_rad: float = 0.1745  # 10 deg
    bay_zone_look_s: float = 1.0        # 칸 줄 안 판정 전에 선 관측을 기다리는 시간
    bay_exit_lateral_m: float = 0.05    # 칸 줄에서 나가기 시작할 수 있는 횡 오차(선 관측)
    bay_exit_heading_max_rad: float = 0.2618  # 15 deg (조향 없이 나가면 atan(횡/거리)로 더 좁힌다)
    bay_acquire_heading_max_rad: float = 0.1047  # 6 deg: 곧은 시작은 나가지 않고 바로 선 포획(정상 흐름 도착 허용 ±6° 시험과 같은 값)
    # LiDAR bay pose (bay_scan_pose.py): a match against the dock's stored seated scan replaces the map pose in the zone
    # check only when all of these hold; otherwise the map path stays. Measured on y8xs scans (2026-11-20): seated and
    # near-seated fits inliers 0.77-1.0, margin 0.54-0.66 (grid matcher); a sideways wrong fit inliers 0.79, margin 0.27.
    bay_scan_inlier_min: float = 0.70
    bay_scan_margin_min: float = 0.40   # inliers minus the best different pose (another seed's answer)
    bay_scan_heading_max_rad: float = 0.7854   # 45 deg: a fit sideways in the row is a wrong fit, not a pose
    bay_scan_pose_wait_s: float = 4.0   # wait for the LiDAR pose this long (one run, off the scan thread), then the map path
    # Seated check (SETTLING): the stored reference scan says how far the stopped robot is from the stop face. Further
    # than this, the body was held short of it (y8xs 2026-11-20: stopped 7.5 cm out, 40 s of waiting for a charge).
    bay_seat_tol_m: float = 0.03
    # Before the reverse into the rails (entrance ~9.45 mm a side, wheels meet it 7.5 cm before the stop face): the measured
    # lateral must be within this or the dock stops and asks for a centred robot. Tightening only.
    # Sensor accuracy next to this limit (y8xs): the camera line lateral and the LiDAR ICP lateral differed by up to 17 mm
    # on the same stand, the 1 cm grid matcher adds ~1 cm. The limit is tighter than either sensor alone, so a pass needs a
    # centred robot by every measured source (all must pass). Loosen only on measured evidence; never from here.
    bay_entrance_lateral_m: float = 0.008
    bay_rail_entry_along_m: float = 0.13    # stop face to base_link when the wheels meet the entrance roller (0.05 seat + 7.8 cm)
    bay_entrance_runway_m: float = 0.15     # with this much steering distance left the line correction may centre it
    bay_seat_check_delay_s: float = 1.0  # stopped this long before the scan is taken
    bay_exit_extra_m: float = 0.02      # 스테이징 거리보다 이만큼 더 나간다
    bay_exit_speed: float = 0.05        # m/s, 칸 줄 곧은 전진
    bay_exit_front_gap_m: float = 0.08  # 앞 여유가 이보다 작으면 멈춘다
    bay_exit_steer_lat: float = 6.0     # rad/m, 횡 오차 → 목표 방위(선 보며 전진; 시뮬로 부호·크기 확인)
    bay_exit_steer_head: float = 2.0    # 1/s, 목표 방위로 맞추는 이득(0 이면 곧게 나간다)
    # 일방통행(C3→C1, 사이트 v258): 칸 축 기준 하류가 +횡(서쪽). 이 사이트 값이 기본이고 0 이면 검사 없음·회전은 최단 방향.
    bay_downstream_sign: float = 1.0
    # 하류 거절 경계 = 칸 반폭 + 맵 등록 오차(수 cm). 동(상류)쪽은 거절하지 않으므로 경계 오차는 서쪽 입구 앞에서만
    # 보이고, 여유를 더해 입구 바로 앞 로봇이 오차로 거절되는 쪽을 막는다(놓치면 Nav2 가 흐름을 거슬러 간다).
    bay_downstream_map_error_m: float = 0.04
    bay_stage_recheck_s: float = 1.0    # 스테이징 도착 방향 불일치를 이만큼 이어서 봐야 실패(포즈 잡음·일시 None)
    bay_turn_overshoot_rad: float = 0.35  # 회전 지나침 보정 허용(20 deg, 짐칸이 상류로 휘는 양); 넘으면 정지
    bay_corridor_band_m: float = 0.15   # 스테이징 거리 ± 이만큼이 통로선 위(하류 쪽 시작 거절 범위)
    bay_stage_heading_max_rad: float = 1.0472  # 60 deg: 스테이징 도착 코가 칸 축에서 이보다 틀면 실패
    # ALIGNING ends by LiDAR rear gap against the stored seated reference (bay_seat_gap_tol_m) and, while a FRESH scan (bay_scan_fresh_s)
    # shows the gap shrinking by bay_gap_moving_m over the last ~0.3 s (about 40 % of 0.05 m/s), the slip rule and the travel
    # cap stand down: the body IS going back (y8xs 2026-11-20: stopped at x 0.078 twice while teleop passed it). No scan, a stale
    # scan or no point in the strip leaves every rule as it was. The hard limit (cap + 0.10 m) and the progress check stay.
    # Stop-first (y8xs 2026-11-20 round 16: seated skewed -17 deg, the retry's forward back-off pivoted the body 77 deg about its jammed rear in
    # the rails; wheel odometry saw a straight drive): a seated robot the LiDAR finds skewed more than bay_seat_heading_max_rad is not driven
    # out (fail, a person frees it), and a back-off whose LiDAR rear gap grows by less than bay_backoff_moving_ratio of the wheel travel
    # (checked from bay_backoff_check_m on) stops and fails.
    bay_seat_heading_max_rad: float = 0.105
    bay_inrow_along_m: float = 0.15             # stop face to base_link: nearer than this the robot is in the rails (x < 0.1)
    bay_inrow_retry_heading_rad: float = 0.1745  # a retry from ALIGNING there with a line heading beyond this stays (no back-off)
    bay_backoff_check_m: float = 0.02
    bay_backoff_moving_ratio: float = 0.5
    bay_backoff_growth_max_ratio: float = 1.5   # ...and by no more than this x the wheel travel + slack: a turning body inflates the gap
    bay_backoff_growth_slack_m: float = 0.02
    bay_backoff_lower_slack_m: float = 0.015    # the scan lags up to 0.5 s (2 cm at 0.04 m/s): the lower bound gets slack too
    bay_backoff_speed: float = 0.04             # slow back-off inside the bay row (m/s)
    bay_uncharged_hold_s: float = 5.0           # ...and the FILTERED voltage stays that far down this long (raw readings jitter 0.17 V at idle)
    bay_person_call_percent: float = 30.0       # DOCKED without charge evidence below this battery %: a person is called (docking.person_call)
    bay_uncharged_drop_v: float = 0.10          # DOCKED without charge evidence: warn when the pack falls this far below its voltage at docking
    bay_full_battery_percent: float = 98.0      # at or above this a LiDAR-confirmed seat counts as docked without charge evidence
    bay_gap_moving_m: float = 0.006
    bay_seat_gap_tol_m: float = 0.002
    bay_scan_fresh_s: float = 0.5       # 몸 스캔 판정이 이보다 오래되면 없는 것
    bay_scan_wait_s: float = 2.0        # 몸 스캔 없이 이만큼 지나면 실패
    # 짐칸 J-v3 뒤끝은 바퀴축 뒤 0.134–0.135 m(정격 CAD, 뒷면 y_d −14.45 · 축 y_d 120.5; 몸 74.5·42.1·r 82.6 이
    # base_link 치수와 일치, 2026-11-18 tray_overhang_cad.py). 모따기 덕에 쓸리는 반경은 0.137 m.
    bay_turn_rear_overhang_m: float = 0.135
    # 카메라 기준 방향 맞춤·선 찾기(bay_align.py, 실물 y8xs 2026-11-19: 지도-카메라 방향 17~30° 어긋남, 스테이징에서 선 안 보임)
    bay_stage_map_wrong_way_rad: float = 2.0    # 115°: with the camera on the line only a map yaw this far off is a wrong-way arrival
    bay_heading_align_max_rad: float = 0.7854   # 45°: 이 안의 방위 위반만 제자리 회전으로 맞춘다(넘으면 재시도)
    bay_heading_align_tol_rad: float = 0.05     # ~3°: 이 안이면 끝(관측 지연 0.3 s × 0.1 rad/s 1.7° 여유)
    bay_heading_align_tries: int = 2            # 한 도킹당 회전 맞춤 횟수
    bay_heading_align_timeout_s: float = 8.0
    bay_find_wait_s: float = 1.0                # 선이 안 보이면 이만큼 정지해 보고(5 Hz) 나서 후진 크립
    bay_find_speed: float = 0.03
    bay_find_creep_max_m: float = 0.12          # 선이 안 보이는 후진 상한 = 선 시야 여유(Nav2 오차 ~0.10 m, 실측)
    # With the dock's stored seated rear gap known the find creep is bounded by the LiDAR position (x = rear gap - seated gap), not by 0.12 m
    # of odometry: Nav2 can stop 0.10 m beyond staging (y8xs round 17: x 0.42, the line only shows inside x ~0.28). It still stops
    # at bay_find_min_x_m from the seat (outside the rails) and at bay_find_lidar_creep_max_m of travel; the 0.30 turn rule is untouched.
    bay_find_min_x_m: float = 0.20
    # In-place turns closed on the LiDAR yaw (bay_turn_watch.py): odometry and the matched scans may differ this much (8 deg) before the turn stops.
    bay_map_scan_tol_m: float = 0.15            # the map pose and the LiDAR scan pose of the bay may differ this much before a Nav2 start is refused
    bay_turn_needs_scan: bool = True            # no body-scan sample ever handed over = no turn (fail-closed); False only for sims without the bridge
    # ALIGNING inside the rails steers on the LiDAR scan pose (bay_lidar_steer.py), the camera heading being 11-19 deg wrong there
    bay_lidar_steer_along_m: float = 9.0         # reference-scan dock: LiDAR steering from the START of ALIGNING (Nav2 can stop at 0.42, the camera heading is wrong there)
    bay_lidar_ask_s: float = 0.2
    bay_lidar_pose_grace_s: float = 4.0
    bay_lidar_stall_s: float = 1.5               # in the rails the rear gap must change by bay_lidar_stall_m within this while reversing
    bay_lidar_stall_m: float = 0.005
    bay_lidar_jump_m: float = 0.03               # a LiDAR pose this far (lateral) from the predicted one is not evidence
    bay_lidar_jump_rad: float = 0.0873
    bay_lidar_x_gap_tol_m: float = 0.04          # scan x vs (rear band gap - stored seated gap)
    bay_rail_max_angular: float = 0.15
    # The staging turn's sense. 0 = the downstream rule (bay_downstream_sign: the tray swings downstream, clockwise at this site). +1 / -1 force
    # ccw / cw for a robot that cannot turn one way (y8xs: cw never moves the body). The in-place sweep is checked clear every tick either way, and a
    # robot that failed one sense (the watch flipped it) turns the other first at its next dock until the CORE process restarts.
    bay_turn_first_dir: int = 0
    bay_turn_flip_max_rad: float = 0.3491       # flip the sense only when the body barely moved (LiDAR yaw under 20 deg)
    bay_entry_heading_cross_rad: float = 0.1745  # LiDAR vs camera crossbar heading at the entry window (outside the rails): beyond this = a false fit, stop
    bay_entry_strong_inliers: float = 0.85       # a LiDAR fit this strong is believed over a camera crossbar heading that disagrees
    bay_entry_strong_margin: float = 0.40
    bay_entry_heading_hard_rad: float = 0.6981   # LiDAR vs camera heading beyond 40 deg stops even a strong fit
    bay_lidar_first_jump_m: float = 0.05         # the first ALIGNING LiDAR pose vs the entry window's (lateral)
    # Rail entrance (9.45 mm a side) vs LiDAR accuracy (10-15 mm): the reverse corrects the lateral on the LiDAR pose outside the rails and the guard judges
    # the MEAN of the last poses just before the wheels reach the entrance, instead of one pose at the start. The limit stays bay_entrance_lateral_m.
    bay_rail_judge_x_m: float = 0.12
    bay_rail_judge_n: int = 3
    # Lane keeping (user rule 2026-11-21: docking exists to KEEP THE PARKING LINES). Bay pitch 0.21 m -> lane half-width 0.105 m; the body half-width
    # is 0.0566 m (CAD, RobotBody half_width_m), so the body CENTRE may travel +-0.048 m: 0.045 m. bay_line_x_m: the bay line in front (the pink corridor
    # crossbar, seen at bay-frame x ~0.42 on y8xs): to be confirmed from the frames/CAD; a forward move must not reach it.
    # Footprint check (panel B r25-b.md): the body CORNERS (nose 0.042, tray 0.135 behind base_link, half-width 0.0566) must stay within the lane edge.
    bay_lane_edge_m: float = 0.105
    bay_body_front_m: float = 0.042
    bay_body_half_width_m: float = 0.0566
    bay_reseat_tries: int = 4                    # lane reseats (retries from the reverse / the seat) before it stops where it stands
    bay_reseat_out_m: float = 0.12               # each reseat pulls forward this far (plus 3 cm per further try), short of bay_line_x_m
    bay_req_timeout_s: float = 2.5               # an unanswered LiDAR pose request is abandoned after this and asked again
    bay_seat_tries: int = 5                      # the seat pose is asked again when a pose is dropped (up to this many asks)
    bay_track_lost_s: float = 3.0                # inside the row the pose is TRACKED; no accepted pose this long = back to first acquisition (provisional)
    bay_track_rail_lateral_m: float = 0.02       # tracked pose inside the rails: |lateral| above this is dropped (provisional)
    bay_track_rail_x_m: float = 0.09             # the rails only bound x < ~0.078; a 2-5 cm start accepted by the first acquisition must not be dropped
    bay_track_inlier_min: float = 0.70
    bay_first_x_max_m: float = 0.20              # FIRST acquisition in the bay (case I) with a weak margin: provisional until the 9-cell matrix is measured
    bay_first_lateral_m: float = 0.05
    bay_first_heading_rad: float = 0.1047
    bay_first_inlier_min: float = 0.75
    bay_first_margin_prior: float = 0.10         # seated at this dock earlier: a weaker global margin is accepted
    bay_first_margin_noprior: float = 0.12       # no prior: identity recorded "unconfirmed"
    bay_first_margin_wrong: float = 0.05         # below this the best fit is another bay
    bay_row_pose_fresh_s: float = 1.0            # a forward move in the row needs a LiDAR bay pose no older than this (reference-scan dock)
    bay_lane_keep_m: float = 0.045
    bay_line_x_m: float = 0.30                   # base_link: the nose (0.042) + 0.02 behind the crossbar edge at bay-frame x 0.4255 (+-0.03); confirm by tape
    bay_entry_outside_rails_x_m: float = 0.25    # LiDAR x beyond which the camera crossbar heading is cross-checked at the entry window
    bay_lidar_lateral_gain_mult: float = 1.5     # the LiDAR lateral is trusted: correct it fast enough to centre within the runway (the target heading stays capped)
    bay_turn_follow_ratio: float = 0.06         # the follow verdict allows this share of the turn on top of the 8 deg floor (odometry reads ~4 % more)
    bay_turn_stall_s: float = 1.5               # strict stall window: wheels beyond the floor while the LiDAR barely moves
    bay_turn_close_min_rad: float = 0.0524      # a staging turn the LiDAR finds 3..15 deg short is turned on (twice at most)
    bay_turn_close_max_rad: float = 0.2618
    bay_turn_follow_rad: float = 0.1396
    bay_turn_ask_s: float = 0.5                  # a scan-to-scan match every this long while turning
    bay_turn_settle_s: float = 0.4               # after the turn stood still before the confirming match
    bay_turn_watch_wait_s: float = 3.0           # no good match for this long (or two bad ones in a row) fails the turn
    bay_turn_inlier_min: float = 0.60
    bay_find_heading_verify_rad: float = 0.0873  # after the in-place align a fresh scan pose must show the heading within this (5 deg)
    bay_find_heading_max_rad: float = 0.1745     # at the creep's start a LiDAR heading beyond this is aligned first (outside the row) or stops it
    bay_find_lidar_creep_max_m: float = 0.30
    bay_find_extra_m: float = 0.06              # 처음 보인 뒤 더 가는 양 = 정착 크립 0.04 + 여유 0.02
    bay_find_rear_gap_m: float = 0.06           # 뒤 띠 여유가 이보다 작으면 멈춘다(멈춤면 도착 전 0.17 m 이상 남음)