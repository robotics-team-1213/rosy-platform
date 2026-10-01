---
module: rosy_cell
logical_modules: []
owner: SITE
last_verified: { commit: "13614bc0", date: 2026-10-01 }
gates:
  SOURCE:
    state: GO
    evidence: "143 passed at 13614bc0 (2026-10-01 Windows); ROS-free; cell/2 + carry_z; no Motion Intent, IK or reachability"
    cmd: "python -m pytest src/site/cell/test -q"
  LOCAL:
    state: N/A
  ROS-SIM:
    state: HOLD
    evidence: "2026-10-02 C3: demo examples/omx_sim (2 pallets x 2 layers x 4 blocks + 2 slip sheets) compiles to 18 CELL_TRANSFER pairs that all plan on the OMX analytic planner (test/test_cell_omx_sim_layout_contract.py); one transfer of that Job ran its four phases in Gazebo through the OMX owner but no block was placed within tolerance (docs/validation/rosy-cell-gazebo-c3-2026-10-02/README.md)."
    blocker: "No Fleet route (C4) or end-to-end Job run (C6). Step z is the item top face, but the OMX-F TCP is at the fingertips, so a box grasp needs a depth below the top that no Rosy Cell or grant field carries yet."
  ARTIFACT:
    state: N/A
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-399, D-401]
plans:
  - docs/plans/2026-10-01-rosy-layered-architecture-roadmap.md
  - docs/plans/2026-10-01-rosy-cell-pattern-core.md
  - docs/plans/2026-10-02-rosy-cell-c3-gazebo.md
---
