---
module: core_features
owner: CORE
last_verified: { commit: "4e99d92e", date: 2026-10-02 }
gates:
  SOURCE:
    state: GO
    evidence: "227 passed (2026-09-28 Windows); D-316 navigation result correlation regression included."
    cmd: "python -m pytest src/runtime/services/test -q"
  LOCAL:
    state: GO
    evidence: "227 passed (2026-09-28 Windows); host-only test suite."
    cmd: "python -m pytest src/runtime/services/test -q"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-61, D-147, D-168, D-182, D-184, D-228, D-411, D-476, D-620, D-735]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-10-02-d411-pilot-recording-controls-plan.md
---
## 지금 상태

- 라이브러리·계약 등급(D-168 P2)이다. 프로세스가 없으므로 ROS-SIM~FIELD는 N/A이며, 그 판정은 이 패키지를 싣는 `core` 모듈의 gate가 소유한다.
- 2026-09-22 harness에 처음 등록했다. 이전 이력은 `git log -- src/runtime/services`를 본다.
- 자체 `test/`가 있다(docking·swarm, 2026-09-24 `core/test`에서 이전).

## 다음 gate

1. `test_core_logic`(state/mux/safety)·`test_line_follow_api`·`test_slam_reset` 이전 — `core_client`/fixture 혼재로 보류(§6 과제 2).

## 현재 유효한 금지사항

- Depends on `core_common`. Never on `core_api_web` or `core`. Never import `control` (D-126).


- 2026-10-11 D-623: fresh lane boundary revision and current inquiry implemented; independent source review approved, remote regression and DEVICE/FIELD pending.

- 2026-10-16 D-772: NavigationManager의 기존 readback 계약을 보존해 native_handover로 분리하고 terminal/quiescence를 같은 owner lock에서 검증한 인계만 허용한다. 새 정지 source-time cutoff로 인계 전 표본을 배제한다. 50a6ef719 원격 35개 통과, NEW 0. 실제 backend/계측·이안/재투입·DEVICE/FIELD 수용은 미완료다.

- 2026-10-16 D-772: 같은 버전의 새 global capture를 기존 binding에 반영하되 expired/HOLD·source replay·foreign native·stale/future permission을 거절한다. feed/착좌/충전 완료 수명은 갱신하지 않는다. 1f45569ca 원격 CORE/HTTP 190개, 741c9b95f 지속 충전/완료 수명/영상/sensor 134개 통과, 각 NEW 0/skip 0. 실행/계측은 명시적 SIM이며 이안·재투입·DEVICE/FIELD는 미완료다.
