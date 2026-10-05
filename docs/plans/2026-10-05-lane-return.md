# Local Lane Return Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** D-468에 따라 차선 침범을 감지하고 로컬 복귀·재탐색을 먼저 수행한 뒤 마지막으로 Fleet 지원을 요청한다.

**Architecture:** perception의 영상 시각에 묶인 경계와 실제 odometry를 CORE의 ROS-free 복구기에 입력한다. 복구기는 근거 있는 제한 명령만 기존 line-follow/CommandManager 경로에 제안한다. 기록 없는 경우에도 현재 센서 후보를 탐색하며 이동 불가 상태에서는 계산을 계속한다.

**Tech Stack:** Python, ROS 2 Jazzy adapters, pytest, existing signed native ARM64 release.

### Task 1: Decision and evidence contract

Create `docs/adr/D-468-local-lane-departure-return.md`; append the matching ADR Log row and docs log. Add optional containment/pose provenance fields to `contracts/foundation/core_common/protocol/schemas.py`, `middleware/core/services/core_features/line_follow/model.py` and the API reference/SRS together after reading each owning module contract. Existing observations remain parseable; absence is unknown, never safe.

### Task 2: Geometry and actual breadcrumb history

Create `middleware/core/services/core_features/line_follow/lane_return.py` and `middleware/core/services/test/test_lane_return.py`. First test visible boundary crossing, same-corridor false matches, odom reset/staleness, and no-checkpoint search eligibility. Run the new test to prove missing implementation, then implement finite geometry/pose validation, signed footprint margin and bounded actual-pose history. Record all pytest output under `X:/DevTemp/lane-return-20261005/`; compare each run using `python test/known_failures.py <log>`.

### Task 3: Local-first fallback controller

Extend tests with odometry-based return progress, clear-space candidate selection, blocked rear fallback, stale scan/pose zero output, adjacent-lane rejection, exhaustion and Fleet-last ordering. Implement the smallest ROS-free state machine in `lane_return.py` or a sibling if the module budget requires it. Each moving step requires fresh clearance evidence, bounded travel/yaw/time and existing live limits. Include synthetic closed-loop trials with slip/delay and a visible line outside the corridor. No checkpoint means sensor search, not guessed retracing.

### Task 4: Producer and runtime wiring

Modify `middleware/perception/control/sensing/perception/lane_keep.py` and its observation producer to send typed geometry paired with the image stamp. Wire `middleware/core/gateway/core/bridge/observation.py` and original odometry callback to the manager; modify `manager.py`/`stuck_wiring.py` to apply recovery through their existing decision. Add producer/parser/manager integration tests before code. Preserve OFF/E-stop/lease cancellation and other stuck/YIELD behavior. Update contracts and module logs with implemented capabilities only.

### Task 5: Review, commit and integration

Use @requesting-code-review for independent safety review. Stage only exact owned files and include `Safety-Review:` where required. Run relevant tests, known-failures comparison and `python tools/harness/rosy_harness.py lint`. Merge current main into `feat/lane-return`, repeat affected tests, then fast-forward shared main without altering peer WIP. Generated harness files are created only after their input documents are ready.

### Task 6: Runtime and field evidence

Use normal signed release/CI path; verify installed source SHA and live readback before claiming deployment. Preserve calibration and runtime limits. First confirm stopped sensor evidence and capability presence. With field scene ready, test a normal checkpoint followed by a controlled departure, then a no-checkpoint start; report trajectory, recovery attempts, final margin and stop causes. No available field setup leaves FIELD pending, not passed. The original event lacks a complete time-aligned trace, so prevention/return tests cannot establish its exact cause.

### Execution status

- ADR: D-468 accepted; user local-first/Fleet-last instruction incorporated.
- SOURCE: unwired ROS-free policy, optional contract/parser and selected-boundary producer implemented; 76 core-related and 62 perception tests pass. Independent review corrections included.
- SOURCE increment: original odometry header/validated quaternion now feeds the manager; source-time interpolation, epoch reset, replay admission, bounded support/uncertainty and current-body transforms are implemented. Related legacy/architecture checks 109 PASS, 0 NEW; final independent evidence scope 72 PASS, 0 NEW. Package size re-judged at 13717 with unchanged thresholds.
- SOURCE increment: controller counts original image stamps, invalidates retracing across evidence epochs, and retains a normal checkpoint with at least 25 mm body margin and heading error at most 0.12 rad. A no-checkpoint candidate uses bounded measured approach, followed by containment/heading verification. Fleet follows exhausted local candidates.
- HOST CLOSED LOOP: synthetic planar kinematics now exercise current-corridor approach, 20 percent motion slip, stationary wheels, recorded-path retrace, stale authority/floor/clearance and Fleet-last search ordering. Related controller/evidence/legacy/architecture/contract checks: 130 PASS, 0 NEW. Independent source review: 45 PASS, 0 NEW. This is synthetic proof, not ROS simulation or physical acceptance.
- SOURCE arbitration increment: the real manager now feeds admitted geometry/epoch/source stamps into ReturnController before normal following and D-407. Actual candidates retain generation/evidence fencing and are checked again at submission for live authority, pose freshness and motion proof. Accepted Fleet RESUME re-verifies three distinct contained frames before normal following; it does not reopen an exhausted sequence.
- HOST manager closed loop: actual LineFollowManager decisions drive synthetic measured poses through approach, verification and normal following. Tests also exercise expiry without a new tick, source invalidation, unseen camera search, Fleet-last ordering and stale console lifecycle.
- Final merged host checks: 174 PASS, 0 NEW; independent policy/manager/loop 50 PASS, 0 NEW. Harness lint: 0 errors, 21 existing freshness warnings. Aggregate structural verdict re-reviewed at 13933 with unchanged thresholds.
- Remaining: implement and bind a runtime provider of calibrated floor and actual swept-motion proof, then signed release installation/readback and field recovery. The provider is currently unbound, so autonomous recovery motion is not active on the device.
- ROS SIM / DEVICE / FIELD: pending; no acceptance inferred from this plan.
