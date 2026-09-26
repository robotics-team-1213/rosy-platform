---
module: omx_adapter
owner: OMX workcell
last_verified: { commit: "uncommitted", date: 2026-09-26 }
gates:
  SOURCE:
    state: GO
    evidence: "8 workstation/preflight and vendor-lock tests pass; 8 locked ROS packages build in the local amd64 workstation image; disabled OMX-AI profile remains empty-contract"
    cmd: "python -m pytest src/devices/omx/adapter/test src/products/omx/test test/test_omx_vendor_stack_lock.py -q"
  LOCAL:
    state: GO
    evidence: "Source CLI prints {}; vendor source refs are immutable commits; local OCI image digest is sha256:8b4d2fdf534687132cc7d9fb8441b3db63c140edfaaba5164693fd56ca77d861"
    cmd: "PYTHONPATH=src/devices/omx/adapter python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml"
  ROS-SIM:
    state: HOLD
    blocker: "Image package installation was verified; vendor launch graph, simulator/mock path, and camera stream are not exercised"
  ARTIFACT:
    state: HOLD
    blocker: "No workstation image digest or dependency inventory exists; source lock is not an artifact"
  DEVICE:
    state: PARKED
    blocker: "No OMX-AI, leader/follower OpenRB, or workcell camera is connected for physical acceptance"
  FIELD:
    state: PARKED
adrs: [D-61, D-147, D-168, D-273]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-26-omx-ai-workstation-runtime.md
---
