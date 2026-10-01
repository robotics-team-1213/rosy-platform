---
module: omx_adapter
owner: OMX workcell
last_verified: { commit: "979c0785", date: 2026-10-01 }
gates:
  SOURCE:
    state: GO
    evidence: "Baseline at 979c0785: 213 OMX adapter/profile/vendor-boundary tests passed, 3 skipped. D-386 Task 8 source work now separates local PhaseDispatch from ROS acceptance callbacks, journals first UUID and parent acceptance atomically on callback, binds a per-command event sink before ROS dispatch, records timeout as UNKNOWN, exact-cancels a late accepted UUID without reopening HOLD, and validates each phase against a fresh joint-state sequence plus start-state tolerances and calibration/transform/planning-scene revisions. Focused current contract suites: 62 passed, 2 skipped; ROS runtime modules require ROS 2 Jazzy and were skipped on this Windows host. Production workcell planner/gripper factory and deployment composition remain absent. Pinned Pilot ROS 2 Jazzy integration fixture `test_omx_fleet_ros_actionserver.py`: 1 passed, joining Fleet Mission admission, SO_PEERCRED UDS grant/receipt, local Action journal, and one ROS client goal against an in-process ActionServer; it verifies accepted-only Mission state and restart UNKNOWN/no replay. This is not vendor Gazebo or physical evidence."
    cmd: "python -B -X utf8 -m pytest src/products/omx/adapter/test src/products/omx/profile/test test/test_omx_vendor_stack_lock.py test/test_omx_host_inventory.py test/test_omx_multi_preflight.py test/test_dds_identity_contracts.py -q -p no:cacheprovider"
  LOCAL:
    state: GO
    evidence: "Source CLI prints {}; vendor source refs are immutable commits; local OCI image digest is sha256:8b4d2fdf534687132cc7d9fb8441b3db63c140edfaaba5164693fd56ca77d861"
    cmd: "PYTHONPATH=src/products/omx/adapter python -m omx_adapter.cli src/products/omx/profile/config/omx.disabled.yaml"
  ROS-SIM:
    state: HOLD
    evidence: "2026-10-01 Pilot OMX Gazebo: joint1/gripper goals reached ROS SUCCEEDED with joint readback; manual cancel reached ROS CANCELED. Direct pinned vendor action callback test passed (1); a Jazzy in-process ROS ActionServer timeout fault test passed (2 total ROS runtime tests), proving timeout HOLD, cancel ACK/terminal CANCELED, and no owner replay. OMX action/store/PICK_PLACE host regression passed 37, skipped 1. Evidence and limits: docs/validation/model-tool-ros-sim-2026-10-01/README.md. These runs did not exercise Fleet grant handoff, vendor-Gazebo generation/restart races, or four-phase pick/place with object/contact evidence."
    blocker: "Full gate still requires a Fleet Mission admission/grant-to-device-owner simulator harness, a pending vendor goal fenced by generation change, restart recovery to UNKNOWN/HOLD without replay, and four-phase execution with fresh state and independent simulated object/gripper evidence. Simulator has no camera/contact evidence and does not prove independent stop, ARM64, or physical hardware."
  ARTIFACT:
    state: HOLD
    evidence: "Simulation-only immutable evidence manifest and detached SHA-256 record local Pilot/base image IDs, vendor source lock, tool catalog SHA-256, direct Python pins, disabled ER 2/provider credentials, no approved egress data classes, and retention boundaries: docs/validation/model-tool-artifact-2026-10-01/. Manifest is unsigned/local and the OS/transitive dependency inventory is partial."
    blocker: "No signed/published production artifact digest, complete SBOM, or provider deployment/secret-injection configuration is available. Simulation manifest does not qualify as a releasable runtime artifact."
  DEVICE:
    state: PARKED
    blocker: "No OMX-AI, leader/follower OpenRB, or workcell camera is connected for physical acceptance"
  FIELD:
    state: PARKED
adrs: [D-61, D-147, D-168, D-273, D-282, D-336, D-369, D-376, D-386, D-390]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-26-omx-ai-workstation-runtime.md
  - docs/plans/2026-09-29-er2-semantic-actions-mission-implementation.md
  - docs/plans/2026-09-30-omx-pick-place-local-execution.md
  - docs/plans/2026-10-01-pilot-omx-gazebo-practice.md
  - docs/plans/2026-10-01-model-tool-contract-implementation.md
---
