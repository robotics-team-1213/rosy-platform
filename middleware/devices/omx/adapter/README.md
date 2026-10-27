# omx_adapter

Read-only device-specific load-domain assessment and monitoring are available through
`python -m omx_adapter.load_motion_cli`; see [inputs, JSON storage and limits](docs/load-aware-motion.md).
This path does not enable motion or automatic recovery.

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
python -m omx_adapter.cli middleware/devices/omx/profile/config/omx.disabled.yaml
```

When running from a source checkout, set `PYTHONPATH=middleware/devices/omx/adapter`
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

`omx_adapter.pick_place.pick_place_transaction` is an evidence-only transition model for
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

## Measured hardware document validation (D-496)

From an installed adapter environment, run
`python -m omx_adapter.hardware_profile <private-measured-profile.yaml>`.
This checks the draft `rosy.omx-hardware-profile.v1` document's required fields,
ordered joint1 through joint5 (rad, rad/s, rad/s²), gripper range and preload,
jaw/workspace geometry, positive timing/power values, persistent serial path
syntax, and matching measurement-date/evidence-path syntax. Duplicate YAML
keys, unknown fields, missing measurements and non-finite values are rejected.
It reads only the supplied file; it does not resolve/open the serial device.

Exit 0 means **document consistency only**. `motion_admitted` is always false.
The referenced evidence is not authenticated or read; values copied from SIM
and relabelled as hardware cannot be detected by this structural check. Physical
identity, real measurements, independent stop, calibration, payload, recovery,
and binding to an accepted runtime still require independent acceptance. The
validator is not connected to a command owner and does not enable the disabled
profile. Keep actual device identities and filled measurements in `private/`.

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

## Local observation viewer (D-770)

On the camera ROS host, source its ROS setup and select the camera domain, then run:

```bash
python3 deploy/robot/omx/commissioning_view.py
```

The viewer binds only `127.0.0.1:8766`. Access it on that PC, or use an authenticated
SSH forward with the same local port and open `http://127.0.0.1:8766/`.
It subscribes to existing `/top_camera/image_raw`, `/front_camera/image_raw` and
`/omx_commissioning/joint_states`; it never opens cameras or serial ports,
publishes commands, enables a profile or starts the physical observer.
The commissioning observer must already be running for joint values to appear.
Those values are nominal radians from that observer, not accepted physical calibration.

Only advancing source stamps are accepted. Both source and receipt age must be
within two seconds; replay, future clocks, disconnected state and stalled image
loads cannot keep old observations visible as live. Source timestamps describe
host capture/read time, not synchronized camera exposure. This is a temporary
commissioning tool, not a new Fleet API, a physical E-stop or control acceptance.

## ROS joint-state source freshness

The action runtime requires positive, advancing source timestamps within the
configured state-age bound. It deducts transport delay from owner freshness and
rejects incomplete, duplicate-name or nonfinite joint arrays. Rejected packets
cannot refresh the snapshot or watchdog; an active goal then reaches the existing
stale-state HOLD/cancel path. Extra uniquely named mimic joints remain supported.
This validates message integrity and age, not publisher identity or physical stop.

The optional `test/test_omx_native_ros_runtime.py` check runs the native ROS suite
inside a committed remote-runner checkout. Select a Jazzy/Python 3.12 lab host and
pass `ROSY_OMX_NATIVE_RUNTIME_TESTS=1` before that target. The adapter suite uses
domain 113; policy transport/parent-episode tests use domain 199. Both use
localhost discovery and test ActionServers only. No device or vendor launch runs.
