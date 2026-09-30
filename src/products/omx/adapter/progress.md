---
module: omx_adapter
owner: OMX workcell
last_verified: { commit: "979c0785", date: 2026-10-01 }
gates:
  SOURCE:
    state: GO
    evidence: "Baseline at 979c0785: 213 OMX adapter/profile/vendor-boundary tests passed, 3 skipped. D-386 Task 8 source work now separates local PhaseDispatch from ROS acceptance callbacks, journals first UUID and parent acceptance atomically on callback, binds a per-command event sink before ROS dispatch, records timeout as UNKNOWN, exact-cancels a late accepted UUID without reopening HOLD, and validates each phase against a fresh joint-state sequence plus start-state tolerances and calibration/transform/planning-scene revisions. Focused current contract suites: 62 passed, 2 skipped; ROS runtime modules require ROS 2 Jazzy and were skipped on this Windows host. Production workcell planner/gripper factory and ROS-to-Fleet runtime composition remain absent."
    cmd: "python -B -X utf8 -m pytest src/products/omx/adapter/test src/products/omx/profile/test test/test_omx_vendor_stack_lock.py test/test_omx_host_inventory.py test/test_omx_multi_preflight.py test/test_dds_identity_contracts.py -q -p no:cacheprovider"
  LOCAL:
    state: GO
    evidence: "Source CLI prints {}; vendor source refs are immutable commits; local OCI image digest is sha256:8b4d2fdf534687132cc7d9fb8441b3db63c140edfaaba5164693fd56ca77d861"
    cmd: "PYTHONPATH=src/products/omx/adapter python -m omx_adapter.cli src/products/omx/profile/config/omx.disabled.yaml"
  ROS-SIM:
    state: HOLD
    evidence: "Prior isolated vendor Gazebo and synthetic image/camera evidence remains at docs/validation/omx-two-instance-ros-sim-2026-09-26/README.md. D-386's asynchronous source seam and fresh per-phase state/path checks now have ROS-free tests, but no four-phase pinned vendor simulation or ROS callback run is claimed. Docker info timed out after 12 seconds on this Windows host, and Ubuntu WSL reported getpwuid(0) failures before ROS availability could be verified."
    blocker: "Run the modified ROS action adapter against ROS 2 Jazzy and complete Task 9 on the intended Linux workstation, including the response-timeout/late-response path and the pinned four-phase fault scenario. Target-host timing and simulator behavior remain unmeasured. No physical arm/independent stop or selected camera exists, so camera source, format/FPS/drop/latency, calibration, E-stop, ARTIFACT, DEVICE, and FIELD acceptance remain unverified."
  ARTIFACT:
    state: HOLD
    blocker: "A local workstation image ID exists, but no immutable published artifact digest or dependency inventory exists; source lock is not an artifact"
  DEVICE:
    state: PARKED
    blocker: "No OMX-AI, leader/follower OpenRB, or workcell camera is connected for physical acceptance"
  FIELD:
    state: PARKED
adrs: [D-61, D-147, D-168, D-273, D-282, D-336, D-369, D-376, D-386]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-26-omx-ai-workstation-runtime.md
  - docs/plans/2026-09-29-er2-semantic-actions-mission-implementation.md
  - docs/plans/2026-09-30-omx-pick-place-local-execution.md
---
