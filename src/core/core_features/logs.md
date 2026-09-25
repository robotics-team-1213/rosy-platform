# core_features logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-22 이전 이력은 `git log -- src/core/core_features`를 본다.

## 2026-09-22 · uncommitted · docs(harness): register core_features under D-168
- 변경: `AGENTS.md`(없던 경우), `progress.md`, `logs.md` 추가, `harness.yaml` 등록
- 증거: `PYTHONPATH=src/core:src python -m pytest src/core/core/test -q` — core suite 1056 passed, 12 skipped (2026-09-22 Windows); 28 core test files import core_features; no own test/ yet (D-168 KNOWN_WITHOUT_OWN_TESTS)
- gate 변화: 없음(신규 기록). SOURCE HOLD(자체 시험 없음), LOCAL GO(core 스위트), 나머지 N/A
- 결정: D-168
- 교훈: 없음

## 2026-09-22 · uncommitted · core_features(fleet_agent): 재접속 backoff 상한 30s (T5)
- 변경: `fleet_agent/agent.py` — MAX_BACKOFF_S=30.0 상수와 순수 헬퍼 next_backoff() 를 두고 _run 의 백오프 갱신이 이를 쓰게 교체(기존 인라인 60.0 cap 제거). 계약: API Ref §7.6 "1s→2s→…최대 30s"(PRT-006).
- 증거: `python -m pytest src/core/core/test/test_fleet_agent.py -q` 4 passed(신규 값 시험 next_backoff 1→2, 16→30, 30→30 — 적색 확인 후 초록). 근거: communication-protocol-report.md §5 편차 ①.
- gate 변화: 없음.
- 결정: 없음 — 계약 정합 수정.
- 교훈: 없음.

- 같은 세션 T6: RobotIdentity hello 신원 필드 additive + agent hello_payload 실값(근거·증거는 core_common 로그와 동일 세션 기록)

## 2026-09-23 · uncommitted · docs(adr): D-182·D-184 Proposed — 시뮬 리터럴과 시험 위치

- 변경: 안전 코드가 파티션·도메인 리터럴을 갖지 않는 결정과, 동작 시험은 패키지가 가진다는 결정을 진행 기록에 연결했다. `safety/manager.py`와 시험 디렉터리는 그대로다.
- 증거: ADR 기록. 실행 시험 없음.
- gate 변화: 없음. SOURCE HOLD 유지.
- 결정: D-182, D-184 Proposed
- 교훈: 없음

## 2026-09-24 · uncommitted · feat(safety): D-182 simulation actuation is a mode flag

- 변경: `safety/manager.py`가 파티션 이름과 도메인 227 대신 `ROSY_SIMULATION_ACTUATION=1`과 시뮬 시계를 본다.
- 증거: `test/test_policy_sim_literals.py`와 `src/core/core/test/test_control_policy_link.py` 포함 57 passed, 10 skipped (2026-09-24 Windows).
- gate 변화: 없음. SOURCE HOLD(자체 test/) 유지.
- 결정: D-182 Accepted
- 교훈: 없음

## 2026-09-24 · uncommitted · refactor(core): D-168 미사용 `core_events` 선언 제거

- 변경: `package.xml`의 `<depend>core_events</depend>` 제거 — `core_features`의 생산 import는 0건이고(생산 소비자는 오직 `core/core/services.py`), P3는 테스트 import를 결합으로 세지 않는다. `AGENTS.md` Key Files·금지사항·Internal과 `progress.md` 금지사항의 "Depends on" 문구를 `core_common`만으로 동기화.
- 증거: 커밋 직전 `python -m pytest test/ -q` 초록 — D-168 `test_module_structure.py` 포함 (2026-09-24 Windows).
- gate 변화: 없음. SOURCE HOLD(자체 test/) 유지.
- 결정: module-coupling-scorecard §6 과제 4 (D-168 P3 "선언한 결합이 실제로 쓰이는지" 정리).
- 교훈: 없음

## 2026-09-24 · uncommitted · test(core): docking·swarm 시험을 자체 `test/`로 이전

- 변경: `src/core/core/test/{test_docking,test_swarm}.py` → `src/core/core_features/test/`(`git mv`) + `test/conftest.py`(`core_features`·`core_common`·`control` sys.path — control은 `sensor_provider` adapter 한정, D-126). D-168 `KNOWN_WITHOUT_OWN_TESTS`에서 `core_features` 제거, `harness.yaml` 경로 갱신, AGENTS·progress 동기화, SOURCE gate HOLD→GO. `test_core_logic`·`test_line_follow_api`·`test_slam_reset`은 `core_client` fixture 혼재로 이번 회차 보류.
- 증거: `python -m pytest src/core/core_features/test -q` 140 passed (2026-09-24 Windows); 전체 게이트는 커밋 직전 실행.
- gate 변화: SOURCE HOLD→GO(자체 `test/` 확보), LOCAL GO 유지.
- 결정: module-coupling-scorecard §6 과제 2.
- 교훈: 없음

## 2026-09-24 · uncommitted · test(core): lane-network 주차 도크 시험을 자체 `test/`로 (main 병합, D-184)

- 변경: feat/lane-network-junctions 에 main(427ed9d9)을 병합하면서 D-184 `test_behavior_test_ownership` 이 브랜치의 새 `core/test` 시험 8개를 잡았다. `core_features` 동작만 보는 3개(`test_docking_parking.py`·`test_docking_parking_manager.py`·`test_docking_review_fixes.py` — `core`·`core_client` 미사용)를 `src/core/core_features/test/`로 `git mv`. CORE 자체 배선(`core.bridge.docking_mode`·`services.take_docking_mode`·`traffic_gate.line_clock`)을 보는 5개(`test_docking_mode_ownership`·`test_docking_mode_release`·`test_docking_parking_wiring`·`test_line_follow_sim_clock`·`test_mode_listener_isolation`)는 `KNOWN_EXTERNAL_BEHAVIOR_TESTS`에 주석과 함께 고정했다 — 4개가 `core_client` fixture 를 쓰고, main 도 같은 이유로 `test_core_logic` 등 3개를 보류했다.
- 증거: `python -m pytest src/core/core_features/test -q` 198 passed(140 + 이전 58), `python -m pytest test/test_behavior_test_ownership.py -q` 1 passed (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: 5개 고정은 병합 준비 단계의 잠정 판정이다. D-184 결정 2(새 `core/test` 시험은 CORE 공개 계약만)와 긴장이 있어 독립 리뷰에서 유지/분리를 정한다.
- 교훈: 없음

## 2026-09-24 · uncommitted · test(repo): `docking/manager.py` 크기 판정 accept (D-168 P6)

- 변경: `SIZE_VERDICTS`에 `core/core_features/core_features/docking/manager.py`(930줄)를 `accept`(X5)로 추가. main 511줄 → 브랜치 930줄(주차형 도크 단계 27b65067·784ffad2와 리뷰 수정 H1–N6).
- 증거: 병합 뒤 `test_over_budget_code_has_a_recorded_verdict` 가 이 파일을 판정 없음으로 잡았다. 추가 뒤 `python -m pytest test/test_module_structure.py -q` 초록 (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: accept — 소유자 하나(`svc.docking` / `DockingManager`, 충전·주차 두 도크 기종의 한 phase 기계), ROS-free, `core_features/test/test_docking*.py`로 host 시험 가능. 2026-09-06 분리 기준 X5 가 바로 이 파일을 예로 든다. 주차 전용 phase(`_tick_*_pose`, `_begin_turn` 등)를 전략 객체로 떼는 split 대안은 독립 리뷰에 남긴다. D-178 재채점 트리거(`SIZE_VERDICTS` 판정 변경)에 해당하므로 스코어카드 회차 갱신이 필요하다.
- 교훈: 없음

## 2026-09-24 · uncommitted · refactor(docking): 주차형 단계를 `docking/parking_phases.py` 전략으로 분리 (D-168 P6)

- 변경: `docking/manager.py` 930줄 → 663줄. 주차형(`approach="pose"`) 단계 로직 — 진입·언도킹 회전(`begin_turn`·`tick_turning`), 크리프 획득, 추정기·오도메트리 접근, 정렬, 포즈 판정·재착좌 정착, 거리 후진, `_aim`·`_near_spot`·`_observe` — 을 신규 `docking/parking_phases.py`(301줄, `ParkingPhases`)로 옮겼다. `DockPhase`·`DockingExecutor`·`DockingConfig`는 신규 `docking/model.py`(76줄)로 옮기고 `manager` 가 다시 내보낸다(`__all__`) — 기존 import 경로는 그대로다. 기본 기종 정착과 포즈 정착이 같은 DOCKED 전이를 쓰도록 `_mark_docked()` 를 뒀다. `SIZE_VERDICTS` 의 manager 판정을 663줄 accept 로 갱신했다. 시험 `test/test_docking_parking_phases.py` 4건(pose 단계 위임, 거리 후진 위임, 전략의 자기 상태·락 없음, 주차 모듈의 ROS·cv2·threading import 금지).
- 원인: 사용자 결정 2026-09-24 — 크기 예외(accept 930) 대신 분리.
- 증거: 기존 docking 시험은 수정 없이 통과한다(`core_features/test` + `core/test/test_docking_mode_*`·`test_docking_parking_wiring`·`test_mode_listener_isolation` 255 passed → 신규 포함 259 passed, `test_parking_offline` 기본·`-m drift`, `test_mission_harness_contract`) (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: 전략은 자기 락도 자기 상태도 없다. 주차형 단계 상태(`_tracker`·`_turn_target`·`_after_turn`·`_creep_from`·`_creep_done_at`·`_backoff_from`)는 매니저 필드로 남아 매니저가 만들고 되돌리며, 전략은 `ParkingHost` 프로토콜로 적은 매니저 멤버만 쓴다. 모든 진입점이 매니저의 RLock 안(틱·명령 경로)에서만 불리므로 N1(락 안 모드 해제)·H2(`take_mode` 먼저)·estop 먼저 순서는 매니저 한 곳에서 읽힌다. 600줄 목표는 이번 분리로 닿지 않았다 — 남은 663줄은 매니저가 소유해야 할 것(상태·락·모드 이음새·fail/retry/release·기본 기종 단계·배터리 복귀·공개 API)이라 더 떼면 락 소유자가 둘로 갈린다. D-178 재채점 트리거(`SIZE_VERDICTS` 판정 변경)에 해당한다.
- 교훈: 없음

## 2026-09-25 · uncommitted · feat(core_features): D-228 decision library under core_features

- 변경: `core_features/decision` 계약과 로컬 라우터. 허용 집합 밖 동작은 INVALID, selected_action 은 DECIDED 만. SAFE_STOP·EMERGENCY·MANUAL 은 motion 선택지를 규칙보다 먼저 뺀다. src/runtime 과 rosy_pinky_pro 는 만들지 않는다.
- 증거: `python -m pytest src/core/core_features/test -q` 218 passed (2026-09-25 Windows). test_decision.py 11건 포함.
- gate 변화: 없음
- 결정: D-228
- 교훈: 없음

## 2026-09-25 · uncommitted · feat(core_features): lane_recovery returns FOLLOW or STOP

- 변경: `decision/lane.py`. 신선한 가시 차선은 FOLLOW, 그 밖은 STOP. 속도는 만들지 않는다. line_follow.tick 은 그대로다.
- 증거: `python -m pytest src/core/core_features/test/test_lane_recovery.py src/core/core_features/test/test_decision.py -q` 15 passed (2026-09-25 Windows). line_follow.tick 은 수정하지 않았다.
- gate 변화: 없음
- 결정: D-228
- 교훈: 없음

## 2026-09-25 · uncommitted · feat(line_follow): track only when lane_recovery says FOLLOW

- 변경: `line_follow.tick` 은 `lane_recovery_rule` 이 FOLLOW 일 때만 기존 속도 식을 쓴다. HOLD/LOST/WAITING 문구와 손실 래치는 매니저에 남는다.
- 증거: `python -m pytest src/core/core/test/test_line_follow.py src/core/core/test/test_line_follow_sim_clock.py src/core/core_features/test/test_lane_recovery.py -q` 30 passed (2026-09-25 Windows).
- gate 변화: 없음
- 결정: D-228
- 교훈: 없음
