## D-386: OMX phase execution binds asynchronous ROS acceptance and fresh state

**Status:** Accepted (2026-10-01; SOURCE contract only. Runtime wiring, ROS-SIM,
profile activation, ARTIFACT, DEVICE, and FIELD remain gated.)

**Related decisions:** [D-369](D-369-control-authority-and-stop-evidence.md)
keeps local command authority and stop evidence distinct;
[D-376](D-376-omx-pick-place-planning-and-execution-boundary.md) keeps
planning local, requires one ROS goal per motion phase, and leaves production
planner compatibility gated; [D-336](D-336-fleet-omx-local-ipc-boundary.md)
keeps device execution behind the local UDS boundary.

## Context

The source contracts do not yet compose into a real ROS phase run:

- `PickPlaceRunner.PhaseGoalPort.submit()` returns a `DriverSubmission` with the
  accepted ROS goal UUID. `_submit_phase()` records that response before it
  returns and drops a buffered `GOAL_ACCEPTED` event if no UUID was returned.
- `RosArmCommandRuntime.submit()` returns the local `ArmCommandOwner` decision
  after starting `send_goal_async()`. The ROS acceptance callback and UUID arrive
  later. Local policy admission therefore cannot be treated as ROS goal
  acceptance.
- The coordinator binds each command's `source_state_sequence` to the sequence
  used when its whole plan was produced. The command owner requires every
  submitted command to match the latest joint-state sequence and to advance past
  the prior command's sequence. A precomputed later phase cannot satisfy that
  requirement merely by reusing the original sequence.
- Waiting synchronously for the ROS response inside `LocalStopController`'s
  final-submit lock would block the software stop path on middleware response
  time. The independent physical E-stop remains outside this lock and outside
  ROS.

## Decision

1. Distinguish local dispatch from ROS goal acceptance. The Action/phase remains
   `SUBMITTING` until a callback correlated by action, attempt, command, phase,
   and ROS goal UUID records acceptance. The first parent Action acceptance and
   its first accepted phase UUID remain one SQLite transaction. An accepted
   local method call is never evidence of an accepted ROS goal.
2. Do not block the ROS executor or hold the stop-generation lock while waiting
   for an action response. The fence covers the final freshness/generation check
   and dispatch only. Persist intent before dispatch. If a stop or generation
   change races with a later goal acceptance, latch HOLD and request cancellation
   of that exact UUID; do not advance the phase. An unknown or late response
   remains UNKNOWN/HOLD and is never retried automatically.
3. Bind every phase trajectory to fresh execution state. Before dispatch, the
   local planner/validator must either produce a path from the current joint
   state and current planning-scene revision, or prove that the current state is
   within explicit configured start-state tolerances for the planned path. A
   caller may not make a stale path appear fresh by copying a newer sequence
   number into it. Missing, stale, or out-of-tolerance state holds the Action.
  The final local command owner repeats this check at the dispatch boundary. If
  the state sequence advances while the phase intent is durably journaled, the
  command must carry the validated start positions and explicit per-joint
  tolerances; the owner admits only a fresh latest state still inside those
  bounds and consumes that latest sequence for the next-phase freshness fence.
  It does not rewrite the planned source sequence. Missing tolerance evidence,
  a future sequence, or any out-of-tolerance joint remains fail-closed. The
  command owner also enforces a per-joint maximum tolerance from its trusted
  workcell configuration; a caller-supplied tolerance cannot widen that bound.
4. Keep the capability disabled until the ROS callback state machine, stop race,
   and per-phase state validation pass ROS-free fault tests and the pinned
   vendor ROS-SIM. This decision does not select a production planner, configure
   an OMX workcell, or establish physical stopping or device acceptance.

## Consequences

- Task 8 must close the asynchronous acceptance and fresh-state contracts before
  Task 9 can claim a four-phase ROS-SIM integration.
- Tests must separately exercise local dispatch, ROS accept/reject/unknown,
  late acceptance after stop, exact-goal cancel, changed state, and restart
  recovery. A submitted trajectory topic or a success-shaped local receipt is
  not a substitute for the ROS action result.
- ER 2 receives no motion, cancel, software-stop, physical E-stop, or rearm tool.
  Fleet retains mission authority and read-only phase projection; the device
  local owner retains ROS dispatch and exact goal cancellation.

## Validation boundary

This ADR is a source-level contract decision. No ROS callback run, simulator
result, device, physical E-stop, standstill, ARTIFACT, or FIELD acceptance is
claimed. OMX remains disabled.
