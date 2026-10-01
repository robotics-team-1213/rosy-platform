# CORE 안전 정책 — 그림자 모드로 켜고, 근거를 모아 집행한다

- 날짜: 2026-10-01
- 상태: 설계 승인(사용자, 2026-10-01). 구현 전. ADR: [D-400](../adr/D-400-core-safety-policy-off-shadow-enforce.md) (Proposed)
- 브랜치: `docs/core-safety-policy-shadow`
- 잇는 결정: D-47(센서 어댑터 보정 바인딩)과 2026-10-01 addendum(보정 저장소), D-397(URDF NOMINAL < 승인 레코드 < 운영자), D-66(CORE 이미지 슬라이스), D-149/D-208(단일 최종 발행자), D-344 §11·§12(라인 추종 전방 정지·IR guard), D-379(실주행 녹화)

## 1. 문제

CORE의 LiDAR/IR/IMU 안전 정책(`control.sensor_adapter`)은 어느 로봇에서도 켜져 있지 않다.

- `rosy_default.yaml:35`는 "켜기 전까지 CORE는 정지 상태로 남는다"고 적지만 사실이 아니다. `safety.control_policy_required` 기본값이 `false`라 `SafetyManager.evaluate_candidate`(`src/runtime/services/core_features/safety/manager.py:337`)가 명령을 그대로 통과시킨다. readiness HOLD(`bridge/cmd_vel.py:65`)는 이 어댑터를 보지 않는다.
- 그래서 지금 Nav2·teleop 주행의 보호는 Nav2 costmap 회피와 CORE 속도 상한뿐이다. 전방 LiDAR 정지는 라인 추종에만 있다(D-344 §11).
- 그냥 켤 수도 없다.
  - 보정 파라미터가 없으면 워커의 `safety_max_linear` 기본값 0.014 m/s(`sensing/config/robot.yaml:14`, `safety/node.py:114`)가 모든 직진 속도를 1.4 cm/s로 묶는다.
  - 센서가 끊기거나 부팅 직후 첫 스냅샷 전에 0이 아닌 명령이 오면 e-stop이 래치된다(`command/manager.py:209-214`).
  - 보정 레코드는 `calib_node` 형식(D-47 본문)만 읽는다. 이번 주 만든 D-47 addendum 저장소(JSON)와 D-397 URDF NOMINAL은 읽지 않는다.
  - CORE 이미지에 `control` 슬라이스가 없다(D-66). 켜면 CORE가 시작하지 못한다.
  - Gazebo는 `ir_sensor/range`를 발행하지 않는다(`gz_multi.launch.py:236-243`).

## 2. 목표와 비목표

목표

1. 정책을 **판정만 하고 집행하지 않는** 그림자 모드로 Gazebo와 실주행에서 돌려, 집행했을 때의 정지·제한을 측정한다.
2. 측정 근거와 사용자 승인으로 로봇별 집행 모드로 넘어간다.
3. 어댑터 파라미터를 보정 저장소 하나(URDF NOMINAL < 승인 레코드 < 운영자)에서 얻는다.
4. 지금 정책이 꺼져 있다는 사실을 운영자가 화면에서 본다.

비목표

- 정책 규칙(`command_gate.py`) 자체를 바꾸지 않는다. 판정 내용은 측정 대상이다.
- 로봇 배포·SSH는 이 설계의 범위가 아니다. 각 장치 단계는 사용자 승인 뒤 별도로 한다.
- 관제(Fleet) 쪽 변경 없음. 관제↔로봇 소통(B), STOP ALL(C), 관제 미션(D)은 별도 설계다.

## 3. 설계

### 3.1 정책 모드: `off | shadow | enforce`

`control.sensor_adapter.mode`가 `enabled: bool`을 대신한다.

| mode | 워커 | 판정 | `cmd_vel` 영향 | 센서 끊김 |
|---|---|---|---|---|
| `off` (기본) | 만들지 않음 | 없음 | 없음 (지금과 같음) | 해당 없음 |
| `shadow` | 만듦 | 매 후보마다 계산·기록 | **없음** | 기록만 (`unavailable`) |
| `enforce` | 만듦 | 매 후보마다 계산 | 판정대로 제한·정지 | 3.4절 |

- 하위 호환: `enabled: true`는 `enforce`, `enabled: false`는 `off`로 읽는다. `enabled`와 `mode`를 함께 쓰면 설정 오류로 시작을 거부한다.
- `mode`가 `off`가 아니면 `required`·파라미터·보정 검증을 지금처럼 시작 전에 한다. 실패하면 CORE가 시작하지 못한다(D-47 그대로). 단 `shadow`에서는 "실패하면 시작 거부"가 운영을 막을 이유가 없으므로 **`shadow` 구성 실패는 경고 후 `off`로 내려간다**(상태에 `mode_effective: off`, `mode_error` 표시). `enforce` 구성 실패는 지금처럼 fail closed.
- `safety.control_policy_required`는 `enforce`일 때만 의미가 있다. `shadow`에서 이 값이 `true`면 설정 오류다.

### 3.2 그림자 판정 경로

`SafetyManager`에 정책 모드를 둔다. `CommandManager.select_output`이 후보를 고른 뒤:

- `enforce`: 지금 경로 그대로(`evaluate_candidate` → 제한·정지·래치).
- `shadow`: 같은 `evaluate_candidate`를 호출하되 **결과를 출력에 쓰지 않고, e-stop 래치·모드 전환을 하지 않는다.** 판정과 실제 출력을 `ShadowVerdict`로 남긴다.

```
ShadowVerdict
  t, command_id, source, scope           # 후보 정보
  commanded (v, w), output (v, w)        # 실제 나간 값
  verdict: allow | limit | stop | unavailable
  limited (v, w)                         # 집행했다면 나갔을 값
  reason                                 # policy_reason 또는 decision.reason
  eval_ms                                # 평가 시간 (10 ms 예산 대비)
```

- 0 명령(정지 중)은 평가하지 않는다. `enforce`도 0이 아닌 후보만 평가하므로 같은 기준이다.
- 평가 중 예외는 `unavailable`/`policy_failed`로 세고 출력에는 손대지 않는다.
- 판정은 ROS-free 모듈(`core_features/safety/shadow.py`)이 집계한다. bridge는 시계와 발행만 한다(bridge AGENTS.md: 정책은 bridge에 두지 않는다).

기록 경로(세 갈래, 모두 같은 `ShadowVerdict`에서 나온다)

1. **이벤트:** 판정 상태가 바뀔 때만 `safety.shadow_verdict`를 낸다(allow→stop 같은 전이). 같은 상태 반복은 최대 1 Hz로 묶는다.
2. **상태:** `/api/v1/robot/state`의 `safety_policy` 블록 — `mode`, `mode_effective`, `revision`, 판정별 누적 카운터, 마지막 `stop`/`unavailable`의 시각·이유, `eval_ms` p50/p99.
3. **녹화:** CORE가 `safety/shadow`(`std_msgs/String`, JSON 한 줄)를 전이 때만 발행한다. 실주행 녹화(D-379 `rosy_rec.sh`)의 토픽 목록에 더해 주행 영상·LiDAR와 함께 재생·분석한다. 이 발행자는 Twist가 아니다. `test_bridge_timers.py`의 발행자 고정 목록(5 → 6)을 함께 고친다.

CPU: 그림자 모드는 매 후보(최대 50 Hz)마다 평가한다. D-185 CPU 예산 안인지 Gazebo에서 `eval_ms`와 CORE CPU를 재고, 넘으면 평가 주기를 20 Hz(워커 tick과 같음)로 낮춘다.

### 3.3 파라미터 출처: 보정 저장소 하나

새 ROS-free 리졸버 `core/safety_params.py`가 워커 파라미터를 만든다. 두 묶음이다.

| 묶음 | 키 | 우선순위 (낮음 → 높음) |
|---|---|---|
| 보정 (D-47 허용 목록 7개) | `lidar_yaw_offset`, `imu_roll0`, `imu_pitch0`, `cmd_linear_sign`, `cliff_mode`, `cliff_raw_max`, `cliff_clear_raw` | 정적 씨앗 < D-47 저장소의 승인된 레코드 < 운영자 overlay |
| 봉투 (envelope) | `safety_max_linear`(워커 기본 0.014), `safety_max_angular`(기본 0.10) | 제품 프로필 한계(`products/<robot>/profile`) < 운영자 overlay |

- `lidar_yaw_offset`의 정적 씨앗은 URDF NOMINAL(`geometry.yaml` `lidar.forward_deg`, D-397)이고, 승인된 `lidar_mount` 레코드가 다듬는다. `core/lidar_mount.py`와 **같은 해석 함수**를 써서 라인 추종과 안전 정책이 한 값을 본다. 지금의 "어댑터 값과 3° 넘게 다르면 경고"는 둘이 같은 출처가 되므로 필요 없어진다.
- IMU·cliff·`cmd_linear_sign`은 기하가 아니다. 정적 씨앗은 지금의 `auto_calib.yaml`/`robot.yaml` 값이고, D-47 저장소에 새 레코드 종류(`imu_zero`, `cliff_ir`, `motion_sign`)를 더해 다듬는다. 레코드 승인은 지금처럼 운영자만 한다(`store_cli.py accept`). `check_values`에 세 종류의 타당 범위를 더한다.
- 봉투 두 값은 CORE의 속도 상한(`safety.fleet_linear`·`manual_linear`, `fleet_angular`·`manual_angular`, 프로필 최대값) 중 가장 큰 값보다 작으면 안 된다. 작으면 그림자 판정이 항상 `limit`이 되어 측정이 의미를 잃는다. 리졸버가 이 관계를 시작 때 검사한다.
- 결과에 출처를 붙인다(키마다 `nominal | record:<id>@<sha> | overlay`). 보정 revision = 결정된 파라미터와 레코드 id·sha의 sha256. 워커의 profile revision과 정책 바인딩에 이 값을 쓴다.
- **`calib_node` 레코드 경로(`calibration.required/path/context`)는 어댑터가 더 이상 읽지 않는다.** 설정에 남아 있으면 경고하고 무시한다. `calib_node`의 실시간 `safety_node/set_parameters`는 워커 이름이 바뀌어(3.5절) 닿지 않는다.

### 3.4 집행 모드의 센서 끊김

`enforce`에서 판정이 없거나(`policy_unavailable`·`policy_failed`) 근거가 낡았을 때:

| 상황 | 동작 |
|---|---|
| 부팅 후 첫 유효 판정 전 | HOLD — 출력 0, 래치 없음. readiness 사유 `safety_policy_warming`. 대시보드에 "안전 정책 준비 중" |
| 주행 중 끊김이 `stale_hold_s`(기본 2.0 s) 미만 | HOLD — 출력 0, 판정이 돌아오면 다음 후보부터 재개. `safety.policy_hold` 이벤트 |
| 끊김이 `stale_hold_s` 이상 | 지금처럼 e-stop 래치 + EMERGENCY. 관리자 해제 |
| 판정 `stop` (픽업·기하 무효·위치 상실 등) | 지금처럼 래치 |
| 장애물·절벽 → `motion_limited` v=0 | 지금처럼 출력 0, 래치 없음 |

`stale_hold_s`는 `(0, 5]`만 받는다. 끊긴 시간은 마지막 유효 판정의 `observed_at`부터 잰다.

### 3.5 정리 항목 (1단계)

1. `rosy_default.yaml` 주석을 실제 동작으로 고친다(`mode: off` — 정책 없이 통과한다).
2. `core/node.py:87-92`가 `ROSY_DATA_PATH`를 패키지 기본 `data_root`(`/var/lib/rosy`) 때문에 적용하지 못하는 버그는, 3.3절로 어댑터가 `calibration.*` 블록을 읽지 않게 되면서 그 코드와 함께 지운다. 리졸버가 읽는 보정 저장소 루트는 D-47 addendum의 규칙(`ROSY_CALIBRATION_ROOT`가 기본 경로를 이긴다)을 그대로 쓴다.
3. 워커 노드 이름 `safety_node` → `core_safety_worker`. 레거시 `safety_node`와 이름이 겹치지 않고, `calib_node`의 실시간 파라미터 변경이 CORE 워커에 닿지 않는다. `control/watch.py`의 `EXCLUSIVE` 집합과 그래프 고정 시험을 함께 고친다.
4. `mode`·`mode_effective`를 상태와 대시보드 장치 카드에 보인다. `off`인 채로 NAVIGATION에 들어가면 `safety.policy_off` 경고 이벤트를 세션당 한 번 낸다.
5. LiDAR 정면 180°(이미 `origin/main`) 배포 준비: Gazebo `map_v2_fleet_lane` 랩을 180°로 다시 돌려 증거를 남긴다. 로봇 배포는 별도 승인.

### 3.6 Gazebo와 이미지

- Gazebo 프로필: `gz_multi.launch.py`의 CORE overlay(`_core_config`)에 `control.sensor_adapter: {mode: shadow, required: [lidar, imu], parameters: {cliff_enable: false}}`를 둔다. IR은 시뮬에 없으므로 cliff를 끈다는 사실을 상태의 `required`에 그대로 보인다.
- CORE 이미지: `control` 슬라이스(센서 워커와 `rosy.sensor_provider` 진입점)를 포함한다. D-66을 개정한다. 이미지에 들어가도 `mode: off`가 기본이므로 동작은 바뀌지 않는다.

## 4. 단계와 게이트

| 단계 | 내용 | 끝나는 조건 | 장치 |
|---|---|---|---|
| 1 정리 | 3.5절 1–4 | host pytest, 대시보드 브라우저 시험 | 없음 |
| 2a 모드·리졸버 | 3.1, 3.3 | host pytest(아래 5절) | 없음 |
| 2b 그림자 경로 | 3.2 | host pytest, 출력 비간섭 증명 | 없음 |
| 2c Gazebo 그림자 | 3.6 + 랩·Nav2 주행 | 아래 G-sim | 없음 |
| 2d 이미지 | D-66 개정, ARM64 빌드 | CI 빌드·부팅 스모크 | 없음 |
| 2e 장치 그림자 | 로봇별 `mode: shadow` | 아래 G-dev | **사용자 승인** |
| 3 집행 | 3.4, 로봇별 `mode: enforce` | 아래 G-enforce | **사용자 승인** |

게이트

- **G-sim:** `map_v2_fleet_lane` 랩 3회 + Nav2 목표 주행 20회에서, 장애물이 없는 구간의 `stop` 판정 0건, `unavailable`은 시작 후 워밍업 구간에만, `eval_ms` p99 ≤ 10 ms, CORE CPU 증가가 D-185 예산 안.
- **G-dev:** 로봇마다 실주행 그림자 로그 30분 이상. `stop`·`limit` 판정마다 녹화로 원인을 분류(실제 위험 / 오탐). 오탐 비율과 끊김 빈도를 기록.
- **G-enforce:** G-dev 오탐 0건(또는 원인을 고친 뒤 재측정), 해당 로봇의 보정 레코드(`lidar_mount`·`imu_zero`·`cliff_ir`·`motion_sign`) 승인, 사용자 승인.

## 5. 시험

host pytest (ROS 없음)

- `mode` 파싱: 세 값, `enabled` 하위 호환, 둘 다 있으면 거부, `shadow`+`control_policy_required: true` 거부.
- `shadow` 구성 실패 → `mode_effective: off` + 경고, `enforce` 구성 실패 → 시작 거부.
- **비간섭:** 같은 후보 열에 대해 `off`와 `shadow`의 `select_output` 출력이 비트 단위로 같고, `shadow`에서는 e-stop·모드가 바뀌지 않는다(판정을 `stop`·예외·지연 초과로 강제해도).
- 리졸버: 우선순위 세 층, 허용 목록 밖 키 거부, `check_values` 범위 밖 레코드·overlay 무시, 출처 표기, revision 결정성, `safety_max_linear` < CORE 상한 거부, `lidar_mount.py`와 같은 값.
- 3.4 경계: 첫 판정 전 HOLD, `stale_hold_s` 직전 HOLD·재개, 직후 래치.
- 이벤트 묶음: 전이만 내고 반복은 1 Hz 이하.
- 환경변수 우선순위(`ROSY_DATA_PATH`·`ROSY_DATA_GENERATION`).

ROS / Gazebo

- `test_bridge_timers.py`: 발행자 6개(`safety/shadow` 추가).
- 그래프 시험: `/cmd_vel` 발행자는 여전히 `core` 하나, 워커 노드 이름 `core_safety_worker`.
- G-sim 증거는 `X:\DevTemp`에 원본, 요약은 `docs/logs.md`.

## 6. 위험

| 위험 | 대응 |
|---|---|
| 그림자 평가가 Pi CPU를 먹는다 | `eval_ms`·CPU 측정, 20 Hz로 낮출 여지(3.2) |
| 그림자에서 오탐이 많아 집행 전환이 무기한 늦어진다 | 오탐은 원인별로 분류해 정책·보정 쪽 별도 수정으로 넘긴다. 집행은 로봇별이라 한 대씩 갈 수 있다 |
| 보정 저장소에 새 종류 세 개를 더하면 D-47 addendum의 운영 절차가 늘어난다 | 정적 씨앗으로 시작해 그림자를 돌릴 수 있고, 레코드 승인은 G-enforce 조건일 뿐이다 |
| `calib_node` 레코드를 쓰던 경로를 끊는다 | 어느 장치 설정도 그 경로를 켜지 않았다(저장소 검색 결과 0건). 설정에 남아 있으면 경고 |
| `enforce` 래치가 운영을 자주 끊는다 | 3.4의 HOLD 구간, G-dev의 끊김 빈도 측정 |
