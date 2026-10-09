# D-557 현행 D-520 모델 PC 한 바퀴 기준 run — 2026-10-09

**증거 등급: ROS-SIM 한 번.** Fleet trip `arrived`와 CORE `junction_stop`, 최종 명령 `[0, 0]`을 확인했다. D-567 병렬 보정은 연결하지 않았다. 한 번의 완주는 경계 안전성, 반복성, 장치 수용을 증명하지 않는다.

## 재현 조건

- 모델 PC `rosy@100.98.162.71`의 전용 `~/rosy_d567_ws`. 로컬 후보 `4d16150dcd807c7044d44ff2fc122c04e2787876`를 `git archive`로 고정했다. 전송 아카이브 SHA-256 `f3232293e5ca189eb2c3ca636f20d262103bb9b9e6d90e2c5bf57cc6aff5be48`; `lane_arc.py` 양쪽 SHA-256 `04d016bd958905d89c1e0eb50833b478ca4821de721b4be65ff15513c249db53`.
- ROS Jazzy, `colcon build --symlink-install --packages-up-to gz_sim core control description` 16 packages 성공. ROS domain 94, Gazebo partition `rosy_d567`, CORE 8590, Fleet 8591. 다른 ring4 작업공간은 사용하지 않았다.
- world `map_v2_fleet_real.world` SHA-256 `14c8de02f683435a103728a30a24a83237ff9bc03ba1dc6f87a08feb99f31ebb`. CORE overlay SHA-256 `cdea6ad367886fde37e4e3d709ef6b004017a9f5f055e4f272fa057701c89704`: `obstacle_mode: path`, `ir_guard_enabled: true`, `site_floor_map_id: map_v2_fleet`. `line_follow.yaml`와 `camera_lane_mode`의 추가 overlay는 없었다.
- 기존 [ring4 하네스](../lane-trip-lap-sim4-2026-10-09/evidence/ring4_run.sh)에서 작업공간·domain·partition·포트만 바꿔 전용 SIM을 시작하고 한 줄 `lap_d567_baseline`을 [batch](../lane-trip-lap-sim4-2026-10-09/evidence/ring4_batch.sh)에 보냈다. 원본 녹화 `frames.npz` SHA-256 `500138b371cdfb3e35843e4b8eafafb9bbcca593c33312f8434fced03bbb87d9`는 모델 PC 전용 작업공간에 보존했다.

## 관측

- [summary.json](evidence/summary.json): trip `arrived`, 총 55.6 s, GT 이동 2.8211 m, 최종 CORE `HOLD / junction_stop`와 명령 0. `lane_arc` capability는 종료 시 true였다.
- 기존 [ring4_arc.py](../lane-trip-lap-sim4-2026-10-09/evidence/ring4_arc.py)로 [GT log](evidence/log.jsonl)를 다시 계산하면 최대 `|Δr|`는 `ring_s` 0.034 m, `ring_e` 0.041 m, `ring_n` 0.030 m다. 시작 접선 오차는 각각 −4.1°, −3.4°, +8.0°. `lane_arc_edge`와 `nav.lane_arc_end_unarmed`는 없었다.
- 새 목표의 1차 대리 지표는 [evaluate.py](evidence/evaluate.py)로 재현한다. ring 도색선 중심 반지름 0.155/0.345 m와 생성된 `geometry.yaml`의 **Gazebo 충돌 상자 외접 반경 0.08826 m**를 쓴다. GT의 호 주행 132개 표본 중 109개에서 원형 대리 차체가 선 중심을 넘고, 최소 여유는 `ring_s` −28.7 mm, `ring_e` −35.1 mm, `ring_n` −21.9 mm다([metrics.json](evidence/metrics.json)). 이는 SIM 충돌 상자의 외접 원 대리값이며 실제 로봇 충돌 형상이나 도색 두께의 판정이 아니다. 앞서 쓴 0.076 m는 sensing 병진 반경이어서 회전 호의 SIM 상자 외접값으로 부적절했다.
- [events.jsonl](evidence/events.jsonl)은 원시 상태 이벤트다. 별도 추적에서는 `stuck_back_off`, `obstacle_ahead`도 관측되어 `arrived` 외 정지·재개 사유를 확인해야 한다.

## 판정과 다음 실험

**경로 완주: 관측. 차체 경계 수용: 미판정.** 두 도색선 중심 간격 190 mm의 절반 95 mm에서 SIM 상자 외접 반경 88.26 mm를 빼면 중심 자세에 남는 원형 대리 여유는 6.74 mm다. 실제 합격에는 도색선의 허용 침범 범위와 차체 방향별 sweep이 필요하다. 기존 30/50 mm 반지름 오차 문턱은 안전 합격 목표로 맞지 않는다. 다음에는 충돌 메시의 실제 차체 sweep, 자세·투영·시간 오차와 정지 후 추가 이동을 같은 GT 경로에 적용한다. 그다음 Fleet 자세 후보와 승인 바닥선 후보를 같은 시작 조건의 폐루프 SIM에서 비교한다.

## 실물 로봇별 적용 범위

| 로봇 | 이미 측정된 차이 | 현재 적용·승인 판정 |
|---|---|---|
| `rosy_26` / `9dfk` | D-397의 바퀴 반지름/간격 0.0266/0.0953 m. 2026-10-05 카메라 실행 override 높이 0.054908 m, pitch 0.211484 rad. D-500의 카펫 제자리 회전에서 odom과 실제 yaw가 크게 달랐다. | 당시 카메라 실행만 확인. 현재 바퀴 accepted record·camera override·차체/부착물 sweep·정지 거리는 읽기 증거 없음. |
| `rosy_60` / `8kcn` | D-397의 바퀴 반지름/간격 0.0272/0.0975 m. D-423의 카메라 pitch 관측 약 11.2–11.8°; 9dfk override는 적용하지 않았다. | 로컬 PC에 camera 후보 기록은 있지만 현재 장치 accepted record·실행 파라미터·차체/부착물 sweep·정지 거리는 읽기 증거 없음. |

바퀴·카메라 값은 위치 추정과 바닥선 투영에 영향을 준다. 두 로봇의 **물리 차체 반경이 서로 다르다는 측정은 아직 없다.** 공통 URDF의 장치 충돌 메시 외접 반경 0.08257 m와 이 SIM 상자 0.08826 m도 실제 두 로봇의 장착물·케이블·마모를 대신하지 않는다. 모델 PC에서 두 로봇 DNS는 확인됐으나 SSH 공개키 인증이 거절돼 현행 승인·적용 값을 읽지 못했다. 로봇별 기록 digest, 실행 override, 독립 yaw/위치, 실제 차체 sweep, 정지 후 이동을 대조하기 전까지 두 DEVICE 판정은 각각 HOLD다.
