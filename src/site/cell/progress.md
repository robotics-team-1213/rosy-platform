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
    blocker: "needs roadmap P3/P4 (MoveIt OMX-F Gazebo, device Step API)"
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
  - docs/plans/2026-10-02-platform-architecture-v02-migration.md
---
