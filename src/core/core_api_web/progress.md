---
module: core_api_web
owner: CORE
last_verified: { commit: "uncommitted", date: 2026-09-22 }
gates:
  SOURCE:
    state: GO
    evidence: "9 passed (2026-09-22 Windows)"
    cmd: "python -m pytest src/core/core_api_web/test -q"
  LOCAL:
    state: GO
    evidence: "9 passed (2026-09-22 Windows)"
    cmd: "python -m pytest src/core/core_api_web/test -q"
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
- 2026-09-22 harness에 처음 등록했다. 이전 이력은 `git log -- src/core/core_api_web`를 본다.
- 자체 `test/`가 있다.

## 다음 gate

1. 시험 범위를 공개면(패키지 경계) 계약으로 넓힌다.

## 현재 유효한 금지사항

- v1 routers reach `core_features` only through `api/deps` (`test_v1_import_boundary.py`).
