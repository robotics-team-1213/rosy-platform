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

## 2026-10-01 · a527920a · feat(core): D-321 부록 보정 세션 lease
- 변경: `core_features/calibration/session.py` 추가 — 로봇당 한 개의 보정 lease(start/heartbeat/end, ttl 만료), 상태 스냅샷용 `activity()`, API 차단용 `blocking(token_id)`, 이벤트 `calibration.session_started/ended/expired`. `StateManager.set_activity_provider()` 가 lease 를 스냅샷 `activity` 로 실시간으로 싣는다(remaining_s 가 줄어든다). 모드·cmd_vel 은 만지지 않는다(D-2).
- 증거: src/runtime/gateway/test/test_calibration_session.py 13 passed; gateway·api_web·services 전체 1850 passed, 새 실패 0(test_core_node_teardown 1건은 main f16123eb 에서도 실패) (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · 22017f42 · fix(core): 만료 이벤트를 lock 밖에서 발행
- 변경: `_expire_locked()` 는 만료된 세션을 돌려주고 호출자가 lock 을 놓은 뒤 `_announce_expired()` 로 발행한다(start/end 와 같은 규칙). lock 은 다시 plain Lock.
- 증거: 만료 구독자가 lock 을 잡고 lease 를 다시 읽는 시험 통과.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(road_behaviour): D-384 도로 주행 행동 상태 기계(ROS-free, 명령 없음)

- 변경: 새 `core_features/road_behaviour/`(`model.py`·`machine.py`·`table.py`). `step_behaviour(memory, inputs, params)` 순수 함수가 `LANE_FOLLOW`·`FOLLOW`·`HOLD`·`APPROACH`·`STOP_AT_LINE`·`YIELD_CHECK`·`CREEP`·`CROSS`·`FAULT` 중 하나와 속도 상한·갈래 선택만 낸다(D-2, D-151: CORE가 `min()`). 오래된(> 0.3 s)·없는 필수 입력은 `FAULT` 0. 정지 장애물 5 s면 `nav.line_obstacle_hold` 한 번(`LineFollowConfig.obstacle_escalate_s`와 같은 값). `v_cruise` 0.08, CORE 상한 입력과 `min`. 교차로 상태는 `junction_logic_enabled=False` 기본 — `d_jn` 안 교차로는 `HOLD junction_unsupported`. 켜면 일단정지, 도로교통법 제26·27조 양보, Fleet 허가, 경로 > 오른쪽 > 직진 > 왼쪽. 전이표는 `docs/plans/2026-10-01-road-behaviour-transition-table.md`.
- 증거: `src/runtime/services/test/test_road_behaviour.py` 108 passed (2026-10-01 Windows).
- gate 변화: SOURCE. CORE 통합(호출 위치)은 차선 유지 소유 세션 결정 전이다.
- 결정: D-384 §2·§4(Proposed).

## 2026-10-01 · 6d94e88f · docs(road_behaviour): D-384 도로 주행 행동 항목의 커밋 기록
- 변경: 위 `uncommitted · feat(road_behaviour): D-384 도로 주행 행동 상태 기계` 항목은 커밋 6d94e88f로 들어갔다. 로그는 추가만 하므로(harness lint) 그 머리줄을 고치지 않고 이 항목으로 기록한다
- 증거: `git log --oneline -- src/runtime/services/core_features/road_behaviour` 첫 커밋 6d94e88f
- gate 변화: 없음

## 2026-10-01 · uncommitted · fix(fleet_agent): D-370 S7 준비 — Fleet health 탐침이 확장 모양을 받는다

- 변경: `fleet_agent/discovery.py`의 `/healthz` 판정을 `check_health_body`로 뺐다. 본문 1024바이트 이하, JSON 객체, `status == "ok"`이면 채택하고, `role` 키가 있으면 `_rosy-fleet._tcp` TXT `role`(`fleet`, `core_common.protocol.discovery_txt.REQUIRED`)과 같아야 한다. 모르는 키는 무시한다. 여태 본문이 정확히 `{"status":"ok"}`여야 해서 D-370 공개 상태 모양(`role`·`proto`·`contract_version`)을 더하면 탐침이 떨어졌다.
- 증거: `test/test_site_fleet_mdns.py` 신규 2개 시험(사이트·Agent 양쪽 매개변수) — 옛 본문·확장 본문·모르는 키 통과, 다른 role·null role·`degraded`·`down`·status 없음·배열·문자열·JSON 아님·1024바이트 초과 거절. 수정 전 20건 빨강(판정 함수 없음; 옛 정확 비교는 확장 본문을 거절), 수정 후 초록. `test_fleet_agent_mdns.py` 통과.
- gate 변화: 없음(SOURCE). Fleet·Vision `/healthz` 출력은 바꾸지 않았다 — 이미 깔린 로봇 이미지는 정확 비교를 하므로, 서버 쪽 확장은 이 판정을 실은 새 이미지가 퍼진 뒤에 한다.

## 2026-10-01 · uncommitted · fix(road_behaviour): 발행하지 않는 이벤트 이름 두 개를 사유 코드로

- 변경: `nav.road_stop_line_overshoot`, `nav.road_turn_timeout`은 발행하는 곳이 없어 이벤트 목록 규약(test_event_catalogue)에 걸렸다. R1 노드 연결이 발행자와 목록 행을 더할 때까지 이름공간 없는 사유 코드 `road_stop_line_overshoot`, `road_turn_timeout`(NOTICE_*)로 바꿨다. `nav.line_obstacle_hold`는 line_follow가 발행하므로 그대로다.
- 증거: test_road_behaviour.py + test_event_catalogue.py 180 passed.
- gate 변화: 없음(SOURCE, 아직 노드에 연결되지 않은 ROS-free 모델).

## 2026-10-01 · uncommitted · feat(command): 대기 5분 후 bored 표정

- 변경: emotion_map.emotion_for 이 idle_seconds 를 받아 IDLE 5분 이상이면 basic 대신 bored. 모드가 바뀌면 대기 시계 리셋 — 심심함은 대기의 누적이다.
- 증거: test_emotion_map.py 6신규 (변이: bored→basic 되돌리면 빨강).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(localization,state): D-395 P2-1 LocalizationAssist

- 변경: 새 `core_features/localization/assist.py` — 로봇 sensing 노드 JSON 파싱, 정직한 `pose_frame`(CORE 가 odom 대체 중이면 odom, odom→map 승격 없음), 3 s 무응답이면 UNKNOWN(`state_stale`), CandidateReport `robot_id` 를 CORE 신원으로, STALE 판정, `localization.state|candidates|result` 이벤트. `state/manager.py` 는 localization provider 를 live 로 읽는다.
- 증거: `test/test_localization_assist.py` 24.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(localization): D-395 LOCALIZED 이탈 시 자율 주행 정지

- 변경: `LocalizationAssist.on_lost` — 상태가 LOCALIZED 에서 SUSPECT·CANDIDATES·UNKNOWN(`state_stale` 포함)으로 내려가면 한 번 호출. 새 `localization/halt.py` `autonomy_halt`: swarm 취소(`reason: localization`), 도킹 취소, line-follow OFF, `nav.cancel`, NAVIGATION → IDLE. MANUAL 은 건드리지 않는다. `wire_assist` 가 CORE 조립을 맡는다.
- 증거: `test/test_localization_assist.py` +5 (변이: 훅 제거 → 8 빨강).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(localization,docking): D-395 리뷰 — 내부 시작 게이트, 결과 검증, 잠금

- 변경: `LocalizationAssist.autonomy_allowed()`(LOCALIZED + map, 또는 D-395 이전 로봇)와 `gate`(RLock: 상태 반영·이탈 정지와 모든 시작이 같은 잠금). `localization/result` 는 모델 검증(`request_id` 규칙, `reason` ≤ 64), 64 KiB 넘는 메시지는 버림, 거부 로그는 예외 타입과 오류 종류만. `DockingManager.localization_ok` — `dock()` 거부(`NOT_LOCALIZED`), 배터리 복귀는 대기로 남아 LOCALIZED 가 되면 틱이 이어 간다. `wire_assist` 가 바인딩.
- 증거: `test/test_localization_assist.py` +20, `test/test_docking_localization_gate.py` 5.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(core_features): D-400 shadow verdicts without touching the output
- 변경: `SafetyManager.check_decision`/`decision_valid` 분리, `shadow.py` `ShadowLog`(락, 판정 단위 전이 이벤트, 1 s 반복, 최소 0.2 s 간격, suppressed/dropped 카운터), 그림자·집행 바인딩 상호 배타와 `shadow_evaluate`(예외 비전파), `CommandManager`가 그림자를 `announce_pending`에서 바퀴 출력 뒤에 판정, 네비게이션·도킹의 `policy_off`(모드 진입마다 첫 0 아닌 출력), `StateManager.set_safety_policy_provider`.
- 증거: 전체 시험(gateway+services+foundation+api_web+test/) `5 failed, 5919 passed, 249 skipped, 31 warnings, 4 errors in 3428.70s`; `known_failures.py`는 exit 1: 9건 모두 이 브랜치가 건드리지 않은 시험이며(main 4804d417에서도 test_module_separation, test_release_boundary_guards, test_robot_literals, test_dashboard_drive 4건이 같게 실패, test_module_criteria C6와 test_behavior_test_ownership은 main이 이후 고쳤고 이 브랜치는 그 이전 기준) 이 브랜치 기인 실패는 0건.
- gate 변화: 없음. SOURCE만. 그림자는 어느 로봇에서도 켜지 않았다(기본 off).

## 2026-10-02 · uncommitted · feat(localization): D-395 P2-7 확인 기동·귀환 미션 실행기

- 변경: 새 `localization/mission.py` `LocalizationMission` — `LOCALIZED` 가 아닐 때만 `rotate_in_place`(오도메트리 한 바퀴, 0.3 rad/s), `nudge_forward`(≤ 0.10 m, 0.03 m/s, 정면 0.25 m 정지), `lane_to_stopline`(카메라 line-follow 를 이 미션에 한해 LOCALIZED 관문 없이, 세션 속도 0.04 m/s, 정지선 0.12 m·거리·시간에서 끝). `to_square` 는 `unsupported`(map 프레임 없이 차선 경로가 없다, 후속). 바퀴는 NAVIGATION 모드의 nav 슬롯(`set_nav_twist`)으로만 — 50 Hz `select_output` 이 최종 중재. 끝(완료·시간·장애물·e-stop·LOCALIZED·센서 끊김·모드 이탈)은 명령을 지우고 IDLE 로, `localization.mission` 이벤트와 `publish`(ROS `localization/mission`). 시작은 `assist.gate` 안에서 검사·출발. `wire_assist` 가 미션을 만들고 LOCALIZED 진입 훅이 미션을 끝낸다(반환값 `(assist, mission)`).
- 증거: `gateway/test/test_localization_mission.py` 30.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(localization): D-395 P2-7 리뷰 — 못 보는 정면은 막힘, 회전 가드, 모든 종류 LiDAR 끊김

- 변경: `line_follow/clearance.py` 새 `front_sector`(정면 최단 유효 거리·유효 빔·빔 수; inf·NaN·`range_min` 미만은 무효 빔으로 셈, self-mask 반사는 빔에서 뺌). `nudge_forward` 는 정면 ±20° 에 유효 빔이 5 개 미만이거나 무효 빔이 30 % 를 넘으면 거부·정지(`range_min` 안 물체는 그렇게 보인다). `lidar_self_mask` 를 넘긴다. `rotate_in_place` 는 전체 스캔에 0.20 m 안 유효 반사가 있거나 스캔이 낡으면 거부. LiDAR 끊김(0.5 s)은 모든 종류를 `obstacle_sensor_stale` 로 끝낸다. `end()` 의 nav 슬롯 지우기는 한 번(지우면 시험이 빨개진다). `bind_clock` — 브리지가 line clock(use_sim_time 이면 ROS 시계)을 준다.
- 증거: `gateway/test/test_localization_mission.py` +14 (변이: `end()` 의 `clear_navigation` 삭제 → 7 빨강).
- gate 변화: 없음.

## 2026-10-02 · e93fdd8b · fix(localization): state_stale 창을 묶을 수 있는 시계로 (D-395 S1 finding 6)

- 변경: `localization/assist.py` 에 `bind_clock` — 3 s `state_stale` 창이 벽시계 대신 브리지의 line clock(use_sim_time 이면 ROS 시계, 실기는 monotonic)으로 잰다. 로봇 노드는 상태를 자기 노드 시계로 0.5 s 마다 내므로, 벽시계 창은 RTF ≈ 0.17 아래에서 깜빡였다. `received_s` 는 그대로 `clock`(로봇 노드의 ROS 시계).
- 증거: `test/test_localization_assist.py` +2 (RTF 0.1, 벽 5 s 간격에도 stale 없음; 그 시계로 3.1 s 침묵은 stale + halt).
- gate 변화: 없음.

## 2026-10-02 · 80db8125 · fix(localization): D-395 S1 재실행 R5·R6 — 버린 보고는 다시 주지 않고, 검사 중 미션은 `busy`

- 원인: R5 — 미션 시작으로 로봇이 열린 요청을 버린 뒤(`request_id: null`)에도 CORE 가 미션 전 보고를 계속 내줘 Fleet 이 그 보고로 결정하고 `stale_request` 를 받았다(d3). R6 — 로봇의 3 s 검사 중에도 미션을 받았다.
- 변경: `LocalizationAssist.on_state` 는 상태의 `request_id` 가 null 이거나 보관한 보고와 다르면 보고를 버린다. `candidates()` 는 보고의 id 가 상태의 id 와 같을 때만 낸다. 상태보다 먼저 온 새 보고는 새 id 라 남고, 상태가 따라오면 나간다(토픽 간 순서가 엇갈려 버려져도 로봇이 2 s 마다 다시 보고한다). `LocalizationMission.start` 는 상태 `reason == checking` 이면 409 `busy`.
- 증거: `gateway/test/test_localization_api.py` +3, `gateway/test/test_localization_mission.py` +1.
- gate 변화: 없음.

## 2026-10-02 · 776173dc · feat(line_follow): D-407 막힘 복구 상태기계와 관리자 연결

- 변경: `line_follow/stuck_recovery.py`(ROS 없는 상태기계: 열림·관제 요청·답 5종·15 s 시간초과·후진·1 s 정지·재판단·최대 시도), `stuck_wiring.py`(관리자 mixin: self-mask 점에서 몸 기준 앞 띠·뒤·회전 여유, 후진은 관리자 자신의 결정으로), `clearance.body_clearances`, `LineFollowConfig.recovery_*`·`body_*`. `set_mode`(OFF·E-Stop·IDLE)와 운전자 hold 끊김이 막힘을 닫는다.
- 증거: `test_line_stuck_recovery.py` 31 passed(서비스), `test_line_follow_stuck.py` 12 passed(게이트웨이).
- gate 변화: 없음. SOURCE만. 로컬 복구는 기본 꺼짐이고 어느 로봇에서도 켜지 않았다.

## 2026-10-02 · f93d922d · fix(line_follow): D-407 검토 반영과 뒤 사각 규칙

- 변경: 막힘 원인은 래치에서(일시 HOLD 가 막힘을 닫지 않음), 받아들인 답은 증거 개정을 올림, MANUAL·ABORT 는 잠금 안에서 OFF. 뒤 사각(range_min, 몸 뒤끝을 넘는 self-mask 창)은 사용자 결정 2026-10-02 대로 방금 앞으로 지나온 길(`ForwardTrail`, 교통 게이트 뒤 명령 적분)일 때만 들어간다. range_min 없음은 거부, LiDAR 정지 중 scan 없는 RESUME 거부.
- 증거: `test_line_stuck_recovery.py` 43 passed, `test_line_follow_stuck.py` 19 passed.
- gate 변화: 없음. 로컬 복구는 기본 꺼짐.

## 2026-10-02 · b9f1b277 · feat(localization): D-395 S1 R1 — LOCALIZED 물체를 스냅샷으로 넘긴다

- 변경: `LocalizationAssist` 는 `unmapped_objects`·`objects_stamp` 를 그대로 넘긴다. `pose_frame` 이 `odom` 이면(로봇이 말했든 CORE 가 바꿨든) 비우고, `state_stale` 은 새 상태라 원래 없다. 물체가 잘못된 상태는 물체만 버리고 상태는 받는다. 감시용 부가 정보 때문에 상태가 끊겨 자율 주행이 멈추면 안 된다.
- 증거: `test/test_localization_assist.py` +5(통과, odom·stale 에서 비움, 17개·문자열·잘못된 시각에서 상태 유지).
- gate 변화: 없음.

## 2026-10-02 · 410c6832 · feat(core_features): D-411 A teleop/intent 증거 훅
- 변경: `command/manager.py` 에 `intent_sink`·`note_intent` — teleop 판정마다(관리자 앞 거부 포함) `rosy.teleop.intent/1` 을 낸다. 싱크 예외는 명령을 거부하지 않는다. 제어 경로는 이 증거를 읽지 않는다(D-2).
- 증거: `python -m pytest src/runtime/services/test/test_teleop_intent.py -q` → 5 passed (2026-10-02 Windows).
- gate 변화: SOURCE 유지. ROS-SIM HOLD — 계획 Verification ROS-SIM 체크리스트(WSL Ubuntu) 미실행, DEVICE 증거 없음.
- 결정: D-411 A.

## 2026-10-02 · e83a955d · fix(line_follow): D-407 Gazebo 후속 — 재막힘 시도 이어 세기, 몸 폭 뒤 띠

- 변경: recovered 뒤 `recovery_restuck_s`/`recovery_restuck_m` 안의 재막힘은 시도 수를 이어 받음(`restuck_of`), 뒤 띠 = URDF 몸 반폭 + 0.02 m, 거부·중단 사건에 scan 값, e-stop 닫힘 사유 `estop`. FleetAgent 는 실행 중인 루프가 없으면 시작을 미루고 API lifespan 에서 `start_on_loop()`(94a8b833).
- 증거: `test_line_stuck_recovery.py`, `test_fleet_agent_loop.py` 초록.
- gate 변화: 없음.

## 2026-10-02 · 7e699e452 · fix(line_follow): D-407 지나온 길 유효 기간

- 변경: 사각 띠 후진의 지나온 길은 마지막 전진 명령이 `recovery_trail_max_age_s`(30 s) 이내일 때만(관제 대기 포함). 시도·결과 사건에 `trail_age_s`.
- 증거: `test_line_stuck_recovery.py`(29 s 허용, 31 s 거부, 사건에 trail_age_s), `test_line_follow_stuck.py`(관제 대기 중 만료).
- gate 변화: 없음.

## 2026-10-02 · bcce15c9d · fix(fleet_agent): hub 답을 모두 읽는 수신 루프, 재연결 기록, 관제 grace

- 원인: hub 는 heartbeat·사건마다 답하는데 에이전트는 heartbeat 마다 하나만 읽어 답이 쌓였고, websocket 큐가 차 읽기가 멈춰 keepalive 가 끊겼다(D-407 관제 재실행, ASKING 중 `no_console`).
- 변경: `_session`/`_receive_loop`(모든 답 소비, ERROR 는 그 envelope 만), 끊김 경고에 이유, `linked_within(grace)`; 막힘 답 사건 `principal_ref`·`rear_state`·거부 근거(9300adf1d).
- 증거: `test_fleet_agent_link.py` 4 passed, `test_line_stuck_recovery.py` 초록.
- gate 변화: 없음. Gazebo 재확인은 다음 WSL 슬롯.

## 2026-10-02 · 4a5a65083 · fix(fleet_agent): 검토 반영 — WELCOME 뒤에만 연결, 사건 잃지 않기

- 변경: `connected` 는 WELCOME~세션 끝, backoff 는 WELCOME 뒤에만 재설정, HELLO 답 5 s. 보낸 envelope 순서 기억(전송 잠금)과 답 짝짓기, 일시 오류 재전송(3 회), 영구 거부는 seq·종류 기록 후 버림, 미응답·전송 중 취소 사건 재버퍼. `principal_ref` 키 HMAC(0c56f3d6f).
- 증거: `test_fleet_agent_link.py` 12 passed, `test_line_follow_stuck*.py` 46 passed, `test_hub_server.py` 9 passed.
- gate 변화: 없음.

## 2026-10-02 · 8dd300c52 · feat(safety): D-415 SAF-003 Fleet 링크 상실 정책
- 변경: 새 `core_features/safety/fleet_loss.py` `FleetLossMonitor`(ROS 무의존) — FleetAgent 링크가 끊긴 순간 진행 중이던 Fleet 주행 목표(correlation_id)가 `fleet_loss_timeout_s` 동안 그대로면 STOP/HOLD/RETURN_HOME/CONTINUE 를 한 번 적용하고 `safety.fleet_lost`, 재접속 때 `safety.fleet_restored`. `navigation/manager.py` 에 `fleet_goal()` 과 `cancel(correlation_id=…)`(판정 뒤 바뀐 목표는 취소하지 않음, 반환 bool).
- 증거: `test/test_fleet_loss.py` 18 passed(정책별·범위·경쟁·실패 경로). gateway+services+api_web 2537 passed 29 skipped 1 failed — `test_host_hardware.py::test_rows_rosy_io_holds_are_judged_from_fresh_topics`, 깨끗한 main(13e6d5e45)에서도 실패, known_failures.txt 에 없음(이 브랜치 무관).
- gate 변화: 없음(호스트 pytest만, 실기·Gazebo 미확인).

## 2026-10-02 · 758f9878e · fix(safety): D-419(구 D-415) 리뷰 반영 — 링크 진실, goal_changed
- 변경: FleetAgent 는 WELCOME 뒤에만 `connected=True`, 허브 수신마다 `last_rx`(monotonic), 하트비트 답이 `HEARTBEAT_REPLY_TIMEOUT_S`(2 s) 안에 없으면 소켓을 닫는다. `FleetLossMonitor` 는 오래된 `last_rx` 를 끊김으로 보고 단절을 마지막 허브 수신부터 잰다(깜빡이는 링크가 타이머를 되돌리지 않음), 상실 중 설정이 꺼져도 reset 하지 않는다, 취소가 목표를 못 찾으면 `applied: NONE`·`goal_changed`(귀환·HOLD 기록 없음), tick·status 가 락 하나를 쓴다.
- 증거: `test_fleet_loss.py` 25 passed, 새 `test_fleet_agent_link.py` 4 passed(WELCOME 전 미연결, 답 없는 하트비트가 소켓 닫음).
- 번호: 앞 항목들의 D-415(SAF-003)는 **D-419** 로 바뀌었다 — main 에 다른 D-415(콘솔 운영 가시성)가 먼저 들어왔다. ADR 파일 `docs/adr/D-419-saf003-fleet-link-loss-policy.md`.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(safety): D-419 재리뷰 — 링크 신선도 분리, 리더 하나, backoff
- 변경: `FleetLossMonitor` 의 링크 신선도(`freshness_s` = 하트비트 1 s + 답 시한 + 0.5 s)를 판정 시간과 분리(짧은 판정 시간에서 건강한 링크가 STOP 나던 결함). 판정 시간 기본 5 s·범위 4–60 s, `validate_link_timing`(≥ 1 + 답 시한 + 1). FleetAgent: `fleet.heartbeat_reply_timeout_s`(기본 2 s, 0.5–10 검증), 세션마다 리더 태스크 하나가 모든 허브 메시지를 받아 `last_rx` 를 갱신하고 하트비트 답만 하트비트를 깨운다(EVENT ack 소진), 시한을 넘기면 transport 를 즉시 abort, backoff 는 답 3 개를 받은 세션 뒤에만 1 s 로. `recently_heard()`/`link_fresh_s`. `_apply` 는 모니터 락 아래에서 행동한다 — 안전한 이유를 주석으로.
- 증거: `test_fleet_loss.py` 28 passed(실제 1 Hz 박자로 하한 4 s 에서 발화 없음, 답 하나 놓친 기본 설정에서 마지막 수신 뒤 5 s 에 발화), `test_fleet_agent_link.py` 7 passed(WELCOME 전 미연결, EVENT ack 섞인 반쯤 열린 링크 abort, 느린 허브 backoff 1→2→4→8, 안정 세션 뒤 1 s 복귀, 답 시한 검증).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(fleet_agent): D-419 라운드 3 — ERROR 답은 살아 있음, Fleet 없는 로봇 부팅
- 변경: 허브는 메시지마다 한 번 순서대로 답하므로 Agent 가 보낸 요청 종류를 큐에 두고 답을 맞춘다. 하트비트에 대한 ERROR 답(예: 이벤트 행 하나가 상한 허브의 TASK_PROJECTION_UNAVAILABLE)은 답으로 세어 링크를 유지하고 60 s 에 한 번 경고, PAIRING_INVALID·SESSION_NOT_PAIRED·DUPLICATE_IDENTITY·IDENTITY_DRIFT·PROTOCOL_UNSUPPORTED 는 세션을 즉시 끝낸다. EVENT ACK 는 여전히 시한을 채우지 못한다(HEARTBEAT 답에서 큐 재동기). hello 답 시한, WELCOME 확인 뒤에만 last_rx, 이벤트는 보낸 뒤에 꺼냄(취소·오류 시 유지). Fleet 링크가 없는 로봇은 잘못된 답 시한에 경고 후 기본값. 하트비트 주기·여유를 인스턴스 값으로(시험 주입). `fleet_loss.py`: 판정 시간 하한과 기본 신선도를 Agent 상수·`link_timing_floor_s` 한 식에서 유도.
- 증거: `test_fleet_agent_link.py` 16 passed(ERROR 답 유지·안정·경고 1회, 오류 허브 뒤 backoff 1 s 복귀, 페어링 오류 즉시 종료, hello 시한, 이벤트 보존 2건, Fleet 없는 로봇 경고), `test_fleet_loss.py` 31 passed(실제 `_serve`+FakeHub+실제 모니터: 느린 건강 허브 무발화, 침묵 허브 last_rx+timeout 발화, ERROR 허브 무발화). 새 도우미 `test/fleet_hub_fake.py`.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(fleet_agent): D-419 라운드 4 — 인코딩 불가 이벤트, EVENT 에 대한 오류
- 변경: 이벤트는 보내기 전에 인코딩하고, 인코딩할 수 없으면(JSON 밖 데이터) 로그 후 버린다 — 맨 앞에 남으면 모든 세션이 죽었다. 전송 실패(WebSocketException·OSError)와 취소만 이벤트를 남기고, 다른 보내기 오류는 그 이벤트를 버리고 계속한다. 인코딩 뒤에만 `_awaiting` 에 넣는다. 치명 코드는 하트비트에 대한 답일 때만 세션을 끝낸다(PAIRING_INVALID 는 언제나) — 허브가 검증 못 한 EVENT 에 SESSION_NOT_PAIRED 로 답하기 때문. 경고 억제는 (코드, 답한 요청) 별. 시험용 FakeHub 는 하나의 순서 큐로 답하고 EVENT 에 EVENT `{accepted}` 로 답한다.
- 증거: `test_fleet_agent_link.py` 21 passed(인코딩 불가 이벤트 버림·세션 유지·뒤 이벤트 전달, 전송 실패 시 보존, 비전송 오류 시 버리고 계속, EVENT 에 대한 ERROR 는 하트비트를 깨우지 않음, EVENT 에 대한 SESSION_NOT_PAIRED·EVENT_NOT_AUDITABLE 로 세션 유지 + 로그 분리).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(fleet_agent): D-419 최종 리뷰 LOW — 실패한 보내기의 `_awaiting` 항목 회수
- 변경: `_send_text` 는 `ws.send` 가 전송 밖 예외(WebSocketException·OSError 아님)로 실패하면 방금 넣은 `_awaiting` 꼬리 항목을 빼고 다시 던진다. 이전에는 `_event_loop` 가 이벤트를 버리고 세션을 유지하면서 낡은 EVENT 항목이 남아, 뒤 답(하트비트 ERROR 등)이 그 항목에 잘못 맞춰져 살아 있는 허브에서 세션이 끊기고 SAF-003 가 발화할 수 있었다.
- 증거: `test_fleet_agent_link.py::test_non_transport_send_error_drops_that_event_and_goes_on` 가 남은 `_awaiting == [EVENT]`(전달된 이벤트 하나)를 확인. `test_fleet_agent_link.py`+`test_fleet_loss.py` 52 passed.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(fleet_agent): D-419 착지 — main 의 D-407 수신 루프와 병합
- 변경: main 이 따로 바꾼 FleetAgent(D-407 A: `_session`·`_receive_loop`·`_inflight`, `linked_within(grace)`, 이벤트 재전송 3 회·`EVENT_NOT_AUDITABLE` 버림, 세션 끝에 답 없는 이벤트 되돌림, HELLO 답 5 s)와 D-419 FleetAgent(답 시한·`last_rx`·안정 세션 backoff·치명 코드)를 하나로 합쳤다. 리더는 D-419 `_reader_loop` 하나, `_awaiting` 항목은 `(종류, 이벤트)` 라 EVENT 에 대한 ERROR 는 D-407 규칙(`_refuse_event`)으로, 하트비트에 대한 ERROR 는 D-419 규칙(치명 코드·60 s 경고)으로 간다. `_session` 이 hello 를 맡고 `HELLO_TIMEOUT_S`(5 s)를 쓴다, `_serve` 는 끝낸 루프와 이유를 `_end_reason` 에 남겨 `Fleet agent link lost (…)` 로 기록, backoff 는 D-419 대로 답 3 개를 받은 세션 뒤에만 1 s. 실패·취소된 보내기는 어떤 예외든 `_awaiting` 에서 뺀다(되돌림이 맨 앞에 남은 이벤트를 두 번 넣지 않게).
- 시험: `test_fleet_agent_link.py` 를 두 쪽 합본으로 — D-419 의 hello 무응답·취소 보존 시험은 같은 것을 보는 D-407 시험으로 대체, `_awaiting` 튜플, EVENT 오류 로그는 이벤트마다(`event seq`)·하트비트 degraded 경고와 분리. D-407 `Closing` 은 `recv` 로 끊긴다(리더가 `async for` 대신 `recv()`).
- 증거: `test_fleet_agent_link.py`+`test_fleet_loss.py` 62 passed.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · fix(fleet_agent): D-419 착지 리뷰 — 이벤트 동시 전송 상한, 되돌림 중복, 하트비트 시한
- 변경: 답을 기다리는 EVENT 를 `MAX_EVENTS_IN_FLIGHT`(8)개로 묶는다(리더가 EVENT 항목을 뺄 때마다 `_event_slot` 을 깨움) — 긴 단절 뒤 최대 1000 개를 연달아 보내면 이벤트마다 한 번 커밋하는 허브가 그 뒤의 하트비트를 2 s 시한 밖에서 답해 세션이 끊기고 backoff 가 늘며 SAF-003 가 살아 있는 허브에서 STOP 할 수 있었다(MEDIUM). `_requeue` 는 버퍼에 아직 있는 이벤트(같은 객체)를 건너뛴다 — drain 에 걸린 보내기의 항목이 꼬리가 아니면 남아 버퍼가 [1, 1] 이 되던 것(LOW-1). 하트비트의 보내기와 답 대기를 한 `wait_for(reply_timeout_s)` 로(LOW-2). HEARTBEAT 재동기가 건너뛴 EVENT 항목은 버리지 않고 버퍼로 되돌린다. `recently_heard`·`last_rx` 는 `self._clock`. main 의 `reconnecting in N s` 로그 복원. agent.py ruff 지적 17→8(`X | None`, 파싱 `except ValueError`, TRY004 noqa; 남은 것은 main 에도 있는 import 순서·광범위 except).
- 시험: `test_event_backlog_does_not_starve_the_heartbeat`(상한을 풀면 실패 확인), `test_requeue_does_not_duplicate_an_event_held_in_send`, `test_heartbeat_send_held_in_drain_aborts_at_the_deadline`, `test_heartbeat_resync_puts_skipped_events_back`; `test_backoff_keeps_doubling_without_a_stable_session`(이름·설명을 답 3 개 규칙으로), 취소 시험에서 죽은 `_send_lock` 제거·`_awaiting` 비었음 확인. `fleet_hub_fake.FakeHub(service_s=…)` 는 한 번에 하나씩 처리하는 허브.
- 증거: `test_fleet_agent_link.py` 35 passed ×3.
- 열린 D-407 후속(고치지 않음): 일시 오류로 거부되어 `_refuse_event` 가 버퍼 앞에 다시 넣은 이벤트는, 그 사이 세션이 끊기고 재접속 WELCOME 의 `last_event_seq` 가 그보다 큰 seq 를 가리키면(뒤 이벤트는 저장됨) `_session` 의 seq 필터(`e.seq > last_event_seq`)에 걸려 조용히 사라진다. 제안: 재전송 대기 이벤트를 seq 필터에서 면제되는 별도 재시도 목록에 두기(허브는 event_id 로 중복을 걸러 다시 보내도 안전).
- gate 변화: 없음.

## 2026-10-03 · uncommitted · test(fleet_agent): D-419 시험 시간 여유 — 포화된 호스트
- 변경: 시험만. 100 % CPU 호스트에서 시간 여유가 모자라 떨어지던 시험을 넓혔다(논리 실패는 없었다). `test_fleet_loss.py` `_agent_rig` 기본값을 주기 0.1·답 시한 0.8·여유 0.1(신선도 1.0)·판정 1.5 s 로(주기 < 답 시한 < 신선도 < 판정 순서 유지), 느린 허브 2.0 s·degraded 1.5 s 관찰, 침묵 허브 발화 구간 1.5 ≤ t < 2.1 s. `test_fleet_agent_link.py`: degraded 허브 답 시한 1.0 s·`answered >= STABLE_HEARTBEATS`, 밀린 이벤트 시험 답 시한 1.0 s(상한 최악 ~0.23 s, 상한 없으면 200×0.025 = 5 s — 상한을 풀면 여전히 실패함을 확인), `timeouts` → `within_cap`.
- 증거: 아래 커밋 메시지·보고의 3 회 실행.
- gate 변화: 없음.

## 2026-10-03 · b84e72c55 · feat(vision): D-423 학습 모델 상태 저장소(읽기 전용)

- 변경: `core_features/vision/models.py` `ModelStatusStore` — `perception/learned/status`(lane_seg shadow)·`perception/learned/object_det/status`(object_det active) 상태를 작업별로 보관, 나이·stale. `VisionFrameStore.models` 로 붙인다. 교체·선택 기능 없음.
- 증거: `test_vision_models.py` 8 passed; `src/runtime/services/test` 포함 묶음 739 passed, 37 skipped.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · feat(link): D-432 주소 없는 장비 접속

- 변경: FleetAgent가 실제 SRV 주소·port·TLS DNS 이름을 보존한다. 인증/신원 충돌은 종료하고 일시 발견 실패는 jitter로 재시도한다.
- 증거: 관련 Python 계약 시험·실제 loopback TLS HTTP/WS 시험을 실행했다. Pilot Android 설치·화면과 실제 로봇 연결·현장 트래픽 수용은 서로 다른 증거다.
- gate 변화: 실제 장비의 제어·FIELD 관문은 이동하지 않는다.
- 결정: D-432 2026-10-03 추가 결정.

## 2026-10-04 · uncommitted · D-442 U1 MANUAL 보호

- 변경: 살아 있는 수동 세션의 NAVIGATION 전환을 ModeMachine에서 거부한다. teleop 입력과 watchdog 갱신은 같은 모드 잠금 안에서 다시 확인한 뒤 반영한다. API의 자율 진입은 부작용 전에 409 MODE_CONFLICT로 거부한다. 정지와 만료된 세션은 기존 전환을 유지한다.
- 증거: 신규 회귀 시험에서 탈취 5 failed, 경합 1 failed, line-follow 취소 부작용 1 failed를 수정 전에 재현했다. 관련 시험 167 passed, known_failures 비교 NEW 0, lint 0 errors. 독립 재리뷰에서 경합 양방향과 교착 부재를 확인했고 코드 차단 사항 없이 승인했다. 근거는 docs/validation/d427-source-migration/manual-ownership-review-2026-10-04.md.
- gate 변화: 없음. 호스트 검증이며 sim·장치·실주행 수용은 미실행이다.

## 2026-10-04 · uncommitted · feat(vision): 차선 입력의 실제 출처와 정지 설정 예약

- 변경: 읽기 전용 keeper paint 증거는 별도 vision store에서 camera stamp·requested source·실제 모델 판·receipt freshness를 검사한다. stale·잘못된 packet·다른 설정·다른 모델은 unknown이다. Motion 입력으로 소비하지 않는다.
- 변경: ModeMachine의 원자 IDLE 예약은 설정 변경 동안 이동 모드 전환을 막고 정지·비상정지를 유지한다. 보정 admission과 설정 admission은 별도 RLock으로 묶고 내부 mode/docking lock 순서를 유지한다.
- 증거: Host 요청이 정지해 있는 동안 주행 API·최종 전환 거절 및 finally 해제, 보정 admission 경합의 red/green을 포함한 82 passed. 독립 검토: docs/validation/learned-lane-modes-2026-10-04/README.md.
- gate 변화: 없음. SOURCE/LOCAL 관측·admission 검증이며 실제 구동 수용은 별도다.

## 2026-10-04 · uncommitted · fix(line-follow): 저조도 정지와 recovery 차단

- 변경: CAMERA_LINE low_light 관측은 visible=false/confidence=0으로 검증하고 즉시 정지한다. LOST 이후에도 public tick에서 local recovery를 우회하고 기존 back-off를 취소한다. IR·LiDAR 한도는 변경하지 않는다.
- 증거: 모든 후진 조건을 만족한 저조도 LOST에서 -0.03 m/s가 발생하는 RED를 재현한 뒤 차단했다. 이미 BACKING일 때 어두운 관측을 받으면 이전 command decision도 evidence revision으로 거절한다. focused CORE/preview/protocol 143 passed, 1 skipped; recovery API/active-backoff 55 passed. 로그는 X:/DevTemp/rosy-lane-device-20261004/lowlight-*.txt.
- gate 변화: SOURCE/LOCAL. 사용자가 기기 곁에 없으므로 실제 이동은 시험하지 않았다.

## 2026-10-04 · uncommitted · feat(vision): 같은 capture의 bounded raw/annotation pair

- 변경: 최대4개 원본/주석 frame cache는 stamp·frame_id·크기가 일치할 때만 pair로 제공한다. viewer admission은 pair당 공유하며 각 variant를 한 번만 허용한다. stale/missing raw는 대체하지 않고 counterpart는 cache/TTL 안에서만 고정한다.
- 변경: source image age와 monotonic 수신 나이를 합쳐 조도와 raw freshness를 제한한다. 얼굴 handover도 effective quality_age_ms를 전달해 지연된 사진이 추가2초 조명 권한을 받지 않는다. 이동 경로로 사용하지 않는다.
- 증거: pair/malformed/dimension/stale/admission/capture-age와 API/Guard/Bridge/schema 포함162 passed,1 skipped.
- gate 변화: SOURCE/LOCAL. 실제 기기의 capture pair 수신은 별도 증거다.

## 2026-10-04 · uncommitted · fix(vision): preserve fresh overexposed quality
- 변경: 원본 조도 invalid reason overexposed를 preview store, API protocol, face handover sanitizer에 전달한다. low_light 조명 허용 범위와 2초 촬영·수신·handover 신선도는 유지한다.
- 검증: 과다 노출 관측을 버리는 RED 3 failed; API·handover·stale 회귀 포함 GREEN은 X:/DevTemp/rosy-lane-device-20261004/overexposed-api-green.txt. 배포·실주행 미검증, 명령 전송 없음.
- 추가 검증: face handover integration RED 1 failed로 display whitelist 누락을 확인·수정. 최종 focused 129 passed, 3 skipped (overexposed-api-green.txt).

- gate 변화: SOURCE/LOCAL. 실기 노출·조명·주행은 별도 검증이다.

## 2026-10-04 · uncommitted · feat(power): fresh battery evidence and idle saving

- 변경: 반복 저배터리 표본의 wake를 단계 변화로 제한하여 기존 IDLE/STANDBY 타이머가 동작한다. Viewer GET /api/v1/power/health와 공유 typed 응답에 배터리·충전 확인 age, 정책 상한·wake 근거, shutdown 요청, 진단 요약을 제공한다. API Ref v1.92, envelope 1.0 유지.
- 검증: injected clock 회귀와 auth/read-only API, 기존 배터리·정지·sentinel 경로 검증. 최종 근거는 docs/plans/2026-10-04-power-health-and-wake.md. OS halt·EEPROM·GPIO·기본 LiDAR 모터 정책 변경 없음.
- gate 변화: SOURCE/LOCAL; 실제 소비전력·충전·RTC/외부 버튼 wake와 배포는 미검증.

## 2026-10-04 · uncommitted · feat(power): long testing dwell with low battery saving

- 변경: 정상 IDLE/STANDBY 기준을 600/1800초로 늘리고 warning60/300, critical/deep30/120초와 min을 취한다. YAML override·API effective timers에 연결한다. 기존 이동·정보 hold·disabled와 배터리 정지/종료 권한을 유지한다.
- 증거: 주입 시계·설정 parser RED3 failed, 전원/배터리/bridge GREEN180 passed. 구조 재판정은 docs/plans/2026-10-04-power-health-and-wake.md에 기록한다.
- gate 변화: SOURCE/LOCAL. 기기 소비전력·물리 wake·배포 검증은 별도다.

## 2026-10-04 · uncommitted · D-452 승인 Fleet 발견 우선

- 변경: 지속 token과 hostname/CA pin이 있는 Agent는 legacy hub URL보다 발견을 우선하고 잘못된 pin/충돌/신뢰 실패에 우회하지 않는다.
- 증거: focused60 PASS 및 독립 source SPEC·Quality·Safety review PASS, source-checkpoint.md.
- gate 변화: SOURCE/LOCAL focused; 실제 robot/Fleet 연결·다른 망 실행 수락은 별도.

## 2026-10-04 · uncommitted · fix(safety): 활성 양보 구간 기한 보존

- 변경: TURNING/CRAWLING 중 새 YIELD 답변은 기존 거절 계약으로 처리하여 같은 또는 다른 구간이 현재 deadline·phase·twist를 재설정하지 못하게 한다. YIELDED 후 다음 구간과 기존 단일 command publisher·lease·E-Stop 경계를 유지한다.
- 증거: 신규 4개 RED→GREEN, 상태 머신·manager·API 관련 115 PASS. main 병합 후 Fleet/CORE ownership 재판정에서 기존 파일/패키지 예산과 분할 의무는 유지한다.
- gate 변화: SOURCE/LOCAL. 실제 장비 구동·모드 변경·정지 해제·DEVICE/FIELD 수락은 실행하지 않았다.

## 2026-10-05 · uncommitted · feat(vision): D-368 운전자 스트림 게이트와 latest_frame

- 변경: `core_features/vision/stream.py` 추가 — `DriverStreamGate`(마지막 수락 teleop 토큰이 조종 소유권, D-460 임대 없음). 단일 슬롯, 운전자 교체 시 즉시 슬롯 해제, `close` 멱등. `VisionFrameStore.latest_frame(overlay=)` 추가 — 스트림 경로용, viewer 폴링 속도 제한 없이 raw pair 신선도(수신+source age) 검사.
- 증거: `test/test_vision_stream_gate.py` 5 PASS(미운전 409·단일 슬롯·교체 퇴거·멱등 close·빈 토큰 무시). 스토어 회귀는 기존 시험 유지.
- gate 변화: SOURCE. ROS-SIM fps·지연 측정과 DEVICE 영상 수용은 별개(D-368 Validation 참조).

## 2026-10-05 · uncommitted · feat(command): cumulative bounded trial

- 변경: private trial ledger, original odom stamp/frame and final CORE port restriction; no second publisher/API/config activation.
- 증거: synthetic guard26PASS, installed geometry/CORE independent180PASS/NEW0. Actual measurement/braking UNKNOWN, no motion or push.
- gate 변화: SOURCE/LOCAL only; HOLD/readiness retained. Plan docs/plans/2026-10-05-core-bounded-camera-trial.md.

## 2026-10-05 · uncommitted · fix(core): 제한 시험 STOP와 최종 제출 직렬화

- 변경: 소유자가 미확정 양수 제출 의도를 먼저 영속화한 뒤, canonical SQLite `BEGIN IMMEDIATE`와 같은 소유자의 `RLock` 안에서 최종 STOP·신선도 확인부터 기존 `PinkyTwistPort.submit` 콜백까지 유지한다. 공개 `permits` 판정은 제출 권한이 아니며 production bridge는 `submit_fenced`를 사용한다. 다른 연결의 STOP·재개장은 제출 전후로 직렬화되고 잠금 실패는 양수 제출을 거부한다.
- 증거: 실제 SQLite에서 허가 확인 뒤 확정된 STOP에도 0.04가 제출되던 회귀와 writer 중 재개장 허용 회귀 RED 2 FAIL. 동일 소유자·별도 연결의 실제 threaded STOP, 기존 bounded/cmd_vel 시험 GREEN 43 PASS 2.44초 (`X:/DevTemp/rosy-ui-ship/trial-fence/final-tests.log`). 미확정 송신·영속화 실패는 기존 정지 래치를 유지하고 양수 재시도하지 않는다.
- gate 변화: 이 변경의 SOURCE/LOCAL 검증만. 실기 이동·제동·거리 bounds, ARM 산출물·배포·FIELD 수용은 미실행이며 기존 제한 시험은 안전 승인이나 public API/config 활성화가 아니다.

## 2026-10-05 · uncommitted · test(core): D-184 제한 시험 소유 경계 복구

- 변경: ledger·envelope·pose freshness·재개장 순수 정책 검사 10개를 services의 `test_bounded_trial_owner.py`로 옮겼다. 소유자 검사 helper는 실제 `submit_fenced`와 합성 callback만 사용하고 gateway를 import하지 않는다. 기존 테스트 함수 20개의 AST·단언은 모두 보존하며, bridge 최종 제출·준비 상태·미확정 응답·odometry·camera mux·STOP 경합 및 envelope 변조의 bridge 예외 처리는 gateway의 나머지 10개 함수가 검증한다. runtime·frozen 예외 목록·소유권 검사 구현은 바꾸지 않는다.
- 증거: 정규 push의 D-184 실패를 exact RED 1 FAIL로 재현했다. 최종 소유자·gateway 제한 시험·기존 cmd_vel·D-184 검사 44 PASS/2.16초, services 단독 19 PASS/1.13초. 중간 envelope 변조 검사는 owner 예외를 bridge의 ZERO와 혼동하여 1 FAIL이었고 gateway에 원문 그대로 되돌렸다. 원본 실패와 최종 로그는 X:/DevTemp/rosy-ui-ship/trial-fence/ownership-*.log에 보존한다.
- gate 변화: SOURCE/LOCAL 검사 배치만. runtime bytes·권한·서명·실기 bounds·장치 상태·배포 수용은 변경하지 않는다.

## 2026-10-05 · uncommitted · feat(lane): D-468 local return building blocks
- 변경: ROS-free 차체 경계 여유·실제 자세 경로·동일 차로 비교·제한된 역추적/탐색/정렬/검증 정책과 optional containment 관측 입구 추가.
- 증거: 정책/계약/기존 bridge 및 line-follow 관련 76 PASS, 0 NEW. 독립 리뷰에서 발견한 후진 회전 여유·odom 초기화·후보 일관성·시각 재전송·정렬 상한·지면 출처 결함을 회귀 시험으로 고쳤다.
- gate 변화: 아직 manager의 주행 결정에 연결하지 않은 구성 요소. SOURCE 시험 외 SIM/DEVICE/FIELD 수용 없음.

## 2026-10-05 · uncommitted · feat(lane): bind original pose ledger to image geometry
- 변경: 순수 source-time 증거 ledger와 lock-owner mixin. 실제 자세 보간·projection uncertainty/관측 범위·연속성 epoch·시각 재전송을 검증하며 무효 관측/모드 종료는 경계를 폐기한다.
- 증거: source 관련 회귀/구조 검사 109 PASS, 0 NEW. 독립 리뷰가 발견한 잘못된 quaternion과 source/receipt 시각 비교를 고쳤다. 패키지 13717줄 재판정은 기존 소유/모듈 분리와 모든 한도를 유지한다.
- gate 변화: SOURCE evidence admission 연결만. ReturnController의 이동 제안 적용은 아직 없음.

## 2026-10-05 · uncommitted · fix(lane): normal return anchor and measured fallback approach
- 변경: 원본 영상 시각·연속성 epoch로 복구 검증을 제한한다. 정상 기준 위치는 차체 여유 25mm·방향 오차 0.12rad 이내일 때만 저장한다. 기준 경로가 없으면 동일 차로 후보로 저속 접근하고 실제 이동·회전·시간 한도를 적용한다.
- 증거: 경계 직전 기준 위치를 계속 덮어써 복귀하지 못하던 폐루프 실패를 재현·수정했다. 정지 바퀴·20% 미끄러짐·증거 만료·양방향 탐색 후 Fleet 요청을 시험했다. 독립 리뷰의 복구 직후 기준 저장 조건 누락도 회귀 시험으로 수정했다.
- gate 변화: 순수 정책과 합성 평면 운동 시험만. 실제 명령 판단 연결·배포·실기 복구는 미완료다.

## 2026-10-05 · uncommitted · feat(lane): arbitrate measured return before ordinary following
- 변경: 실제 매니저가 typed containment·실측 자세 ledger를 복구 정책에 연결하고 일반 추종보다 먼저 판단한다. 같은 generation/evidence_revision과 최종 CORE 경로를 사용하며, 제출 순간의 권한·자세 신선함·이동 공간 판정을 다시 검사한다.
- 증거: 매니저 폐루프에서 접근·세 영상 검증·정상 추종 재개를 시험했다. 독립 리뷰에서 재현한 운전자 권한 만료, 순수 회전 중 live linear ceiling 철회, Fleet RESUME 뒤 stuck 재생성을 각각 회귀 시험으로 수정했다.
- gate 변화: 명령 제안 연결의 호스트 증거만. 실제 바닥·swept path 공급자는 아직 런타임에 연결하지 않았고 장치 배포·주행은 수행하지 않았다.

## 2026-10-05 · uncommitted · feat(lane): require complete scan and swept-body clearance for D-468
- Change: validate complete fine-resolution 360-degree scan coverage and valid ranges; self-masked, stale, partial, or malformed evidence denies return. Sweep the candidate against body geometry, blind range, braking margin, and downstream linear scaling.
- Evidence: lane manager/stuck recovery checks 89 PASS, 0 NEW; gateway and architecture checks recorded in the bridge log. Host source only.
- Gate: source provider available; physical floor extent and device/field behavior remain unverified.

## 2026-10-05 · uncommitted · fix(lane): retain scan provenance and operator fallback authority
- Change: preserve LiDAR source stamps, reject replayed/non-increasing scans, keep no-return rays unknown, and expand the full body sweep for worst-case motion since scan acquisition. Local exhaustion holds for operator input with actual geometry evidence; accepted operator YIELD retains CORE arbitration through its active phases.
- Evidence: services suite 871 PASS, 0 NEW; D-468 focused manager/scan/API checks 53 PASS, 0 NEW. Full gateway suite is running with contract source paths configured.
- Gate: host-only source evidence; signed deployment, device readback, and field recovery remain unverified.

## 2026-10-06 · uncommitted · feat(lane): D-476 expected-road bridge in CORE, default off
- 변경: `line_follow/lane_bridge.py` 추가. 짧은 차선 손실(`line_not_visible`·`observation_stale`·`no_observation`)이 검증된 차로 내부 추종 바로 뒤에 오면 D-468 checkpoint 차로의 직선 연장을 odom에서 천천히 따른다. 실측 이동 × 1.08로 D-384 0.10/0.25 m 사다리, `lost_after_s − 0.5 s`에서 끝. bridge 호를 D-422 의도로 두고 몸 간격과 D-468 동작 증명을 통과해야 한다. 끝나면 bridge 이동을 포함한 trail로 D-468 역추적 경로를 다시 만든다(`ReturnController.rebase_retrace`, 동작 같음). 손실 시계는 건드리지 않는다. `line_follow.bridge_*` 파라미터, 기본 `bridge_enabled: false`. safety 파일(`body_stop.py`·`clearance.py`)은 바꾸지 않았다.
- 증거: `test_lane_bridge.py` 24 PASS(꺼짐 = 오늘 동작, 진입 거부 6종, 거리·시간 상한, 장애물·bridge 호 쓸기, 재획득, D-468 인계, LOST 시계 동일). services 전체 895 PASS, gateway 전체 2168 PASS·17 skip, known_failures 둘 다 0 new. 패키지 크기 guard는 main이 이미 13933+150 끝(14083)이라 14235로 다시 판정했다(`test/architecture/test_module_structure.py` SIZE_VERDICTS, 착지 전 독립 재검토 필요).
- gate 변화: SOURCE 호스트 시험만. 결정 7의 재생·시뮬(모델·사이트 PC)·장치 단계 전에는 켜지 않는다.
- 결정: D-476 (Proposed)
- 교훈: 없음

## 2026-10-06 · uncommitted · fix(lane): D-476 independent review fixes
- 변경: 열린 stuck에서는 bridge하지 않고, 손실 시계가 거꾸로 가면 끝낸다. D-468 역추적 경로는 bridge가 끝나는 틱에 한 번만 다시 만든다(장애물·stuck 같은 이른 반환 포함). bridge 중에도 `apply_if_current`가 제출 재검사를 한다. `_init_bridge` 중복 호출 제거, 모드 변경 시 경로 힌트 초기화. API Reference의 `RECOVERING` 설명에 D-468·D-476 사용을 적었다.
- 증거: `test_lane_bridge.py` 41 PASS(새 실패-먼저 시험 4: stuck, 한 번 rebase, 힌트 초기화, 역행 시계는 직접 호출 시험으로 확인). services 912 PASS, gateway 2168 PASS·17 skip, architecture/harness 219 PASS·1 skip, known_failures 셋 다 0 new. 크기 판정 14258, 독립 재판정 ACCEPT.
- gate 변화: 없음. SOURCE 호스트 시험만.
- 결정: D-476 (Proposed)
- 교훈: 없음

## 2026-10-07 · uncommitted · feat(state): D-494 2 상태 스냅샷의 odom_pose

- 변경: `StateManager.set_odom_pose(x, y, yaw)`가 받은 순간의 벽시계(UTC epoch 초)를 `stamp`로 붙여 보관하고, `snapshot()`이 `odom_pose`로 싣는다. odom이 한 번도 오지 않으면 `null`이다. map 자세가 `pose`를 가져도 같이 싣는다.
- 증거: `test_state_odom_pose.py` 2 PASS(null→값, 하트비트 왕복, 옛 스냅숏 파싱). services 941 passed, known_failures 0 new.
- gate 변화: 없음.
- 결정: D-494 (Proposed)

## 2026-10-07 · uncommitted · fix(state): D-494 검토 — 유한하지 않은 odom 표본을 버린다

- 변경: `OdomPose`를 frozen·유한 값만으로 바꾸고, `set_odom_pose`는 NaN/inf 표본을 버리고 이전 값을 두며 한 번만 경고한다. NaN 하나가 `/state`를 500으로 만들지 않는다.
- 증거: `test_state_odom_pose.py` 3 PASS, gateway `/robot/state` NaN 시험 PASS.
- gate 변화: 없음.
- 결정: D-494 (Proposed)

## 2026-10-07 · uncommitted · feat(line_follow): D-494 교차로 지시 게이트
- 변경: 새 `core_features/line_follow/junction.py`. 지시 하나를 보관하고 틱 결정을 그대로 두거나 0으로 만든다. 지시 없음·만료 + 교차로 감지는 `junction_waiting`, `left`·`right`는 분기 후보가 없어 곧바로 `junction_unresolved`, `stop`은 측정 odom으로 `stop_after_m` 뒤 `junction_stop`(odom 없으면 바로). `straight`는 D-476 route hint를 채운다. 모드 변경이 지시를 지운다
- 증거: `test_line_junction.py` 18 PASS, `test_line_junction_api.py` 8 PASS. services·api_web·contracts/foundation·line-follow 문서 시험 1859 PASS·18 skip, gateway 2187 PASS·17 skip, Fleet 버전 고정 시험 90 PASS, `test/known_failures.py` 0 new (2026-10-07 Windows)
- gate 변화: 없음. SOURCE 호스트 시험만. 실기·SIM 미실행(Gazebo는 이 노트북에서 돌리지 않음)
- 결정: D-494 (Proposed) 4항, 구현 부록 2026-10-07
- 교훈: 오늘 인식은 CORE에 분기 후보를 주지 않는다. 좌·우 주행은 분기 계약 ADR이 먼저다

## 2026-10-07 · uncommitted · feat(line_follow): D-495 교차로 제한 회전
- 변경: `junction.py`에 `turn_deg`가 있는 좌·우 지시의 회전(odom yaw, ±5°)→전진(`advance_m`, 절반 속도)→차선 재획득(0.20 m·5 s) 동작을 더했다. odom 낡음·점프, 모드 변경·E-Stop·운전자 해제, D-422 근접, 동작 확인 실패, 한도 0, stuck, 시간 초과, 새 지시는 `aborted`와 0 명령이다. `turn_deg` 없는 좌·우는 그대로 `unresolved`
- 증거: `test_line_junction.py` 44 PASS, `test_line_junction_api.py` 9 PASS. services·api_web·contracts/foundation·line-follow 문서·perception 배선 1968 PASS·18 skip, gateway 2188 PASS·17 skip, perception 2704 PASS·109 skip, `test/known_failures.py` 0 new (2026-10-07 Windows)
- gate 변화: 없음. SOURCE 호스트 시험만. SIM(모델 PC map_v2_fleet_real)·DEVICE 미실행
- 결정: D-495 (Proposed), 구현 메모 2026-10-07
- 교훈: 기본값을 켜는 ADR은 그 값의 전제(`recovery_local_enabled`, keep 모드)와 되돌리기 경로를 코드로 확인해야 한다

## 2026-10-07 · uncommitted · feat(line_follow): D-495 supports_junction_turn
- 변경: `LineFollowManager.supports_junction_turn`: 최근 2 s 안의 신선한 `line/keep_debug` 프레임이 `corner_turning: true`를 실을 때만 참(keep 모드 + 교차로 감지 + 제한 회전). 능력 `junction_turn`의 근거
- 증거: services·api_web·contracts/foundation·line-follow 문서·perception 배선/lane_keep 1969 PASS·18 skip, gateway 2190 PASS·17 skip, `test/known_failures.py` 0 new (2026-10-07 Windows; 동시 실행 중 `test_site_rooms.py` 자식 프로세스 시간 시험 한 번 실패, 단독·재실행 통과)
- gate 변화: 없음. SOURCE 호스트 시험만. SIM·DEVICE 미실행
- 결정: D-495 (Proposed) 결정 개정 2026-10-07
- 교훈: 인식 파라미터는 CORE 설정이 아니다. 능력 판정은 살아 있는 증거로 한다

## 2026-10-07 · uncommitted · fix(line_follow): D-495 독립 안전 검토 M1–M8·L1·L2
- 변경: 정지 확인 0.2 s 뒤 회전, 지연 보정(`junction_turn_lead_s`)과 ±5° 0.3 s 머무름, 전진 한도 `advance_m`/속도+2 s, 연속 `junction_reacquire_frames` 재획득과 ±30° 방향, 보정 lease·미바인딩 동작 확인 중단, 같은 지시 무동작, CAMERA_LINE 전용, `stop`은 교차로에서도 HOLD, 교차로 전 손실은 `lane_lost_before_junction`
- 증거: services·api_web·contracts/foundation·line-follow 문서·perception 배선/lane_keep·Gazebo launch 고정 시험 2007 PASS·18 skip, gateway 2192 PASS·17 skip, 문서 시험 1 PASS, `test/known_failures.py` 0 new (2026-10-07 Windows). 검토 탐침 `probe_lag.py`·`probe_junction.py` 재실행
- gate 변화: 없음. SOURCE 호스트 시험만. SIM·DEVICE는 D-495 수용 점검표
- 결정: D-495 (Proposed) 독립 안전 검토 반영 2026-10-07
- 교훈: 지연이 있는 odom 위의 닫힌 고리는 지연 보정과 머무름 확인이 있어야 허용 오차를 지킨다

## 2026-10-07 · uncommitted · fix(line_follow): D-495 안전 재검토 N1·R1–R3
- 변경: 한 교차로 정지의 진입 yaw를 기억해 모든 회전이 진입 yaw + turn_deg를 겨눈다. 실행된 지시의 반복은 `JUNCTION_ALREADY_DONE`. 머무름 완료에 odom 정지 확인. 정지 중 감지 끊김에도 첫 감지 유지
- 증거: services·api_web·contracts/foundation·line-follow 문서·perception 배선/lane_keep·Gazebo launch 고정 2013 PASS·18 skip, gateway 2192 PASS·17 skip, `test/known_failures.py` 0 new (2026-10-07 Windows). 탐침 `probe_resend.py` 85.8°, `probe_lag2.py` 전 경우 ±5° 안
- gate 변화: 없음. SOURCE 호스트 시험만. SIM S1–S6·DEVICE D1–D6은 D-495 점검표
- 결정: D-495 (Proposed) 안전 재검토 반영 2026-10-07
- 교훈: 다시 보내는 지시는 현재 자세가 아니라 고정된 기준(진입 방향)을 겨눠야 오차가 쌓이지 않는다

## 2026-10-07 · uncommitted · fix(line_follow): D-495 최종 안전 검토 N2·L1·L3
- 변경: 교차로 정지 기록(감지·진입 방향·실행 기록)이 모드 변경 뒤에도 남는다. 진입 방향은 lost_after_s 무감지 뒤, 실행 기록은 다른 place_id 지시 때 끝난다. HTTP 409 JUNCTION_ALREADY_DONE 시험. 정지 판정 속도 설정값 `junction_still_linear`·`junction_still_angular`
- 증거: services·api_web·contracts/foundation·line-follow 문서·perception 배선/lane_keep·Gazebo launch 고정 2016 PASS·18 skip, gateway 2193 PASS·17 skip, `test/known_failures.py` 0 new (2026-10-07 Windows). 탐침 `probe_final.py`: 재선택 뒤 같은 지시 409, 다른 방향은 돌지 않음
- gate 변화: 없음. SOURCE 호스트 시험만
- 결정: D-495 (Proposed) 최종 안전 검토 반영 2026-10-07
- 교훈: 안전 기록은 세션(모드)이 아니라 물리적 상황(같은 교차로)에 묶어야 재선택으로 우회되지 않는다

## 2026-10-07 · uncommitted · merge(main): D-495와 D-476 rev 1 병합
- 변경: main(D-476 rev 1, D-494 1·2·3항, API v1.113)을 병합했다. `bridge_enabled` 로봇 기본값은 꺼짐을 유지한다(rev 1은 `ir_guard_enabled`와 바닥 근거가 없으면 CORE 시작을 거부함). `recovery_local_enabled`는 켜짐. API Ref 교차로 행은 v1.114. 크기 판정: schemas 1335, core_features 14934. 조건이던 분리 계획은 `docs/plans/2026-10-07-line-follow-recovery-subpackage.md`이고 독립 검토 대기
- 증거: services·api_web·contracts/foundation·문서·perception 배선/lane_keep·Gazebo launch·test/architecture 2193 PASS·19 skip, gateway 2206 PASS·17 skip, Fleet 버전 고정 89 PASS, `test/known_failures.py` 0 new (2026-10-07 Windows)
- gate 변화: 없음
- 결정: D-494 4항, D-495 (Proposed) main 병합 메모
- 교훈: 기본값을 켜는 결정은 병합 때 다른 브랜치가 더한 전제(IR guard·바닥 근거)와 다시 맞춰야 한다

## 2026-10-07 · uncommitted · fix(line_follow): D-495 junction_turn 능력은 동작 확인이 가능할 때만
- 변경: `supports_junction_turn`이 `bind_return_motion(proof_configured=...)`를 요구한다. 크기 판정 문구는 독립 재판정으로 바꾸었고 분리 계획에 junction.py 위치 이유를 더했다
- 증거: services·api_web·contracts/foundation·문서·perception 배선/lane_keep·Gazebo launch·test/architecture 2196 PASS·19 skip, gateway 2211 PASS·17 skip, `test/known_failures.py` 0 new (2026-10-07 Windows)
- gate 변화: 없음
- 결정: D-495 (Proposed) 착지 전 검토 반영
- 교훈: 능력 보고는 그 동작을 실제로 허가할 증거와 같은 조건이어야 정직하다

## 2026-10-07 · uncommitted · feat(line_follow): IR 감시는 알려진 횡단보도 구간에서 쉰다 (D-491)

- 변경: `crosswalk_zone.py`(odom 고정 구간), `LaneReturnMixin._crosswalk_rest`, `manager.py`에서 IR 판정이 left/right/centre이고 구간 안이면 `crosswalk`(사유 `ir_guard_crosswalk`, 정지·비킴 없음). 설정 `ir_row_x_m`(로봇 패키지, URDF), `crosswalk_zone_max_m`, `crosswalk_odom_error_fraction`. 계약 `CrosswalkExtentEvidence`, API v1.114.
- 증거: `test_ir_guard_crosswalk.py` 11건(구간 안 centre/left/right 계속, 구간 없음·NOMINAL·불확실도 없음·지나침·길이 상한·odom 끊김·IR 줄 없음은 `lane_departure`), 계약 시험 1건, URDF 일치 시험 1줄.
- gate 변화: 없음. IR 감시 기본 꺼짐. SIM·DEVICE 수용 별도.

## 2026-10-07 · uncommitted · fix(line_follow): 횡단보도 휴식은 회전·차로 이탈·거리 상한에서 끝난다 (D-491 리뷰)

- 변경: 독립 리뷰가 회전 뒤에도 구간이 끝나지 않아 IR 감시가 다른 도로에서 계속 쉬는 것을 재현했다(fail-open). 구간은 진행각 0.3 rad 초과, IR 줄이 영상 진행선에서 0.10 m + 여유 밖, 먼 끝 통과, epoch 변경에서 버린다. 한 번 쉬는 거리는 odom 실측으로 상한이 있고, 그 뒤 IR이 한 번 clear를 읽어야 다시 쉰다. 구간 판정은 감시가 켜진 매 틱에 돈다(자세 조회가 늦어 구간을 잃지 않게).
- 증거: `test_ir_guard_crosswalk.py` 17건. 회전·차로 이탈 시험은 각 검사를 끄면 실패함을 확인했다(MAX_TURN_RAD, CORRIDOR_HALF_M 변이). NOMINAL 거부는 구간 단위로, odom 끊김은 구간이 고정된 뒤로 시험을 고쳤다(리뷰: 로직 없이도 통과하던 두 시험).
- gate 변화: 없음. 결정 1의 D-468 문구를 ADR 구현 메모에서 정정했다(장치 기본에서 D-468 꺼짐).

## 2026-10-07 · uncommitted · test(line_follow): 260919 유격을 STL·URDF에서
- 변경: `test_lane_return_margin.py`가 몸을 `PINKY_PRO_GEOMETRY`에서, 260919 안쪽 가장자리를 STL 직선(160 mm)에서 가져온다. 유격 23.45 mm, u 4.3 mm·15 mm에서 차로 안·checkpoint, u ≥ 유격이면 아님. 5 mm 경우는 `VERY_NARROW_EDGE` 스트레스 차로로 이름을 바꿈. 수신기 코드 변경 없음
- 증거: perception 2712 PASS·109 skip, services+test/test_sim2real_gaps.py+test/architecture 1230 PASS·1 skip, gateway 2211 PASS·17 skip, `test/known_failures.py` 0 new (2026-10-07 Windows). generate·lint 0 error
- gate 변화: 없음. SOURCE 호스트 시험만. SIM 재실행(G-16)·매트 실측은 남음
- 결정: D-468 구현 메모 정정, D-476 개정 1 수치 (2026-10-07)
- 교훈: 시험 상수는 출처 있는 기하에서 끌어온다. 설명 없는 sim 값은 registry에 열어 둔다(G-16)

## 2026-10-07 · uncommitted · feat(line_follow): D-498 교차로 회전의 현장 근거
- 변경: `_turn_basis`: D-400 enforce 증명 또는 현장 근거(`junction_turn_site_accepted` + 신선한 IR 가드 판정(이탈 아님) + 신선한 스캔의 D-422 몸체 정지). `supports_junction_turn`은 읽을 때마다 재판단. 현장 근거로 시작한 회전이 근거를 잃으면 `turn_basis_lost`
- 증거: `test_junction_turn_site_basis.py` 15 PASS, `test_line_junction.py` 73 PASS. services·api_web·contracts/foundation·문서·perception 배선/lane_keep·test/architecture·Fleet 버전 고정 2297 PASS·19 skip, gateway 2212 PASS·17 skip, `test/known_failures.py` 0 new (2026-10-07 Windows). core_features 15050 (판정 14934+150=15084 안)
- gate 변화: 없음. SOURCE 호스트 시험만. 현장 설정·SIM·DEVICE는 D-498 순서
- 결정: D-498 (Proposed)
- 교훈: 없음

## 2026-10-07 · uncommitted · feat(line_follow): NOMINAL 지면 횡단보도 구간과 앞뒤 거리 여유 (D-491 개정)

- 변경: `CrosswalkZones.observe`가 지면 표시를 보지 않고 `uncertainty_m`(≤ 0.015 m)만 요구한다(D-468과 같다). 여유에 `crosswalk_range_error_fraction`(기본 0.05) × 먼 끝 거리를 더하고, 쉬는 거리 상한도 같은 비율만큼 늘린다.
- 증거: `test_ir_guard_crosswalk.py` 20건(NOMINAL + 운전자 확인에서 쉼, 불확실도 없음/초과는 구간 없음, 거리 여유가 끝을 넓힘). 실기 9dfk 측정은 D-491 개정 절.
- gate 변화: 없음. 장치 반영은 릴리스 뒤.

## 2026-10-07 · uncommitted · test(line_follow): D-495/D-498 교차로 회전 SIM 결과 기록
- 변경: 코드 변경 없음. 모델 PC SIM 기록 `docs/validation/d495-junction-sim-2026-10-07/result.md`.
- 증거: 현장 근거 회전 9건 오차 −4.08…+2.75°(모두 ±5° 안, 2–4° 덜 돎). 장애물·IR·스캔·odom 주입 7건 모두 다음 명령 주기(20 ms)에 0. 재획득 0/9, bridge 진입 0틱.
- gate 변화: 없음. SIM 증거만이고 SIM 수용 항목 S1·S2·S6은 미통과다.
- 결정: D-495, D-498 (Proposed). 결함 후보: `lane_return_evidence.py:52` 음수 odom 나이 리셋, `junction.py:318-320` CAMERA_LINE 선택 직후 회전 `aborted odom`, `unresolved`가 실행 기록에 안 남음(`junction.py:347-352`, `363-366`, `397-400`), 로봇 기본값 `recovery_local_enabled: true` + enforce 없음이면 출발 불가(`lane_return.py:326-327`).
- 교훈: 없음

## 2026-10-07 · uncommitted · fix(line_follow): 모드 선택 직후 교차로 회전은 첫 odom을 기다린다
- 변경: `junction.py` `_start_turn`에서 신선한 odom이 없으면 바로 `aborted odom`으로 끝내지 않고 `armed`로 남아 `junction_stopping` HOLD(명령 0)를 내며 첫 거부 시각부터 기다린다. `POSE_MAX_AGE_S`(0.3 s)를 넘도록 odom이 없으면 전과 같이 `odom`으로 중단한다.
- 증거: `test_line_junction.py::test_turn_armed_right_after_mode_select_waits_for_the_first_odom_sample` 먼저 실패 후 통과, `test_no_fresh_odom_at_the_junction_aborts_before_turning`은 0.3 s 대기 뒤 중단으로 바뀜.
- gate 변화: 없음. 호스트 시험만. SIM(`s2_sw_r110_a0`, `s9_scan_turn` 재현) 미실행.
- 결정: D-495 SIM 결과 결함 3 (`docs/validation/d495-junction-sim-2026-10-07/result.md`)

## 2026-10-07 · uncommitted · fix(line_follow): 회전 뒤 unresolved도 그 교차로 실행 완료로 기록한다
- 변경: `junction.py` `_maneuver`의 `unresolved` 전이 세 곳(재획득 중 D-407 stuck, 재획득 시간 한도, `REACQUIRE_M` 이동)을 `_unresolved(j, decision)` 하나로 모으고, 상태가 아직 `reacquiring`일 때 `_mark_done(j)`를 먼저 부른다. 진입 방향은 이미 지워져 있으므로 같은 `place_id` 재전송은 두 번째 회전을 쌓지 않고 409 `JUNCTION_ALREADY_DONE`이 된다. 다른 `place_id`가 기록을 지운다.
- 증거: `test_line_junction.py::test_unresolved_after_the_turn_counts_as_done`(세 경로) 먼저 실패 후 통과.
- gate 변화: 없음. 호스트 시험만. SIM S6(`s6_unresolved_resend`) 미실행.
- 결정: D-495 SIM 결과 결함 4 (`docs/validation/d495-junction-sim-2026-10-07/result.md`), 리뷰 R1

## 2026-10-07 · uncommitted · fix(line_follow): odom 원천 시각이 CORE 시계보다 조금 앞서도 자세 기록을 지우지 않는다
- 변경: `model.py`에 `SOURCE_FUTURE_TOLERANCE_S = 0.1`(기존 `manager.observe` 값)을 두고 `manager.observe`와 `lane_return_evidence.observe_pose`가 같이 쓴다. odom 나이가 `[-0.1, 0)`이면 0으로 보고, `-0.1`보다 앞서면 그 샘플만 버린다(trail·epoch 유지). 0.3 s 초과 리셋은 그대로다.
- 증거: `test_lane_return_evidence.py`(1 ms 앞 유지, 0.2 s 앞 버림·epoch 불변), `test_line_junction.py::test_turn_completes_with_odom_stamps_1_ms_ahead_of_core_clock` 먼저 실패 후 통과.
- gate 변화: 없음. 호스트 시험만. SIM(D-495 harness, odom 지연 제거) 미실행.
- 결정: D-495 SIM 결과 결함 2 (`docs/validation/d495-junction-sim-2026-10-07/result.md`)
- 교훈: 없음

## 2026-10-07 · uncommitted · core_features(line_follow): D-468 departure only on positive evidence (D-507 7)
- 변경: `recovery/lane_return.py` 추종 단계는 신선한 `ready` corridor 에서 `margin + uncertainty_m < 0`(또는 증명된 차로 안이지만 체크포인트 차로가 아님)일 때만 이탈을 연다. 그 밖은 `ReturnAction('tracking','containment_unknown')`. `recovery/lane_return_decision.py` 는 그 틱을 오늘의 추종 결정으로 넘기고 상태 `lane_return_containment` 을 채운다. 몸 기하 없음도 recovery off 와 같다(`lane_return_body_unknown` HOLD 제거). 포즈 불연속·epoch 변화는 그대로 이탈을 연다.
- 증거: `python -m pytest middleware/core/gateway/test middleware/core/services/test contracts -q` → `X:/DevTemp/d507-impl/b6/run.txt`, known_failures 비교.
- gate 변화: SOURCE. 선 잃음(근거 없음)은 이제 D-468 복귀가 아니라 손실 시계 → LOST 다. bridge 소진 뒤 역추적도 양의 증거가 있을 때만.
- 결정: D-507 7
- 교훈: 기존 시험 여럿이 `corridor=None` 을 이탈 신호로 썼다 — 이탈 시험은 몸이 경계를 넘은 corridor 로 쓴다.

## 2026-10-08 · uncommitted · fix(line_follow): LiDAR 원본 시각도 하나의 미래 허용치를 쓴다 (D-507 8)
- 변경: `clearance.return_scan_view`가 1 ns라도 앞선 스캔을 버리던 것을 `SOURCE_FUTURE_TOLERANCE_S`(0.1 s) 안이면 나이 0으로 받고, 넘으면 버린다. odom(`lane_return_evidence.observe_pose`)과 선 관측(`manager.observe`)은 이미 같은 상수를 쓴다.
- 증거: `test_lane_return_scan.py`(1 ms·0.1 s 앞 받음, 0.1 s+1 ns 앞 버림), `test_lane_return_evidence.py`(허용치 밖 표본을 버려도 다음 표본이 trail을 잇는다, 실제 불연속은 끊는다). 변이 확인 4건.
- gate 변화: 없음. 호스트 시험만.
- 결정: D-507 8
- 교훈: 없음

## 2026-10-08 · uncommitted · feat(line_follow): D-507 6 motion_admitted, 9 site_floor_map_id
- 변경: `recovery/motion_admit.py` `motion_admitted(now, linear, angular, kind, map_id=None)` 하나로 D-476 bridge, D-468 복귀·역추적(`lane_return_decision.py`의 탐침·동작·제출 재확인), D-498 `_turn_basis`가 허가를 받는다. (a) enforce 증명이 살아 있으면 그것만(그대로), (b) 아니면 현장 근거: `site_floor_map_id`(지시의 `map_id`가 있으면 같아야 함), 동작별 IR 판정(bridge `clear`, 접근·회전·전진 `centre` 아님, 복귀·역추적 모두), path·URDF 몸·신선한 스캔·그 twist의 D-422 sweep > 재출발 간격. (c) 현장 근거 후진은 `retrace`만, 뒤 방향 sweep(360° 스캔 반전)이 재출발 간격 위이고 신선할 때만. 설정 `bridge_site_no_dropoffs`·`junction_turn_site_accepted` 삭제, `site_floor_map_id`로 대체(옛 키는 시작 거부).
- 증거: `test_motion_admit.py`(IR 판정 행렬, 선언 null·map_id 불일치, sweep·낡은 스캔, 후진은 retrace만, 뒤 sweep 미달·낡음, 현장 근거 역추적 0.03 m/s·5 s 한도, enforce 그대로), gateway `test_site_floor_declaration.py`. IR 행렬·후진 규칙 변이 6건 모두 실패 확인 후 복원.
- gate 변화: 없음. SOURCE 호스트 시험만. SIM·DEVICE는 D-507 수용 절차.
- 결정: D-507 6·9 (Accepted 2026-10-07)
- 교훈: 없음

## 2026-10-08 · uncommitted · test(line_follow): D-507 10 D-422 기억 몸 밖 규칙의 safety 시험·검토·SIM
- 변경: 코드 변경 없음(구현은 main `35945410f`·`32f98d98b`). `test_line_follow_body_stop.py`에 시험 6건: 패키지 Pinky 겹에서 정지 간격 안 실제 상자는 그 틱 0 지시(lidar), range_min 0.12에서 몸 밖으로 사라진 상자는 다음 틱 0 지시(memory), C1 range_min으로 움직이는 동안 몸 안 점은 매 스캔 기억 0(B9 래치 형태, 진입 판정을 빼면 실패), 몸 밖 기억은 바퀴 움직임 `obstacle_path_horizon_m`까지 유지·뒤에 만료, C1 사각 원판이 패키지 URDF 몸 안이라는 전제 고정, 몸 안 진입 점은 접촉으로 버림. `tools/harness/safety_review.py` EXEMPT에 두 커밋의 독립 safety 검토 기록.
- 증거: 독립 검토(code-reviewer opus) APPROVE WITH NOTES, HIGH·CRITICAL 없음. SIM 모델 PC `docs/validation/d422-memory-outside-body-sim-2026-10-08/result.md`: 수정 전 B9 19 run 중 래치 7, 이 코드 22 run 래치 0·memory 정지 사건 0, 상자 4회 모두 lidar 정지·접촉 없음(주행 중 0.08 m 앞 상자 0 지시까지 0.15–0.17 s).
- gate 변화: D-507 10 SOURCE·SIM. DEVICE(D9 근거리)는 열림.
- 결정: D-507 10, D-422
- 교훈: trailer 없이 main에 들어간 safety 커밋은 amend 할 수 없어 독립 검토를 EXEMPT로 남긴다. 착지 전에 `safety_review.py`를 돌린다.
- 교훈: 없음

## 2026-10-08 · uncommitted · test(line_follow): D-507 7 개정 — 이탈 조건 (2)·(3) 직접 시험
- 변경: `test_lane_return.py`에 추종 중 odom 점프(차로 근거 없음), epoch 변경(차로 근거 없음), 연속 자세로 체크포인트가 아닌 차로 안에 듦(여유 0.04 m) 세 시험을 더했다. 각각 다른 조건이 열 수 없게 만들었다. main 머지에서 `test_motion_admit.py` 현장 근거 역추적 시험은 bridge 뒤 몸이 경계를 넘은 `ready` 프레임(1)으로 이탈을 연다(보이지 않는 차로는 더는 역추적하지 않는다). bridge Rig에 `edges=` 인자를 더했다.
- 증거: 변이 3건(조건 (3) 제거, 점프 이탈 제거, epoch 이탈 제거)이 각각 새 시험 하나만 실패시키고 복원했다. lane_return·lane_bridge·junction·motion_admit 450 passed.
- gate 변화: 없음. SOURCE 호스트 시험만.
- 결정: D-507 7 (2026-10-08 개정)
- 교훈: 기존 인접 차로 시험은 0.20 m 점프를 써서 (3)이 (2)에 가려졌다 — 조건별 시험은 다른 조건이 못 열게 만든다.

## 2026-10-08 · uncommitted · fix(line_follow): D-507 7 검토 — unknown은 오늘 경로, 새 체크포인트는 기준을 되살린다
- 변경: `lane_return_decision.py` — `containment_unknown`과 쉬는 D-468(추종 단계)의 비-로컬 틱은 결정을 돌려주지 않고 None을 돌려줘 `_apply_recovery`(D-407 막힘)가 그 틱을 가진다. D-407이 가진 동안에도 `lane_return_containment: unknown`을 보인다. `lane_return.py` — 체크포인트를 새로 잡으면(검증·추종 두 곳) 점프가 남긴 `_reference_invalid`를 지운다.
- 증거: `test_unknown_containment_opens_d407_stuck_exactly_as_recovery_off`(복귀 켬·끔이 같은 시각 같은 막힘), `test_checkpoint_taken_after_a_jump_is_the_new_reference`·`..._first_taken_while_tracking_...`. 각 수정을 되돌리면 그 시험만 실패한다.
- gate 변화: 없음. SOURCE 호스트 시험만.
- 결정: D-507 7 (2026-10-08 개정)
- 교훈: "복귀를 끈 것과 같다"는 결정을 돌려주지 않는 것(None)이다 — 결정을 돌려주면 그 뒤 경로(D-407)가 건너뛰어진다.

## 2026-10-08 · uncommitted · fix(line_follow): D-507 2·4 pivot_past_line_m 부호 있음 [−0.30, 0.30]
- 변경: `junction_approach.check_expect`가 음수 pivot을 받는다(측정 가로선이 장소 너머, 회전교차로 입구·T자의 먼 쪽 경계). 기대 창 점은 그대로 `expect_in_m − pivot`, 접근 목표 = 측정 선 + pivot. 목표가 로봇 자리이거나 뒤면 접근 0, 제자리 회전, 후진 없음(기존 `max(0, distance)`). 직진 띠 옆 반폭은 양수 pivot일 때만 그 값, 아니면 D-491 0.10 m.
- 증거: `test_junction_approach.py` 음수 pivot 접근 0.1 m, 목표 뒤 접근 0, 창 0.6 m, 띠 반폭, 범위 −0.31 거절. sign 변이(범위 0 하한 복원) 5건 실패 확인 뒤 복원.
- gate 변화: SOURCE. SIM 재실행(SW spoke)은 열림.
- 결정: D-507 2·4 개정(2026-10-08 사용자 결정)

## 2026-10-08 · uncommitted · fix(line_follow): D-507 6 가로선 띠는 테이프 중심 ± 폭/2 (검토)
- 변경: `cross_line_band`가 측정 선을 테이프 중심으로 보고 [선 − 테이프/2 − e, 선 + 테이프/2 + e]를 쓴다(keeper `_across_path`와 Fleet 지도 모형이 중심을 잰다). 띠가 끝나는 먼 끝도 + 테이프/2.
- 증거: `test_junction_approach.py` 띠 경계(.3776/.3774, .4224/.4226)와 범위·odom 오차 경계(x .3214/.3816) 다시 계산.
- gate 변화: SOURCE.
- 결정: D-507 6, 2 개정 검토

## 2026-10-08 · uncommitted · docs(core): D-507 2·4 부호 있는 pivot의 API Ref 번호를 v1.135로 옮김
- 변경: main 병합으로 v1.133·v1.134가 다른 브랜치(D-507 7)에 쓰여, 이 브랜치의 API Ref 행·`app.py`·버전 핀을 v1.135로 옮겼다. 앞 항목의 v1.133은 그 때의 번호다.
- 증거: `test/test_line_follow_contract_docs.py`, `test_protocol_version_alignment.py` 버전 핀 통과.
- gate 변화: 없음.

## 2026-10-08 · uncommitted · fix(line_follow): D-468 궤적은 HOLD 틱에도 odom을 받는다
- 변경: `ReturnController.observe()`가 epoch 확인과 `PoseTrail` 추가를 맡고 `tick()`은 그것을 부른다. `manager.tick`이 매 틱(`obstacle_ahead` 같은 비국소 HOLD 포함) `_feed_return_trail`로 궤적만 먹인다. 이탈 판단은 여전히 국소 틱의 `tick()`에서만 돈다. 0.5 s 넘는 HOLD 뒤 첫 틱이 간격(D-507 7 규칙 (2))으로 보여 이탈과 `sensor_search`를 열던 결함이다. ADR 바뀜 없음.
- 증거: `test_lane_return_manager.py` 1 s 장애물 HOLD(odom 계속, 정지) 뒤 tracking 유지·search 없음, 0.6 s odom 공백과 0.2 m 자세 점프는 여전히 이탈. 변이(`_feed_return_trail` 호출 제거) 시 회귀 시험 실패 확인 뒤 복원. lane_return/bridge/junction/motion_admit/stuck/road + gateway line_follow 819 passed, `known_failures` 0 new.
- gate 변화: SOURCE. SIM·장치는 열림.
- 결정: D-468, D-507 7 (규칙 그대로)

## 2026-10-08 · uncommitted · fix(line_follow): 지도 교차로의 기대 창이 없으면 감지로 회전하지 않음
- 변경: `junction_approach._in_window`에서 `map_id`가 있고 `expect_in_m`·`expect_tol_m` 창이 없는 `straight`·회전 지시는 가로선 감지를 `junction_unexpected`로 HOLD하고 지시를 보존한다. 지도 없는 옛 지시와 `stop`은 그대로다. D-507 3항과 API reference에 보충했다.
- 증거: 변경 전 map-backed left/straight 회귀 2건 실패(각각 조기 회전·실행), 변경 후 CORE 교차로·API·Fleet·계약 시험 194건 통과, `known_failures` 신규 0. B9 게이트 켬 SIM의 조기 회전 2/6 유형을 소스에서 차단한 것이며 SIM 재실행·굽이 통과·실물 수용은 열림.
- gate 변화: SOURCE만. SIM·DEVICE·FIELD는 열림.
- 결정: D-507 3항 보충.

## 2026-10-08 · uncommitted · feat(line_follow): D-507 보충, 지도 굽이를 odom 호로 지남 (action `bend`)
- 변경: `recovery/junction_bend.py`(새 mixin) — `bend` 지시는 `armed` 동안 카메라 추종을 그대로 두고 받은 뒤 odom 이동 거리를 센다. 곧은 확신 추종 틱이 닻(몸이 따라온 선)을 남긴다. 호 시작점 `bend_tol_m` + 0.25 m 앞부터 곧은 확신이 아닌 첫 틱(또는 호 시작점 `bend_tol_m` 앞)에서 `bending`: 닻 직선 + 반지름 `bend_radius_m` 호 + 나가는 직선을 pure pursuit로 좇고, `reacquiring`은 나가는 직선을 0.20 m·5 s 안에서 좇으며 D-495 재획득이나 다음 교차로 감지로 끝, 아니면 `unresolved`. 매 틱 D-495 기동 twist(D-422 몸 sweep, enforce 증명)와 `motion_admitted(..., 'bend', map_id)`(IR `clear`만). 거리(odom × 1.08 > 남은 경로 + 0.05)·시간 상한, 근거 상실 `bend_basis_lost`. `junction.py`는 action·검증·`MANEUVER`·운동 근거 종류만 고쳤고, D-495 재획득 상수는 `junction_approach.py`로 옮겼다(값 그대로).
- 증거: `test_junction_bend.py` 26건(지시 없음과 비트 같음, 카메라 추종 뒤 호와 재획득, lead 창 안 손실로 넘겨받기, 장애물 HOLD에서는 넘겨받지 않음, 닻 없음, 창 밖 감지 unexpected, IR·스캔 stale 근거 상실, IR centre, D-422 막힘 HOLD·재개·오래 막히면 끝, 거리·시간 상한, unresolved, 다음 교차로 감지로 끝, 재전송이 거리 유지, 필드 검증). services 전체 1310 passed(첫 커밋 기준).
- SIM 뒤 고침: 추적 lookahead를 D-476 `bridge_lookahead_m`으로(모서리 안쪽으로 일찍 돎), 카메라 자신의 HOLD에서만 넘겨받기, 닻 없으면 호 시작점까지 지금의 HOLD, D-422 막힘은 중단이 아니라 그 틱 HOLD(`junction_bend_blocked`). `junction.py`는 굽이 `reacquiring`에서도 `obstacle_ahead`를 이어 보게 했다.
- gate 변화: SOURCE. SIM은 `docs/validation/lane-bend-odom-sim-2026-10-08`, DEVICE 열림.
- 결정: D-507 보충(2026-10-08 "지도 기반 odom 통과")
