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
`deploy/omx/stack.lock.yaml`.

The current profile names OMX-AI as its target but is intentionally disabled.
The measured joint map and hardware plugin stay empty.

```bash
python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml
```

When running from a source checkout, set `PYTHONPATH=src/devices/omx/adapter`
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

The ROS modules are optional imports. The checked-in profile remains disabled
and has no measured joint map, serial identity, camera model, calibration, or
enabled capability. Keep ARTIFACT, DEVICE, and FIELD gates closed until
immutable artifact provenance, target-host timing, selected-device identity,
physical stop/recovery, and measured camera format/FPS/drop/latency evidence
exist.
