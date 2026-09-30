# OMX Local Pick-and-Place Execution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect one operator-approved Fleet `PICK_PLACE` Action to a locally resolved and planned, bounded, phase-by-phase ROS execution with durable feedback, independent goal confirmation, and fail-closed stop/recovery.

**Architecture:** ER 2 and vision produce semantic target candidates and evidence; Fleet owns Mission admission, ordering, grant, and Mission feedback; one device-local OMX Action owner resolves 3D poses, obtains a collision-checked plan, validates and submits one ROS goal at a time, and persists phase/workflow state. ROS controller feedback, gripper readback, local stop, physical E-stop, and Fleet goal evidence remain distinct facts. The initial implementation targets the fixed OMX workcell only and leaves its hardware capability disabled until physical acceptance gates pass.

**Tech Stack:** Python, Pydantic, SQLite, ROS 2 Jazzy `rclpy`, `ros2_control` `JointTrajectoryController`, pinned ROBOTIS OMX-F simulation, optional MoveIt 2 Task Constructor (MTC) as a plan-only backend, pytest, Docker Compose.

---

## Decision and Scope

### Chosen execution shape

Use a local, injectable `PickPlacePlanProvider` that returns 3D target evidence and a staged joint-trajectory plan. Prefer MTC as a **planning-only** backend after its ROS 2 Jazzy/package/robot-model compatibility is proven against the pinned OMX-F stack. MTC must not directly execute trajectories: the existing device-local `ArmCommandOwner` remains the only path that submits `FollowJointTrajectory` goals. If the pinned environment cannot support MTC, stop at the provider contract and propose a separately reviewed deterministic backend; do not replace planning with direct image-to-joint conversion.

Dispatch four bounded motion goals (`approach`, `grasp`, `transfer`, `release`) sequentially. Between motion goals, the device transaction waits for the appropriate fresh gripper/object evidence. The SQLite ROS-goal phase ledger represents only phases that submit a ROS goal. Semantic workflow states such as `VERIFY_HOLD` and `VERIFY_PLACEMENT` are separate durable Action workflow events; they must not be represented as fake ROS goals.

Fleet continues to admit one `PICK_PLACE` Action through the existing same-host D-336 UDS boundary. The model receives only read-only Mission status and candidate-only replan tools. Fleet's existing registered producer endpoint `/api/fleet/goal-evidence` and D-348 verifier remain authoritative for Mission `GOAL_CONFIRMED`; do not add a second Mission completion verifier or model-controlled motion/cancel/E-stop tool.

### Alternatives considered

| Option | Decision | Reason |
|---|---|---|
| ER 2 pixel/point output converted directly to joint targets | Reject | The grant has pixel boxes and calibration identities, but no depth, 3D pose, grasp, collision, or reachability proof. |
| MTC sends controller goals directly | Reject | It bypasses the local owner, stop-generation check, phase journal, and the one-writer boundary. |
| Local plan-only backend; owner validates and submits each phase | Choose | Keeps model, planning, ROS execution, safety, and goal evidence under their assigned owners while preserving per-phase feedback and cancellation. |

### Explicit non-goals

- Do not enable `src/products/omx/profile/config/omx.disabled.yaml`, advertise a live OMX capability, publish an artifact, activate a device, or claim physical acceptance.
- Do not introduce a generic message bus, model-to-ROS/DDS access, direct motor/gripper API for ER 2, separate public Franka API, or automatic Action retry/replay.
- Do not claim controller cancel ACK, ROS `SUCCEEDED`, local software latch, or a Mission API response as physical standstill or independent placement confirmation.

## Current Baseline and Gaps

- `src/products/omx/adapter/omx_adapter/action_runner.py` validates Fleet grants, persists the parent Action, and now exposes owner/attempt-scoped phase journal calls. It does not resolve a plan, submit the next phase, receive ROS callbacks, or expose phase history in the Fleet receipt.
- `src/products/omx/adapter/omx_adapter/action_store.py` has the ordered SQLite phase ledger. It fences goal IDs and cancel/result transitions, but `begin_phase()` currently requires the parent Action to be `ACCEPTED`/`RUNNING`; first-phase intent ordering must be adjusted without permitting replay.
- `src/products/omx/adapter/omx_adapter/command_owner.py` currently validates a single final joint-position map. `ros_runtime.py` sends one-point trajectories and does not expose the ROS goal UUID to the Action journal.
- `src/products/omx/adapter/omx_adapter/target_evidence.py` and `ResolvedTargetEvidence` identify a unique fresh image-space target only. They do not contain depth or a workspace pose.
- `src/products/omx/adapter/omx_adapter/pick_place_transaction.py` consumes arm, gripper, and placement evidence but never submits ROS goals. `gripper_contract.py` verifies readback but does not issue a gripper command.
- `src/site/fleet/fleet/server/goal_evidence_service.py` already authenticates a separately registered producer and verifies the accepted Mission predicate, current Action/attempt, fresh post-action camera evidence, evaluator revision, and fresh OPEN gripper readback. The device/Fleet wiring and actual registered camera producer are absent.
- `DeviceActionReceipt` is strict (`extra="forbid"`) and currently has no phase summary. Fleet `MissionDispatcher` does not persist intermediate phase changes; `MissionProgressService` and ER 2 status context expose Action/goal/stop axes but no active manipulation stage.
- `src/products/omx/profile/config/omx.disabled.yaml` remains disabled and empty. `src/products/omx/adapter/progress.md` records ROS-SIM as HOLD, ARTIFACT as HOLD, DEVICE as PARKED, and FIELD as PARKED.

## Contracts to Preserve

| Concern | Contract |
|---|---|
| Model/tools | `get_mission_status` remains read-only; `propose_replan` remains candidate-only. No `move_arm`, `set_gripper`, `CancelAction`, `StopLocal`, E-stop, or rearm tool is exposed to the model. |
| Identity | Preserve `mission_id`, `step_id`, `action_id`, `attempt_id`, `workcell_id`, `instance_id`, `request_digest`, `authority_epoch`, and `dispatch_generation` end to end. One grant still represents one attempt. |
| Geometry | Resolve pixels only with a matching local RGB-D/known-work-surface observation, depth, intrinsics, optical frame, transform, timestamp, and calibration revisions. Missing, stale, ambiguous, out-of-workspace, or inconsistent evidence returns HOLD before ROS submission. |
| ROS goals | Persist an intent before every driver submission. Record the exact accepted ROS UUID. One active goal per owner. Only a matching goal may advance its phase. Rejection/unknown/abort/cancel/result loss never starts the next phase. |
| Cancellation | Cancel the current phase by its exact ROS goal UUID through a dedicated phase-cancel operation. ACK is not terminal result or standstill. If the selected driver cannot target a goal, keep the request unresolved and hold. |
| Completion | ROS phase success is not pick/place success. Require fresh gripper hold/release evidence and the existing independently registered Fleet camera goal-evidence producer. Fleet releases Mission claims only on its verified predicate. |
| Stop/recovery | Check Fleet epoch/generation and the persisted local stop fence immediately before each goal submission. Never hold a stop lock over the whole physical Action. Restart converts unresolved Action/goal/workflow to UNKNOWN/HOLD; never replay. Physical E-stop stays independent. |
| Wire/API | Keep existing operations; if phase summaries are added to `DeviceActionReceipt`, introduce a versioned UDS v2 response while preserving v1 compatibility. Update schema, API reference, Fleet producer/consumer, and contract tests together. Add no new public REST path. |

## Implementation Tasks

### Task 0: Close the planner and receipt-version decision gates

**Files:**
- Inspect: `docs/adr/D-327-semantic-manipulation-actions-and-device-adapters.md`
- Inspect: `docs/adr/D-369-control-authority-and-stop-evidence.md`
- Inspect: `docs/adr/D-336-fleet-omx-local-ipc-boundary.md`
- Inspect: `deploy/robot/omx/stack.lock.yaml`, `Dockerfile`, `compose.yaml`, `README.md`
- Create at implementation start: a new accepted ADR with an ID checked against `docs/reference/ROSY ADR Log.md`

1. Record the exact chosen local planner boundary: MTC plans only; OMX owner performs all trajectory submissions. Record v1/v2 UDS compatibility and what phase summary is visible to Fleet.
2. In the pinned Linux ROS 2 Jazzy workstation image, probe whether the selected OMX-F robot model, planning scene, kinematics, MTC packages, and trajectory export can build together. Do not add unpinned dependencies or grow the default runtime image during this probe.
3. If compatibility fails, stop and record the blocker/options in the ADR. Do not substitute guessed Cartesian-to-joint arithmetic or direct MTC controller execution.

**Gate:** Accepted ADR and reproducible dependency probe before Task 1 can produce a production plan provider.

### Task 1: Define typed pose and staged-plan contracts

**Files:**
- Create: `src/products/omx/adapter/omx_adapter/manipulation_plan.py`
- Modify: `src/products/omx/adapter/omx_adapter/target_evidence.py` only for a new typed 3D evidence adapter; retain the pixel-only resolver's existing behavior
- Test: `src/products/omx/adapter/test/test_omx_manipulation_plan.py`
- Test: `src/products/omx/adapter/test/test_omx_target_evidence.py`

1. Write failing tests for `ResolvedObjectPose`, `PlannedMotionPhase`, and `ResolvedPickPlacePlan` identity, units, frame IDs, timestamps, calibration/transform/scene revisions, covariance or uncertainty bounds, exact ordered phase set, and finite bounded values.
2. Require source and destination depth/pose evidence to cite the same current observation family and match the Fleet grant's camera identity, frame digest, capture time, calibration revision, and transform revision. A bounding box alone must fail.
3. Require exactly one each of `approach`, `grasp`, `transfer`, and `release`; reject duplicate/reordered phases, incomplete joint maps, empty plans, stale joint-state sequence, and stale planning-scene revision.
4. Define a `PickPlacePlanProvider` protocol with `resolve_and_plan(grant, local_observation, workcell_profile)`. Keep it injectable; provide only test fakes in ROS-free tests.
5. Run: `python -B -X utf8 -m pytest src/products/omx/adapter/test/test_omx_manipulation_plan.py src/products/omx/adapter/test/test_omx_target_evidence.py -q -p no:cacheprovider`.

**Expected:** Invalid/missing depth, identity, calibration, covariance, workspace, or phase evidence is rejected before a command object can reach ROS.

### Task 2: Validate and submit complete bounded joint trajectories

**Files:**
- Modify: `src/products/omx/adapter/omx_adapter/command_owner.py`
- Modify: `src/products/omx/adapter/omx_adapter/ros_runtime.py`
- Test: `src/products/omx/adapter/test/test_omx_command_owner.py`
- Test: `src/products/omx/adapter/test/test_omx_ros_runtime.py`

1. Add failing tests for multi-point trajectories with exact configured joint names, finite positions/velocities/accelerations, strictly increasing `time_from_start`, bounded duration, joint/path limits, current calibration, and current source state sequence.
2. Reject missing/extra joints, non-monotonic points, NaN/inf, exceeded limits, empty points, stale state, and planner/profile revision mismatch before calling the ROS port.
3. Preserve each planned waypoint and timing value in the `FollowJointTrajectory.Goal`; do not collapse a collision-checked path to its final point.
4. Preserve the single-owner invariant: one active trajectory goal, no direct topic submission, and every phase passes through `ArmCommandOwner`.
5. Run: `python -B -X utf8 -m pytest src/products/omx/adapter/test/test_omx_command_owner.py src/products/omx/adapter/test/test_omx_ros_runtime.py -q -p no:cacheprovider`.

**Expected:** Owner rejects unsafe trajectories without ROS I/O; accepted plans reach the action port unchanged except for validated message conversion.

### Task 3: Surface stable ROS goal identity and result events

**Files:**
- Modify: `src/products/omx/adapter/omx_adapter/ros_runtime.py`
- Modify: `src/products/omx/adapter/omx_adapter/command_owner.py` only if the handle protocol needs a typed result snapshot
- Test: `src/products/omx/adapter/test/test_omx_ros_runtime.py`
- Test: `src/products/omx/adapter/test/test_omx_ros_runtime_vendor_sim.py`

1. Write failing tests that an accepted ROS goal exposes its exact `goal_handle.goal_id.uuid` as a canonical lowercase UUID; a rejected/unknown goal has no accepted goal identity.
2. Add a typed per-goal event snapshot/callback for acceptance, running/feedback, cancel response, and terminal status/result. Attach every event to `command_id`, semantic stage, and UUID; ignore or quarantine late events for another UUID.
3. Preserve the distinction among goal acceptance, running feedback, cancel ACK, final `SUCCEEDED`/`ABORTED`/`CANCELED`, and joint-state readback. Callback exceptions become UNKNOWN, never success.
4. Run the ROS-free test first, then the pinned vendor simulation probe in Task 8.

**Expected:** One ROS goal can be correlated to one local phase without treating a cancel response or action status as standstill evidence.

### Task 4: Execute phases through one fenced local coordinator

**Files:**
- Create: `src/products/omx/adapter/omx_adapter/pick_place_runner.py`
- Modify: `src/products/omx/adapter/omx_adapter/action_runner.py`
- Modify: `src/products/omx/adapter/omx_adapter/action_store.py`
- Modify: `src/products/omx/adapter/omx_adapter/local_stop.py` only if a per-submit fence hook is needed
- Test: `src/products/omx/adapter/test/test_omx_action_store.py`
- Create: `src/products/omx/adapter/test/test_omx_pick_place_runner.py`
- Test: `src/products/omx/adapter/test/test_omx_stop_fence.py`

1. Mint an internal, action/attempt-scoped phase recorder only after the Fleet peer and grant have been validated. ROS callbacks use this in-process handle; they do not impersonate a Fleet peer UID or expose phase-write methods over UDS.
2. Persist the first phase intent while the parent Action is `SUBMITTING`, then send the first ROS goal inside the existing stop/generation fence. Permit only this ordered state transition; restart from `SUBMITTING` remains UNKNOWN and is never retried.
3. Add one `ActionStore` transaction for the first ROS response that records the parent Action's accepted/rejected/unknown outcome and the first phase's accepted goal UUID/state together. The intent remains durable before ROS submission; if the process fails before this response transaction commits, recovery marks the Action and phase UNKNOWN and never resubmits. Do not split parent acceptance and first-phase acceptance into separate commits that can leave contradictory state.
4. For each subsequent phase, require the prior phase's exact goal UUID and terminal `SUCCEEDED`, then persist the next phase intent before sending it through the same owner and stop fence.
5. Route `CancelAction` and local-stop cancel fanout to the active phase's exact ROS UUID. If the driver lacks `cancel_phase(action, phase)`, do not call the legacy broad cancel method as a fallback; leave the Action unresolved/HOLD.
6. Persist goal UUID, acceptance, running, cancel ACK, and terminal result in `omx_action_phases`. Persist non-ROS workflow states/evidence references in the existing Action event journal; do not fabricate goal IDs for `VERIFY_HOLD` or `VERIFY_PLACEMENT`.
7. On rejection, timeout, callback loss, generation change, stop latch, unexpected result, or UUID mismatch, stop sequence progression and retain Action/claim in UNKNOWN or HOLD. Do not execute rollback motion automatically.
8. Run: `python -B -X utf8 -m pytest src/products/omx/adapter/test/test_omx_action_store.py src/products/omx/adapter/test/test_omx_pick_place_runner.py src/products/omx/adapter/test/test_omx_stop_fence.py -q -p no:cacheprovider`.

**Expected:** Tests prove no phase is skipped, replayed, submitted after stop, or canceled through an ambiguous goal identity.

### Task 5: Join gripper readback and independent Mission goal evidence

**Files:**
- Modify: `src/products/omx/adapter/omx_adapter/pick_place_transaction.py`
- Modify: `src/products/omx/adapter/omx_adapter/gripper_contract.py` only for the selected typed actuator/readback contract
- Modify: `src/products/omx/adapter/omx_adapter/pick_place_runner.py`
- Test: `src/products/omx/adapter/test/test_omx_pick_place_transaction.py`
- Test: `src/products/omx/adapter/test/test_omx_gripper_contract.py`
- Inspect/test without duplicating its verifier: `src/site/fleet/fleet/server/goal_evidence_service.py`, `src/site/fleet/test/test_goal_evidence_service.py`, `src/site/fleet/test/test_mission_api.py`

1. Define measured workcell-profile gripper open/close targets and independent object-present/held/released readback revisions. Do not infer gripper positions or force thresholds from joint names.
2. Execute `approach` → `grasp` → fresh matching held-object evidence → `transfer` → `release` → fresh OPEN/no-object readback. Any missing, stale, conflicting, or mismatched observation goes to HOLD.
3. Record local Action terminal only from explicit phase and gripper readback results. Keep `GOAL_CONFIRMED` under Fleet's existing registered camera producer and GoalEvidenceService; preserve its fresh post-action image, predicate, evaluator revision, OPEN gripper, and current action/attempt checks.
4. Prove both arrival orders: goal evidence before Action terminal is reconciled at terminal; Action terminal first leaves Mission waiting and eventually HOLDs on the configured grace timeout if no evidence arrives.
5. Run: `python -B -X utf8 -m pytest src/products/omx/adapter/test/test_omx_pick_place_transaction.py src/products/omx/adapter/test/test_omx_gripper_contract.py src/site/fleet/test/test_goal_evidence.py src/site/fleet/test/test_goal_evidence_service.py src/site/fleet/test/test_mission_api.py src/site/fleet/test/test_mission_store.py -q -p no:cacheprovider`.

**Expected:** Arm completion, gripper hold/release, independent placement evidence, and Mission completion remain separate correlated facts.

### Task 6: Deliver bounded phase feedback to Fleet and ER 2 status reads

**Files:**
- Modify: `src/contracts/foundation/core_common/protocol/schemas.py`
- Modify: `src/products/omx/adapter/omx_adapter/action_api.py`
- Modify: `src/products/omx/adapter/omx_adapter/action_runner.py`
- Modify: `src/site/fleet/fleet/server/local_action_transport.py`
- Modify: `src/site/fleet/fleet/server/mission_dispatcher.py`
- Modify: `src/site/fleet/fleet/server/mission_store.py`
- Modify: `src/site/fleet/fleet/server/mission_progress.py`
- Modify: `src/site/fleet/fleet/ai/tool_dispatch.py` only to add a bounded read-only progress field to the existing status tool
- Modify: `docs/reference/ROSY API & Protocol Reference.md`
- Test: `src/products/omx/adapter/test/test_omx_action_api.py`
- Test: `src/site/fleet/test/test_mission_dispatcher.py`
- Test: `src/site/fleet/test/test_mission_progress.py`
- Test: `src/site/fleet/test/test_er2_tool_dispatch.py`
- Create: `test/test_fleet_omx_action_phase_contract.py`

1. Add a strict `DeviceActionPhaseReceipt` summary with semantic phase ID, ordinal, bounded phase state, and observation time. Do not expose joint trajectories, image bytes, credentials, or raw planner scene. Keep ROS UUIDs local unless a reviewed support requirement proves Fleet needs them.
2. Version the UDS response as v2 for phase summaries, retain v1 compatibility for existing non-phased operations, and configure the phased Fleet transport to require v2 without silent fallback. Keep the six existing operation names; add no new external command operation.
3. In one Fleet SQLite transaction, persist each phase snapshot as an idempotent `fleet_mission_events` event keyed by mission/action/attempt/phase ordinal and local journal event ID. A repeated identical event is a no-op; changed identity/state under a reused event ID is a conflict.
4. Project only current `active_phase` and bounded ordered phase status into existing Mission progress. Extend `get_mission_status` as read-only; ER 2 cannot submit, cancel, stop, or rearm through this result.
5. Test response loss/restart, stale attempt/generation, duplicate event, out-of-order phase update, missing v2 summary, and terminal Action with pending goal evidence.
6. Run: `python -B -X utf8 -m pytest test/test_fleet_omx_action_phase_contract.py src/products/omx/adapter/test/test_omx_action_api.py src/site/fleet/test/test_mission_dispatcher.py src/site/fleet/test/test_mission_progress.py src/site/fleet/test/test_er2_tool_dispatch.py -q -p no:cacheprovider`.

**Expected:** Operators and the existing read-only model tool can see which local stage is active, while no phase feedback can authorize or issue motion.

### Task 7: Prove restart, stop, cancellation, and unresolved-object recovery

**Files:**
- Modify/test: `src/products/omx/adapter/omx_adapter/action_store.py`
- Modify/test: `src/products/omx/adapter/omx_adapter/local_stop.py`
- Modify/test: `src/products/omx/adapter/omx_adapter/pick_place_transaction.py`
- Test: `src/products/omx/adapter/test/test_omx_action_store.py`
- Test: `src/products/omx/adapter/test/test_omx_stop_fence.py`
- Test: `src/products/omx/adapter/test/test_omx_pick_place_transaction.py`

1. Inject stop before intent, between intent and driver acceptance, during an accepted phase, during cancel, after gripper close, and after release but before goal evidence.
2. Assert that local latch/generation blocks every later phase; cancel ACK is recorded separately; matching terminal result is still required; unresolved held-object state restores to HOLD with `object_may_be_held=true`.
3. Reopen the SQLite stores at every in-flight state. Verify action, phase, workflow event, and Mission remain UNKNOWN/HOLD as appropriate and never re-submit a prior ROS goal.
4. Require explicit operator reconciliation and newer generation before software rearm. Keep physical E-stop reset and standstill as independent, unimplemented device acceptance evidence.
5. Run the Task 4 and Task 5 suites plus `src/site/fleet/test/test_mission_progress.py`.

**Expected:** No automatic retry, regrasp, release, phase continuation, software rearm, or goal confirmation follows restart/stop ambiguity.

### Task 8: Add full phase sequence to pinned ROS-SIM

**Files:**
- Modify: `src/products/omx/adapter/test/test_omx_ros_runtime_vendor_sim.py`
- Modify: `deploy/robot/omx/probe_vendor_owner_sim.sh`
- Modify only if needed: `deploy/robot/omx/stack.lock.yaml`, `fetch_sources.py`, `Dockerfile`, `compose.yaml`
- Update: `deploy/robot/omx/README.md`

1. Add a repeatable, headless simulation scenario with no serial/video device grants and isolated ROS domain. Start from the pinned ROBOTIS OMX-F follower simulation; do not make Gazebo/MTC part of the default runtime profile.
2. Exercise a no-op multi-waypoint plan, all four phase UUIDs, feedback ordering, one active goal, targeted cancel, timeout, rejected goal, late result, stale joint state, stop-generation change, restart-to-UNKNOWN, and the gripper simulation readback.
3. Verify the selected JTC controller and joint map from the locked stack; ensure no leader trajectory subscriber or second command writer exists. Confirm phase goals use the action interface rather than fire-and-forget topics.
4. Run on the intended Linux workstation with the documented simulation compose profile and the existing `deploy/robot/omx/probe_vendor_owner_sim.sh` probe. Record image digest, ROS distro, vendor lock revision, host, timing, and test output in a dated `docs/validation/omx-pick-place-ros-sim-<date>/` report.

**Expected:** ROS-SIM proves only software sequencing against the pinned simulator. It does not close ARM64 artifact, device, E-stop, gripper force/load, camera calibration, or field gates.

### Task 9: Update capability/readiness gates; keep deployment held

**Files:**
- Modify: `src/products/omx/adapter/progress.md`
- Append: `src/products/omx/adapter/logs.md`
- Modify only after evidence exists: `src/products/omx/profile/config/omx.disabled.yaml`
- Update: `docs/plans/2026-09-30-action-message-identity.md`
- Generate: `src/products/omx/adapter/index.md`, `docs/index.md`, root `STATUS.md` through `python tools/harness/rosy_harness.py generate`

1. Record SOURCE, LOCAL, ROS-SIM, ARTIFACT, DEVICE, and FIELD separately. Do not copy simulated acceptance to DEVICE/FIELD.
2. Keep the current profile disabled while any of these are missing: exact arm/gripper revision and joints, selected camera and synchronized depth, camera-to-workcell calibration, payload/workspace/collision limits, measured gripper actuation/readback, independent E-stop/drive behavior, stop latency, recovery/rearm procedure, signed artifact digest, and operator/device acceptance.
3. Advertise no capability and start no physical controller until all profile and device gates have explicit evidence. When the physical hardware is unavailable, finish at ROS-SIM and report DEVICE/FIELD PARKED.
4. Run the OMX package suites, Fleet phase contract suites, D-346 quick gate, docs harness lint, module structure, and `git diff --check`; run Linux `colcon build` and ROS-SIM only on the pinned Linux workstation.

## Acceptance Checklist

- [ ] ER 2 receives no motion, cancel, software stop, physical E-stop, or rearm tool.
- [ ] Target pixels cannot become a trajectory without exact fresh 3D evidence, accepted calibration, planning scene, and bounded path.
- [ ] Every one of the four motion goals has an intent before submission and one exact UUID-bound terminal result before the next stage.
- [ ] At most one trajectory goal is active through one `ArmCommandOwner`; no topic, leader, MTC execution manager, or second process bypasses it.
- [ ] Per-phase status survives UDS readback, Fleet restart, and duplicate/out-of-order receipt delivery without changing Mission identity or replaying motion.
- [ ] Gripper hold/release and independent camera placement evidence are fresh, identity-bound, and independently verified before Fleet reports `GOAL_CONFIRMED`.
- [ ] Cancel ACK, controller terminal state, local stop latch, physical E-stop, and standstill evidence remain distinct in APIs and UI/model status.
- [ ] Any missing depth/calibration, plan, driver feedback, cancellation target, producer evidence, stop readback, or restart reconciliation produces UNKNOWN/HOLD.
- [ ] Disabled profile remains disabled until measured hardware and safety evidence exists; no simulation result is called physical acceptance.

## Official Technical References

- [ROS 2 Actions design](https://design.ros2.org/articles/actions.html): goal UUID, acceptance/rejection, feedback, cancellation, and terminal state are separate goal-scoped facts.
- [ROS 2 Jazzy Joint Trajectory Controller](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html): monitored `FollowJointTrajectory` is the action interface; only one goal is active, and trajectory points carry timed joint setpoints.
- [ROS 2 Jazzy JTC cancellation deceleration](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/decelerate_on_cancel.html): smooth deceleration is an explicit controller configuration and still is not independent physical E-stop proof.
- [MoveIt Task Constructor pick-and-place](https://moveit.picknik.ai/main/doc/tutorials/pick_and_place_with_moveit_task_constructor/pick_and_place_with_moveit_task_constructor.html): staged local planning can compose manipulation subtasks. The linked page is Rolling documentation; package/API compatibility with the pinned Jazzy target is a Task 0 gate, not assumed.

## Execution Order

Task 0 ADR/dependency gate → Task 1 pose and plan contract → Task 2 trajectory contract → Task 3 ROS goal identity → Task 4 phase coordinator → Task 5 gripper/Fleet goal evidence → Task 6 Fleet/ER 2 read-only progress → Task 7 fault recovery → Task 8 pinned ROS-SIM → Task 9 readiness and docs.

Do not start Tasks 2–8 with a fake production planner, synthetic hardware profile, or borrowed calibration. If Task 0 cannot choose a supported local planner and complete phase feedback path, stop at the interface and keep the capability disabled.

## Execution Status (2026-10-01)

- **Task 0 — complete, gated:** Accepted D-376 defines MTC as plan-only and the local OMX owner as the only trajectory submitter. The pinned workstation image lacks MoveIt/SRDF/OMX kinematics configuration; Jazzy package availability was observed, but planner/model compatibility was not established. No production planner was added.
- **Task 1 — source contract complete:** Added typed RGB-D observation, resolved 3D pose, bounded staged plan, and injectable plan-provider protocol. No pixel-to-pose implementation was added.
- **Task 2 — source contract complete:** The command owner validates every timed waypoint and requires configured rate limits for multi-point paths. The ROS adapter maps all waypoints and derivative fields without collapsing the path. Host coverage passes; the Jazzy integration test could not be re-verified in this run because the Docker Python process entered uninterruptible I/O wait.
- **Task 3 — source contract implemented, ROS verification pending:** Added canonical UUID and typed acceptance/feedback/cancel/terminal events bound to command and phase. Callback failures fail closed and request goal cancellation when possible. The ROS runtime integration assertion is present, but no current pass is claimed; rerun it in the pinned workstation environment.
- **Task 4 — source coordinator path implemented; ROS/device wiring pending:** `PickPlaceRunner` persists ordered phase intent, submits one validated goal through the local owner port inside the stop/generation fence, accepts progress only for the active command/phase/UUID, and advances only after matching terminal success plus an explicit caller `advance()`. `ActionRunner` can inject the phase runner after authenticated grant/attempt validation; `CancelAction` and unresolved-stop cancel fanout route through the active phase UUID or a goal-specific driver method, with no broad cancel fallback. Unknown acceptance and stop-fence rejection hold the Action and prevent retry. This is a source contract only: no production factory connects the plan provider, `ArmCommandOwner`, and `RosArmCommandRuntime`; ROS callbacks and stop timing remain unverified.
- **Task 5 — local SOURCE workflow gate implemented; workcell profile pending:** Semantic workflow state is append-only in the Action journal. The next motion phase requires both transaction state and its durable event to agree; grasp requires fresh held-object readback, and local Action success requires four successful ROS phases plus fresh OPEN/no-object readback. The transaction no longer duplicates Fleet's placement verifier; the existing registered Fleet producer remains the only path to `GOAL_CONFIRMED`, and its two arrival-order/grace behavior is covered by Fleet tests. No gripper actuation target or force threshold was invented: exact measured hardware targets, sensor revisions, driver wiring, and device acceptance remain unavailable, so this is not an executable hardware profile.
- **Task 6 — SOURCE contract implemented:** `PICK_PLACE` uses UDS v2 with the existing six operation names; Fleet requires the bounded phase summary and never falls back to v1. The local receipt contains at most four fixed phase IDs, ordinals, ROS phase states, local journal event IDs, and timestamps, with no ROS UUID or motion payload. Fleet stores identity-fenced phase events idempotently, rejects changed evidence under a reused event identity and later state regression, and projects the latest ordered state into Mission progress and the existing read-only `get_mission_status` result. V1 remains compatible for non-phased operations; no new command/API or Mission goal-confirmation path was added.
- **Tasks 7–9 — not started:** Full restart/stop fault injection, pinned ROS-SIM phase integration, and final readiness gates remain open.

Current source evidence: OMX adapter/profile/vendor-boundary suite **211 passed, 3 skipped**. Task 5 focused adapter and Fleet goal-evidence suites passed **49 tests**. Task 6 shared-contract, UDS, Fleet dispatcher/progress, and ER 2 status suites passed **92 tests**. Host tests do not prove ROS callback execution, planner compatibility, a gripper driver, device behavior, or physical stopping. The OMX capability remains disabled.
