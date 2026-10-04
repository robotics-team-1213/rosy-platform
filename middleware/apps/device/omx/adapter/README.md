# omx_adapter

This package is the disabled-by-default software boundary for a future OMX-AI
fixed workcell. Its generic ROS bindings can be exercised against ROS action
servers and camera message publishers without selecting or enabling hardware.

It validates a model-neutral profile and emits the standard
`ros2_control`/MoveIt controller contract: a joint-state broadcaster and a
`JointTrajectoryController` action. It does not open a serial port, create a
fake joint state, or advertise an arm capability while the physical revision,
driver integration, mount, power budget, payload, calibration, and recovery
remain unaccepted. The vendor stack source is pinned separately in
`deploy/robot/omx/stack.lock.yaml`.

The current profile names OMX-AI as its target but is intentionally disabled.
The measured joint map and hardware plugin stay empty.

```bash
python -m omx_adapter.cli middleware/apps/device/omx/profile/config/omx.disabled.yaml
```

When running from a source checkout, set `PYTHONPATH=middleware/apps/device/omx/adapter`
or build/source the ROS workspace first. The empty JSON contract from the
disabled profile is expected. A non-empty contract is not physical acceptance.

`omx_adapter.command_owner` provides a ROS-free, disabled-by-default policy
boundary for one arm command writer. It checks workcell and runtime-session
identity, owner admission, fresh monotonic joint-state sequence, calibration
revision, bounded goals, and configured joint limits. Action timeout, cancel,
or fault latches software HOLD and requires explicit operator recovery with
new feedback.

`omx_adapter.ros_runtime` connects that policy to a
`FollowJointTrajectory` action client, filters vendor joint feedback to the
configured arm joints, and schedules polling from a steady-clock ROS timer.
Its action handle separately records server cancellation acknowledgement and
terminal action status. This has workstation simulation evidence only; it
does not guarantee a physical deadline or prove that the arm stopped. The
runtime exposes no remote command endpoint and provides no DDS access control,
so deployment still needs an isolated graph and exactly one admitted local
writer.

`omx_adapter.camera_contract` admits only fresh image/CameraInfo pairs with an
exact capture timestamp, configured optical frame, dimensions, persistent
camera identity, calibration revision, and matching SHA-256 digest of all
CameraInfo calibration fields. `omx_adapter.ros_camera_runtime` matches messages
by exact stamp, bounds pending pairs, and retains one latest accepted pair.
Identity and calibration digest are operator-supplied admission data; these
modules do not discover a physical camera or prove that it produced the
messages.

`omx_adapter.target_evidence` resolves an operator selector against candidates
that name the same observation. It returns one object identity plus frame,
camera, calibration and transform provenance, or refuses stale, missing,
cross-observation, or ambiguous selectors. Points and boxes remain image-pixel
evidence; this module does not produce a 3D pose, grasp, trajectory, or pick
success claim. Coordinate selectors must already be in source-observation
pixels; cropped coordinates without a verified inverse transform are refused.

`omx_adapter.pick_place_transaction` is an evidence-only transition model for
approach, grasp, hold verification, transfer, release, and independent placement
predicate verification. `gripper_contract` requires fresh, advancing,
workcell/session-bound gripper readback for hold and release receipts. An
ambiguous driver result, cancel, readback, or restart leaves the transaction in
HOLD; it never resubmits a stage or releases a possibly held object. These
ROS-free types are tested with fakes only and are not connected to
`RosArmCommandRuntime`, a gripper, an HTTP endpoint, or an enabled product
profile.

`omx_adapter.action_store` records a semantic request and its content digest
before a caller may mark driver submission. Request-key retries return the
existing Action or conflict; they never create a second attempt implicitly.
After restart, an in-flight submission becomes `UNKNOWN` and remains unresolved
until a matching driver result is reconciled. A cancel acknowledgement remains
`CANCEL_REQUESTED`, separate from a final driver result. This store is not yet
connected to Fleet stop generations, a driver goal query, or a local Action API,
so it does not authorize or submit physical commands.

The ROS modules are optional imports. The checked-in profile remains disabled
and has no measured joint map, serial identity, camera model, calibration, or
enabled capability. Keep ARTIFACT, DEVICE, and FIELD gates closed until
immutable artifact provenance, target-host timing, selected-device identity,
physical stop/recovery, and measured camera format/FPS/drop/latency evidence
exist.

## D-442 owner HOLD recovery

Simulation CellOwner optionally exposes GetOwnerState and RecoverOwner on the existing
Fleet-only local UDS ActionApi. This additive interface sends no motion and cannot rearm
LocalStop. Arbiter-only `preempt(reason)` exact-cancels the current goal once and latches
HOLD; it is not exposed remotely. Pilot/leader automatic arbitration remains a later step.

A named Fleet operator first reads GET `/api/fleet/workcells/{workcell_id}/owner` and the
current dispatch generation. After resolving the HOLD cause and checking fresh joint
readback, the operator posts `/api/fleet/workcells/{workcell_id}/owner/recover` with
`operator_confirmed: true`, that exact `observed_sequence`, and `expected_generation`.
Viewer credentials can read but cannot recover; anonymous operator fallback is refused.
Fleet journals INTENT before the UDS call and RESULT after it. Exact device identity,
current authority/generation, open local stop, fresh post-HOLD feedback, calibration and
no unresolved local Action (including PREPARED) are required. Any refusal preserves HOLD.
A journal commit error restores HOLD before releasing its lock. If the reply is lost,
read back state and audit before deciding on another explicit request; no automatic replay.
Recovery only makes the owner ready. A new separately admitted command is needed to move.

Host regression and its limits: docs/validation/d427-source-migration/omx-preempt-recovery-2026-10-04.md.
No real operator, ROS transport, physical standstill or device recovery is claimed here.
