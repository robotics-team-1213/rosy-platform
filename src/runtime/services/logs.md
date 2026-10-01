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


## 2026-09-29 · uncommitted · feat(traffic): D-337 T3 — observer wiring, config gate, status contract

- Change: SignalObserverMonitor (daemon thread, injectable clock) owns the polling schedule — confirmed evidence reaches the manager with the server frame age compensated into the receipt time, and the fresh->stale transition publishes nav.traffic_policy_signal_source_stale (warning) exactly once per lapse. TrafficPolicyStatus gains signal_source_kind (camera|fused — fused only while the measured light is usable), signal_head_age_s, signal_head_frozen, computed in _set_status from the same usability rule the verdict uses. The T2 poller export now includes the monitor.
- Evidence: services test_observer_source.py +3 (age compensation through the manager status, once-per-lapse announcement with re-arm after recovery, start/stop). traffic policy suite +3 (status view across fresh/stale/frozen, observer absent by default, binds+starts from config, missing map/scene fails the build). Combined host run 501 passed; semantic road simulation 2 passed; flake8 clean on changed lines.
- Gate: SOURCE/LOCAL only; no live observer on the bench, ROS-SIM, device, or FIELD acceptance. T4 (dashboard signal-source row) remains.
## 2026-09-30 · uncommitted · feat(docking): D-350 하드웨어 단계·degrade·만춫·히스테리시스

- 변경: ①ChargingConfirmation에 instrumented kwarg — false면 Phase 1(계측 없는 도크)에서 전압 비하락만으로 판정, source 프로퍼티로 단계 보고. ②DockPhase.CHARGED_HOLD 추가. ③DockingConfig에 full_enter_v(8.2V)/full_exit_v(8.0V)/instrumented(bool) — 만춫 히스테리시스·Phase 1 플래그. ④manager._check_full — DOCKED 중 만춫 감지 시 docking.full 이벤트 1회 방출, full_exit_v 아래로 떨어지면 재방출 허용. ⑤API Ref §8에 docking.full 행 추가. ⑥deploy/robot/pinky_pro/config/capabilities.dock-enabled.yaml 오버레이 신설.
- 증거: test_docking_phases.py 6 passed (degrade·instrumented·peak_v·source). test_docking.py + mode_ownership + battery = 226 passed 전체.
- gate 변화: 없음.
- 결정: Phase 1에서 D-27 억제는 안 함(1소스로는 안전 경로를 못 끈다). Phase 2부터 2소스 확정 시에만.
- 교훈: manager는 _cfg를 쓴다 (_config 아님) — 첫 커밋에서 9건 적신.
## 2026-09-30 · uncommitted · feat(docking): D-351 재시도 갈래 — 도달 실패/전류 없음/충전 단절 구분

- 변경: manager._tick_settling에 contact_no_current 갈래 추가 — load_present=true인데 charging=false가 settle 타임아웃까지 지속하면 즉시 DOCK_FAILED(contact_no_current), 재시도하지 않는다(산화 접점은 재시도로 안 낫는다). 도달 실패(재착좌)와 충전 단절(charge_lost, DOCKED 유지)은 기존 동작 유지.
- 증거: 도킹 전체 115 passed (기존 + 신규 phase 시험).
- gate 변화: 없음.
- 결정: D-351 — 재시도 예산은 도달 실패에만 쓴다. 전류 없음은 폴트 보고.
- 교훈: 없음.
## 2026-09-30 · uncommitted · refactor(docking): D-353 봉합점 구현 착지

- 변경: ①`docking/strategies.py` 신설 — ChargingStrategy·FullChargeStrategy Protocol + VoltageFullCharge 기본 구현 (전압 임계·히스테리시스). ②manager가 `_check_full`을 FullChargeStrategy에 위임, 만춫 시 `DockPhase.CHARGED_HOLD` 진입. ③DockAgent.poll()이 `core_common.device_poll.poll_json()`으로 폴링을 위임 (인라인 urllib 제거, 4상태 실패 매핑 유지). 기존 시험 전부 통과 — Protocol은 duck typing이라 기존 클래스가 자동으로 구현한다.
- 증거: 도킹·모드·배터리·봉합점 시험 231 passed. device_poll 공유 유틸리티와 어휘 1:1 대응.
- gate 변화: 없음.
- 결정: 설계가 바뀌면 새 전략 파일 1개 — manager·ChargingConfirmation 본체 불변.
- 교훈: Protocol 봉합점의 구현 비용이 0이라는 것을 몸으로 확인했다 (기존 시험 한 건도 안 깨짐).

## 2026-09-30 · uncommitted · fix(docking): D-353 뒤끝 — 도크 계약 시험을 poll_json 경로로 재연결

- 변경: D-353이 DockAgent._parse를 core_common.device_poll.poll_json으로 옮기면서 test/test_dock_contract.py의 "문서 payload가 클라이언트처럼 파싱된다" 시험이 깨졌다( AttributeError: _parse). poll_json을 monkeypatch로 갈아끼워 HTTP 없이 실제 매핑 경로(문서→DockStatus)를 돌리도록 재작성했다. agent.py의 중복 import(같은 줄 2회, 머지 흔적)도 제거.
- 증거: test_dock_contract 7 passed(전체), services 스위트 265 passed, 경계 수비·target·목표증거 등록부 포함 99 passed (2026-09-30 Windows). poll_json 자체는 test_design_seams가 이미 소유.
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 파싱을 공용 계층으로 옮길 때 그 계층을 소비하는 계약 시험까지가 한 변경 단위다.

## 2026-09-30 · e3eb2561 · feat(line-follow): 조향을 아는 앞 물체 정지(path)와 수동 한도 계단 각속도 상한

- 변경: `core_features/line_follow/clearance.py` 에 `scan_points`(LiDAR → 로봇 좌표 점, `lidar_forward_deg` 반영)와 `path_clearance`(의도 (linear, angular) 의 짧은 호 둘레 ±half_width 띠 안 점까지의 호 길이, 호는 horizon 과 90° 중 짧은 쪽, 선속도 0 이면 제자리 회전) 추가. `manager.py` — `observe_scan_points` 가 점을 받고 틱이 의도 조향(관측 + IR 비킴)으로 여유 거리를 재서 기존 stop/resume 떨림 방지를 그대로 쓴다. 쓸 관측이 없으면 마지막 의도. 새 설정 `obstacle_mode`(path 기본 | sector), `obstacle_corridor_half_width_m` 0.09, `obstacle_path_horizon_m` 0.40(≥ resume), `max_angular_follows_manual` true. `angular_ceiling` 콜백(서비스가 `safety.limits.manual_angular` 연결)으로 유효 상한 = min(max_angular, 수동 한도); 자를 때 선속도도 같은 비율(곡률 유지), 한도 0·NaN·예외면 `angular_limit_zero` HOLD. 조향 계산은 `_steer` 하나로 모았다.
- 증거: 새 `src/runtime/gateway/test/test_line_follow_obstacle_path.py` 18 passed — 모서리 벽 0.2 m 앞에서 왼쪽으로 크게 돌면 정지 없음, 같은 장면 sector·직진은 정지, 호 위 상자는 정지·떨림 방지·재출발, LiDAR 끊김 HOLD, 계단 L0 0.10→L1 0.30 즉시 추종, 덮어쓰기, IR 비킴 상한. `pytest src/runtime/gateway/test -k "line_follow or clearance or ir"` 247 passed, 5 skipped (2026-09-30 Windows).
- gate 변화: SOURCE 진행. ROS-SIM(가제보 L 모서리 0.20 m 기본값으로 한 바퀴)·DEVICE 미실행.
- 결정: D-344 §11 보강, §13.

## 2026-09-30 · 794e75bb · fix(line-follow): 검토 반영 — sector 기본, 급회전 창·near-field, 풀림 지연, L1 문턱

- 변경: `obstacle_mode` 기본 `sector`(사용자 결정 — path 는 가제보 한 바퀴·실물 LiDAR 좌우 확인 뒤). `path_clearance` 회전각 창 max(90°, resume/R)·최대 180°, 0..180° 띠 안이고 `obstacle_stop_m` 안인 점은 직선 거리로 센다, 제자리 회전은 정지 거리 안 점. 막힘은 `obstacle_release_s`(0.2) 동안 계속 비어야 풀린다(path). 관측 전에는 호를 재지 않는다(WAITING). `obstacle_ahead` 가 `obstacle_escalate_s`(5) 이어지면 `nav.line_obstacle_hold` 한 번. 살아 있는 `manual_angular` < `lane_auto_min_manual_angular`(0.30 = L1)면 `limit_level_too_low` HOLD.
- 증거: `test_line_follow_obstacle_path.py` 21 passed — 0.18 m 벽(직진 정지·돌기 추종 한 시험), range_min 0.15 m 급회전 상자(옛 창은 못 봄), 제자리 회전, 풀림 지연, 의도 교대 떨림 없음(지연을 0 으로 두면 20 틱 중 10 번 출발 — 변이 확인), 띠 안 벽 LOST 없이 HOLD + 사건 한 번, 관측 전 WAITING, 잃은 시야에서 마지막 의도, L0 거절·L1 출발. (2026-09-30 Windows)
- gate 변화: SOURCE. ROS-SIM·DEVICE 미실행.
- 결정: D-344 §11 보강, §13.

## 2026-09-30 · 61c25393 · fix(line-follow): 재검토 R1·R2 — 풀림 지연은 연속 측정만, 모드 선택마다 새 앞 물체 세션

- 변경: (R1, 08e791af) 틱이 호를 재지 않으면(LiDAR 끊김·계단 정지·한도 0·OFF·관측 전) 풀림 지연 시작점을 지운다 — 끊김 앞의 빈 측정이 풀림에 세지지 않는다. 틱 본문을 `_tick_locked` 로 옮기고 `finally` 에서 지운다. (R2, 61c25393) `set_mode` 가 막힘·지연·정지 시작·알림 여부를 지운다. sector 는 마지막 거리가 재출발 거리 안이면 막힌 채 시작한다(다음 스캔 전 한 틱도 가지 않게). (R3, c673f6cd) `max_angular_follows_manual: false` 는 L1 문턱을 우회하지 않고, 문턱을 끄는 것은 `lane_auto_min_manual_angular: 0` 뿐이라고 설정 주석·D-344 에 적었다.
- 증거: `test_line_follow_obstacle_path.py` 24 passed — LiDAR 0.6 s 끊김 뒤 지연 재시작(`finally` 의 지우기를 빼면 빨강), 재선택 뒤 두 번째 정지가 두 번째 `nav.line_obstacle_hold`(R2 를 빼면 빨강), sector 재선택 막힘 유지(R2 를 빼면 빨강), 덮어쓰기로 문턱 못 넘음. gateway `-k line_follow` 85 passed, 3 skipped ×3 (2026-09-30 Windows; 부하 중 한 번 1 failed 가 있었으나 세 번 다시 돌려 재현 안 됨).
- gate 변화: SOURCE.
- 결정: D-344 §11 보강, §13.

## 2026-09-30 · uncommitted · refactor(line_follow): 데이터 모델을 model.py 로 분리(파일 예산)
- 변경: `core_features/line_follow/manager.py`(704 행, 예산 600) 에서 `LineFollowMode`·`LineObservation`·`LineFollowConfig`·`LineFollowDecision`·`_finite` 를 `line_follow/model.py` 로 옮겼다. manager 는 잠금 한 개를 가진 주인(tick·observe·set_mode·물체/IR/계단 게이트)만 남는다(561 행). manager 가 같은 이름을 다시 내보내 기존 import 는 그대로다. docking/model.py 선례(크기 예외가 아니라 분리).
- 증거: `pytest src/runtime/gateway/test -k "line_follow or clearance or ir"` 통과, `test/architecture/test_module_structure.py` 통과, pyflakes 깨끗.
- gate 변화: 없음(동작 불변).

## 2026-10-01 · uncommitted · fix(command): release_emergency 도 리스너 계약을 지킨다

- 변경: release_emergency() 가 잠금 해제 후 change_listeners 를 transition() 과 같은 계약으로 돌린다(EMERGENCY→IDLE). 여태 리스너를 건너뛰어 모드 미러·도킹 정리가 해제를 못 봤다.
- 증거: test_core_logic.py 두 시험(해제 리스너 호출, 실패하는 리스너는 자기만 건너뜀).
- gate 변화: 없음.

## 2026-10-01 · f34781ae · feat(line_follow): 시작 때 정한 LiDAR 장착 yaw 를 받는다
- 변경: `LineFollowManager.use_lidar_forward(deg, source)` 와 `lidar_forward_source` — CORE 가 정한 장착 yaw(D-47 부록)를 설정에 넣고 출처를 기억한다.
- 증거: gateway `test_lidar_mount_source.py`, services 265 passed (2026-10-01 Windows).
- gate 변화: 없음(값 주입 경로만).

## 2026-10-01 · uncommitted · fix(fleet_agent): D-382 F10·I4 — 구독 해제와 이벤트 seq 사본

- 변경: FleetAgent가 `EventBus.subscribe`가 돌려준 해제 함수를 쥐고 종료 때 부른다(없는 `events.unsubscribe`를 부르던 결함, F10). 버스가 모든 구독자에게 넘기는 링 버퍼 속 같은 `EventMessage`의 `seq`를 덮어쓰지 않고 사본에 Agent seq를 매긴다(`/api/v1/events`·`/ws/events`·감사의 seq가 바뀌던 문제, F7의 일부). F7의 재시작 뒤 누락(부팅 세대)은 다음 이미지 회차(L2).
- 증거: `test_fleet_agent.py` 신규 2건 — 수정 전 실패, 수정 후 통과. 시험용 `DummyEventBus`가 실제 버스에 없는 `unsubscribe`를 갖고 있어 결함을 가렸으므로 실제 표면(`subscribe`가 해제 함수를 돌려줌)으로 맞췄다.
- gate 변화: 없음(SOURCE/LOCAL). 로봇에는 다음 이미지·payload로만 간다.

## 2026-10-01 · uncommitted · feat(command): D-385 모드→표정 정책 emotion_map

- 변경: core_features/command/emotion_map.py — EMOTION_BY_MODE 와 막힘(bored) 우선순위. 모르는 모드는 None(표정 유지). ROS-free.
- 증거: gateway/test/test_emotion_map.py (어휘가 감정 노드의 GIF 이름 안에 있는지도 검증).
- gate 변화: 없음.

<<<<<<< HEAD
## 2026-10-01 · uncommitted · feat(road_behaviour): D-384 도로 주행 행동 상태 기계(ROS-free, 명령 없음)

- 변경: 새 `core_features/road_behaviour/`(`model.py`·`machine.py`·`table.py`). `step_behaviour(memory, inputs, params)` 순수 함수가 `LANE_FOLLOW`·`FOLLOW`·`HOLD`·`APPROACH`·`STOP_AT_LINE`·`YIELD_CHECK`·`CREEP`·`CROSS`·`FAULT` 중 하나와 속도 상한·갈래 선택만 낸다(D-2, D-151: CORE가 `min()`). 오래된(> 0.3 s)·없는 필수 입력은 `FAULT` 0. 정지 장애물 5 s면 `nav.line_obstacle_hold` 한 번(`LineFollowConfig.obstacle_escalate_s`와 같은 값). `v_cruise` 0.08, CORE 상한 입력과 `min`. 교차로 상태는 `junction_logic_enabled=False` 기본 — `d_jn` 안 교차로는 `HOLD junction_unsupported`. 켜면 일단정지, 도로교통법 제26·27조 양보, Fleet 허가, 경로 > 오른쪽 > 직진 > 왼쪽. 전이표는 `docs/plans/2026-10-01-road-behaviour-transition-table.md`.
- 증거: `src/runtime/services/test/test_road_behaviour.py` 108 passed (2026-10-01 Windows).
- gate 변화: SOURCE. CORE 통합(호출 위치)은 차선 유지 소유 세션 결정 전이다.
- 결정: D-384 §2·§4(Proposed).

## 2026-10-01 · 6d94e88f · docs(road_behaviour): D-384 도로 주행 행동 항목의 커밋 기록
- 변경: 위 `uncommitted · feat(road_behaviour): D-384 도로 주행 행동 상태 기계` 항목은 커밋 6d94e88f로 들어갔다. 로그는 추가만 하므로(harness lint) 그 머리줄을 고치지 않고 이 항목으로 기록한다
- 증거: `git log --oneline -- src/runtime/services/core_features/road_behaviour` 첫 커밋 6d94e88f
- gate 변화: 없음
=======
## 2026-10-01 · a527920a · feat(core): D-321 부록 보정 세션 lease
- 변경: `core_features/calibration/session.py` 추가 — 로봇당 한 개의 보정 lease(start/heartbeat/end, ttl 만료), 상태 스냅샷용 `activity()`, API 차단용 `blocking(token_id)`, 이벤트 `calibration.session_started/ended/expired`. `StateManager.set_activity_provider()` 가 lease 를 스냅샷 `activity` 로 실시간으로 싣는다(remaining_s 가 줄어든다). 모드·cmd_vel 은 만지지 않는다(D-2).
- 증거: src/runtime/gateway/test/test_calibration_session.py 13 passed; gateway·api_web·services 전체 1850 passed, 새 실패 0(test_core_node_teardown 1건은 main f16123eb 에서도 실패) (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · 22017f42 · fix(core): 만료 이벤트를 lock 밖에서 발행
- 변경: `_expire_locked()` 는 만료된 세션을 돌려주고 호출자가 lock 을 놓은 뒤 `_announce_expired()` 로 발행한다(start/end 와 같은 규칙). lock 은 다시 plain Lock.
- 증거: 만료 구독자가 lock 을 잡고 lease 를 다시 읽는 시험 통과.
- gate 변화: 없음.
>>>>>>> main
