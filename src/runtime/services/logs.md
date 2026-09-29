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

## 2026-09-24 · uncommitted · feat(core_features): readiness `component_state`, state `received_age` (D-32)
- 변경: `navigation/readiness.py` `NavigationReadinessGate.component_state()` — 게이트가 required 가 아니어도 한 구성요소의 마지막 보고를 `ready`/`inactive`/`stale`/`unobserved` 로 돌려준다(CORE-only 에서 무동작 bringup 의 `motor/ready: false` 를 읽기 위해). `state/manager.py` `StateManager.received_age()` — 채널의 마지막 표본 이후 초.
- 증거: `src/core/core/test/test_hardware_runtime_truth.py::test_component_state*` 4 passed, `src/core/core_features/test` 포함 1553 passed (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: D-32, D-192.
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

## 2026-09-25 · uncommitted · refactor(runtime): move core_features under src/runtime (D-231)

- 변경: src/runtime/core_features로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 runtime 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음
## 2026-09-26 · uncommitted · FleetAgent pinned mDNS location

- 변경: `fleet_agent`가 승인된 지속 연결 토큰과 예상 호스트·사이트 CA가 있을 때만 Avahi 후보를 조회하고 TLS health를 확인한다. 실패하면 CORE를 막지 않고 재시도하며, 연결 단절 후에도 재조회한다.
- 증거: Agent·first-boot·Fleet 통합 집중 58 passed, 변경 Python flake8 통과. 실제 Pi/Ubuntu 네트워크는 미검증.
- gate 변화: LOCAL 범위만 추가.
## 2026-09-28 · uncommitted · add camera-fault eligibility policy

- Change: add a ROS-free, fail-closed evaluator for explicitly selected IR_LINE, NAV_GOAL, and TELEOP alternatives; it reports reasons, evidence ages, and a short expiry but issues no motion command.
- Evidence: new policy suite 5 passed. Full services suite was not run in this change.
- Gate: SOURCE/LOCAL baseline unchanged; no runtime or device acceptance claimed.

## 2026-09-28 · uncommitted · echo navigation correlation on CORE result events

- Change: `NavigationManager` carries the optional attempt correlation through `nav.started`, cancel request, and the final Nav2 result event. A canceled request does not clear it before a possible final result callback.
- Evidence: core services 227 passed; focused gateway API/core-logic/event-catalogue tests passed except one known baseline event-literal classification failure outside this change.
- Gate: host SOURCE/LOCAL only. No live Nav2, artifact, device, or field evidence.

## 2026-09-28 · uncommitted · publish late canceled-attempt result safely

- Change: add a correlated result publication path that emits the terminal action result for a canceled goal without mutating navigation state owned by a newer goal.
- Evidence: focused navigation manager lifecycle regression passes.
- Gate: SOURCE/LOCAL only. No live Nav2, artifact, device, stop readback, or field evidence.

## 2026-09-28 · uncommitted · fix(core): scope task correlation to Nav2 goal generation

- Change: carry `correlation_id` with each GoalTracker generation, reject moving-goal takeover while a Fleet attempt owns navigation, and clear the active association on cancel. Later moving-goal results cannot inherit the previous Fleet ID.
- Evidence: CORE services 227 passed; focused gateway navigation and GoalTracker regressions 19 passed; changed implementation lint passed.
- Gate: SOURCE/LOCAL only. The real Nav2 bridge and physical device remain unverified.
## 2026-09-28 · uncommitted · verify canceled navigation result isolation

- Change: publish a canceled generation''s terminal event independently of current navigation state; preserve CANCELED/ABORTED reason codes.
- Evidence: services suite 227 passed; navigation manager and GoalTracker regressions 67 passed.
- Gate: SOURCE/LOCAL only; live Nav2, artifact, device, stop readback, and field evidence remain open.

## 2026-09-29 · uncommitted · feat(traffic): unsignalized junction rule `stop_and_go`

- Change: `TrafficPolicyConfig.junction_rule` (`signal_controlled` default | `stop_and_go`) — an operator declaration, never a camera absence verdict. After the existing complete-stop and dwell at the stop line, `stop_and_go` with no observed signal proceeds (`PROCEED / unsignalized_proceed` at `proceed_speed_scale`); any observed signal, weak false positives included, holds (`HOLD / signal_unexpected`). `signal_conflict`, stale, map/scene mismatch, and stop-line confidence checks still run before the rule; `signal_controlled` behavior is unchanged. Status now carries `junction_rule`.
- Evidence: design `docs/plans/2026-09-29-traffic-policy-unsignalized-junction-design.md`. Focused suites on Windows: gateway traffic policy+API+runtime config, foundation 101, services 227 → 380 passed; protocol schemas, api_web, dashboard → 105 passed 47 skipped; semantic road simulation + event catalogue → 74 passed.
- Gate: SOURCE/LOCAL only; no ROS-SIM closed loop over an unsignalized scene, device, or FIELD acceptance. Multi-junction scenes and a second signal source (ESP32/observer) are future work (design §7).

## 2026-09-29 · uncommitted · feat(traffic): D-337 T1 — measured-light signal head fusion

- Change: `SignalHeadEvidence` (observer `/observed` measured light: red/yellow/green booleans, confidence, frozen, stable, map/scene coupling) plus `TrafficPolicyManager.observe_signal()` with the same age compensation and evidence-revision bump as camera `observe()`; reset and staged-apply clear it. The dwell-complete verdict now fuses both sources per D-337 §3: agreement uses min confidence, a confirmed different colour holds (`signal_source_conflict`), observer-only confirmed colour drives the verdict (end of infinite `signal_unknown` when the camera cannot see the head), a usable but indeterminate head (dark or plural lamps) is `signal_dark` and never licenses entry, unusable (stale/frozen/pending/scene-mismatch) heads are silence — camera alone, exactly the pre-T1 behavior. `stop_and_go` holds `signal_unexpected` on any usable head evidence, dark included. No producer yet (T2 poller), no schema/API change (T3).
- Evidence: design `docs/plans/2026-09-29-robot-signal-source-integration-design.md` (§2 field names aligned). Host (Windows): traffic policy+API+foundation+services 383 passed; semantic road simulation + event catalogue 74 passed (observer-disabled behavior byte-identical).
- Gate: SOURCE/LOCAL only; no poller transport, ROS-SIM, device, or FIELD acceptance. T2 (httpx poller with fake transport) is next.

## 2026-09-29 · uncommitted · feat(traffic): D-337 T2 — observer source transport

- Change: new `core_features/traffic_policy/observer_source.py` — `SignalObserverSourceConfig` (http(s) url, operator `roi_map` lamp-position→colour binding with duplicate/unknown-target rejection, timeout/poll-interval bounds), `parse_observed` (`/observed` body → `SignalHeadEvidence`: stable layer decides lit/pending, raw layer lends its worst mapped-lamp confidence, colour comes from the operator position map and never from the observer `group`), and `SignalObserverPoller` with injectable transport and clock. Silence contract: frozen, pending-debounce, malformed bodies and any transport failure return None — a fabricated head is never built (503 NO_FRAME included). `last_outcome`/`last_age_s` feed the T3 readback. Default transport imports httpx lazily; scheduling/threading stays with the T3 wiring. SIZE_VERDICTS gains the manager.py accept verdict (609 lines after the D-337 fusion; one owner, ROS-free, transport already split into observer_source.py) — the parallel track's schemas.py/fleet over-budget items are untouched and remain theirs.
- Evidence: new `src/runtime/services/test/test_observer_source.py` (17 tests: binding validation, position→colour mapping, worst-lamp confidence, frozen/pending silence, 7 malformed-body mutations, outcome labels, http failure, poller→manager closed path to `signal_red`). Services suite 251 passed; traffic policy+API+foundation 156 passed; flake8 clean. Remaining `test_module_structure.py` failures (schemas.py 739, fleet 10631, app.py re-judge) pre-exist on main from the parallel Fleet/protocol work.
- Gate: SOURCE/LOCAL only; no live observer on the bench, ROS-SIM, device, or FIELD acceptance. T3 (config gate + services wiring + status fields + API Ref MINOR) is next.
