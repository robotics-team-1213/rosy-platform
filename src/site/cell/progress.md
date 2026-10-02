---
module: rosy_cell
logical_modules: []
owner: SITE
last_verified: { commit: "9da93450", date: 2026-10-02 }
gates:
  SOURCE:
    state: GO
    evidence: "143 legacy Cell tests pass through installed rosy-palletizing wheel; compatibility facade and canonical module share types/functions; ROS-free"
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
adrs: [D-399, D-401, D-413]
plans:
  - docs/plans/2026-10-01-rosy-layered-architecture-roadmap.md
  - docs/plans/2026-10-01-rosy-cell-pattern-core.md
  - docs/plans/2026-10-02-rosy-cell-c3-gazebo.md
  - docs/plans/2026-10-02-platform-architecture-v02-migration.md
---
