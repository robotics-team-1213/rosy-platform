---
module: omx_adapter
owner: OMX workcell
last_verified: { commit: "b235ffa4", date: 2026-10-01 }
gates:
  SOURCE:
    state: GO
    evidence: "213 OMX adapter/profile/vendor-boundary tests passed, 3 skipped. SOURCE includes typed 3D RGB-D plan contracts, bounded timed trajectories, typed ROS goal events, atomic phase acceptance, a stop-fenced PickPlaceRunner, semantic transaction/journal phase gates, conservative possible-held-object semantics, restart-to-UNKNOWN/HOLD recovery, fresh gripper release before local Action success, exact-phase cancel routing, and Fleet's versioned phase receipt/progress projection. Fleet placement verification remains separate. The production plan/ROS/gripper factory and ROS-to-Fleet runtime wiring are absent."
    cmd: "python -B -X utf8 -m pytest src/products/omx/adapter/test src/products/omx/profile/test test/test_omx_vendor_stack_lock.py test/test_omx_host_inventory.py test/test_omx_multi_preflight.py test/test_dds_identity_contracts.py -q -p no:cacheprovider"
  LOCAL:
    state: GO
    evidence: "Source CLI prints {}; vendor source refs are immutable commits; local OCI image digest is sha256:8b4d2fdf534687132cc7d9fb8441b3db63c140edfaaba5164693fd56ca77d861"
    cmd: "PYTHONPATH=src/products/omx/adapter python -m omx_adapter.cli src/products/omx/profile/config/omx.disabled.yaml"
  ROS-SIM:
    state: HOLD
    evidence: "Prior isolated vendor Gazebo and synthetic image/camera evidence is recorded at docs/validation/omx-two-instance-ros-sim-2026-09-26/README.md. This change's coordinator-to-RosArmCommandRuntime callbacks and target Linux timing were not verified."
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
