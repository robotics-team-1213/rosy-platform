---
module: core_features
owner: CORE
last_verified: { commit: "uncommitted", date: 2026-09-25 }
gates:
  SOURCE:
    state: GO
    evidence: "docking·swarm·decision — test_decision.py 포함 (2026-09-25 Windows)"
    cmd: "python -m pytest src/runtime/features/test -q"
  LOCAL:
    state: GO
    evidence: "218 passed (2026-09-25 Windows), test_decision.py 포함"
    cmd: "python -m pytest src/runtime/features/test -q"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-61, D-147, D-168, D-182, D-184, D-228]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- 라이브러리·계약 등급(D-168 P2)이다. 프로세스가 없으므로 ROS-SIM~FIELD는 N/A이며, 그 판정은 이 패키지를 싣는 `core` 모듈의 gate가 소유한다.
- 2026-09-22 harness에 처음 등록했다. 이전 이력은 `git log -- src/runtime/features`를 본다.
- 자체 `test/`가 있다(docking·swarm, 2026-09-24 `core/test`에서 이전).

## 다음 gate

1. `test_core_logic`(state/mux/safety)·`test_line_follow_api`·`test_slam_reset` 이전 — `core_client`/fixture 혼재로 보류(§6 과제 2).

## 현재 유효한 금지사항

- Depends on `core_common`. Never on `core_api_web` or `core`. Never import `control` (D-126).
