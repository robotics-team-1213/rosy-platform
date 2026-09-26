---
module: omx
logical_modules: []
owner: OMX workcell
last_verified: { commit: "uncommitted", date: 2026-09-26 }
gates:
  SOURCE:
    state: GO
    evidence: "8 workstation/preflight and vendor-lock tests pass; 8 locked ROS packages build in the local amd64 workstation image; model is selected as omx_ai while runtime, plugin, and joint map remain empty/disabled"
    cmd: "python -m pytest src/products/omx/test src/devices/omx/adapter/test test/test_omx_vendor_stack_lock.py -q"
  LOCAL:
    state: GO
    evidence: "Disabled OMX-AI profile CLI prints {}; local workstation image digest is sha256:8b4d2fdf534687132cc7d9fb8441b3db63c140edfaaba5164693fd56ca77d861"
    cmd: "PYTHONPATH=src/devices/omx/adapter python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml"
  ROS-SIM:
    state: HOLD
    blocker: "Image package installation is verified; vendor launch graph, simulator/mock path, and camera stream are not exercised"
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
