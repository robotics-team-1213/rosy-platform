---
module: rosy_cell
logical_modules: []
owner: SITE
last_verified: { commit: "uncommitted", date: 2026-10-01 }
gates:
  SOURCE:
    state: HOLD
    blocker: "core modules not yet implemented (plan docs/plans/2026-10-01-rosy-cell-pattern-core.md)"
    cmd: "python -m pytest src/site/cell/test -q"
  LOCAL:
    state: N/A
  ROS-SIM:
    state: HOLD
    blocker: "needs roadmap P3/P4 (MoveIt OMX-F Gazebo, device Step API)"
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
---
