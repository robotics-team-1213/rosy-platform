# OMX-AI two-instance ROS-SIM probe — 2026-09-26

## Inputs and environment

- Source checkout: `feat/omx-sim-gates`, based on `4c6dc965`; the exact result commit is recorded by the integration history.
- Vendor source lock: `deploy/omx/stack.lock.yaml`, ROBOTIS `open_manipulator` 5.1.2 at `0a4af6a923b8b7d80b8c20506d1839c54d2e993e`.
- Built local Linux/amd64 Docker image: `rosy-omx-workstation:sim-gates-v2`, image ID `sha256:3858136d3cd552228549e5c9369b24e23c7fa051c4afc7497251f781cd023954`.
- Host: Windows Docker Desktop Linux engine. This is not the intended Ubuntu field workstation or an immutable published artifact.
- Each probe container had `--network none`, no device grants, `rmw_cyclonedds_cpp`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`, and its own `ROS_DOMAIN_ID` (`71` for `omx_01`, `72` for `omx_02`). The container names were `rosy-omx-sim-gates-01` and `rosy-omx-sim-gates-02`.
- Build command: `docker build --progress plain --tag rosy-omx-workstation:sim-gates-v2 deploy/omx`. Host tests: `python -X utf8 -m pytest test/test_omx_workstation.py test/test_omx_multi_preflight.py -q -p no:cacheprovider --basetemp X:\DevTemp\rosy-omx-sim-gates-pytest` → 21 passed.

## Observations

| Probe | Result |
|---|---|
| Vendor AI follower launch | Both instances exposed `/arm_controller/follow_joint_trajectory`; `arm_controller` and `joint_state_broadcaster` became active. `/joint_states` was present. |
| Simulation configuration | The Gazebo process used `-s --physics-engine gz-physics-bullet-featherstone-plugin`; controller manager logged `Enforcing command limits is enabled`. No `previous async trigger` or unsupported mimic-constraint warning appeared in the inspected logs. |
| Bounded trajectory | `joint1` goal `0.1` rad over 2 simulated seconds was accepted, returned feedback, and ended `SUCCEEDED` with error code 0 in the first build. |
| Cancel | A 10-second `joint1` goal was accepted; cancellation after about one wall second returned one canceling goal and final status `CANCELED` (5), error code 0. This also succeeded on `omx_02` after `omx_01` was stopped. |
| Two-instance isolation | With both v2 containers running, stopping `omx_01` left `omx_02`'s action and both controllers active. Restarting `omx_01` left the `omx_02` action available. |
| Gripper | A `gripper_joint_1` goal of `0.005` rad returned `SUCCEEDED`; one subsequent joint-state sample showed `gripper_joint_1=+0.00233`, `gripper_joint_2=-0.00257` rad. This confirms opposite directions in the sampled simulation state, not calibrated grip force or final positioning. |

## Direct leader input conflict and correction

The pinned vendor AI simulation launch remapped the controller's trajectory topic to `/leader/joint_trajectory` while also exposing its action. In the first image, a 10-second action goal for `joint1=+0.2` rad was accepted, then a leader topic message requested `joint1=-0.2` rad. The action still returned `SUCCEEDED` (status 4, error code 0), while a later joint-state sample read `-0.1999996` rad. The two inputs therefore cannot be admitted concurrently as a single command owner.

`omx-ai-sim-action-only.patch` removes the direct leader remap from the **simulation launch**. In the v2 image, the same probe found zero subscribers on `/leader/joint_trajectory`; the action returned `SUCCEEDED`, and a later joint-state sample read `+0.2000002` rad. The native follower launch has not been changed or approved for field control. The action server is still directly reachable by any participant in its ROS graph, so this patch alone is not a native command admission service.

## Gate conclusion

- **ROS-SIM: HOLD overall.** The vendor graph, isolated two-instance restart/cancel, and simulation action path are observed. A general per-instance command owner, stale-state/timeout HOLD policy, measured target-workstation timing, and camera topics are absent. The simulated gripper and command limits do not prove physical safety.
- **ARTIFACT: HOLD.** The local image ID is recorded for reproducibility; no registry digest, dependency manifest, or signed native amd64 runtime exists.
- **DEVICE/FIELD: PARKED.** No OMX-AI device, serial interface, camera, physical stop, or site acceptance was tested.
- **Next implementation:** make the native instance runner admit exactly one selected command mode and route commands through a bounded owner before enabling an OMX workcell. Re-test simultaneous leader/action input, fault/timeout HOLD, and stop/recovery on the intended Linux workstation, then on the physical arm.
