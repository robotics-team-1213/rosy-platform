---
module: isaac_sim
owner: sim
last_verified: { commit: "uncommitted", date: 2026-09-30 }
gates:
  SOURCE:
    state: GO
    cmd: "python -m pytest test/architecture/test_module_structure.py test/test_module_functional_surface.py -q"
    evidence: "structure scan sees the package; D-73 functional surface declared (3 host tests)"
  LOCAL:
    state: GO
    cmd: "python -m pytest src/sim/isaac_sim/test -q"
    evidence: "test_graph_contract·test_model_checks·test_prepare_urdf 통과 (2026-09-30 Windows)"
  ROS-SIM:
    state: HOLD
    blocker: "Isaac Sim 6.1 실행·USD import·ROS graph는 GPU 호스트에서 미실행. 명령 신선도 watchdog 부재로 장시간 주행·Nav2 수용 전 (D-322)"
  ARTIFACT: { state: N/A }
  DEVICE: { state: N/A }
  FIELD: { state: N/A }
plans: []
---
## 2026-09-30 initial marker

Package marker landed so the D-168 structure scan sees `src/sim/isaac_sim`. Host tests exist and run (D-322 검증 절: URI·namespace·초기 wheel 계약); the earlier "no own tests" note here was wrong and is corrected in the same tree.
