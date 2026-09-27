# ROSY Platform P1 — OMX local controller source gate

**Date:** 2026-09-27

**Evidence:** SOURCE/LOCAL host checks only. ROS-SIM, ARTIFACT, DEVICE and FIELD
retain their separate module gate states; this record does not promote them.

| Criterion | Current source evidence | Gate conclusion |
|---|---|---|
| Workcell identity and one writer | `deploy/omx/host_inventory.py` requires explicit `enabled`, unique instance IDs, different follower/leader `/dev/serial/by-id/` selections and unique active selections per host. `ArmCommandOwner` validates workcell, instance, session, owner, command ID, joint names, limits and feedback age. | Static input and policy guard pass; Linux device FD and ROS graph ownership are unmeasured. |
| Actual hardware identity | The tracked inventory example keeps both workcells disabled and all serial/camera selections null. `src/products/omx/config/omx.disabled.yaml` is also disabled. | Real OMX-L/F revision, serial identities, firmware, power, camera and calibration are unknown; no operational capability can open. |
| Joint readback provenance | `ArmCommandRuntime._on_joint_state` copies names and positions from ROS `JointState`, assigns its own sequence and `time.monotonic()` receipt time, then assigns `calibration_revision` from configuration. | Receipt freshness is guarded, but hardware sample time, source driver, calibration provenance and measured joint accuracy are not established. |
| Cancel and stop | `RosTrajectoryActionPort` records a cancel response/final action status; `ArmCommandOwner` enters software HOLD for stale state, timeout and cancel. | An action server accepting cancel is not physical standstill. Independent stop path, stop latency, post-stop joint/driver readback and recovery require DEVICE measurement. |
| Native ROS and optional LeRobot | Existing vendor Gazebo probe and tests cover an isolated ROS action path. No LeRobot owner is installed in the tracked runtime. | Target Ubuntu service/FD/graph behavior is open. ROS↔LeRobot mode transition is a requirement only if both will access the same device. LeRobot bench is not a Fleet mission prerequisite. |

The focused Windows host command passed **107 tests, 3 skipped**:

```text
python -B -X utf8 -m pytest src/devices/omx/adapter/test src/products/omx/test test/test_omx_vendor_stack_lock.py test/test_omx_host_inventory.py test/test_omx_multi_preflight.py test/test_dds_identity_contracts.py -q -p no:cacheprovider
```

## Required next evidence before P1 DEVICE

1. Record selected OMX-L/F hardware revision, by-id ports, joint/gripper and
   camera identity, firmware, power and independent stop path in private host
   inventory. Keep secrets and real serials outside this public repo.
2. On the selected Ubuntu host, inspect the installed vendor stack, action
   server, `joint_states` publisher, serial FDs and any competing process. Pin
   which process is the final trajectory writer; reject duplicate writers.
3. Compare source-stamped physical joint/driver samples to the ROS receipt and
   configured calibration revision. Define acceptable age and accuracy from
   measured hardware, including stale/missing/reordered samples.
4. Under an operator-controlled bench procedure with an independent stop,
   measure cancel, stop, power loss, restart and recovery. Record actuator and
   driver state after each case; software HOLD and action result alone cannot
   clear the gate.
5. Only after that evidence, decide the minimum OMX Device Action API and
   compare its real request/result with the P0 Pinky trace. Do not add a shared
   execution library or a public capability from these host tests.

**Sources:** `src/devices/omx/adapter/{omx_adapter/command_owner.py,omx_adapter/ros_runtime.py,progress.md}`,
`deploy/omx/{host_inventory.py,host-inventory.yaml.example,README.md}`,
`src/products/omx/config/omx.disabled.yaml`, D-282, D-296, D-298, D-299.
