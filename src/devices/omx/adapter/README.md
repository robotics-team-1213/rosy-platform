# omx_adapter

This package is the ROS-native boundary for the selected OMX-AI fixed workcell.

It validates a model-neutral profile and emits the standard
`ros2_control`/MoveIt controller contract: a joint-state broadcaster and a
`JointTrajectoryController` action. It does not open a serial port, create a
fake joint state, or advertise an arm capability while the physical revision,
driver integration, mount, power budget, payload, calibration, and recovery
remain unaccepted.

The current profile names OMX-AI as its target but is intentionally disabled.
The measured joint map and hardware plugin stay empty. The vendor stack source
is pinned separately in `deploy/omx/stack.lock.yaml`; later workstation image
and runtime work must preserve this profile boundary.

```bash
python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml
```

When running from a source checkout, set `PYTHONPATH=src/devices/omx/adapter`
or build/source the ROS workspace first.

The empty JSON contract from the disabled profile is expected. A non-empty
contract is not a physical acceptance result.

`omx_adapter.command_owner` provides a ROS-free, disabled-by-default policy
boundary for one arm command writer. It checks workcell and runtime-session
identity, owner admission, fresh monotonic joint-state sequence, calibration
revision, bounded goals, and configured joint limits. Action timeout, cancel,
or fault latches a software HOLD and requires explicit operator recovery with
new feedback. Timeout detection is caller-driven: a runtime must schedule
`poll()` periodically with a measured bound; this policy has no autonomous
watchdog. `cancel_outcome: call_returned` means only that the local cancel call
returned, not that the action server accepted it or the actuator stopped. This
policy is not connected to a ROS/vendor action server. Keep ROS-SIM, DEVICE,
and FIELD gates closed until their separate scheduling, action-result, fault,
physical-stop, and recovery evidence exists.
