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
