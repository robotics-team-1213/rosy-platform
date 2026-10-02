---
module: core_common
owner: CORE
last_verified: { commit: "b587404b", date: 2026-10-02 }
gates:
  SOURCE:
    state: GO
    evidence: "424 passed/1 skipped; includes the additive FleetCellTransferGrant / CELL_TRANSFER contract and finite robot-base pose checks"
    cmd: "python -m pytest src/contracts/foundation/test -q"
  LOCAL:
    state: GO
    evidence: "424 passed/1 skipped on Windows host; contract shapes do not imply a UDS listener, runner, or device acceptance"
    cmd: "python -m pytest src/contracts/foundation/test -q"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-61, D-147, D-168, D-18, D-283, D-268, D-411]
plans:
  - docs/plans/2026-09-29-er2-mission-action-contract-closure.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-29-policy-evidence-contract-design.md
  - docs/plans/2026-09-29-policy-evidence-contract.md
  - docs/plans/2026-10-02-d411-pilot-recording-controls-plan.md
---
## 지금 상태

- 라이브러리·계약 등급(D-168 P2)이다. 프로세스가 없으므로 ROS-SIM~FIELD는 N/A이며, 그 판정은 이 패키지를 싣는 `core` 모듈의 gate가 소유한다.
- 2026-09-22 harness에 처음 등록했다. 이전 이력은 `git log -- src/contracts/foundation`를 본다.
- 자체 `test/`가 있다.

## 다음 gate

1. 시험 범위를 공개면(패키지 경계) 계약으로 넓힌다.

## 현재 유효한 금지사항

- Leaf of the core chain. Do not import `core_events`/`core_features`/`core_api_web`/`core`.
