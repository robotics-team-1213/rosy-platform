## D-393 Pinky 트랙 Nav2 위치추정 — AMCL `update_min_d` 0.02, 목표 허용오차 0.05 m / 0.10 rad, 운용 규칙을 제안한다

**Status:** Proposed (2026-10-01). 이 ADR은 제안만 한다. 로봇 설정·params 파일은 바꾸지 않는다. 적용은 아래 게이트(반복 sim A/B, 사용자 승인을 받은 실물 주행)를 통과한 뒤 별도 변경으로 한다. 증거는 Gazebo Harmonic 1대, 행당 n=1이다.

잇는 결정:

- **D-369:** 최종 `/cmd_vel`은 CORE 하나다. 아래 목표는 모두 CORE를 거친 Nav2 목표다.
- **D-364:** 차선 유지는 선 따라가기가 아니라 차로 지키기다. 4항(차선 따르기 항법)은 이 결정의 범위 밖이다.
- **D-205:** map_v2_fleet 차선 트랙 전환 순서.

### Context

map_v2_fleet 트랙에서 Nav2 목표 6개를 CORE를 거쳐 주차 시작 자세(-1.0, 0, 0°)에서 보냈다. AMCL은 초기 자세만 주고 global localization은 쓰지 않았다.

**한계 (먼저 읽는다).** sim 전용이다: Gazebo Harmonic, 로봇 1대, 행당 n=1, WSL 부하 30–60. sim은 실물이 아니다. 아래 수치는 방향을 보이는 증거이지 합격 기준이 아니다.

| AMCL `update_min_d` | AMCL 오차 평균 / p95 | 후진 구간 평균 / 최대 | AMCL 점프 (>2 cm / 0.1 s) |
|---|---|---|---|
| 0.15 | 7.8 / 9.6 cm | 9.4 / 10.2 cm | 10 |
| 0.005 | 12.4 / 23.9 cm | 15.3 / 25.0 cm | 45 |
| 0.02 | 2.9 / 5.9 cm | 3.0 / 8.5 cm | 24 (0.31 m 스파이크 1건) |

- **목표 결과:** 6/6 도달. 위치 오차 평균 3–5 cm(최대 13 cm). 측정한 오도메트리·회전 보정(1.02 / 0.91)을 적용하면 yaw 오차는 최대 17°다.
- **차선 이탈:** 샘플의 29–32 %가 어느 차선 중심선에서든 10 cm보다 멀다. 점유 맵에는 차선이 없어서 Nav2는 차선을 직선으로 가로지른다.
- **실물 재생(같은 날 앞서, 추정):** 0.005는 느린 후진에서 발산했고 0.02는 안정적이었다. 추정이며 이 ADR이 실물로 확인한 것이 아니다.
- 0.02 행의 점유 점프 24건과 0.31 m 스파이크 1건은 0.15보다 점프가 많다. 평균 오차는 가장 좋지만 이 한 건이 n=1에서 우연인지 구조인지 모른다. 그래서 반복 A/B가 게이트다.
- 증거 위치(저장소 밖): `X:\DevTemp\rosy-ml-work\nav-eval\`의 평가 스크립트와 출력.

**사실 (저장소에서 확인).**

1. 기기의 AMCL은 `src/runtime/navigation/params/nav2_params.yaml`의 값을 쓴다: `amcl.update_min_d: 0.15`(34행), `update_min_a: 0.1`(33행). 경로는 `deploy/robot/pinky_pro/native/rosy-navigation.service`(ExecStart `ros2 launch navigation hardware.launch.py`) → `src/runtime/navigation/launch/hardware.launch.py`(기본 `params_file`은 `navigation/params/nav2_params.yaml`, `write_prefixed_nav2_params`로 접두 재작성) → `src/runtime/navigation/launch/bringup_launch.xml`이다.
2. `src/runtime/sensing/config/localization.yaml`의 `update_min_d: 0.005`(20행), `update_min_a: 0.02`는 `src/runtime/sensing/launch/localization.launch.py`와 이를 포함하는 `localized_robot.launch.py`만 읽는다. 기기 서비스는 이 경로를 타지 않는다. 즉 0.005는 기기 설정이 아니다.
3. 목표 도달: `nav2_params.yaml` 162–163행 `general_goal_checker`(`nav2_controller::SimpleGoalChecker`) `xy_goal_tolerance: 0.25` m, `yaw_goal_tolerance: 0.25` rad(약 14°). 같은 파일의 RPP는 `lookahead_dist: 0.6`, `min_lookahead_dist: 0.3`이고, sim 시험 패치 `src/runtime/sensing/map/map_260905_update_v2/config/nav2_sim_rpp_trial.patch.yaml`은 `lookahead_dist: 0.20`, `min_lookahead_dist: 0.15`다. 같은 맵 폴더의 `nav2_sim_core.patch.yaml`은 이미 `xy_goal_tolerance: 0.03`, `yaw_goal_tolerance: 0.10`을 쓴다.

### Decision (제안)

1. **AMCL `update_min_d`는 Pinky 트랙 프로필에서 0.02로 한다.** 대상은 기기 경로의 `nav2_params.yaml`이다. 0.005(sensing 설정)와 현재 0.15는 후진·저속에서 오차가 크거나 발산한다는 증거가 있다(위 표). `update_min_a`는 이 ADR이 바꾸지 않는다.
2. **목표 허용오차는 xy 0.05 m / yaw 0.10 rad로 한다.** 현재 0.25 m는 sim 전방 주시 거리 0.15 m보다 커서 RPP가 이미 도착했다고 보고 제자리에서 돈다. 또 25 cm는 차선 폭의 1–2배라서 어느 차선에 섰는지 구분하지 못한다. 0.05 m는 sim에서 측정한 위치 오차 평균 3–5 cm(최대 13 cm)보다 약간 크다. 최대 13 cm가 0.05 m를 넘으므로 적용 전에 반복 A/B에서 도달률을 다시 본다.
3. **운용 규칙.**
   - 알려진 주차 자세에서 출발한다.
   - 180° 대칭인 맵에서는 global localization을 쓰지 않는다.
   - 로봇을 들어 옮긴 뒤에는 운영자가 자세를 다시 초기화한다.
   - 맵 기록(map record)에 실물 상자가 sim 월드보다 4–6 cm 작다고 적는다(sim 안쪽 벽 2.80 × 1.25 m).
4. **차선 따르기 항법(Nav2를 차선 그래프 위로 보내는 것)은 이 ADR의 범위 밖이다.** 위 29–32 % 차선 이탈은 격차로만 기록한다.

### Gates before applying

1. 반복 sim A/B: `update_min_d` 값마다 n ≥ 5. 평균·p95·점프 수와 0.31 m 같은 스파이크의 빈도를 본다. 0.02가 0.15보다 나쁘지 않아야 한다.
2. 허용오차 0.05 m / 0.10 rad에서 6개 목표 도달률과 제자리 회전 여부를 같은 반복으로 본다.
3. 실물 주행. 로봇 설정 변경과 모션은 사용자 승인이 필요하다(로봇은 공유·게이트 상태다).

### Alternatives

- **0.005 유지(sensing 설정 그대로):** sim에서 오차 평균 12.4 cm, 점프 45건. 기각.
- **0.15 유지:** 오차는 중간이나 후진 구간이 9.4 cm다. 0.02가 반복 A/B에서 안 지켜지면 되돌아갈 후보로 남긴다.
- **허용오차 0.25 m 유지:** RPP 제자리 회전과 차선 구분 불가. 기각.
- **지금 params를 바꾼다:** n=1 sim 증거로 기기 설정을 바꾸지 않는다. 기각.

**Consequences:** 승인되면 기기 `nav2_params.yaml` 한 곳의 키 3개(`update_min_d`, `xy_goal_tolerance`, `yaw_goal_tolerance`)가 바뀐다. 허용오차를 줄이면 도달 실패와 재시도가 늘 수 있다. 차선 이탈은 이 ADR로 줄지 않는다.

**Open:** 0.02의 점프 24건·0.31 m 스파이크 원인, 실물 재생(추정)의 실물 확인, 차선 따르기 항법, 실물 상자 치수 반영.

**References:** `src/runtime/navigation/params/nav2_params.yaml`, `src/runtime/sensing/config/localization.yaml`, `src/runtime/navigation/launch/hardware.launch.py`, `deploy/robot/pinky_pro/native/rosy-navigation.service`, D-369, D-364, D-205, [D-346](D-346-commit-time-collision-defenses.md).
