---
module: omx_adapter
owner: OMX workcell
last_verified: { commit: "bed604ef", date: 2026-09-30 }
gates:
  SOURCE:
    state: GO
    evidence: "190 OMX adapter/profile/vendor-boundary tests passed, 3 skipped. SOURCE now includes typed 3D RGB-D pose and four-phase plan contracts, full timed multi-waypoint validation/preservation, and typed command/phase-bound ROS goal event contracts. The current ROS runtime callback integration test has not passed in this run; no Fleet phase receipt wiring or production planner exists."
    cmd: "python -B -X utf8 -m pytest src/products/omx/adapter/test src/products/omx/profile/test test/test_omx_vendor_stack_lock.py test/test_omx_host_inventory.py test/test_omx_multi_preflight.py test/test_dds_identity_contracts.py -q -p no:cacheprovider"
  LOCAL:
    state: GO
    evidence: "Source CLI prints {}; vendor source refs are immutable commits; local OCI image digest is sha256:8b4d2fdf534687132cc7d9fb8441b3db63c140edfaaba5164693fd56ca77d861"
    cmd: "PYTHONPATH=src/products/omx/adapter python -m omx_adapter.cli src/products/omx/profile/config/omx.disabled.yaml"
  ROS-SIM:
    state: HOLD
    evidence: "ROS ArmCommandRuntime uses a steady-clock timer, actual FollowJointTrajectory action client, filtered vendor joint feedback, cancel acknowledgement/final status, and readback in an isolated vendor Gazebo instance; synthetic ROS Image/CameraInfo topics verify exact-stamp pairing and calibration digest admission. Prior two-instance evidence: docs/validation/omx-two-instance-ros-sim-2026-09-26/README.md"
    blocker: "Simulation evidence is Docker Desktop amd64 only. Target Linux workstation timing and fault behavior are unmeasured; no physical arm/independent stop or selected camera exists, so camera source, format/FPS/drop/latency, and device calibration remain unverified."
  ARTIFACT:
    state: HOLD
    blocker: "A local workstation image ID exists, but no immutable published artifact digest or dependency inventory exists; source lock is not an artifact"
  DEVICE:
    state: PARKED
    blocker: "No OMX-AI, leader/follower OpenRB, or workcell camera is connected for physical acceptance"
  FIELD:
    state: PARKED
adrs: [D-61, D-147, D-168, D-273, D-282, D-336, D-369, D-376]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-26-omx-ai-workstation-runtime.md
  - docs/plans/2026-09-29-er2-semantic-actions-mission-implementation.md
  - docs/plans/2026-09-30-omx-pick-place-local-execution.md
---
