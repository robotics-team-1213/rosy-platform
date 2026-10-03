---
module: isaac_sim
owner: sim
last_verified: { commit: "bed604ef", date: 2026-09-30 }
gates:
  SOURCE:
    state: GO
    cmd: "python -m pytest test/architecture/test_module_structure.py test/test_module_functional_surface.py -q"
    evidence: "structure scan sees the package; D-73 functional surface declared (3 host tests)"
  LOCAL:
    state: GO
    cmd: "python -m pytest learning/envs/isaac/test -q"
    evidence: "test_graph_contract·test_model_checks·test_prepare_urdf 통과 (2026-09-30 Windows)"
  ROS-SIM:
    state: HOLD
    blocker: "Model-PC Isaac 5.1 installation is historical D-434 evidence; current runner uses 6.1 import APIs. Actual remote import/ROS graph, command freshness stop, sensors/Nav2 and two-robot Fleet acceptance remain unverified. Host 10 passed/1 skipped on 2026-10-04 does not promote runtime (D-322/D-434)."
  ARTIFACT: { state: N/A }
  DEVICE: { state: N/A }
  FIELD: { state: N/A }
plans:
  - docs/plans/2026-10-04-isaac-navigation-integration-review.md
---
## 2026-09-30 initial marker

Package marker landed so the D-168 structure scan sees `src/sim/isaac_sim`. Host tests exist and run (D-322 검증 절: URI·namespace·초기 wheel 계약); the earlier "no own tests" note here was wrong and is corrected in the same tree.
