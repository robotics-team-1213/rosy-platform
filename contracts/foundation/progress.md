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
adrs: [D-61, D-147, D-168, D-18, D-283, D-268, D-411, D-433, D-620, D-775]
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

## 2026-10-17 · D-775 실측 교정 운영 연결

실측 수치 묶음의 목적별 승인·영속 저장·현재 촬영 session 확인·미리보기·철회 경로를 추가했다.
기존 tracking/sighting 승인과 World/CORE 권한은 유지한다. 원격 시험의 커밋·실행·실패 수정·skipped와
실측 근거의 한계는 [구현 검증 기록](../../docs/validation/measured-camera-lifecycle-2026-10-16/result.md)에 모은다. 기존 모듈 gate의 물리 수용 범위를
넓히지 않는다. D-598의 현재 현장 readback·로봇별 오차 계수는 아직 확보하지 못했다.

## 2026-10-24 · D-856 공유 자원 키의 contract leaf

source76의 core_common.resource_keys는 stdlib-only 자원 식별자 정규화다. safety/decision 양쪽이 이 leaf를 소비하고 기존 Fleet import는 같은 함수 재수출로 보존한다. wire·API 버전·writer 권한은 바꾸지 않는다. Foundation 전체와 관련 Fleet/구조 집중 원격1292 passed/skip0와 FULL23개 각각exit0/known0 NEW·독립 안전 검토를 확인했다. [원본 실패·skip·물리 수용의 한계](../../docs/validation/harbor-physical-proposals-2026-10-24/result.md)를 따른다. runtime/물리 수용 gate는 그대로다.
