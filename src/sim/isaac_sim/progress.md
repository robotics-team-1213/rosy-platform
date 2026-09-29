---
module: isaac_sim
owner: sim
last_verified: { commit: "uncommitted", date: 2026-09-30 }
gates:
  SOURCE:
    state: GO
    cmd: ":"
    evidence: "structure scan sees the package"
  LOCAL:
    state: GO
    cmd: ":"
    evidence: "host-testable graph contract"
  ROS-SIM: { state: N/A }
  ARTIFACT: { state: N/A }
  DEVICE: { state: N/A }
  FIELD: { state: N/A }
plans: []
---
## 2026-09-30 initial marker

Package marker landed so the D-168 structure scan sees `src/sim/isaac_sim`. No own tests by design (D-322).
