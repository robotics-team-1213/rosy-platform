# control 구조 평가 — 무엇을 어떤 순서로 고칠 것인가

**작성:** 2026-09-22. **결정:** [D-171](../adr/D-171-control-structural-refactor-order.md).
**선행:** [D-168](../adr/D-168-ros-package-structure-standard.md) 구조 기준,
[control 패키지 분리 설계](2026-09-22-control-package-split-design.md),
[module split criteria](2026-09-06-module-split-criteria.md)(C1/C2/X1–X6).

## 1. 질문

control(제품 코드 약 23.5k줄)을 고치는 작업은 세 가지로 나뉜다.

- 라이브러리 모듈에서 ROS를 걷어내는 일
- 노드 파일 안의 판단을 밖으로 뽑는 일
- 패키지를 나누는 일

지금까지는 줄 수(D-168 P6)와 배포 단위(P1a)를 보고 "무엇을 나눌까"를 파일 하나씩 판정했다. 이 문서는
그 대신 **하나의 척도로 세 작업을 비교**해 순서를 정한다.

## 2. 척도

**host에서 시험할 수 있는 판단의 비율.** 판단이란 제품 모듈의 AST에 있는 `If`·`IfExp`·`BoolOp`·
`Compare`·`Match` 노드다. 분기, 임계, 비교가 여기에 든다.

어떤 모듈 내부 import 폐쇄에 ROS(rclpy, `*_msgs`, tf2_ros 등)가 하나라도 있으면, 그 모듈은 host
pytest가 import할 수 없다. 그 모듈 안의 판단은 09-06 C1의 정의 그대로 "host가 볼 수 없는 결정"이다.

- **이유:** 줄 수는 09-06 X1이 말하듯 분리 근거가 못 된다. 반면 이 척도는 안전 판단이 실제 값으로
  시험될 수 있는지를 직접 잰다. control의 판단 중 상당수(교정 게이트, 안전 게이트, 주행 판정)는
  `/cmd_vel_raw` 후보와 `calibration/ready`로 이어지므로, 시험 가능성이 곧 안전 증거의 질이다.
- **한계:** 판단 수는 복잡도의 대리값일 뿐이다. 시험이 그 판단을 실제로 덮는지는 따로 확인해야 한다.
  아래 §5가 그 사례다.

## 3. 측정 결과 (2026-09-22, main `11f1164`)

| 항목 | 값 |
|---|---|
| 제품 모듈 (`control/`, `tools/`·`map/` 제외) | 147개, 23,506줄 |
| 판단 | 8,014 |
| host import 가능 모듈 | 111 |
| **ROS에 묶인 판단** | **2,845 (36%)** |
| └ 노드 14개 안 | 1,449 |
| └ 노드가 아닌 모듈 19개 안 ("누출") | 1,388 |
| (참고) `tools/` 시뮬 도구 | 43개, 판단 1,011 중 56%가 ROS에 묶임 |

**누출**이란 노드가 아닌데 ROS 타입을 직접 import하는 모듈을 말한다. 노드는 `Node`를 상속한 클래스를
정의한 모듈이다. 누출 19개 가운데 셋은 ROS를 다루는 것이 역할인 **경계 어댑터**다.

- `tf_buffer`: tf2 Buffer 래퍼
- `web_map_control`: slam_toolbox 서비스 클라이언트
- `sensor_provider`: D-126 진입점

나머지 **16개가 진짜 누출**이며, 판단 1,339개와 3,345줄을 담고 있다.

누출 모듈은 대부분 메시지 객체를 **만들기만** 한다. ROS 이름을 쓰는 곳의 수는 이렇다.

| 모듈 | 판단 | ROS 이름 사용 |
|---|---|---|
| `calibration_rotation` | 187 | `Twist` 1곳 |
| `calibration_atomic` | 75 | `String` 1곳 |
| `calibration_relocation` | 81 | 3곳 |
| `wander.judge` | 139 | `Twist` 5곳 |
| `wander.contact` | 57 | `Twist` 6곳 |
| `goal_escape` | 39 | `String` 4곳 |
| `wander.navigator` | 209 | 26곳 (TF 조회 포함 — 가장 무거움) |
| `wander.senses` | 137 | 27곳 (메시지 언팩) |

이 모듈들의 판단을 import하는 host 시험은 거의 없다. 이들이 값을 돌려주고 메시지는 노드가 만들게
하면, 판단 1,388개가 host로 넘어온다. 고정점 계산으로 확인했다. 누출 모듈끼리 서로 import하기
때문에, 하나씩 풀면 연쇄로 풀린다.

## 4. 세 작업의 비교

| 트랙 | 대상 | host로 넘어오는 판단 | 비용 | 위험 | 필요한 검증 |
|---|---|---|---|---|---|
| **1. ROS 타입은 노드 경계에서만** | 누출 16개 | ~1,339 (고정점으로 1,388) | 낮음: 모듈당 메시지 생성 1~27곳을 노드로 이동 | 낮음: 판단 코드는 그대로 두고 반환형만 바뀜 | host pytest + 해당 노드의 ROS 스모크 |
| **2. 노드 안 판단 추출** | 노드 14개 | 최대 1,449 (파일마다 설계에 따라) | 높음: 상태 구조 설계, AST 시험 재배치 | 중~높음: 교정·안전 게이트 순서 | host pytest + ROS-SIM rig 시나리오 |
| **3. 패키지 분리** | `control_sensing`/`control_safety` | **0** | 높음: import 약 200줄, 시험 122개, 배포 5곳 | 중간: provider 이름, 이미지 구성 | 이미지·배포 계약 시험, DEVICE readback |

패키지 분리는 배포 이미지를 줄이는 이득(P1a)만 준다. host 시험 가능성은 조금도 올리지 않는다. 또한
트랙 1이 끝나면 옮길 모듈 대부분이 ROS 없는 순수 모듈이 되므로 이동도 쉬워진다. 그래서 순서는
**1 → 2 → 3**이다.

## 5. 교정 클러스터 (트랙 2의 첫 대상)

`startup_calibration_node.py`(955줄, 판단 418)와 `calib_node.py`(642줄, 판단 193)를 읽기 전용으로
분석했다.

- **C1이 발화한다.** 두 파일 모두 rclpy를 import한다. 그래서 시험 9개 파일의 50개 시험이 메서드를 AST로
  떼어 `exec`로 돌린다. 이 우회 자체가 C1의 증상이다.
- **C2는 발화하지 않는다.** startup은 50 ms 타이머 하나(단계 7개를 하나의 생애주기로 디스패치)이고,
  calib은 주기 타이머 둘과 1회성 타이머 하나다.
- **실제 값으로 시험되지 않는 판단**
  - startup: 스탬프 창(−0.2..max_age, 단계별 0.2/0.25/1.0 s), 재배치 기한, odom 쿼터니언 노름
    0.9–1.1, IR·초음파 범위, IMU(중력 8–11.5, 자이로 <0.15 — 단계 4개는 예외, 기울기 <20°, deg/s 변환),
    카메라(평균 5–250, 대비 ≥2).
  - **발행되는 준비 완료 판정:** 상태 딕셔너리의 `'ready'`는 기존 설정 모드에서 뒤따르는
    `**configured_status(...)`가 덮어쓴다. 의도된 동작일 수 있지만, 주행 허용을 정하는 판단이 딕셔너리
    병합 순서에 숨어 있고 노드 수준 시험이 없다. `calibration/ready`의 소비자는
    `safety/node.py`, `wander/node.py`, `web_node.py` 셋이다.
  - calib: 모듈 수준 순수 함수 5개(`ir_valid` 50..4000, `looks_floor`, `looks_cliff`,
    `approach_heading`, `snap_lidar_yaw`)와 절벽 임계 계산(`th = cliff_hi + 0.4·gap`). 이를 참조하는
    시험은 없다. `test_os_calibration_commit.py`는 `ir_valid`를 항등 함수로 바꿔 넣는다. 확인함.
- **숨은 결합 — 시뮬 시간.** `tools/gz/calibration_mapping_rig.py`는 모듈 전역 `time`을 모의 시간으로
  바꿔 끼운다. 대상은 10개 모듈이다(`calibration_mapping_rig.py:195-199`).
  - 교정: `startup_calibration_node`, `calibration_rotation`, `calibration_atomic`
  - 안전: `safety.node`, `safety.evidence`, `safety.bumper`
  - 주행: `wander.node`, `wander.senses`, `wander.judge`, `goal_node`

  트랙 1이 고칠 누출 중 넷(`safety.evidence`, `safety.bumper`, `wander.senses`, `wander.judge`)이 이
  목록에 있다. 이 모듈들은 `import time`과 `time.monotonic()` 호출 형태를 유지해야 한다. 새 모듈이
  `time.monotonic()`을 직접 부르면 이 교체 대상에서 빠진다. 그러면 1 s 히스테리시스, 0.75 s 신선도, 2 s 정지 기한이 가속 시뮬에서 벽시계로 돌아
  조용히 어긋난다.
- **calib의 절벽 로직은 시뮬로 검증할 수 없다.** rig가 IR을 상수 `[2000, 2100, 2200]`으로 발행하기
  때문이다. 벤치나 DEVICE 실행이 필요하다.

## 6. 트랙별 완료 조건

- **트랙 1**
  - `test/test_control_ros_edge.py`의 `KNOWN_ROS_LEAKS`가 빈 집합이 된다.
  - 모듈을 하나 고칠 때마다, 그 모듈을 쓰는 노드의 host 시험과 ROS 스모크를 함께 돌린다.
- **트랙 2**
  - 파일마다 추출 대상 판단에 실제 값 host 시험이 생긴다.
  - 그 판단을 AST로 떼어 돌리던 시험은 새 모듈을 직접 import하도록 바꾼다.
  - `calibration/ready`에 닿는 변경은 rig 기본 시나리오(`RIG_COMPONENT=all`과 분리 모드)와
    비상정지 음성 사례를 ROS-SIM에서 통과해야 병합한다.
- **트랙 3:** 분리 설계 문서 §6의 2~5단계를 따른다.

## 7. 재현

측정은 AST 정적 분석으로 했다. 판단 수, 직접 ROS import, 내부 import 폐쇄로 본 host import 가능성,
시험 파일의 import와 소스 경로 참조를 셌다. 누출 목록은 `test/test_control_ros_edge.py`가 매 실행마다
다시 도출해 기준선과 대조한다. 판단 수 같은 나머지 수치는 이 문서 작성 시점의 일회성 측정이다.
다시 잴 때는 §2의 정의를 그대로 쓴다.

## 8. 첫 적용에서 드러난 것 (2026-09-23)

트랙 1의 첫 모듈 `calibration_atomic`을 D-171 규칙 (d)로 검증하면서 세 가지가 드러났다.

- **교정 ROS-SIM 경로가 끊어져 있었다.** `run_calibration_spaces.py`가 실행하는
  `tools/gz/run_track260905.sh`는 흡수 때 빠져서, 보관된 옛 Rosy Control 저장소에만 있었다. 이 스크립트를
  live 경로(`rosy_control/`을 `control/`로)에 맞춰 이식했다. 한 프로세스 모드(`RIG_SINGLE_PROCESS=1`)와
  비상정지 음성 사례(`RIG_ESTOP_PROBE=1`, `rig_estop_probe.py`)도 추가했다.
  `src/apps/control/test/test_rig_script_references.py`는 rig가 없는 스크립트를 참조하면 적색이 된다.
- **rig는 ext4에서 돌린다.** WSL `/mnt/f`(Windows 파일 시스템)에서 돌린 첫 실행은 시험 주행 시작 시
  오도메트리 나이 0.22 s(허용 0.2 s)로 실패했다. 같은 코드를 `/tmp` 복사본에서 돌리면 통과한다.
  `/mnt/f`에서는 기준본을 돌리지 않았으므로 원인을 파일 시스템 지연으로 확정하지는 않는다.
- **미해결 — 한 프로세스 모드 결함.** `RIG_COMPONENT=all`은 노드 7개를 `SingleThreadedExecutor` 하나에
  싣는다. 이 모드에서는 시험 주행 도중 안전 게이트 출력이 신선도 창(0.25 s)을 벗어나 교정이
  "Fresh final safety command evidence required"로 `failed`가 된다. 기준본(HEAD)과 후보본이 같은
  메시지로 실패하므로 기존 결함이다. 분리 모드에서는 기준본과 후보본 모두 이 메시지가 0회였다.
  D-171 규칙 (d)는 이 모드에 대해 A/B 동등만 요구하도록 개정했다.

| 검증 (`calibration_atomic`, rig 기본 시나리오, ext4) | 기준본(HEAD `10ceb53`) | 후보본 |
|---|---|---|
| 분리 모드 | `ready` (sim 179.5 s) | `ready` (sim 180.0 s) |
| 비상정지 음성 | — | `failed` "Emergency stop engaged" (`validating_motion`에서 누름) |
| 한 프로세스 모드 | `failed` 게이트 신선도 (sim 19.0 s) | `failed` 같은 메시지 (sim 28.5 s) |
| `/cmd_vel` 발행자 | `safety_node` | `safety_node` |
