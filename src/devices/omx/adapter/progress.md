---
module: omx_adapter
owner: OMX workcell
last_verified: { commit: "uncommitted", date: 2026-09-26 }
gates:
  SOURCE:
    state: GO
    evidence: "28 ROS-free command-owner policy tests, including cancel-call failure and future-dated feedback; 99 focused adapter/product/vendor-lock/identity/preflight tests pass; locked ROS packages build in the local amd64 workstation image; disabled OMX-AI profile remains empty-contract"
    cmd: "python -B -X utf8 -m pytest src/devices/omx/adapter/test src/products/omx/test test/test_omx_vendor_stack_lock.py test/test_omx_host_inventory.py test/test_omx_multi_preflight.py test/test_dds_identity_contracts.py -q -p no:cacheprovider"
  LOCAL:
    state: GO
    evidence: "Source CLI prints {}; vendor source refs are immutable commits; local OCI image digest is sha256:8b4d2fdf534687132cc7d9fb8441b3db63c140edfaaba5164693fd56ca77d861"
    cmd: "PYTHONPATH=src/devices/omx/adapter python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml"
  ROS-SIM:
    state: HOLD
    evidence: "The 2026-09-26 two-instance vendor simulation observed bounded action, cancellation, restart isolation, and sampled joint feedback; see docs/validation/omx-two-instance-ros-sim-2026-09-26/README.md"
    blocker: "ArmCommandOwner is not wired to ROS/vendor actions. Timeout is checked only when a caller invokes poll(); no bounded runtime scheduler or cancellation-result path is integrated. Target-workstation timing and camera topics remain unverified."
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
