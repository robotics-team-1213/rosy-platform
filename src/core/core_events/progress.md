---
module: core_events
owner: CORE
last_verified: { commit: "uncommitted", date: 2026-09-22 }
gates:
  SOURCE:
    state: HOLD
    blocker: "자체 test/ 없음 — 검증이 src/core/core/test에 흩어져 있어 패키지 경계로 드러나지 않는다 (D-168 KNOWN_WITHOUT_OWN_TESTS)"
  LOCAL:
    state: GO
    evidence: "core suite 1056 passed, 12 skipped (2026-09-22 Windows); no own test/ yet (D-168 KNOWN_WITHOUT_OWN_TESTS)"
    cmd: "PYTHONPATH=src/core:src python -m pytest src/core/core/test -q"
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
- 2026-09-22 harness에 처음 등록했다. 이전 이력은 `git log -- src/core/core_events`를 본다.
- 자체 `test/`가 없다. 검증은 `core` 스위트가 대신한다(LOCAL 증거).

## 다음 gate

1. 이 패키지만 import하는 시험을 자체 `test/`로 옮기고 D-168 `KNOWN_WITHOUT_OWN_TESTS`에서 뺀다 → SOURCE GO.

## 현재 유효한 금지사항

- Depends only on `core_common`.
