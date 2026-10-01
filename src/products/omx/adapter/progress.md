---
module: omx_adapter
owner: OMX workcell
last_verified: { commit: "38dcb8fe", date: 2026-10-02 }
gates:
  SOURCE:
    state: GO
    evidence: "Baseline at 979c0785: 213 OMX adapter/profile/vendor-boundary tests passed, 3 skipped. D-386 Task 8 source work separates local PhaseDispatch from ROS acceptance callbacks, journals first UUID and parent acceptance atomically on callback, binds a per-command event sink before ROS dispatch, records timeout as UNKNOWN, exact-cancels a late accepted UUID without reopening HOLD, and validates each phase against fresh joint-state sequence, start-state tolerances, and calibration/transform/planning-scene revisions. Follow-up atomically records parent Action HOLD when a ROS phase terminal is CANCELED; the pinned Pilot Jazzy Fleet-to-ROS ActionServer suite passed 2 parametrized cases, including generation-change stop, terminal ROS CANCELED, Mission HOLD reconciliation, and stale-grant replay rejection. Action API regression passed on Windows; the combined Pilot Action API plus Fleet-to-ROS test run passed 18. The fixture uses an in-process ActionServer, not vendor Gazebo, and proves neither physical stop nor E-stop. Production planner/gripper factory and deployment composition remain absent. 2026-10-02 (D-402, plan C2): analytic top-down CELL_TRANSFER planner for the simulation profile only: FK/IK from pinned open_manipulator 5.1.2 URDF with drift pins, FK-IK round trip, limit/workspace/singularity/yaw/home/carry_z/duration rejections, four-phase shape without diagonals, real ArmCommandOwner accepts all phases, direct-driver rejection of non-PICK_PLACE kinds, gripper-free start state; adapter suite 247 passed, 5 skipped. No collision scene; limits nominal; no Gazebo run."
    cmd: "python -B -X utf8 -m pytest src/products/omx/adapter/test src/products/omx/profile/test test/test_omx_vendor_stack_lock.py test/test_omx_host_inventory.py test/test_omx_multi_preflight.py test/test_dds_identity_contracts.py -q -p no:cacheprovider"
  LOCAL:
    state: GO
    evidence: "Source CLI prints {}; vendor source refs are immutable commits; local OCI image digest is sha256:8b4d2fdf534687132cc7d9fb8441b3db63c140edfaaba5164693fd56ca77d861"
    cmd: "PYTHONPATH=src/products/omx/adapter python -m omx_adapter.cli src/products/omx/profile/config/omx.disabled.yaml"
  ROS-SIM:
    state: HOLD
    evidence: "2026-10-01 Pilot OMX Gazebo: joint1/gripper goals reached ROS SUCCEEDED with joint readback; manual cancel reached ROS CANCELED. Direct pinned vendor action callback test passed (1); a Jazzy in-process ROS ActionServer timeout fault test passed (2 total ROS runtime tests), proving timeout HOLD, cancel ACK/terminal CANCELED, and no owner replay. OMX action/store/PICK_PLACE host regression passed 37, skipped 1. Evidence and limits: docs/validation/model-tool-ros-sim-2026-10-01/README.md. Pilot SIM camera/recording and offline LeRobot v3 readback passed for a 15-frame real Gazebo episode (docs/validation/omx-demonstration-lerobot-2026-10-01/README.md). These runs did not exercise Fleet grant handoff, vendor-Gazebo generation/restart races, or four-phase pick/place with object/contact evidence."
    blocker: "Full gate still requires a Fleet Mission admission/grant-to-device-owner simulator harness, a pending vendor goal fenced by generation change, restart recovery to UNKNOWN/HOLD without replay, and four-phase execution with fresh state and independent simulated object/gripper evidence. Pilot workcell RGB recording is available; full Fleet pick/place still has no contact/object evidence and does not prove independent stop, ARM64, or physical hardware."
  ARTIFACT:
    state: HOLD
    evidence: "Simulation-only immutable evidence manifest and detached SHA-256 record local Pilot/base image IDs, vendor source lock, tool catalog SHA-256, direct Python pins, disabled ER 2/provider credentials, no approved egress data classes, and retention boundaries: docs/validation/model-tool-artifact-2026-10-01/. Manifest is unsigned/local and the OS/transitive dependency inventory is partial."
    blocker: "No signed/published production artifact digest, complete SBOM, or provider deployment/secret-injection configuration is available. Simulation manifest does not qualify as a releasable runtime artifact."
  DEVICE:
    state: PARKED
    blocker: "No OMX-AI, leader/follower OpenRB, or workcell camera is connected for physical acceptance"
  FIELD:
    state: PARKED
adrs: [D-61, D-147, D-168, D-273, D-282, D-336, D-369, D-376, D-386, D-390, D-402, D-403]
plans:
  - docs/plans/2026-10-01-omx-demonstration-lerobot-design.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-26-omx-ai-workstation-runtime.md
  - docs/plans/2026-09-29-er2-semantic-actions-mission-implementation.md
  - docs/plans/2026-09-30-omx-pick-place-local-execution.md
  - docs/plans/2026-10-01-pilot-omx-gazebo-practice.md
  - docs/plans/2026-10-01-model-tool-contract-implementation.md
---
