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

## 2026-10-02 · uncommitted · feat(omx): C4b wave 1 — v2 CELL_TRANSFER, 종류별 완료 기록, 수락 저장소 (G4, G8, G2a)
- 변경: (G4) `action_api.py`는 v1 CELL_TRANSFER 제출을 journal 전에 `UNSUPPORTED_VERSION`으로 거절. (G8) `action_store.py` 완료 기록을 행의 `action_kind`로 고른다 — PICK_PLACE는 기존 이름 그대로, CELL_TRANSFER는 `cell-transfer-workflow`/`CELL_TRANSFER_ACTION_COMPLETED`. 스키마 변경 없음(1194→1191행, 판정 갱신). (G2a) 새 `cell_acceptance.py` `CellAcceptanceStore`: 수락한 셀·레시피 텍스트, 해시(소유자가 다시 계산), kinematics 확인, 미해결 Action 중 교체 거절, 교체 시 레시피 폐기, `capability_current`·`accepted_cell_sha256`·`accepted_item_geometry`. 문서 검증은 port이고 palletizing 검증은 `rosy_agent/omx_cell_documents.py`가 주입한다(D-413 §1).
- 증거: C4b 보고.
- 남음: G9(PUT/GET /cell, seat↔Action 배제), G7, CELL_TRANSFER phase 진행기(아래 deploy 기록).
- gate 변화: 없음.

## 2026-10-03 · uncommitted · feat(omx): C4b 1b — owner 식별 보고 (C3)
- 변경: `ActionApi(identity=...)`에 읽기 전용 `GetOwnerIdentity`(v2)를 더했다. 조립이 준 `{workcell_id, instance_id, simulation, profile}`을 돌려준다. 식별이 없는 owner는 `UNKNOWN_OPERATION`이라 Fleet이 하달하지 않는다(D-403 §7, D-390 §5).
- 증거: `test/test_fleet_omx_cell_transfer_contract.py`, `test/test_platform_cell_owner_assembly.py`.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · fix(omx): C4b 1c — GetAction은 다른 principal을 '없음'으로 답하지 않는다
- 변경: `ActionRunner.get`이 다른 principal의 Action에 None 대신 PermissionError를 내어 API가 403 PEER_NOT_ALLOWED로 답한다. `ACTION_NOT_FOUND`는 정말 journal에 없는 Action에만 쓴다.
- 증거: `test/test_fleet_omx_cell_transfer_contract.py::test_only_action_not_found_reads_as_absent`.
- gate 변화: 없음.
