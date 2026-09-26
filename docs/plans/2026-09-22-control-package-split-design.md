# control 패키지 분리 설계

**상태:** Proposed (2026-09-22). 0단계와 1단계의 `web_node.py`까지 실행했다(§6). 실행은 단계별
커밋으로 하며, 각 단계는 host pytest와 D-168 구조 시험이 초록인 상태로 끝난다.
**근거 기준:** D-168 P1(패키지 인정)·P6(줄 수 예산), `2026-09-06-module-split-criteria.md` C1/X6.
**순서 (D-171, Accepted):** 이 문서의 패키지 분리(§6의 2~5단계)는 트랙 3이다. 트랙 1(ROS 타입은 노드
경계에서만)과 트랙 2(노드 판단 추출, §4의 교정 파일 2개가 첫 대상) 뒤에 한다. 근거와 수치는
[control 구조 평가](2026-09-22-control-structural-evaluation.md)에 있다.
**소유:** `test/test_module_structure.py`의 `SIZE_VERDICTS`에서 `control`,
`startup_calibration_node.py`, `calib_node.py`가 이 문서를 가리킨다(`web_node.py`는 600줄 아래로
내려가 판정이 삭제됐다).

## 1. 왜 분리하는가 — P1 판정

줄 수(제품 코드 약 28k, 패키지 예산 10k)는 검토를 강제했을 뿐이고, 분리 근거는 P1(a)다.

- **배포 단위가 다르다.** 배포 launch 폐쇄(`navigation/hardware.launch.py` →
  `control/line_follow.launch.py`)가 쓰는 control 실행 파일은 4개(`ir_adc_node`,
  `camera_detect_node`, `line_observer_node`, `road_observer_node`)뿐이다. 그런데 io 이미지는
  `deploy/robot/Dockerfile:117-122`에서 control 전체를 복사한다. 여기에는 레거시 비교 그래프,
  교정 도구, 디버그 웹, `tools/gz`가 모두 들어 있다.
- **core가 싣는 provider도 별도 단위다.** `rosy.sensor_provider: control`(D-126)은
  `safety.node.SafetyNode`(sensor_only)와 `command_gate` 폐쇄 약 36모듈·4.5k줄을 끌어온다.
  core 쪽 opt-in provider와 io 쪽 증거 노드는 서로 다른 설치 단위다.

P1(b) 계약 소유와 P1(c) 장애 격리는 발화하지 않는다. 이미 노드마다 별도 프로세스로 뜨기 때문이다.

## 2. 현재 구조 (2026-09-22 실측)

- **import 그래프는 비순환이다.** 비시험 모듈 128개와 `tools/` 40개에서 강결합 성분이 0개다.
- **층은 한 방향이다.** `sensing/*`(37, leaf) ← `control/control/*`(50) ←
  `planning/*`·`safety/*`·`wander/*` ← 노드 모듈 순서로 쌓인다.
- **가장 많이 쓰이는 모듈:** `sensing.lidar`(15), `tf_buffer`(7), `control.control.recover`(8),
  `rotation_envelope`(7).
- **진입점:** console_scripts 14개와 `rosy.sensor_provider` 1개다.

| 분류 | 진입점 |
|---|---|
| 배포 증거 노드 | `ir_adc_node`, `camera_detect_node`, `line_observer_node`, `road_observer_node` |
| core provider | `rosy.sensor_provider: control` (`sensor_provider.py`) |
| 레거시 최종 발행자 | `safety_node` (robot/wander/dashboard_control launch 전용) |
| 교정 도구 | `calib_node`, `startup_calibration_node` |
| 디버그 웹 | `web_node`, `watch_node` (D-150) |
| 레거시 내비 그래프 | `wander_node`, `goal_node`, `localization_node` |
| launch 참조 없음 | `obstacle_observer_node`, `control_node` |

## 3. 목표 구조 — 3개 패키지

모든 의존은 아래 방향으로만 흐른다: `control` → `control_safety` → `control_sensing`.
세 패키지 모두 `src/apps/`에 둔다(D-147, D-168 P4의 `apps` 행: core 계약만 의존).

| 패키지 | 내용 | 선언 의존(워크스페이스) |
|---|---|---|
| `control_sensing` | `sensing/*`, `tf_buffer`, 증거 노드 4개 + `obstacle_observer`/`localization`, `line_follow.launch.py`, `localization.launch.py`, camera/line_follow 설정 | 없음 |
| `control_safety` | `safety/*`, `control.control`의 안전 폐쇄(`command_gate`, `lidar_guard`, `obstacle_risk`, `motion_sweep`, `footprint_*`, `rotation_*`, `actuation`, `policy_handoff`, `escape_space`, `safety_profile`, `calibration_profile/certificate`, `route`), `calibration_{record,storage,lock,snapshot}`, `sensor_provider` + 진입점, `safety_node` | `control_sensing` |
| `control` (잔류) | wander, goal, planning, 나머지 `control.control`, 교정 노드 2개, web/watch, `control_node`, `tools/`, 레거시 launch, maps | `control_safety`, `control_sensing` |

결과: io 이미지는 `control_sensing`만 복사하면 된다. (2026-09-24 D-196 개정으로 바뀌었다 — 아래 개정 참고.) core가 provider를 쓸 때는
`control_safety`까지만 필요하다. 잔류 `control`은 개발·교정·레거시 비교용이다.

**4번째 `control_calibration`은 지금 만들지 않는다.** `startup_calibration`이 `planning`을
import하고 `tools/gz/calibration_mapping_rig`가 다시 `startup_calibration`을 import한다.
그래서 지금 떼어 내면 패키지 사이클이 생긴다. `planning`·`path_follow`·`pursuit`·`escape_budget`을
라이브러리로 먼저 뽑은 다음에 재검토한다(X3: 예정된 작업이 없으면 만들지 않는다).

**개정 (2026-09-24, D-196):** `control_sensing`에 넣기로 했던 것 중 장치 코드는 devices로 간다.
- `ir_adc_node`와 `sensing/ir_adc.py`는 `devices/pinky_pro`로 간다. D-192 §4의 0x08 독자를 한 계열에 모으기 위해서다.
- `camera_detect_node`의 캡처부와 `sensing/camera_controls.py`는 `devices/common/camera`로 간다.
- `control_sensing`에는 알고리즘만 남는다. line/road/dock observer는 `Image`를 구독하고, 카메라
  기하는 프로필/TF에서 받는다.

이 개정은 트랙 3의 첫 단계에서 함께 실행한다. io 이미지 폐쇄는 `devices/pinky_pro` + `devices/common/camera` + `control_sensing`이 된다.

## 4. 파일 단위 분리 (P6 `split` 판정 3건)

패키지 이동과 별개로, 같은 패키지 안에서 ROS와 무관한 부분을 형제 모듈로 뽑는다.
방식은 09-06 C1의 `bridge/translate.py` 선례를 따른다. 목표는 줄 수가 아니라 host 시험으로
검증되는 결정이다.

| 파일 | 현재 | 뽑을 것 |
|---|---|---|
| `web_node.py` (1,091 → 558, **완료 2026-09-22**) | `WebNode` 30메서드 430줄, 중첩 HTTP `_handler` 243줄, `MapControl`, PNG/카메라 렌더 | `web_render.py`(렌더, 순수 함수), `web_http.py`(요청 라우팅·파싱). 노드에는 ROS 구독과 배선만 남긴다 |
| `startup_calibration_node.py` (954) | `StartupCalibrationNode` 36메서드 890줄 | 교정 상태기계(단계 전이·판정 임계)를 `calibration_sequence.py`로. 노드는 타이머와 토픽 I/O만 |
| `calib_node.py` (640) | `CalibNode` 28메서드 516줄 + 순수 함수 7개 | 모듈 수준 순수 함수(`approach_heading`, `snap_lidar_yaw` 등)를 위와 같은 교정 모듈로 합친다 |

## 5. 막는 것

1. **D-149 기록 불일치 — 0단계에서 먼저 푼다.** D-149 승격 기록(`docs/logs.md`,
   2026-09-21)은 배포 폐쇄의 control 실행 파일을 3개로 적었다. 실제로는
   `line_follow.launch.py:53`의 `road_observer_node`가 조건 없이 뜬다. 관측 노드라서
   D-149의 취지(증거 생산만)는 지켜지지만, 기록과 계약 시험이 이 노드를 세지 않는다.
2. **provider 이름 유일성.** core는 진입점을 이름 `"control"`로 찾아 `matches[0]`을 쓴다
   (`control_sensor_adapter.py:119-145`). 이전 중에 두 패키지가 같은 이름을 등록하면 먼저
   찾은 쪽이 조용히 선택된다. 따라서 "`rosy.sensor_provider:control` 등록자는 정확히 1개"라는
   시험을 먼저 추가한다.
3. **Python 이름공간.** `control.control.*` 경로와 상대 import 약 204줄을 새 최상위 이름의
   절대 import로 바꿔야 한다.
4. **시험이 내부를 import한다.** 시험 157개 중 122개가 `control.*`를 import한다
   (`control.control` 66, `sensing` 43, `planning` 15). 36개는 경로로 소스를 읽는다.
5. **패키지 이름 참조.** 외부 launch·시험에 9곳이 있다(hardware.launch 1, gz_sim 6, 시험 2).
   배포 쪽은 `gz_sim/package.xml`, `deploy/image/required-ros-packages.txt:7`,
   `inputs.lock.yaml:130`, `deploy/robot/Dockerfile:117,122`이다. 문서의 `core/control`
   언급은 24개 파일에 124곳이다.
6. **X6 — 경합 확인.** 브랜치 `map-v2-fleet-world`가 `sensing/lane.py`, `sensing/lane_bev.py`,
   `line_observer_node.py`를 고치고 있었다. 2026-09-22 local main `5207531`에 병합되어 해소됐다.
   2단계를 시작하기 전에 그 시점의 다른 브랜치를 같은 방식으로 다시 확인한다.

## 6. 이전 순서

각 단계는 하나의 커밋 묶음이고, 끝나는 시점에 host pytest 전체와
`test/test_module_structure.py`가 초록이어야 한다.

0. **기록 정정 — 완료(2026-09-22).** D-149 Validation에 `road_observer_node`를 넣는 정정 문단을
   덧붙였다. `test/test_control_deploy_closure.py`가 systemd 유닛·compose에서 include 사슬을
   따라 배포 실행 파일을 도출해 네 개와 집합 동일성으로 고정하고, `rosy.sensor_provider:control`
   등록자가 정확히 1개임을 검사한다(변이 증명 3건). 3단계에서 진입점을 옮길 때 이 시험의
   기대 경로(`core/control/setup.py`)를 같은 커밋에서 바꾼다.
1. **파일 단위 분리(§4)** — `web_node.py` 완료(`web_state`/`web_http`/`web_render`/`web_map_control`, `test_web_http.py`). 교정 파일 2개는 남음. 패키지 경계를 바꾸지 않으므로 먼저 해도 되며, 이후 이동할 모듈 크기가
   줄어든다. `SIZE_VERDICTS`의 해당 항목은 파일이 600줄 아래로 내려가면 삭제한다(시험이 삭제를
   강제한다).
2. **`control_sensing` 신설** — 착수 전 X6 재확인. `sensing`·`tf_buffer`를 옮기고 `control/sensing/__init__`에
   재수출 shim을 둔다. 증거 노드와 `line_follow.launch.py`를 옮기고, 같은 커밋에서
   `hardware.launch.py`, gz_sim launch 2개, Dockerfile io 단계, `required-ros-packages.txt`,
   `inputs.lock.yaml`을 고친다. `navigation → control` 예외(D-168 `KNOWN_*`)는 이때
   `navigation → control_sensing`으로 바뀐다. 이 결합을 배포 조립층으로 올릴지는 같은 단계에서
   정한다.
3. **`control_safety` 신설.** 안전 폐쇄와 `sensor_provider`를 옮기고, 진입점을 옮기면서 같은
   커밋에서 옛 진입점을 지운다. 0단계의 유일성 시험이 이 단계를 지킨다.
4. **시험 이전.** 패키지별로 시험을 새 모듈 import로 옮기고, shim을 삭제한다.
5. **maps를 `navigation/map`으로 이동(D-150).** 그 뒤 gz_sim의 control share 참조를 걷어낸다.

## 7. 바뀌는 계약 시험

- `test/test_control_absorption_package.py` — 패키지 경로와 resource marker
- `test/test_control_launch_boundary.py` — 패키지 이름
- `test/test_module_separation.py` — `CONTROL_PKG`(:19), 레거시 발행자 경로(:58), `SLICE_TOPS`, `TOP_TO_PACKAGE`
- `test/test_line_follow_runtime.py` — Dockerfile COPY 문자열과 share 이름
- `test/test_module_structure.py` — `KNOWN_UNDECLARED`/`KNOWN_DIRECTION`, `SIZE_VERDICTS`
- `src/core/core/test/test_control_sensor_adapter.py`, `test_control_policy_link.py`
- `src/sim/gz_sim/test/test_map_v2_traversal.py`, `test_world_profiles.py`
- `tools/harness/harness.yaml` — 새 모듈 2개 등록(D-168 P2)

## 8. 하지 않는 것

- 레거시 비교 그래프(`safety_node` 최종 발행자 기본값)는 없애지 않는다. `control_safety`로
  옮길 뿐이며, 고정은 `test_module_separation`이 계속 맡는다.
- `wander`/`goal`/`localization` 레거시 내비 그래프를 새 패키지로 만들지 않는다(X3).
- `obstacle_observer_node`, `control_node`(launch 참조 없음)의 삭제는 이 설계 범위가 아니다.
  0단계 폐쇄 시험 결과를 보고 따로 판단한다.
