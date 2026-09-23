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
