## D-397 Pinky Pro 기하 — URDF가 NOMINAL을 정하고, 로봇마다 캘리브레이션이 다듬는다

**Status:** Proposed (2026-10-01). 저장소의 기본값과 계약만 바꾼다. 로봇에는 아무것도 배포하지 않았다(SSH·deploy 없음). 아래 "기기에서 달라지는 것"은 사용자 승인 뒤에만 배포한다.

잇는 결정:

- **D-16:** Pinky Pro 업스트림 URDF 가져오기(커밋 6455b1a9). 이 ADR의 기하 원천이다.
- **D-47 addendum (2026-10-01):** 버전 관리되는 캘리브레이션 저장소(`core_common/calibration_store.py`). 승인된 레코드가 정적 값을 이긴다. **이 ADR은 그 addendum을 개정한다:** 정적 값을 URDF NOMINAL로 정하고, 승인된 레코드 **위에** 운영자 층을 새로 둔다(Decision 4). D-47에 같은 날짜의 상호 참조 줄을 달았다.
- **D-364 3항:** NOMINAL 카메라 프로필(`camera_nominal.yaml`). 높이·피치·x 오프셋이 이제 URDF 값이다.
- **D-196:** 로봇 패키지 `config/core.yaml` 층. `line_follow.lidar_forward_deg`가 여기 산다.

### Context

같은 기하 값이 저장소 곳곳에 따로 적혀 있었고 서로 달랐다. 바퀴 반지름은 bringup이 0.027, Gazebo가 0.028이었고, 바퀴 간격은 둘 다 0.0961로 URDF와 맞지 않았다. sensing의 LiDAR 정면은 소나에 맞춘 경험값 190°(π+10°)였는데, CORE는 180°를 썼고 측정은 181–182°였다. 카메라 높이는 0.067이었는데 URDF는 0.0634, 측정은 0.0575–0.062다. 어느 값이 원천인지 정해 두지 않아서 값마다 근거가 달랐다.

사용자 결정(2026-10-01): Pinky Pro의 모든 기하 파라미터는 NOMINAL 기본값을 URDF에서 가져오고, 로봇마다 캘리브레이션이 그것을 다듬는다.

### Decision

1. **원천은 URDF 하나다.** `src/sim/description/urdf/rosy.urdf.xacro`(업스트림 6455b1a9)와 `robot.urdf.xacro`의 arg 기본값(cam_tilt_deg 8, cam_mount_z 0.0495)을 계산한 값이 NOMINAL이다.
2. **값은 생성 파일 하나에 둔다.** `tools/calibration/urdf_nominal.py`가 ROS 없이(표준 라이브러리만) xacro의 고정 조인트 사슬을 계산한다. 매크로 파라미터와 기본값, `${pi}`, 사칙연산, `xacro:if`, 중첩 매크로, 충돌 메시(STL)를 다룬다. 결과는 `src/products/pinky_pro/profile/config/geometry.yaml`에 쓰고, 머리말에 두 xacro 경로를 적는다. 해시는 적지 않는다(릴리스 비밀 검사가 40자리 16진수를 거부하고, 주석만 바뀐 xacro 수정이 검사를 깨면 안 된다). 허용하는 xacro는 macro/if/unless/arg, 알려진 두 include, 링크 안의 관성 도우미뿐이고, 그 밖의 것(property, insert_block, element, 모르는 include·매크로·파라미터, 1 1 1이 아닌 메시 scale)은 추측하지 않고 실패한다(Windows CI에는 ROS xacro가 없다).
3. **드리프트는 테스트가 막는다.** `tools/calibration/test/test_urdf_nominal.py`가 `geometry.yaml`을 다시 만들어 체크인된 파일과 다르면 실패한다. 같은 파일이 아래 소비자 기본값이 모두 `geometry.yaml`과 같은지 확인한다.
4. **우선순위: URDF NOMINAL < 승인된 캘리브레이션 레코드 < 운영자 덮어쓰기.** `calibration_store.resolve(..., override=)`가 이 순서를 구현한다. 운영자 덮어쓰기는 세 곳이다.
   - **CORE:** 로컬 오버레이(`~/.rosy/rosy.yaml` 또는 `ROSY_CONFIG`)의 `line_follow.lidar_forward_deg`가 이제 승인된 `lidar_mount` 레코드를 **이긴다**(전에는 레코드가 이겼다). 어댑터 `lidar_yaw_offset`과의 비교 경고는 그대로 남는다.
   - **bringup:** launch 인자 `wheel_radius`/`wheel_separation`(0 = 없음; NaN·음수는 버리고 로그).
   - **sensing line_observer:** `camera_pitch_rad_override`/`camera_height_m_override`(NaN = 없음).

   덮어쓰기도 레코드와 같은 `check_values` 타당성 검사(LiDAR 150–210°, 바퀴 ±10 %, 카메라 물리 범위)를 통과해야 하고, 실패하면 경고하고 레코드·NOMINAL 값을 쓴다. 레코드 승인은 지금처럼 운영자만 한다.
5. **URDF는 업스트림 CAD이지 측정이 아니다.** 로봇 한 대의 진실은 줄자 측정과 승인된 캘리브레이션 레코드다. URDF 값은 캘리브레이션이 없을 때의 출발점이고, `check_values`의 타당 범위(바퀴 ±10 %, LiDAR 150–210°)도 이 값을 중심으로 한다.

### URDF NOMINAL (`geometry.yaml`)

틀: `base_footprint`(바닥), x 앞, y 왼쪽. 높이는 바닥에서 잰다.

| 항목 | 값 | 유도 |
|---|---|---|
| base_footprint → base_link z | 0.028 m | 고정 조인트 |
| LiDAR(`rplidar_link`) | x −0.017, 높이 0.125 m, yaw π → 스캔 틀에서 정면 180° | 0.028 + 0.067 + 0.030 |
| 카메라(`front_camera_link`) | x 0.03317, 높이 0.06343 m, 피치 8° (0.139626 rad) | 마운트 (0.020, 0, 0.0495, 피치 8°) + (0.015, 0, −0.0121) |
| 바퀴 | 반지름 0.028, 조인트 y ±0.04055, 접지 간격 0.0971 m | 충돌 원기둥 오프셋 ±0.008 |
| IR 왼·가운데·오른쪽 | x 0.0295, y +0.020 / 0 / −0.020, 높이 0.013 m, 반폭 0.020 | |
| 초음파 | x 0.0267 m | |
| IMU | base_link에서 (−0.044, 0, 0.0525) | |
| 회전 반경(base_link z축) | 0.0826 m(충돌 메시, 기기 URDF), 0.0883 m(Gazebo 충돌 상자) | 차체·바퀴·램프 |

회전 반경은 두 값을 모두 적는다. 기기가 읽는 URDF(`is_sim` false)는 STL 충돌 메시를 쓰고, 그 최대값이 0.0826이다. Gazebo용 상자는 메시의 외접 상자라서 모서리가 0.0883으로 크다. sensing의 회전 바닥값은 메시 값을 mm 단위로 올린 0.083이다.

### 측정된 차이 (로봇·세션별)

| 항목 | URDF | 측정 |
|---|---|---|
| LiDAR 정면 | 180° | 181–182°(주행 중 LiDAR 이동, 카메라 벽) |
| 카메라 피치 | 8° | 8–11.8°(로봇·세션마다 다름) |
| 카메라 높이 | 0.0634 m | 0.0575–0.062 m(맞춤) |
| 바퀴 반지름 / 간격 | 0.028 / 0.0971 m | 8kcn 0.0272 / 0.0975, 9dfk 0.0266 / 0.0953 |

차이는 이 ADR이 고치지 않는다. 각 로봇의 측정 레코드를 운영자가 승인하면 그 로봇에서 레코드가 URDF 값을 이긴다. 위 측정값은 모두 새 `check_values` 범위 안에 든다(테스트로 확인).

### 바꾼 기본값

| 소비자 | 전 → 후 |
|---|---|
| sensing `lidar.py` `MOUNT_YAW_DEG` / `NOSE_YAW` | 10 → 0 / π+10° → π (소나 경험값 폐기) |
| sensing `robot.yaml` `lidar_yaw_offset`, `scan_yaw_offset`; `auto_calib.yaml` `lidar_yaw_offset` | 3.31612558 → 3.14159265 |
| `camera_nominal.yaml` `pitch_rad` / `height_m` / `x_offset_m` | 0.1396 / 0.067 / 0.034 → 0.139626 / 0.06343 / 0.03317 |
| bringup `rosy_params.yaml`, `pinky_pro_adapter.yaml`, adapter `DEFAULTS`, 노드 기본값 | 0.027 / 0.0961 → 0.028 / 0.0971 |
| bringup launch `wheel_radius` / `wheel_separation` | 항상 0.027 / 0.0961을 넘김 → 0.0(없음), 양수면 운영자 덮어쓰기 |
| `calibration_store` `NOMINAL_WHEEL_*`, `LIDAR_NOMINAL_DEG` | 0.027 / 0.0961 → 0.028 / 0.0971, 창은 180 ± 30 |
| road_state `ir_x_m` / `ir_half_span_m`, `road_replay.py` | 0 / 0.012 → 0.0295 / 0.020 (IR은 여전히 `ir_geometry_measured` false로 꺼짐) |
| sensing 회전 바닥값 `.083`(safety, evidence, lidar_guard) | 리터럴 → `body.ROTATION_RADIUS` 0.083(값 그대로) |
| Gazebo DiffDrive, Isaac `wheel_distance` | 0.0961 → 0.0971 |
| sim `map_v2_fleet_real` `cam_mount_z` / 높이 | 0.05307 / 0.067 → 0.0495 / 0.06343 |
| sim `map_v2_fleet_lane` line_observer `camera_x_offset_m`(25°) | 0.034 → 0.028481 |

CORE `core.yaml`의 `lidar_forward_deg: 180`은 이미 URDF 값이어서 바꾸지 않고 드리프트 테스트로 묶었다. sensing `robot_radius` 0.076은 `body.py` URDF 상수(바퀴·캐스터 도달)에서 계산되는 값이라 그대로 두고, 상수들을 `geometry.yaml`에 묶었다.

### 기기에서 달라지는 것 (배포 전 사용자 승인 필요)

- **바퀴 반지름 0.027 → 0.028:** 승인된 `wheel_odometry` 레코드가 없는 로봇에서 오도메트리 거리와 명령 → 바퀴 rpm 환산이 약 3.7 % 바뀐다. 간격 0.0961 → 0.0971은 회전 환산을 약 1 % 바꾼다. 레코드가 승인된 로봇은 레코드를 쓴다.
- **sensing LiDAR 정면 190° → 180°:** safety·wander·calib 노드의 전방 섹터가 10° 돈다. CORE line_follow는 이미 180°였다.
- **카메라 NOMINAL 높이 0.067 → 0.0634, x 0.034 → 0.0332:** NOMINAL ground로 투영하는 차선 증거의 거리 척도가 약 5 % 바뀐다. 승인된 `camera_profile` 레코드가 있으면 레코드를 쓴다.
- **bringup launch 인자의 뜻:** 전에는 `wheel_radius:=…`가 레코드에 지는 씨앗이었고, 이제는 레코드를 이기는 운영자 덮어쓰기다.
- **CORE LiDAR 정면:** 로컬 오버레이의 `line_follow.lidar_forward_deg`가 승인된 `lidar_mount` 레코드를 이긴다. 오버레이에 값을 둔 로봇은 배포 뒤 레코드가 아니라 그 값을 쓴다.
- **시작 캘리브레이션 인증서가 무효가 된다:** `lidar_yaw_offset`이 인증서 구성 지문에 들어간다(`calibration_sequence.py` 467행의 키 목록, `calibration_certificate.py` 77행의 `configuration_fingerprint` 비교). 190° → 180°로 바뀌면 기존 인증서는 맞지 않으므로 배포 뒤 시작 캘리브레이션을 다시 돌린다.
- **바퀴 레코드는 배포 전이나 함께 승인한다:** 8kcn(0.0272 / 0.0975)과 9dfk(0.0266 / 0.0953)의 `wheel_odometry` 레코드를 승인해 두지 않으면 두 로봇은 NOMINAL 0.028 / 0.0971로 달린다.
- **sim 랩을 다시 돈다:** `map_v2_fleet_lane`의 line_observer 카메라 x 0.034 → 0.028481, `map_v2_fleet_real`의 `cam_mount_z` 0.05307 → 0.0495. 랩 합격은 이 변경 전 값으로 받은 것이다.
- **재생 결과(리뷰, 2026-10-01):** 보정 안 된 기본 프로필로는 target-on-paint가 1.5 % → 5.5 %로 오른다(none 234 → 139). 보정된 프로필은 변하지 않는다. 즉 NOMINAL 높이 변경은 보정이 없는 로봇에서 차선 투영 결과를 실제로 바꾼다.
- **열린 질문:** 기기의 calib_node 스냅샷(저장된 sensing 캘리브레이션 yaml)이 아직 `lidar_yaw_offset` ≈ 190°를 들고 있을 수 있다. 그 스냅샷이 `robot.yaml`보다 우선하면 sensing은 계속 190°로 돈다. 배포 전에 각 로봇의 스냅샷 값을 읽어 확인해야 한다(이 ADR은 로봇에 접속하지 않았다).

### 하지 않은 것

- `robot_radius` 0.076(병진 원 반경)을 0.083/0.088로 올리지 않았다. 정지 거리 바닥(76 + 17 + 18 mm)과 좁은 통로 여유가 이 값에서 나오므로, 바꾸려면 안전 봉투를 다시 정하는 별도 결정이 필요하다.
- sensing safety 노드의 `lidar_yaw_offset`은 여전히 파라미터 값을 쓰고 `lidar_mount` 레코드를 읽지 않는다. 레코드가 sensing 안전 경로를 다듬게 하는 것은 별도 변경이다.
- 시뮬레이션 계획 반경(`robot_radius` 0.086, 여유 포함), 미로 생성기의 다른 로봇 모델(`gen_maze_world.py` 0.164/0.028), 검토 안 된 원형(`tools/perception/prototype/`)은 바꾸지 않았다.

### Validation

- `python tools/calibration/urdf_nominal.py --check`와 `tools/calibration/test/test_urdf_nominal.py`(재생성 비교, 손 계산 재현, 소비자 드리프트, 지원하지 않는 xacro마다의 실패 테스트).
- 순서·타당성 테스트: `src/contracts/foundation/test/test_calibration_store.py`(세 종류, 비현실적 덮어쓰기 거부), `src/products/pinky_pro/bringup/test/test_wheel_calibration.py`, `src/runtime/gateway/test/test_pinky_lidar_forward_device.py`, `src/runtime/gateway/test/test_lidar_mount_source.py`, `src/runtime/sensing/test/test_calibrated_values.py`.
- 호스트 pytest 통과는 기기·실주행 수용이 아니다. 배포 뒤 각 로봇에서 측정 레코드 승인 여부와 주행 거리를 다시 본다.
