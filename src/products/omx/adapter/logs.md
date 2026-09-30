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
