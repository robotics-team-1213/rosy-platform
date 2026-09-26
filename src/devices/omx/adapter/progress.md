---
module: omx_adapter
owner: OMX workcell
last_verified: { commit: "uncommitted", date: "2026-09-26" }
gates:
  SOURCE:
    state: GO
    evidence: "13 focused profile, product-config, and vendor-lock tests passed on Windows; disabled OMX-AI profile remains empty-contract"
    cmd: "python -m pytest src/devices/omx/adapter/test src/products/omx/test test/test_omx_vendor_stack_lock.py -q"
  LOCAL:
    state: GO
    evidence: "Source CLI prints {}; vendor source refs are immutable commit IDs"
    cmd: "PYTHONPATH=src/devices/omx/adapter python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml"
  ROS-SIM:
    state: HOLD
    blocker: "Separate pinned OMX workstation image and official Jazzy ROS graph are not built or exercised"
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
