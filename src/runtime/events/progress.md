---
module: core_events
owner: CORE
last_verified: { commit: "uncommitted", date: 2026-09-24 }
gates:
  SOURCE:
    state: GO
    evidence: "test_audit.py가 자체 test/로 이전 — 70 passed (2026-09-24 Windows)"
    cmd: "python -m pytest src/runtime/events/test -q"
  LOCAL:
    state: GO
    evidence: "70 passed (2026-09-24 Windows)"
    cmd: "python -m pytest src/runtime/events/test -q"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-61, D-147, D-168]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- 라이브러리·계약 등급(D-168 P2)이다. 프로세스가 없으므로 ROS-SIM~FIELD는 N/A이며, 그 판정은 이 패키지를 싣는 `core` 모듈의 gate가 소유한다.
- 2026-09-22 harness에 처음 등록했다. 이전 이력은 `git log -- src/runtime/events`를 본다.
- 자체 `test/`가 있다(LOG-001 audit 계약, 2026-09-24 `core/test`에서 이전).

## 다음 gate

1. `test_core_logic`의 EventBus 구간 분리 — `core_client` fixture 혼재로 보류(§6 과제 2).

## 현재 유효한 금지사항

- Depends only on `core_common`.
