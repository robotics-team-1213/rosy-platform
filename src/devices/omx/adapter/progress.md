---
module: omx_adapter
owner: OMX workcell
last_verified: { commit: "uncommitted", date: 2026-09-26 }
gates:
  SOURCE:
    state: GO
    evidence: "28 ROS-free command-owner policy tests; 99 focused adapter/product/vendor-lock/identity/preflight tests pass; 11 ROS 2 Jazzy tests pass on final source, including synthetic camera pairing/digest/replay rejection and isolated vendor Gazebo no-op/readback/cancel; disabled OMX-AI profile remains empty-contract"
    cmd: "python -B -X utf8 -m pytest src/devices/omx/adapter/test src/products/omx/test test/test_omx_vendor_stack_lock.py test/test_omx_host_inventory.py test/test_omx_multi_preflight.py test/test_dds_identity_contracts.py -q -p no:cacheprovider"
  LOCAL:
    state: GO
    evidence: "Source CLI prints {}; vendor source refs are immutable commits; local OCI image digest is sha256:8b4d2fdf534687132cc7d9fb8441b3db63c140edfaaba5164693fd56ca77d861"
    cmd: "PYTHONPATH=src/devices/omx/adapter python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml"
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
adrs: [D-61, D-147, D-168, D-273, D-282]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-26-omx-ai-workstation-runtime.md
---
