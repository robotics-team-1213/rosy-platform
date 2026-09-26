---
module: omx
logical_modules: []
owner: OMX workcell
last_verified: { commit: "uncommitted", date: "2026-09-26" }
gates:
  SOURCE:
    state: GO
    evidence: "13 focused tests pass; model is selected as omx_ai while runtime, plugin, and joint map remain empty/disabled"
    cmd: "python -m pytest src/products/omx/test src/devices/omx/adapter/test test/test_omx_vendor_stack_lock.py -q"
  LOCAL:
    state: GO
    evidence: "Disabled OMX-AI profile CLI prints {}"
    cmd: "PYTHONPATH=src/devices/omx/adapter python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml"
  ROS-SIM:
    state: HOLD
    blocker: "Vendor source is pinned; workstation image and installed ROS graph are not built"
  ARTIFACT:
    state: HOLD
    blocker: "No OMX workstation image digest or package inventory"
  DEVICE:
    state: PARKED
    blocker: "No OMX-AI hardware or workcell cameras available for measured commissioning"
  FIELD:
    state: PARKED
adrs: [D-196, D-231, D-232, D-273]
plans:
  - docs/plans/2026-09-26-omx-ai-workstation-runtime.md
---

OMX-AI is the chosen fixed-workbench target. It is not enabled. The official
source revisions are locked in `deploy/omx/stack.lock.yaml`; leader/follower
ports, measured joints, plugin configuration, and camera selection remain
unset. The OMX-AI workstation image is planned separately from the Pinky Pro
ARM64 product image.
