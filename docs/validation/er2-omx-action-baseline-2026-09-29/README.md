# ER 2 / OMX Action baseline — 2026-09-29

## Evidence scope

SOURCE review and Windows host pytest only. No OMX hardware inventory was
provided to this checkout; no device probe, physical command, stop test, or
field observation was performed.

## Current control boundary

| Area | Confirmed in source | Unknown / gate |
|---|---|---|
| Product target | `omx_ai` is selected in `src/products/omx/profile/config/omx.disabled.yaml` | Physical OMX-AI revision/serial and installed vendor stack are not identified |
| Enablement | Profile has `enabled: false`, empty `driver_package`, `hardware_plugin`, and `joint_names` | Do not enable or advertise an arm capability |
| Arm command policy | `omx_adapter.command_owner.ArmCommandOwner` checks configured workcell/session identity, one active trajectory, joint-state freshness, calibration revision, bounds, timeout and HOLD | It is an in-process policy; this does not identify the physical serial/driver owner |
| ROS writer candidate | `RosArmCommandRuntime` creates one `FollowJointTrajectory` client for `/arm_controller/follow_joint_trajectory` and consumes joint states | No accepted physical server or endpoint has been inventoried; action result is not physical stop evidence |
| Gripper | Existing tests contain synthetic gripper joint data, but runtime filters against the configured arm joint names | No gripper API/driver, force/width readback, object-hold evidence, load limit, or release verification is present |
| Camera/target evidence | Camera contract requires exact image/CameraInfo stamp, optical frame, dimensions, identity, calibration revision and digest | Physical camera identity, calibration, TF/scene revision, target tracking, grasp pose and placement evidence are unselected/unmeasured |
| Stop/recovery | Arm policy requests action cancellation and latches software HOLD on fault/timeout | No independent hardware E-stop, stop/readback path, safe-load behavior, restart ownership or physical stop timing has been accepted |
| Deployment | `deploy/robot/omx/host-inventory.yaml.example` places disabled workcells on a candidate workstation; README says inventory is not connected to an operational control service | No filled private inventory, accepted native service unit, published artifact, selected serials or device acceptance |

## Commands run

```text
python -m pytest src/products/omx/adapter/test/test_omx_profile.py src/products/omx/adapter/test/test_omx_command_owner.py src/products/omx/adapter/test/test_omx_ros_runtime.py src/products/omx/adapter/test/test_omx_ros_runtime_vendor_sim.py -q
38 passed, 2 skipped (2026-09-29, Windows host)
```

The skipped tests and existing workstation simulation evidence do not establish
physical driver, gripper, independent stop, deployment artifact, DEVICE or FIELD
acceptance. Code may add ROS-free evidence and durable state handling while the
capability remains disabled. Do not connect a real actuator or claim a physical
stop until the workcell inventory and independent stop/readback owner are
identified and accepted.
