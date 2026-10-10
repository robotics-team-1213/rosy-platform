---
module: isaac_sim
owner: sim
last_verified: { commit: "055fd333ce", date: 2026-10-11 }
gates:
  SOURCE:
    state: GO
    cmd: "python tools/remote/remote_pytest.py --log-dir X:/DevTemp/isaac-headless-contracts -- test/architecture/test_module_structure.py test/test_module_functional_surface.py"
    evidence: "structure scan sees the package; D-73 functional surface declared; validation runs remotely per D-584"
  LOCAL:
    state: GO
    cmd: "python tools/remote/remote_pytest.py --log-dir X:/DevTemp/isaac-headless -- learning/envs/isaac/test"
    evidence: "2026-10-11 원격 pytest 75 passed/1 skipped, known_failures 신규 0; 실제 Jazzy URDF 생성·mesh 검사는 별도 통과"
  ROS-SIM:
    state: HOLD
    blocker: "2026-10-11 별도 SDK pip check/헤드리스 CORE 연결 확인. fixed links 병합으로 무명령 caster jitter를 줄이고 wheel force drive에서 기존 CORE auth API의 전진·회전·입력 만료 후 실제 정지를 관찰했다. 격리된 CORE 강제 종료 뒤 SDK watchdog 정지도 관찰했다. 목표 angular 0.3 rad/s에 약 0.19 rad/s로 추종 오차가 남아 I1 HOLD. SDK GUI menu는 종료 시 정리 대신 시작 단계에서 제외한다. 상세 source/실행/종료 판정은 docs/validation/isaac-headless-repair-2026-10-11/result.md 참조. 실제 STL 맵, 센서, Nav2, 두 대 Fleet와 RL은 미확인(D-322/D-434)."
  ARTIFACT: { state: N/A }
  DEVICE: { state: N/A }
  FIELD: { state: N/A }
plans:
  - docs/plans/2026-10-04-isaac-navigation-integration-review.md
---
## 2026-09-30 initial marker

Package marker landed so the D-168 structure scan sees `src/sim/isaac_sim`. Host tests exist and run (D-322 검증 절: URI·namespace·초기 wheel 계약); the earlier "no own tests" note here was wrong and is corrected in the same tree.
