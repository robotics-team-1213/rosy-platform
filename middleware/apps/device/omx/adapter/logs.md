# omx_adapter logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-22 이전 이력은 `git log -- src/apps/omx_adapter`를 본다.

## 2026-09-22 · uncommitted · docs(harness): register omx_adapter under D-168
- 변경: `progress.md`, `logs.md` 추가, `harness.yaml` 등록, `AGENTS.md`에 harness 기록 안내 추가
- 증거: `python -m pytest src/apps/omx_adapter/test -q` 10 passed (2026-09-22 Windows)
- gate 변화: 없음(신규 기록). SOURCE/LOCAL GO, ARTIFACT HOLD, ROS-SIM/DEVICE/FIELD PARKED
- 결정: D-168
- 교훈: 없음

## 2026-09-25 · uncommitted · refactor(devices): move omx_adapter under src/devices/omx/omx_adapter (D-231)

- 변경: src/devices/omx/omx_adapter로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 장치 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음

## 2026-09-26 - prepare selected OMX-AI workcell target
- Change: record OMX-AI as selected but keep runtime disabled; remove the unmeasured six-joint default; lock official ROBOTIS Jazzy source revisions and add a separate workstation image plan.
- Evidence: focused profile/product/vendor-lock suite: 13 passed; disabled CLI output: `{}`.
- Gate change: SOURCE/LOCAL evidence refreshed; ROS-SIM and ARTIFACT remain HOLD; DEVICE/FIELD remain PARKED.
- Decision: D-273; execution plan: `docs/plans/2026-09-26-omx-ai-workstation-runtime.md`.

## 2026-09-26 · uncommitted · feat(omx): add single-owner arm command policy (D-282 P3)

- 변경: hardware-free command admission policy 추가. 명시적 workcell/runtime-session identity, 단일 active owner, fresh joint-state sequence/calibration, per-joint bounds, bounded goal을 확인하고 action fault/cancel/timeout 후 software HOLD를 유지한다.
- 증거: in-memory action fake 기반 정책 시험 26 passed. ROS graph, vendor action server, serial device, physical stop은 시험하지 않았다.
- gate 변화: SOURCE 코드 증거만 추가; action 통합과 대상 workstation timing이 남아 ROS-SIM HOLD, 실기기·독립 stop/recovery 근거 전까지 DEVICE/FIELD PARKED.
- 결정: D-282; recovery는 명시적 operator 확인과 더 최신의 유효 feedback을 요구하며 자동 goal replay는 금지한다. 실행 순서: `docs/plans/2026-09-26-omx-ai-workstation-runtime.md`.

## 2026-09-26 · uncommitted · fix(omx): report cancellation evidence precisely (D-282 P3)

- 변경: action cancel API 호출의 local 결과를 `cancel_outcome`으로 구분하고 호출 예외를 `cancel_call_failed`로 보고한다. monotonic clock보다 미래인 joint feedback은 거부하고 HOLD한다.
- 증거: command-owner ROS-free 시험 28 passed; 전체 focused adapter/product/vendor-lock/identity/preflight 시험 99 passed. 테스트는 가짜 action port와 주입 clock을 사용한다.
- 제한: `poll()`은 호출자 구동이다. bounded 주기 scheduler, ROS/vendor action 연결, action server의 cancel acknowledgement는 아직 없다. API 반환은 실제 취소나 정지를 증명하지 않는다.
- gate 변화: SOURCE 근거 보강. 두 인스턴스 vendor 시뮬 결과는 연결된 probe 보고서로 확인; target workstation timing·camera topics·실물 stop/recovery가 남아 ROS-SIM HOLD, DEVICE/FIELD PARKED.
- 결정: D-282; 실제 OMX capability는 계속 비활성.

## 2026-09-26 · uncommitted · OMX ROS arm and calibrated camera runtime

- Added optional ROS 2 FollowJointTrajectory runtime wiring with configured-joint feedback filtering, steady-clock watchdog polling, cancellation acknowledgement, and terminal action status. Profile remains disabled and runtime has no remote command endpoint.
- Added exact-stamp Image/CameraInfo pairing with bounded unmatched queues, one latest frame, persistent camera identity, optical frame, calibration revision, and a SHA-256 check over all CameraInfo calibration fields.
- Evidence: 99 focused host tests and 11 ROS 2 Jazzy tests in the pinned amd64 image, including isolated vendor Gazebo no-op/readback/cancel and synthetic camera pairing/digest/replay rejection.
- Limits: target Linux workstation timing, physical stop/recovery, camera selection/calibration, immutable artifact, and field runtime remain unverified.
- 변경: Added generic ROS arm-action execution and camera frame admission; OMX profile remains disabled.
- 증거: 99 focused host tests and 11 ROS 2 Jazzy tests pass, including isolated vendor Gazebo no-op/readback/cancel and synthetic camera pairing/digest/replay rejection.
- gate 변화: SOURCE GO; ROS-SIM HOLD pending target-workstation timing and physical fault/stop evidence; ARTIFACT HOLD; DEVICE/FIELD PARKED.

## 2026-09-26 · uncommitted · owner competition in locked vendor simulation

- 변경: opt-in vendor ROS-SIM 시험에서 두 정책 소유자를 허용하되 활성 action 중 경쟁 요청은 `busy`로 거절되고 두 번째 action이 전송되지 않는지 확인한다.
- 증거: 네트워크·장치 허가 없는 잠긴 amd64 이미지에서 Gazebo action/result/cancel 시험 통과. 한 시험 종료에서 간헐적 rclpy 정리 예외를 관측했으며 재실행은 깨끗했다.
- gate 변화: ROS-SIM 부분 근거만 추가. 외부 DDS 참여자의 직접 action 호출과 실물 정지 경계는 검증되지 않았다.

- 후속: 동시 부하 중 action server 발견이 controller 활성화보다 빨라 goal이 거절된 race를 관측했다. vendor 시험은 `list_controllers`의 `arm_controller=active`를 확인한 뒤 전송하도록 고쳤고, 독립 시뮬레이터 두 번 재실행해 통과했다.

## 2026-09-29 · uncommitted · record semantic Action baseline and attempt ledger

- Change: recorded the current OMX semantic-action boundary and added a durable local Action attempt ledger with request identity, restart-to-UNKNOWN recovery, and no automatic replay. Selector resolution and pick-place transaction logic remain evidence-only; they do not submit ROS goals.
- Evidence: OMX adapter suite 72 passed/3 skipped. Fleet Mission service requires a separate fresh camera goal predicate after driver Action success. The OMX profile remains disabled with empty driver/workcell configuration.
- Gate: SOURCE only. No selected physical workcell, gripper feedback, calibrated camera, independent physical stop, target workstation runtime, or device/field acceptance was available or claimed.

## 2026-09-29 · uncommitted · add bounded local Device Action API and runner (D-336)

- Change: added one-request newline JSON UDS handling with Linux SO_PEERCRED UID allowlisting, a 64 KiB bound, absolute pre-provisioned socket path, and no directory auto-creation. The disabled-by-default runner validates the typed Fleet grant, canonical SHA-256 digest, expiry, target instance, current epoch/generation and capability before it writes the action intent. Fleet action/attempt IDs are retained.
- Failure behavior: journal before driver submission; a timeout becomes UNKNOWN and is not replayed. A PREPARED intent can resume once; SUBMITTING/UNKNOWN cannot. Cancel acknowledgment remains CANCEL_REQUESTED, driver terminal readback is attempt-scoped, and no Action terminal state confirms the Mission goal or physical stop.
- Evidence: OMX adapter/profile/vendor-boundary suite 140 passed, 3 skipped. Windows source tests use fake injected ports; no selected ROS/gripper port, systemd entrypoint, physical stop proof, DEVICE or FIELD acceptance is present.
- Gate: SOURCE only; capability remains disabled.

## 2026-09-29 · uncommitted · fix(omx): 제출 기록을 정지 펜스 잠금 안으로

- 변경: `action_runner.submit()`이 driver 호출만 fence 잠금 안에서 돌리고 `record_submission`(SUBMITTING→ACCEPTED)은 잠금 밖에서 하던 것을, 기록까지 `_fenced_submission` 연산으로 묶어 잠금 안에서 마치게 했다. 이전에는 정지 요청 스레드가 잠금 해제 즉시 cancel 팬아웃을 실행해 아직 SUBMITTING인 진행 중 시도를 `cancel_unresolved`의 ACCEPTED/RUNNING 필터가 놓쳤다 — 펜스가 살아 있는 동안 도착한 정지가 진행 중 제출을 취소 없이 흘려보내는 결정적 경주(b3a65e3c 이후 main에서 `test_stop_and_final_submit_are_serialized_through_the_driver_call` 상시 붉음).
- 증거: `python -m pytest src/products/omx/adapter/test/ src/runtime/gateway/test/test_protocol_version_alignment.py src/runtime/api_web/test/ -q` 160 passed 16 skipped. 회귀로 gateway API·dashboard·fleet 777 passed 5 skipped. flake8 clean.
- gate 변화: 없음. SOURCE/LOCAL — 실기 드라이버 직렬화는 DEVICE 회차가 증명한다.
- 결정: D-333/D-336 정지 경계의 시험 의도(제출과 정지 취소가 driver 호출로 직렬화)를 구현에 맞춘 수정이다.
- 교훈: 저널은 파일 끝에 붙인다 — 머리글 앵커는 그 항목이 마지막인지 확인하고.

## 2026-09-30 · uncommitted · OMX pick-and-place plan, trajectory, and ROS goal contracts (D-376)

- Change: Added D-376, typed 3D RGB-D planning contracts, validation for complete timed trajectories, preservation of all waypoints in FollowJointTrajectory, and command/phase-bound ROS goal event contracts. No production planner or pixel-to-pose resolver was added.
- Evidence: The OMX adapter/profile/vendor-boundary host suite passed (190 passed, 3 skipped). Changed Python files passed flake8 with max line length 120. The ROS integration test did not complete because the Docker Python process entered uninterruptible I/O wait. Harness lint reported 0 errors and 18 freshness warnings before this log entry; git diff --check passed.
- Gate: SOURCE contract evidence only. ROS callback integration is unverified in this run; Fleet phase receipt wiring, the full phase coordinator, production planning, gripper I/O, ROS-SIM, artifact, device, and field evidence remain open. OMX stays disabled.

## 2026-09-30 · uncommitted · persist first phase intent and atomic response

- Change: ActionStore permits only ordinal-zero phase intent while the parent is SUBMITTING and records the parent's first acceptance/rejection/unknown response with the phase state and ROS goal identity in one SQLite transaction.
- Evidence: ActionStore tests cover accepted, rejected, unknown, database rollback on the second event write, process restart after first intent, and rejection of a goal ID when acceptance is not positive. The focused ActionStore suite passes.
- Gate: SOURCE persistence contract only. No ActionRunner phase coordinator, ROS submission callback wiring, Fleet phase receipt, physical stop, or capability activation is claimed.

## 2026-09-30 · uncommitted · mint validated attempt-scoped phase recorder

- Change: Added a private ActionRunner factory for an in-process phase recorder after authenticated peer, grant freshness/digest, principal, stored request, workcell, instance, generation, and attempt checks. The recorder is bound to one action/attempt and takes no peer UID for callback writes; ActionApi exposes no new operation.
- Evidence: Action API plus ActionStore tests passed (33 passed). Changed ActionRunner, recorder, ActionStore, and tests passed flake8 with max line length 120.
- Gate: SOURCE trust-boundary contract only. The ROS phase coordinator and per-phase stop-fenced submission path remain open.

## 2026-09-30 · uncommitted · hold unresolved phase state under local stop

- Change: ActionStore now moves every in-flight phase to UNKNOWN in the same transaction that holds its parent Action. The existing goal UUID remains attached for later matching terminal readback, and no next phase can begin.
- Evidence: The ActionStore suite passed (22 passed), including an accepted first phase followed by HOLD, retained goal identity, UNKNOWN phase state, and rejected continuation. Changed files passed flake8 with max line length 120.
- Gate: SOURCE stop-state persistence only. This does not prove driver cancellation, standstill, or physical E-stop behavior; per-phase ROS submit/cancel wiring remains open.

## 2026-10-01 · uncommitted · add fenced pick-place phase coordinator

- Change: Added a ROS-free coordinator that journals and submits one validated motion phase at a time, correlates events by command/phase/UUID, requires explicit advancement after terminal success, and holds on unknown acceptance, event overflow, or a closed stop fence. ActionRunner now offers an authenticated phase-runner injection seam, and Action/stop cancellation uses the exact active phase goal or remains unresolved when no goal-specific cancel path exists.
- Evidence: Focused action API and coordinator tests passed (20 passed). Full OMX adapter/profile/vendor-boundary suite passed (208 passed, 3 skipped). D-346 quick gate passed (95 passed, 18 warnings); changed Python files passed flake8 with max line length 120; harness lint reported 0 errors and 18 freshness warnings; git diff --check passed.
- Gate: SOURCE only. The workcell production factory, real ArmCommandOwner/RosArmCommandRuntime binding, callback integration, Fleet phase projection, ROS-SIM, device, and field acceptance remain open; the OMX capability remains disabled.

## 2026-10-01 · uncommitted · gate semantic phases on durable gripper evidence

- Change: Added an attempt-scoped append-only workflow journal and local Action terminal gate. The coordinator now requires a semantic phase gate; the workflow recorder opens the next motion phase only when transaction state and durable journal state agree. Local Action success requires all four ROS phases plus fresh held-object and later open/no-object gripper readbacks. Removed the duplicate local placement predicate; Fleet's registered goal-evidence service remains authoritative for Mission `GOAL_CONFIRMED`.
- Evidence: Focused ActionStore/transaction/gripper/coordinator suites passed (42 passed). Task 5 transaction/gripper/Fleet goal-evidence suites passed (49 passed). Full OMX adapter/profile/vendor-boundary suite passed (211 passed, 3 skipped). Changed Python files passed flake8 with max line length 120; harness lint and D-346 were green on the latest merged main tree.
- Gate: SOURCE only. No measured gripper actuation profile, production sensor/driver, camera producer/device binding, Fleet phase receipt, ROS-SIM, or physical acceptance is present. The OMX capability remains disabled.

## 2026-10-01 · uncommitted · project durable OMX phases into Fleet status

- Change: Added strict four-phase receipt summaries and UDS v2 for phased `PICK_PLACE` while retaining v1 for non-phased operations and all existing operation names. Fleet now requires v2 without fallback, persists attempt/fence-bound phase snapshots idempotently, rejects reused event identities with changed evidence and state regression, and exposes only bounded active/ordered phase progress through Mission status and the existing read-only ER 2 status tool. Phase summaries contain no ROS goal UUID or motion payload; Action success still waits for independent Fleet goal evidence.
- Evidence: Task 6 contract/UDS/dispatcher/progress/ER 2 status suites passed (92 passed). Full OMX adapter/profile/vendor-boundary suite passed (212 passed, 3 skipped). Full Fleet suite passed (951 passed, 6 skipped). D-346 quick gate passed (95 passed, 22 freshness warnings); harness lint reported 0 errors and 22 freshness warnings. Changed implementation Python files passed flake8 with max line length 120; `git diff --check` passed. The module-size ratchet was re-judged for the single-store phase transaction and bounded shared schemas; zero-growth applies from the new measured baselines.
- Gate: SOURCE contract only. No production plan/ROS/gripper factory, ROS-to-Fleet runtime wiring, ROS-SIM phase run, device or physical stop evidence exists. OMX capability remains disabled.

## 2026-10-01 · uncommitted · fail closed on restart and possible held object

- Change: Grasp completion now marks the object possibly held until fresh gripper readback. Restart recovery atomically changes unresolved local Actions and phases to UNKNOWN and appends an ACTION_WORKFLOW_STATE HOLD event with preserved evidence references and conservative held-object state. An UNKNOWN, HOLD, or canceling Action can no longer record semantic progress. Fleet retains successful four-phase snapshots across store reopen while keeping Mission goal evidence PENDING; exact cancel ACK remains separate from terminal result.
- Evidence: Focused restart/stop/runner/transaction/gripper/Fleet progress suites passed (64 passed). Full OMX adapter/profile/vendor-boundary suite passed (213 passed, 3 skipped). Changed implementation Python files passed flake8 with max line length 120; `git diff --check` passed. The action-store size verdict was re-judged at 1109 lines because recovery updates must share its SQLite transaction.
- Gate: SOURCE only. No ROS runtime callback, controller behavior, independent physical E-stop, standstill, or device acceptance was demonstrated. OMX capability remains disabled.

## 2026-10-01 · uncommitted · fix(api): error responses echo the request's protocol version

- Change: `ActionApi._error` hard-coded `"version": 1`, so a v2 `SubmitAction` refused by the stale authority/generation fence answered v1 and the Fleet client read a valid 403 `GRANT_REJECTED` as `LocalActionUnavailable` before ever reaching the rejection branch; a v2 `GetAction` 404 failed the same way. `_error` now carries the version of the request it answers — default 1 only for frames rejected before version validation (bad JSON, framing, unsupported version) — threaded through every post-validation path: operation errors and all four exception handlers. API Ref v1.66 pins the envelope rule (D-382 conformance).
- Evidence: `test/test_fleet_omx_action_identity_contract.py` 10 passed — the stale-fence case was red before this change and is the mutation proof. OMX adapter + Fleet suites 1112 passed (`test_console_hub_integration` uvicorn-startup timing flaked once on this loaded Windows host; passes alone and green on CI). flake8 max 120 clean; harness lint 0 errors.
- Gate: SOURCE only. Same-host UDS contract semantics; no device, capability, or wire-format change.
- Lesson: the cross-contract identity test lives in the root `test/` tree, outside both module suites — module-green is not seam-green, and the seam is exactly where this defect sat.

## 2026-10-01 · uncommitted · merge phase recovery and record readiness gates

- Change: Merged the Task 7 restart recovery and conservative held-object changes, then integrated the current main API Ref v1.66 contract updates. Main now contains merge commit `979c0785`. Updated the pick-and-place plan and OMX readiness record: SOURCE is GO; ROS-SIM/ARTIFACT are HOLD; DEVICE/FIELD are PARKED; the OMX profile remains disabled.
- Evidence: OMX adapter/profile/vendor-boundary suite 213 passed, 3 skipped; Fleet phase/API identity seam 45 passed; Fleet progress/API doc-pin suites 23 passed; generated-current 1 passed; harness lint 0 errors, 22 freshness warnings. D-346 first run had 93 passed and 2 generated STATUS staleness failures; after `rosy_harness.py generate`, the two affected tests passed. `git diff --check` passed.
- Gate: Task 8 ROS-SIM remains HOLD. Docker engine availability timed out after 12 seconds on this Windows host; Ubuntu WSL failed with `getpwuid(0)` before ROS could be checked. No new simulation evidence or report is claimed. Hardware, independent E-stop, ARTIFACT, DEVICE, and FIELD remain unverified; OMX capability remains disabled.

## 2026-10-01 · uncommitted · D-385 exposes ROS phase acceptance and state-binding gates

- Change: Accepted D-385 to distinguish local submit from ROS action acceptance, prevent waiting under the local stop lock, cancel exact goals accepted after a stop race, and require current-state path validation for every phase. Updated the execution plan to add these gates before the pinned four-phase ROS-SIM and kept OMX disabled.
- Evidence: Source review found `RosArmCommandRuntime.submit()` returns the local owner decision while `send_goal_async()` resolves later; `PickPlaceRunner` requires synchronous `DriverSubmission` with UUID. The runner also requires a command's state sequence to equal the plan-time sequence, while `ArmCommandOwner` requires the latest sequence and strict advancement. ROS-free runner/runtime baseline: 6 passed, 2 skipped (ROS Jazzy modules unavailable in this Windows host). ADR, progress, generated-record, and module-log contracts passed (80 passed, 22 freshness warnings); harness lint reported 0 errors and 22 freshness warnings; git diff --check passed.
- Gate: No production callback integration or four-phase runtime path exists yet. The previous Docker availability probe timed out and WSL did not expose a usable ROS environment. Task 8 source integration must close the D-385 tests before Task 9 simulation; ROS-SIM remains HOLD, ARTIFACT HOLD, DEVICE/FIELD PARKED, and capability disabled.

## 2026-10-01 · uncommitted · correct OMX phase ADR number to D-386

- Change: A concurrent branch already reserved D-385 for the image-layer deployment decision. Kept that committed historical log entry intact, moved the final OMX decision to D-386, and declared D-385 reserved in the ADR gap registry until its owning branch lands.
- Evidence: ADR body/index, ADR gap continuity, all module logs/progress, and generated-record contracts passed (7 passed); the combined network-topology and harness suites passed (80 passed, 22 freshness warnings). Harness lint was rerun after renumbering; its only error was the required append-only guard on the already committed D-385 history, which this correction preserves.
- Gate: D-386 defines source contract only. ROS acceptance wiring, fresh per-phase state/path validation, pinned ROS-SIM, ARTIFACT, DEVICE, and FIELD remain open; OMX stays disabled.

## 2026-10-01 · uncommitted · implement D-386 asynchronous phase response and fresh start-state checks

- Change: Replaced the runner's synchronous goal-UUID return assumption with local `PhaseDispatch` plus callback-bound ROS acceptance. The first parent Action and phase UUID are recorded atomically from the ROS response; timeout records UNKNOWN, and a late UUID is journaled and exactly canceled without reopening HOLD. `RosArmPhaseGoalPort` binds callbacks before dispatch through the single `ArmCommandOwner`. Each phase now checks a fresh joint-state snapshot, bounded start-state tolerances, and current calibration/transform/planning-scene revisions before binding the fresh sequence; the command owner rechecks that sequence at dispatch.
- Evidence: Focused runner, ActionStore, stop-fence, plan, ROS-runtime, and architecture-size suites passed (62 passed, 2 skipped). The two skipped tests require ROS 2 Jazzy. Changed OMX Python files passed flake8 with max line length 120. A broader OMX/profile/vendor run produced 219 passed and 3 skipped with one transient unrelated DDS identity subprocess failure; that exact test passed when rerun alone. The repository size verdict was re-judged for the two durable late-acceptance/cancel journal events; `git diff --check` passed.
- Gate: SOURCE integration is partial. The rclpy callbacks, watchdog timeout, and late-acceptance cancel path remain unverified on ROS 2 Jazzy; the production planner/workcell composition and pinned four-phase ROS-SIM remain open. Docker and WSL are unavailable on this host; ROS-SIM HOLD, ARTIFACT HOLD, DEVICE/FIELD PARKED, OMX capability disabled.

## 2026-10-01 · uncommitted · D-390 Pilot simulation action bridge
- Change: Add a simulation-only HTTP facade, one-time pairing, one seat, bounded relative goals and ROS action event readback. Accept ROS-generated NumPy UUID byte arrays. Keep the physical OMX profile disabled.
- Evidence: adapter suite 163 passed/3 skipped on Windows; Gazebo joint, gripper and cancel probe in docs/validation/pilot-omx-gazebo-2026-10-01/.
- Gate: ROS-SIM control slice observed; camera, recording, restart recovery and DEVICE/FIELD remain HOLD.

## 2026-10-01 · uncommitted · test(omx): pinned Jazzy timeout/cancel callback fault coverage

- Change: Added an isolated ROS 2 ActionServer fault test that keeps an accepted trajectory goal active beyond the configured owner timeout, accepts the owner's cancellation request, and returns a terminal CANCELED result. The test asserts timeout HOLD is preserved and a repeated command is refused after cancel ACK and terminal result. This is not standstill/E-stop evidence.
- Evidence: In `rosy-omx-pilot:local` (`sha256:e94662607c72a7cea83c9449178099c4c9476afab0519275ce0da82a88f3da9a`), pinned vendor callback test passed (1); ROS callback suite passed (2). Windows ROS-free Action/store/PICK_PLACE regression passed 37, skipped 1. Report: `docs/validation/model-tool-ros-sim-2026-10-01/README.md`.
- Gate: ROS-SIM remains HOLD: no Fleet Mission/grant runtime handoff, vendor-Gazebo generation/restart race, or four-phase object/gripper-evidence run. Simulation-only manifest is unsigned and dependency inventory is incomplete. ARTIFACT HOLD; DEVICE/FIELD PARKED; capability disabled.

## 2026-10-01 · uncommitted · fix(pilot-sim): serve calibration.js on the sim port
- Change: `pilot_sim_api.PILOT_ASSETS` lacked `calibration.js`, which main's Pilot `app.js` now imports (c04de23a), so `/pilot` on port 8088 never mounted and `test_pilot_sim_browser.py` timed out on `[data-sim-code]`. Added it to match the CORE allowlist in `core_api_web/api/app.py`.
- Evidence: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest src/products/omx/adapter/test/test_pilot_sim_browser.py` 1 passed; adapter suite 168 passed, 3 skipped (2026-10-01 Windows).
- Gate: none.

## 2026-10-01 · uncommitted · test(omx): join Fleet grant to a ROS 2 ActionServer goal

- Change: Added `test_omx_fleet_ros_actionserver.py`, joining Fleet Mission admission, the version-2 UDS API with `SO_PEERCRED`, the OMX Action journal, `PickPlaceRunner`, and the real `RosArmCommandRuntime` ROS action client against an in-process ROS 2 ActionServer. It verifies one approach goal, callback-bound UUID/result, accepted-only Mission state, and restart recovery to `UNKNOWN` without replaying the same grant. The fixture uses a bounded no-op joint trajectory and no camera/contact/gripper evidence.
- Evidence: `rosy-omx-pilot:local`, SHA-256 `e94662607c72a7cea83c9449178099c4c9476afab0519275ce0da82a88f3da9a`, ROS 2 Jazzy: 1 passed. The test checks that Fleet's initial `SUBMITTING` receipt may precede the asynchronous ROS acceptance callback. A stable joint-state fixture preserves stale-state validation without a sample-sequence race.
- Gate: ROS-SIM remains HOLD. This in-process contract fixture is not the vendor Gazebo generation/restart scenario or four-phase grasp/place proof; ARTIFACT remains HOLD and DEVICE/FIELD remain PARKED. Capability remains disabled.

## 2026-10-01 · uncommitted · test(omx): Fleet generation-stop terminal reconciliation

- Change: When an exact ROS phase result is terminal `CANCELED`, `ActionStore` now atomically records the phase result and holds the incomplete parent Action with reason `ROS_PHASE_CANCELED_ACTION_INCOMPLETE`. The Fleet-to-ROS ActionServer regression trips the Fleet generation fence while a goal is pending, sends stop over the authenticated UDS, waits for ROS terminal CANCELED, reconciles the device receipt to Mission HOLD, and confirms an old grant cannot replay a second goal.
- Evidence: The regression was first run red on the Windows ROS-free unit test (parent stayed ACCEPTED), then green after the journal fix. In pinned `rosy-omx-pilot:local` (`sha256:e94662607c72a7cea83c9449178099c4c9476afab0519275ce0da82a88f3da9a`), Fleet-to-ROS plus Action API suites passed **18** tests. The generation-stop case uses an in-process ROS 2 ActionServer, not vendor Gazebo; it does not establish standstill, independent E-stop, or hardware safety.
- Gate: SOURCE and ROS callback contract evidence only. Full ROS-SIM remains HOLD pending vendor Gazebo pending-goal fencing and four-phase evidence; ARTIFACT remains HOLD; DEVICE/FIELD remain PARKED.

## 2026-10-01 · uncommitted · feat(omx): record SIM demonstrations and export LeRobot v3
- 변경: D-390 부록·API v1.69·Pilot 기록 패널·SIM 카메라·원본 recorder·오프라인 exporter. ROS 수락 전에 목표를 등록하고, recording I/O는 별도 writer로 분리.
- 증거: adapter/Pilot/network 259 passed, 28 skipped; quick tier 95 passed; Chromium recording retry/outcome/stale/dispose 1 passed; 실제 LeRobot 0.4.4 reader 3 passed. Gazebo 원본 15프레임 및 동일 원본 export 재독출 PASS. docs/validation/omx-demonstration-lerobot-2026-10-01/README.md 참조.
- gate 변화: 물리·ARTIFACT/FIELD 승격 없음. 짧은 SIM 시연/데이터 형식 증거만 추가.
- 결정: D-390 부록; D-18 typed API와 reference 동시 갱신.
- 교훈: LeRobot 0.4.4는 explicit timestamp를 거부; source ns를 int64로 유지. Windows shared recording mount는 프레임 누락을 만들 수 있으므로 Linux volume 사용.

## 2026-10-01 · uncommitted · fix(omx): fence recording closure and isolate storage faults
- 변경: 리뷰의 중요 문제 3개 해소 — recording 오류로 lease watcher 종료 금지, hidden 중 늦은 seat 획득 즉시 반납, 종료 저장 중 interruption을 manifest에 반영.
- 증거: 리뷰 수정 race/runtime/recorder 21 passed; Chromium 2 passed; 최종 adapter/foundation/assets/network 624 passed, 6 skipped. 최종 tree와 같은 해시의 실제 Gazebo 12프레임→LeRobot 재독출 PASS; 같은 실행 lease 만료 incomplete. 독립 리뷰 재검토 완료.
- gate 변화: 기존 gate 유지; DEVICE/FIELD 승격 없음.
- 결정: D-390 부록.
- 교훈: 파일 쓰기 완료 전 들어온 interruption과 logical closure 경계를 구분한다.

## 2026-10-02 · 38dcb8fe · feat(omx): CELL_TRANSFER analytic top-down planner (D-402, plan C2)
- 변경: 커밋 e244b602, 4ef93a96, 38dcb8fe. `config/omx_f_kinematics.yaml`(open_manipulator 5.1.2 `0a4af6a9…` `omx_f.urdf` 값, 드리프트 시험), `kinematics.py`(URDF 체인 FK, 해석 수직하향 IK: elbow-up, q2+q3+q4=+π/2, yaw/180° 손목 후보, 타입 있는 거절), `pose_plan.py`(`CellPlanningProfile`, `CellTransferRequest`, `CellTransferPlan`, `AnalyticCellTransferPlanner`, `validate_cell_transfer_plan`), `deploy/robot/omx/sim/cell_profile.yaml`(명목상 시뮬 한계). `ActionRunner`는 `CELL_TRANSFER`를 phase runner로만 실행하고 직접 경로는 `PICK_PLACE` 외 종류를 journal 전에 거절. `PickPlaceRunner`는 `CellTransferPlan`을 받고 그 그리퍼 관절을 start-state 검사에서 뺀다.
- 증거: adapter suite 247 passed, 5 skipped(기준 190 passed); known_failures 0 new; architecture 76 passed, 1 skipped; flake8 0. 생성된 네 phase를 실제 `ArmCommandOwner`가 모두 수락. 도달 고리(프로필 한계, yaw 0, +x): z 0.005 m에서 joint1 축 반경 0.05–0.281 m, z 0.10 m에서 0.05–0.254 m(내경은 특이점 반경).
- gate 변화: SOURCE 증거 추가, ROS-SIM HOLD 유지(C3). DEVICE/FIELD PARKED.
- 결정: D-402, D-403 §9. Fleet grant schema에 `CELL_TRANSFER`는 넣지 않음(C4).
- 교훈: URDF `end_effector_joint`의 y −0.0016 m 오프셋 때문에 손목점이 yaw에 따라 달라진다. joint1은 TCP가 아니라 손목점에서 구한다.

## 2026-10-02 · 31ada4b4 · fix(omx): C2 independent review fixes (D-402)
- 변경: 커밋 189e780f, 31ada4b4. 그리퍼 start-state는 approach·grasp에서 검사하고 transfer·release에서만 뺀다. 계획기는 그리퍼가 열림 허용오차 밖이면 `GRIPPER_NOT_OPEN`으로 거절한다. `PickPlaceRunner`는 `CellTransferPlan`에 수락 프로필(`cell_profile`)을 요구하고 `validate_cell_transfer_plan`을 부르며, 제외 집합은 계획이 아니라 프로필의 그리퍼 관절이다. `planning_limit_fraction: 0.8`로 한계의 80%에서 시간 매개화(owner는 전체 한계로 검사). 복귀는 시작 home의 q5로 돌아간다. yaw는 π를 법으로만 맞는다는 점을 docstring과 D-402 §5에 적었다. `ActionRunner`는 종류별 phase runner factory 맵을 쓴다. phase 최대 시간 30 → 40 s, owner `action_timeout_s` 45 s.
- 증거: adapter suite 258 passed, 5 skipped; known_failures 0 new. 무작위 배치 800개(실현 가능 550): 비grasp 최장 phase p50 16.2 s, p90 28.1 s, p95 35.2 s, max 63.3 s; 30 s 상한은 8.7%, 40 s는 3.1% 거절. 리뷰 probe 재실행: 점 사이 quintic 보간 최대 가속도 0.62 rad/s²(전체 한계 0.5의 1.25배; 0.8 비율 전 약 1.65배), 그리퍼 −0.1 시작은 거절됨.
- gate 변화: 없음. SOURCE GO 유지, ROS-SIM HOLD(C3).
- 결정: D-402 §3·§5·§6. C4 작업으로 남김: `action_store.py`의 완료 journal 이름 `PICK_PLACE_ACTION_COMPLETED`와 `result_source='pick-place-workflow'`는 종류 중립이 아니다. `CELL_TRANSFER` 완료 경로를 열 때 함께 바꾼다.
- 교훈: 계획이 스스로 내세운 값(`gripper_joint_names`)으로 안전 검사를 줄이지 않는다. 제외 집합은 수락된 프로필에서 온다.

## 2026-10-02 · uncommitted · fix(omx): close final-owner joint-state sequence race
- Change: Bind validated start positions and per-joint tolerances to each PickPlaceRunner command. After the durable phase-intent write, the final ArmCommandOwner compares the latest fresh joint-state sample against that binding; it consumes the latest sequence only when all joints remain in tolerance. Missing evidence and out-of-tolerance drift remain fail-closed. D-386 now defines this final-dispatch rule. Vendor probe startup preflight is 180 seconds, one generation case, and stop-on-first-failure.
- Evidence: Regression tests failed before the fields existed; afterward, owner/runner tests passed. Full OMX adapter suite: 171 passed, 4 skipped. Changed Python files passed flake8 and py_compile. Vendor Gazebo attempt ended before Fleet grant because the controller was not observed active in the former 45-second preflight; launch log later showed activation and a joint3 command-limit warning. No ROS goal was sent. Current Jazzy in-process rerun skipped at collection because rclpy was unavailable to the selected interpreter.
- Gate: SOURCE GO. ROS-SIM HOLD; new 180-second vendor retry remains pending. ARTIFACT HOLD; DEVICE/FIELD PARKED. No hardware stop, E-stop, grasp/place, or field claim.

## 2026-10-02 · uncommitted · fix(omx): make start tolerance ceiling owner-controlled
- Change: Add trusted per-joint max_start_state_tolerances to ArmCommandConfig. Tolerance-qualified submissions fail closed when policy is absent or a command asks for a wider bound. Vendor probe verifies read-only /repo, loopback-only networking, and no serial/video grants itself.
- Evidence: New missing-policy, oversized-tolerance, malformed-map, negative, and non-finite config tests. Full OMX adapter suite: 176 passed, 4 skipped. Flake8 and Python compilation passed. The first complete Jazzy ROS callback rerun remained skipped at collection because rclpy was unavailable to the selected interpreter; no ROS-SIM claim is made.
- Gate: SOURCE GO; ROS-SIM HOLD. This review fix does not change ARTIFACT HOLD or DEVICE/FIELD PARKED.

## 2026-10-02 · uncommitted · fix(omx): center final state check on planned start
- Change: Bind the planned phase start positions, not the measured validation sample, as the final owner reference. The owner compares latest readback to the original planned start tolerance and consumes only the latest sequence, avoiding a second allowance after journaling. Probe refuses ttyACM, ttyUSB, and ttyS device grants as well as serial/by-id and video devices.
- Evidence: Regression reproduces measured state at +0.009 followed by dispatch readback +0.011 against a +0.010 planned bound; dispatch rejects. Runner regression verifies planned start remains the owner reference. Focused owner/runner suite: 58 passed. Full OMX adapter suite rerun pending.
- Gate: SOURCE GO; ROS-SIM HOLD; ARTIFACT HOLD; DEVICE/FIELD PARKED.

## 2026-10-02 · uncommitted · test(omx): verify planned-start tolerance budget
- Change: Record the measured runner/owner regression result after centering final admission on the planned phase start.
- Evidence: Full OMX adapter suite 178 passed, 4 skipped; flake8, py_compile, and git diff checks passed. The in-process Jazzy test was skipped because rclpy was unavailable to the selected interpreter. Vendor retry remains unrun.
- Gate: SOURCE GO; ROS-SIM HOLD; ARTIFACT HOLD; DEVICE/FIELD PARKED.

## 2026-10-02 · 4e99d92e · fix(pilot-sim): D-411 A 새 Pilot 자산 서빙
- 변경: `pilot_sim_api.PILOT_ASSETS` 에 `recording.js`·`screens/robot-recording.js` — `app.js` 가 `drive.js` 를 정적으로 부르므로 SIM 포트도 서빙해야 한다(구조 규칙 6).
- 증거: `python -m pytest src/products/omx/adapter/test/test_pilot_sim_api.py -q` → 4 passed; `test_shell_assets.py` 자산 동치 시험 통과 (2026-10-02 Windows).
- gate 변화: SOURCE 유지. ROS-SIM HOLD — 계획 Verification ROS-SIM 체크리스트(WSL Ubuntu) 미실행, DEVICE 증거 없음.
- 결정: D-411 A.

## 2026-10-02 · uncommitted · feat(omx): admit tagged Fleet Cell Transfer grants
- 변경: `ActionApi`와 digest 검증이 `FleetActionGrant`/`FleetCellTransferGrant`를 `action_kind`로 구분해 파싱한다. `CELL_TRANSFER`는 전용 phase runner가 등록되지 않으면 저널 전에 거부하고, 등록된 경우에도 capability callback의 셀 해시 확인을 통과해야 한다. camera-blind Cell Transfer의 `observation_id`는 로컬 저널에 빈 값으로 기록하며 기존 ActionStore 스키마와 PICK_PLACE 관측 필수 조건은 유지한다. 낡은 합성 test grant를 실제 tagged schema fixture로 바꿨다.
- 증거: 전체 OMX adapter test 271 passed, 5 skipped; Cell Transfer API/runner, phase-runner 전용 실행, 해시 불일치 및 무관측 저널을 확인했다. `py_compile`, 허용된 기존 style 위반(E501/W503/W504/E704/E126) 제외 flake8, `git diff --check` 통과. Fleet UDS end-to-end invocation은 1 skipped. 전체 파일 flake8은 이 변경 전부터 있던 style 위반을 보고하므로 무오류로 기록하지 않는다.
- Gate: SOURCE GO. 이 checkpoint는 ROS-SIM, Gazebo, 장치 동작이나 실제 셀 해시 공급자를 증명하지 않는다. ROS-SIM HOLD; ARTIFACT HOLD; DEVICE/FIELD PARKED.

## 2026-10-02 · d8f96fb8 · feat(omx): C3 Gazebo CELL_TRANSFER probe (D-402, plan C3)

- 변경: `deploy/robot/omx/probe_cell_transfer.py`(owner 프로세스 하나: 프로필로 만든 `ArmCommandOwner` → `AnalyticCellTransferPlanner` → `PickPlaceRunner` → `/arm_controller`; `gripper_contract` readback, `gz model -p` = `sim_model_pose`), `run_cell_sim.sh`(owner 없는 vendor follower). 프로덕션 코드는 바꾸지 않았다. 대역은 플래그와 evidence JSON에 남긴다: owner lock 안 sequence rebind, 첫 RUNNING_FEEDBACK만 runner로, tmpfs journal, 표시된 DetachableJoint sim aid.
- 증거: docs/validation/rosy-cell-gazebo-c3-2026-10-02/README.md (실행 16회, 허용오차 안 배치 0회). 네 phase ROS `SUCCEEDED`(run8). 그대로의 runner/owner는 run1 `joint_state_sequence_mismatch`, run2–4·7 `joint_state_stale` HOLD(feedback 119건 처리 5.94 s, journal 쓰기 최대 0.64 s). 마찰 파지 실패: 깊이 15 mm는 운반 중 낙하인데 모든 gate 통과, 22 mm는 joint5 −0.327 rad 비틀림으로 transfer start-state HOLD. DetachableJoint sim aid는 손가락이 블록을 지나 닫혀(gripper −0.42/짝 +0.71) owner `joint_state_limit` HOLD. 무하중 그리퍼 readback 오차 ≤ 0.0003 rad, 하중 아래 mimic 차 0.02–0.09 rad.
- gate 변화: ROS-SIM HOLD 유지(C3 증거 추가; C6·Fleet 경로 아님).
- 결정: D-402 §3·§8, D-403 §5·§8. C4 과제: owner/runner 경쟁과 콜백 그룹 분리, wall/sim 시간 기준, release 전 hold 재확인, grasp 깊이 필드, `CELL_TRANSFER` grant schema.
- 교훈: SUCCEEDED 네 개와 그리퍼 계약 통과만으로는 물체 이동을 말할 수 없다. `sim_model_pose`가 낙하를 잡았다.

## 2026-10-02 · f63bb564 · fix(omx): C3b — C3 결함 수정, 대역 없는 Gazebo 단일 배치

- 변경: 커밋 bc6a9955(A1 owner `start_state_window`: lock 안에서 최신 state로 검사·바인딩), 1df18501·3d4a693b(A2 RUNNING 한 번만 journal, feedback은 메모리 계수, joint-state·watchdog와 ActionClient 콜백 그룹 분리, 대기 이벤트 replay 경쟁), e9d5c1b6(A3 `owner_clock="sim"` + `wall_clock_bound_factor` 4.0), c832a53d(A4 release 전 `verify_held_object`, `ITEM_LOST_IN_TRANSIT`), 2b534abf·4316246b(A5 phase별 관절 허용오차 장치, 실측으로 덮어쓰기 없음), a31ebde1(B1 `grasp_depth`), bd56fa7a·2de7832d(B2 폭 맞춤 닫힘, Gazebo 보정 jaw 사상, release 부분 열림), cb58f71f(B3 런타임 sim aid, 대역 없는 probe, 인피드 yaw π/2), aee19f65·f63bb564(pose_plan.py 크기 판정).
- 증거: host adapter+profile+cell+layout+architecture 602 passed, 6 skipped, 실패 2(아키텍처 크기 판정은 수정 커밋으로 해소; `test_control_imports_no_core_code`는 main 기존 실패). 컨테이너(rclpy) ROS·runner·owner·planner 148 passed, 1 skipped. Gazebo `final-single`: 인피드 → 팔레트 A 층 0 슬롯 0, xy 0.30 mm, yaw 0.0009 rad, 윗면 z 0.0 mm, 네 phase SUCCEEDED, owner HOLD 0, RTF 0.46–0.71. `final-three`: 배치 3/3 허용오차 안이지만 마지막 하강이 슬롯 2 블록을 24.9 mm 밀었다. docs/validation/rosy-cell-gazebo-c3-2026-10-02/README.md C3b 절.
- gate 변화: ROS-SIM HOLD 유지(단일 transfer 증거 추가; Fleet 경로·종단 Job·이웃 간섭 남음). DEVICE/FIELD PARKED.
- 결정: D-401·D-402 보강(2026-10-02, C3b). sim aid는 로봇 쪽 joint, hold 증명 뒤에만 붙인다.
- 교훈: 메시로 유도한 그리퍼 사상은 Gazebo 접촉과 0.16 rad 어긋났다. 접촉 순간 link 포즈로 확인하고 측정으로 보정한다. 손가락이 블록에 닿지 않고 멈추면, 먼저 빈손 닫힘으로 자기 간섭(joint5 ≈ π/2)을 의심한다.

## 2026-10-02 · e40d182c · fix(omx): C3b 독립 리뷰 수정 (FIX REQUIRED)

- 변경: e63c0b42(B1: goal 응답 전에 온 feedback을 버퍼에 두었다가 GOAL_ACCEPTED 뒤에 RUNNING_FEEDBACK 하나로 재생한다. 관찰 실패로 표시하지 않는다. timeout 시험은 `last_terminal_decision`를 기다린다), 7ae0f65c(ROS 종료 status를 journal보다 먼저 기록; done/succeeded는 그대로 마지막), 92dfea40(minor 1: `max_start_window_rad` 0.1 상한 + 그리퍼 외 전 관절 포함 요구, cap 없는 owner는 정확 sequence 일치 / minor 2: owner 시계 역행 시 `owner_clock_jumped_back` HOLD), 664d0841(minor 3: 닿을 수 없는 release 폭은 계획 거절), a4f446d8(minor 4: `cell.yaml` `fingertip_overhang_m`, 프로필과 계약 시험으로 묶음), 53467537(minor 5: `accepted_item_geometry`로 수락 레시피의 폭·깊이만 허용, `ITEM_GEOMETRY_MISMATCH`), e582dc5b(minor 7), e40d182c(크기 판정).
- 증거: 아래 WSL 반복과 Gazebo 재실행은 evidence README의 "리뷰 수정" 절에 있다.
- minor 8(잠금 순서): 실재하지만 좁다. runner replay가 `_event_lock`을 쥔 채 늦은 수락 경로에서 `cancel_goal` → owner lock을 잡는다. 반대로 watchdog은 owner lock 안에서 `handle.cancel()`을 부른다. 거기서 `cancel_goal_async`가 **동기적으로 예외를 던질 때만** `CANCEL_ACK`를 바로 emit → runner `_event_lock`으로 간다. 정상 경로는 응답 콜백이 나중에 executor에서 돌아 교착이 없다. 고치지 않았다. C4에서 owner lock 밖으로 cancel 호출을 옮길 때 같이 정리한다.
- gate 변화: 없음(ROS-SIM HOLD 유지).
- 교훈: 콜백 그룹을 나누면 rclpy가 future done 콜백과 feedback의 순서를 보장하지 않는다. Windows는 rclpy 시험을 건너뛰므로, 동시성 변경은 WSL/컨테이너 반복(≥20회)으로 확인한다.

## 2026-10-02 · 0380d789 · fix(omx): re-review fixes N1 and minor 4

- 변경: fb3997c4(N1: GOAL_ACCEPTED를 emit하기 전까지 feedback은 세기만 하고, 그 뒤 하나로 재생한다. runner는 추월당한 RUNNING_FEEDBACK을 journal 없이 인정한다), 0380d789(minor 4 장치 쪽: 수락 item 형상에 `height_m`, `grasp_depth_m > height_m − fingertip_overhang_m`이면 `GRASP_DEPTH_BELOW_FINGERTIPS`로 거절).
- 증거: host suites 629 passed, 실패는 main 기존 `test_control_imports_no_core_code` 하나. WSL Jazzy rclpy 반복 결과는 evidence README에 있다.
- gate 변화: 없음(ROS-SIM HOLD 유지).
- 결정: `fingertip_overhang_m`는 `rosy_cell.cell/2`의 필수 필드가 됐다. 버전은 올리지 않았다. /2는 아직 배포되지 않았고 이 브랜치 밖에서 쓰인 적이 없기 때문이다.

## 2026-10-02 · aa77cb9c · test(omx): WSL rclpy loop under nice -n 19 during another session's Gazebo

- 변경: 없음(검증 기록).
- 증거: HEAD 20회 반복(`nice -n 19`, `ROS_DOMAIN_ID=77`, WSL load average 33–55): 12/20 통과. 실패는 `joint_state_stale`(시험의 0.2–0.5 s joint-state 나이 상한)과 그 뒤의 HOLD다. 같은 조건에서 base `7ae0f65c`(이전 무부하 25/25)와 HEAD를 번갈아 8회씩 돌렸다: base 5/8, HEAD 7/8. base도 같은 시험(`test_slow_feedback…`, `test_runtime_subscribes…`)에서 실패하므로 회귀가 아니라 부하로 본다. 원본: `X:\DevTemp\rosy-cell-c3\c3b\wsl-loop3.txt`, `ab2-loop.txt`.
- gate 변화: 없음.
- 결정: 수용 기준(연속 20회 무실패)은 WSL이 비면(17:00 KST 이후) nice 없이 다시 확인한다.

## 2026-10-02 · c07896af · merge: main (D-413, pl3 dispatch safety) into feat/rosy-cell-c3-gazebo

- 변경: 시작 상태 메커니즘을 하나로 합쳤다. main의 `TrajectoryCommand.expected_start_state_positions`/`start_state_tolerances`(모든 관절)와 `ArmCommandConfig.max_start_state_tolerances`(관절별 상한)를 남겼다. C3b의 `start_state_window`, `max_start_window_rad`, `start_window_exempt_joints`는 지웠다. 두 쪽의 성질은 모두 남는다.
  - owner가 lock 안에서 최신 fresh state로 다시 검사한다(b0979ad6, C3b A1). 최신 sequence에 바인딩한다(`_last_command_state_sequence`).
  - 요청자의 sequence는 더 오래될 수는 있어도 더 새로울 수는 없다. 이미 쓴 sequence는 거절한다. 시계 역행은 `owner_clock_jumped_back`로 HOLD한다.
  - 기준점은 계획된 시작점이다(11ae6e70).
  - C3b의 grasp 뒤 그리퍼 예외는 owner의 예외 목록이 아니다. runner가 그 관절을 자기가 방금 검사한 readback에 묶는다. 이 방식은 main의 "모든 관절" 규칙보다 엄격하다.
- 상한 결정: main은 관절별 정책(7735c307)을 두었고, C3b는 0.1 rad 한 값을 두었다. 관절별 쪽을 남겼다. 프로필은 관절마다 기준 허용오차와 grasp 뒤 덮어쓰기 중 큰 값을 상한으로 만든다(현재 모든 관절 0.02 rad). C3b의 0.1보다 5배 엄격하고, 프로필이 요구할 수 있는 값은 모두 덮는다.
- cap 없는 owner: C3b는 창을 무시하고 정확 일치로 넘어갔다. main은 `start_state_tolerance_policy_missing`로 거절한다. 더 엄격한 main 쪽을 남겼다. C3b 시험은 지우지 않고 그 결과를 검사하도록 바꿨다. 보낸 command 객체는 원본 그대로다(main 시험 `action.commands == [command]`). C3b 시험은 바인딩을 `_last_command_state_sequence`로 확인한다.
- 증거: owner 68, adapter 전체·layout·cell·compat 501 passed / 5 skipped(모듈 경로 PYTHONPATH).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · feat(pilot-sim): D-411 B `/target` 의 `rosy.controls/1`
- 변경: `PilotSimRuntime.controls()` 가 `joint_jog` 하나를 낸다. 관절 한계 = 고정된 vendor URDF 범위(`config/omx_f_kinematics.yaml` `urdf_limit`, `urdf_position_limits()`) ∩ owner SIM 허용 범위. 1회 최대 변화는 `core_common.protocol.controls.BOUNDED_JOG_MAX_STEP_RAD` 하나를 `OmxSimJog` 와 함께 쓴다. `/target` 이 `controls` 를 싣는다.
- 증거: `python -m pytest src/products/omx/adapter/test/ -q` (2026-10-02 Windows). Gazebo 미실행.
- gate 변화: SOURCE 유지. ROS-SIM HOLD.
- 결정: D-411 B. 실물 OMX 는 열지 않는다(D-390).
- 후속: vendor URDF 한계는 모든 관절 ±2π 라 교집합은 지금 `pilot_sim_server.py` 의 허용 리터럴(팔 ±3.0, 그리퍼 ±0.5)과 같다. 검토된 SIM 명목 한계는 `deploy/robot/omx/sim/cell_profile.yaml` 에 있는데 Pilot SIM owner 는 아직 그것을 읽지 않는다 — owner 허용 범위를 cell_profile 에서 만들도록 옮긴다(그리퍼는 Part C2 에서 시작).

## 2026-10-02 · 10daaae5 · feat(pilot): D-411 B SIM 이 Pilot 조립 모듈을 서빙
- 변경: `PILOT_ASSETS` 에 `controls.js`·`arm-stick.js`·`screens/compose.js`·`widgets/joint_jog.js`. 렌더 시험의 가짜 런타임이 빈 `items` 대신 `joint_jog` 를 알린다(빈 목록은 이제 "조작부 없음"으로 그려진다).
- 증거: `python -m pytest src/products/omx/adapter/test -q`, `test_pilot_sim_browser.py` 통과 (2026-10-02 Windows).
- gate 변화: SOURCE 유지. ROS-SIM HOLD.
- 결정: D-411 B. 실물 OMX 는 열지 않는다(D-390).

## 2026-10-02 · uncommitted · test(pilot-sim): D-411 B 렌더 시험 런타임이 실제 소유자처럼 군다
- 변경: `test_pilot_sim_browser.py` 가짜 런타임 — 실행 중 `ready:false`·`owner_state:"active"`·`active_goal`, 준비된 스냅샷이 준 sequence 만 받음, 한 번에 하나. 실제 SIM HTTP API 로 스틱을 잡은 채 3 개 이상 순차 목표, 거절 0 시험.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest src/products/omx/adapter/test/test_pilot_sim_browser.py -q` (2026-10-02 Windows).
- gate 변화: SOURCE 유지. ROS-SIM HOLD.
- 결정: D-411 B. 실물 OMX 는 열지 않는다(D-390).

## 2026-10-02 · uncommitted · feat(omx): C4b wave 1 — v2 CELL_TRANSFER, 종류별 완료 기록, 수락 저장소 (G4, G8, G2a)
- 변경: (G4) `action_api.py`는 v1 CELL_TRANSFER 제출을 journal 전에 `UNSUPPORTED_VERSION`으로 거절. (G8) `action_store.py` 완료 기록을 행의 `action_kind`로 고른다 — PICK_PLACE는 기존 이름 그대로, CELL_TRANSFER는 `cell-transfer-workflow`/`CELL_TRANSFER_ACTION_COMPLETED`. 스키마 변경 없음(1194→1191행, 판정 갱신). (G2a) 새 `cell_acceptance.py` `CellAcceptanceStore`: 수락한 셀·레시피 텍스트, 해시(소유자가 다시 계산), kinematics 확인, 미해결 Action 중 교체 거절, 교체 시 레시피 폐기, `capability_current`·`accepted_cell_sha256`·`accepted_item_geometry`. 문서 검증은 port이고 palletizing 검증은 `rosy_agent/omx_cell_documents.py`가 주입한다(D-413 §1).
- 증거: C4b 보고.
- 남음: G9(PUT/GET /cell, seat↔Action 배제), G7, CELL_TRANSFER phase 진행기(아래 deploy 기록).
- gate 변화: 없음.

## 2026-10-03 · uncommitted · feat: journal Cell hold release and local Action completion
- Change: reuse physical gripper transaction rules with canonical Cell grant provenance; optionally compose durable workflow gates with the real Skill phase runner. Require matching scoped fresh hold/release readback before local terminal success. Provider/clock/cancel errors and snapshot recovery stay HOLD.
- Evidence: focused planner/API/runner/transaction/boundary suite 36 passed; sensor and cancel failure review corrections included. Full OMX adapter plus provider/Skill/boundary regression: 371 passed / 5 skipped. Quick tier: 96 passed / 25 freshness warnings. Independent review: 31 passed, no remaining Critical/Important findings.
- Gate: SOURCE/LOCAL only. Fleet independent goal confirmation, two-ledger Cell replay and ROS-SIM remain open.

## 2026-10-03 · uncommitted · feat(omx): C4b 1b — owner 식별 보고 (C3)
- 변경: `ActionApi(identity=...)`에 읽기 전용 `GetOwnerIdentity`(v2)를 더했다. 조립이 준 `{workcell_id, instance_id, simulation, profile}`을 돌려준다. 식별이 없는 owner는 `UNKNOWN_OPERATION`이라 Fleet이 하달하지 않는다(D-403 §7, D-390 §5).
- 증거: `test/test_fleet_omx_cell_transfer_contract.py`, `test/test_platform_cell_owner_assembly.py`.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · fix(omx): C4b 1c — GetAction은 다른 principal을 '없음'으로 답하지 않는다
- 변경: `ActionRunner.get`이 다른 principal의 Action에 None 대신 PermissionError를 내어 API가 403 PEER_NOT_ALLOWED로 답한다. `ACTION_NOT_FOUND`는 정말 journal에 없는 Action에만 쓴다.
- 증거: `test/test_fleet_omx_cell_transfer_contract.py::test_only_action_not_found_reads_as_absent`.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · feat(omx): C4b 1d — journal 식별
- 변경: 새 `journal_identity.py`가 owner SQLite journal에 임의 `journal_id`를 한 번 만든다. `ActionApi`는 식별이 있으면 모든 receipt와 GetAction 404 응답에 그것을 싣는다. `DeviceActionReceipt.journal_id`(선택) 추가.
- 증거: `test/test_platform_cell_owner_assembly.py::test_owner_journal_identity_is_persistent_per_journal_and_in_every_reply`.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · feat(omx_adapter): D-411 C 그리퍼 절대 목표·쥠 readback·시연 `action.gripper`
- 변경: 순수 `pilot_sim_gripper.py` `gripper_state()`(open·closed·holding·moving·unknown, 허용오차 0.05 rad, 정지 판정 0.5 s/0.005 rad). `PilotSimRuntime` 그리퍼 모드(`gripper_open`·`gripper_closed`): 공통 `_dispatch`(instance → 허용 → 단일 진행 목표 → ready → 제공한 sequence), `submit_gripper`(절대 위치, 범위 밖 `gripper_limit`), 스냅샷 `gripper`, `controls()` 가 그리퍼를 `joint_jog` 에서 빼고 `gripper` 항목을 낸다. 그리퍼 목표가 `SUCCEEDED` 로 끝난 뒤의 팔 조그는 그리퍼 칸에 그 목표 위치를 보낸다(readback 이면 쥠이 풀린다). `sim_admission_limits()` — SIM owner 허용 범위 = `deploy/robot/omx/sim/cell_profile.yaml` ∩ URDF(팔·그리퍼 모두; 리터럴 ±3.0/±0.5 제거), 목표 길이 상한 2.0 s, 셀 프로필 바이트를 출처 해시에. `POST /api/v1/sim/omx/gripper`(조그와 같은 영수증·seat·만료·409 규칙). 시연 기록: 출처 `gripper_joint`(선택), 행 `action.gripper`(= `action` 그리퍼 칸, 다르면 `gripper_action`), 목표 길이 0.1–2.0 s, LeRobot `action.gripper` 특성·프레임. 이전 에피소드는 그대로 검증·export.
- 증거: `python -m pytest src/products/omx/adapter/test/ -q` → 312 passed, 5 skipped (2026-10-03 Windows; `test_pilot_sim_browser.py` 3개 포함 — 실제 SIM HTTP API 로 프리셋·슬라이더·배지).
- gate 변화: SOURCE 유지. ROS-SIM HOLD — OMX Gazebo 에서 그리퍼 열기/닫기/쥠·시연 export 미실행.
- 결정: D-411 C, 구현 부록 7–9. 실물 OMX 는 열지 않는다(D-390).
- 후속: Gazebo 에서 물체를 쥔 닫기 목표가 컨트롤러 허용오차로 실패하면 owner 가 HOLD 로 가고 배지는 `unknown` 이 된다 — ROS-SIM 에서 확인. 쥔 채 팔 조그가 같은 허용오차로 실패하는지도 함께 본다.

## 2026-10-03 · uncommitted · fix(omx_adapter): D-411 C 검토 — 속도 제한·제한 조임·안쪽 범위·stall probe
- 변경: 그리퍼 목표 `gripper_velocity_limit`(|목표−readback|/duration > min(셀, URDF) 그리퍼 속도), 서술자 `gripper.max_velocity`. 쥔 채 팔 조그는 멈춘 위치 + `gripper.preload`(셀 프로필 0.05 rad, 고정·ratchet 없음·닫힘을 넘지 않음). Pilot 에 알리는 범위 = 허용 범위 − `start_state_tolerance_rad`, 그 밖으로 더 나가는 조그 거절. 실패 끝은 `terminal_status_<s>_result_<c>` 이고 holding 이 아니다. URDF 에 없는 셀 관절은 오류, 교집합 한 번. 그리퍼 움직임은 watchdog 에서도 표본. `gripper_state(fresh=)`, 공개 `gripper_joint_for_goals`, 시연 길이 상한은 core_common 에서. SIM 패치에 JTC `constraints`(goal_time 1.0, 팔 goal 0.02, 그리퍼 goal 0.0, stopped_velocity_tolerance 0.05 — 명목). `probe_pilot_sim_http.py`: 그리퍼는 `POST /gripper`, 닫기 뒤 열기, `--stall`(정육면체 쥐기, 끝 사실 기록, 쥔 채 조그 세 번).
- 증거: `python -m pytest src/products/omx/adapter/test/ -q` 와 `test/test_omx_pilot_probe.py test/test_omx_workstation.py` 통과 (2026-10-03 Windows; probe 시험은 실제 SIM API·런타임 + owner 를 흉내 낸 가짜 팔 — ROS-SIM 증거 아님). SIM 패치는 vendor 0a4af6a9 원본 세 파일에 `git apply` 확인.
- gate 변화: ROS-SIM HOLD — `--stall` 이 `holding` 의 차단 관문(progress.md blocker).
- 결정: D-411 C, 구현 부록 9–13.

## 2026-10-03 · uncommitted · fix(omx_adapter): D-411 C Gazebo 관문 뒤 — 조임 재발행·속도 여유·probe·Gazebo 전용 제약
- 변경: 쥐고 있음이 된 닫기 뒤 watchdog 이 그리퍼만 멈춘 위치 + preload 로 옮기는 목표 하나(`hold-<id>`)를 낸다(JTC 가 SUCCEEDED 뒤 닫기 목표의 마지막 점을 계속 명령해 첫 조그가 조임을 줄였다). 터미널 때 readback 이 없으면 첫 신선한 readback 이 멈춘 위치. `/state` `gripper.hold_target`. 속도 판정 0.05 rad 여유. 실패 reason 형식 고정 시험. probe: 닿을 수 있으면 정확한 목표, 첫 목표 전 readback 을 `before` 로, `bash -c 'source /opt/ros/jazzy/setup.bash; exec "$@"'` 로 gz, `--pace-margin` 0.9, 보고서에 `open_readback`·`close_goals`·`hold_target`. SIM 패치: 제약을 `gazebo_arm_controller_constraints.yaml`(Gazebo launch spawner `--param-file` 만)로 옮김.
- 증거: 관문 1회차 `X:\DevTemp\d411-simC\stall3_harness.log`(닫기 4.05 s, 0.359 rad, 조그 세 번 0.377/0.388/0.416). 호스트 `src/products/omx/adapter/test`, `test/test_omx_pilot_probe.py`, `test/test_omx_workstation.py` 통과 (2026-10-03 Windows). 고친 뒤 Gazebo 재실행 없음.
- gate 변화: ROS-SIM HOLD — 다시 빌드한 이미지로 우회 없이 재실행 필요.
- 결정: D-411 구현 부록 12·14.

## 2026-10-03 · uncommitted · fix(omx-sim): D-411 C 관문 수용 — probe 경합 두 개, 쥠 drift 보고
- 변경: `probe_pilot_sim_http.py` — 그리퍼 목표가 SUCCEEDED 된 뒤 readback 이 멈출 때(0.2 s 동안 Δ<0.002 rad, 최대 1.5 s)까지 기다린 뒤 위치 확인(쥔 채 조그 뒤 readback 도 같음); 목표 POST 가 `joint_state_sequence_mismatch`/`readback_not_recently_served` 면 새 `/state` 로 한 번 재시도; stall 보고서에 `holding_drift_rad`(열린 쪽 +, 판정 없음).
- 증거: Gazebo 관문 2회차 수용 — `rosy-omx-pilot:d411c2` `sha256:5c905d91b62269c57f1be7e7ded03f34e5ddb9855b9e4e118158f4075b81052b`, workstation `sha256:326a62d04e765675a1438e75c037f60ba086b302692f3037ea20bd5fe196fe0a`, `X:\DevTemp\d411-simC2` (빌드·제약·기본·target 통과, `--stall` 3회차 통과: 닫기 2.29 s, 0.352 rad, holding, `hold-` 목표 0.295, 조그 세 번 SUCCEEDED·holding, 열림 0.352→0.366→0.375→0.389). 호스트 `test/test_omx_pilot_probe.py`(이른 SUCCEEDED·재시도·drift 시험 포함)와 `src/products/omx/adapter/test` 통과 (2026-10-03 Windows).
- gate 변화: ROS-SIM — D-411 C `holding` 수용(컨트롤러 결정). 나머지 ROS-SIM 항목은 HOLD 그대로.
- 결정: D-411 구현 부록 15.
- 후속: 쥔 채 조그 drift +0.037 rad/3 조그 — `gripper.preload` 조정·정육면체 미끄러짐 조사, 기준이 정해지면 `holding_drift_rad` 로 관문 판정.

## 2026-10-03 · uncommitted · fix: install canonical OMX geometry for Cell owner composition
- Change: install the existing canonical kinematics YAML under share/omx_adapter/config. Default loading resolves the source asset, installed Python prefix or lazy ament package share; explicit paths stay exact and missing assets refuse. No geometry values or approval hashes changed.
- Evidence: installed default load reproduced FileNotFoundError before the fix; prefix/ament path tests failed before the resolver change. OMX/owner/replay regression: 365 passed / 5 skipped. Wheel built from an X: source copy and force-installed into the isolated venv; actual build_cell_owner initialized from site-packages with injected ROS ports, matched the pinned profile geometry and kept local stop closed. Removing the installed asset caused FileNotFoundError and was restored. pip check and production flake8 passed.
- Review: independent 29 passed; no Critical/Important findings. Final quick tier plus install-path tests: 100 passed / 26 existing warnings. Installed YAML equals source byte-for-byte.
- Gate: SOURCE/LOCAL only. This closes host installed-resource composition, not Jazzy/colcon, live ROS timer, Fleet fencing/seat integration, thin-sheet geometry or the full two-layer/two-pallet vendor Gazebo acceptance.


## 2026-10-03 · uncommitted · fix: retain the UDS owner after a caller disconnects
- Change: real Linux Fleet HTTP-to-UDS tests derive peer UID from SO_PEERCRED, assert 0660 and wait for identity readback. A closed caller now ends only its connection; the owner and durable journal remain live without replay.
- Evidence: deterministic disconnect regression failed with BrokenPipeError before fix 6fab54172. Windows focused 44 passed / 2 skipped; adapter/owner/readback 377 passed / 7 skipped; production flake8 passed. Broad Linux ROS 28 passed / 2 failed, no server thread exception. Existing UDS .5 s timeout also failed on main; slow ROS feedback freshness remains unresolved.
- Gate: partial Linux transport proof only; broad Linux suite is not green. See docs/validation/cell-fleet-uds-2026-10-03/README.md. G7/G9, ROS Cell composition, thin sheets and full two-layer/two-pallet Gazebo acceptance remain open. No deploy, credential registration, physical enablement or push.

## 2026-10-04 · uncommitted · D-442 U3 owner 선점과 named 운영 복구

- 변경: Arbiter 전용 선점은 exact-goal cancel 후 HOLD를 유지한다. Fleet named operator 인증·감사와 bounded UDS recovery를 CellOwner owner/local-stop/journal에 연결했다. fresh post-HOLD readback과 PREPARED 포함 미해결 Action을 검사하고 잠금으로 stop·claim 경합을 직렬화한다. commit 실패는 HOLD 복원, ACK 유실은 자동 재전송 금지다.
- 증거: RED 회귀 후 최종 관련 API/transport/owner/store/Cell/안전 구조 152 passed(43.14 s). 실제 호스트 HTTP→UDS frame→owner 연결과 SQLite commit 실패·claim/stop 경합 회귀 포함. X:/DevTemp/rosy-d427/resume/recovery-final.txt 및 docs/validation/d427-source-migration/omx-preempt-recovery-2026-10-04.md. Fleet 구조는 독립 재판정 29,264 줄이며 split·예산·+150은 유지했다.
- gate 변화: 없음. SOURCE/호스트 후보 검증이다. 실제 UDS·ROS-SIM·CI·ARM64·DEVICE·FIELD는 NOT_RUN, motion/reset/profile enable은 실행하지 않았다.

## 2026-10-04 · uncommitted · fix(omx): Pilot 운전석과 Cell 하달 상호 배제

- 변경: 같은 owner·Action SQLite에 운전석 admission과 durable Pilot pending/goal/terminal fence를 결합했다. 최종 owner admission·gripper preload를 검사하고 실제 경과 시간 만료·원래 운전석에 한정한 해제 취소·retained CLI callback을 연결했다. 응답 유실과 재시작의 미해결 Pilot intent는 HOLD다.
- 증거: 독립 검토가 이전 운전석 preload, wall/sim 만료 차이, 지연 취소의 다음 운전석 침범을 재현했고 수정 후 원래 repro 2개와 독립 22 tests 통과. 최종 owner/Pilot/API/builder/architecture 257 passed·기존 2 skips, 부모 통합 42 passed, fast462 passed·기존2 skips·NEW0.
- gate 변화: SOURCE/LOCAL. 실제 ROS 경합과 장치 티칭 수락은 NOT_RUN이다. 재시작 exact-goal reconciliation API 없이 미해결 intent를 자동 해제하지 않는다.

## 2026-10-05 · uncommitted · fix(pilot): 승인 화면 자산 제공 정합

- 변경: OMX Pilot 정적 자산 목록에 peer-approval.js를 포함한다. 요청·운전석·명령 수락 동작은 바꾸지 않는다.
- 증거: pre-push에서 자산 집합 불일치를 재현했고 Pilot shell·CI 계약 16 passed로 확인했다.
- gate 변화: SOURCE/LOCAL 정적 제공 수리. OMX 실기·운전석 수용은 별도다.

## 2026-10-05 · uncommitted · fix(peer-assets): Pilot 승인 모듈 정적 경로 일치

- 변경: SIM·개발 서버 allowlist에 기존 peer-approval.js를 더해 CORE와 같은 정적 자산을 제공한다. API·제어 권한·UI 구성 변경 없음.
- 증거: test_shell_assets.py 4 passed, known_failures NEW 0.
- gate 변화: SOURCE/LOCAL. 실제 장치·FIELD 검증은 별도다.

## 2026-10-05 · c2425e6ea · 정책 세션과 원본 runtime 결선

- 변경: 단독 SIM learned_policy owner에만 연결, 단일 관측 전달과 watchdog lease 검증, callback 선등록과 늦은 원본 이벤트 보존, 설치 파일 바이트 기록, I/O 후 전체 권한/원본 source 경계 검증.
- 검증: 관련 HOST 585 PASS/4 SKIP/NEW0; 격리 Jazzy 기존 runtime 6 PASS. 새 실제 ROS 정책 결선은 관측 만료로 거부돼 수용 보류. 근거 X:/DevTemp/policy-runtime/.
- gate 변화: SOURCE/HOST 개발. 설치·추론·Fleet 부모 결과·장치·물리 수용은 별도이며 운영 설정 변경 없음.

## 2026-10-05 · 8669ef8db · native 정책 callback 순서·실패 수렴

- 변경: 원본 handle event 전달을 별도 lock으로 직렬화, acceptance 이전 cancel ACK 보존, 저장 실패 시 내부 취소 한 번으로 재귀 요청 제한. 일반 state lock은 sink I/O에서 해제한다.
- 증거: 결정적 HOST 순서2개 및 재귀 취소1개 RED 확인 후 PASS. 실제 localhost Jazzy transport 8 PASS(기존6+정책세션2), 완료·권한철회 CANCELED 및 종료 확인. fixture는 명시적 관측2초/lease12초이며 원래50ms/500ms 실패와 구분.
- gate 변화: native transport/journal 결선만 확인. 실제 model inference/vendor task/Fleet grant/장치/물리 정지 및50ms 성능은 미수용. 기존 운영 설정과0.20m 전체 물리거리 제한 유지.

## 2026-10-05 · uncommitted · fix(harness): OMX 커밋 저널의 정확한 형식 복구

- 변경: c2425e6ea의 이미 커밋된 저널에 한정해 branch 이름 헤딩을 원본 커밋으로 바꾸고 범위 필드를 gate 변화로 정정했다. 기존 본문 증거·수용 보류·운영 설정 미변경 사실은 그대로 보존한다. 기존 정확한 SHA 쌍 복구 장치에 새 예외를 등록했으며 검사 무변경으로 주장하지 않는다.
- 증거: 불변 원문은 c2425e6eac860d3f670cef0520377e4e4c2042d5와 a41b149db083ca18d3de7bab4ad59d6d76b11c63의 logs.md에 남는다. 정규화 원본 블록 SHA256: `a982ed57cb8e69bbc509ba636d3c5e3cf96d441c23c010304ffbc18ab67a4b19`. 정규화 정정 블록 SHA256: `33858a56f2c9d58edbcae2370a6898b0989ad525e9d49214ee6846d182bfbdf5`. 정확한 쌍만 허용하고 원문·정정 변형, 다른 항목 수정·삭제, 알 수 없는 쌍을 거부하는 실제 회귀 검증을 수행한다.
- gate 변화: SOURCE/LOCAL 감사 형식 정정. 원래 HOST 수치와 ROS 수용 보류를 승격하지 않으며 DEVICE/FIELD 수용이나 자동 활성화 근거를 추가하지 않는다.

## 2026-10-05 · uncommitted · fix(harness): native callback 저널 한 항목의 형식 정정

- 변경: 이미 커밋된8669ef8db 항목의 branch 헤더를 해당 커밋으로, gate 필드를 gate 변화로 정정한다. 본문과8 PASS의 제한된 transport 범위는 변경하지 않는다. 기존 SHA 쌍 복구 규칙에 이 정확한 쌍만 등록했다.
- 증거: 원문은8669ef8db의 logs.md에 보존. 정규화 원문 SHA256 ed55535bed54123338dad2db22c24fc159009907552540b7a3beb83274365973, 정정 SHA256 95d2f5a14fc08506ecb646845926ac48bdcb839609a7ef50929111d71be5921d. exact/old/new/missing/other-edit/delete/unknown-pair7개 회귀로 다른 변경은 거부한다.
- gate 변화: SOURCE/LOCAL 기록 형식 수리만. 실행 시간·장치·물리 수용을 추가하지 않는다.

## 2026-10-05 · uncommitted · fix(release): 공개 journal SHA 경로 검증 기록 이동

- 변경: harness log-map 추출 뒤 남은 네 공개 digest 기록을 실제 YAML의 정확한 행 SHA와 여덟 값으로 이동했다. 비밀 scanner 규칙과 나머지 record 내용·순서는 변경하지 않았다.
- 검증: 기존 main에서 두 guard 실패를 재현한 뒤 관련 guard 103 PASS/NEW0, 독립 정책 검토 16 PASS/NEW0. 근거 X:/DevTemp/policy-parent/provenance-migration-pass.txt 및 provenance-migration-independent-review.md.
- gate 변화: SOURCE/LOCAL 감사 기록 보정만이며 실행·장치·물리 수용은 추가하지 않는다.


## 2026-10-05 · uncommitted · feat(omx): 검증된 Action parent와 정책 원본 사실 연결

- 변경: 실제 runner가 peer·원본 grant·저장된 attempt를 검증한 뒤 읽기 전용 capability를 발급한다. parent/events/phases 단일 SQLite snapshot과 current D18·lease·실제 goal·전체 설치 byte closure를 대조하고 마지막 provider 호출 뒤 만료를 재확인한다. 기존 Action 종류와 허용 동작, 공개 API는 바꾸지 않는다.
- 증거: capability 누락 RED1, 직접 구성한 capability와 reseal manifest RED2, final-read/source/전체 intent RED9, 마지막 provider 만료 RED1 후 HOST33 PASS/NEW0. WAL 교차 store·terminal 후 새 발급 거절·restart·허위 SUCCEEDED·원본 source 변경 거절 포함. 합성 driver/model/authority HOST 범위이며 별도 native transport 결과를 대신하지 않는다.
- gate 변화: private SOURCE/HOST 상관관계만. execution_authorized/episode_fleet_qualified/inference 검증 false, task unknown 및 wire journal_id 미발명. 실제50ms/500ms·모델·DEVICE/FIELD·GT 수용 보류와 모든 시도 합계 물리0.20m 상한 유지. no push/활성화/주행.

## 2026-10-05 · uncommitted · feat(learning): 동일 정책 실행 Episode와 Fleet export

- 변경: 기존 owner journal singleton을 parent 원장과 같은 BEGIN에서 읽고 실제 ActionAPI v2 receipt를 검증한다. 별도 execution profile에 원본 설치 byte closure·intent·native callback·D18를 보존하며 Fleet에서 동일 tuple/journal/goal와 전체 receipt를 비교한다. 관측은 metadata-only, status incomplete/task unknown이고 기존 시연·DatasetStore·승격 허용은 유지한다.
- 증거: producer 부재 RED1, false0 RED1, reseal trajectory/clock/install RED6 및 native scalar RED2 후 관련61 PASS/NEW0. captured bytes 재검산·manifest fsync 뒤 source/native/API 재검증과 마지막 TTL을 유지한다. 합성 model/driver HOST 범위, X:/DevTemp/policy-episode/ 근거.
- gate 변화: SOURCE/HOST 공용 실행 증거 연결. raw RGB/inference/task/원래50ms500ms/DEVICE/FIELD는 미수용이며 새 실행 권한이나 GT는 만들지 않는다. 모든 로봇·시도 합계0.20m 상한 유지, push/배포/활성화/주행 없음.
