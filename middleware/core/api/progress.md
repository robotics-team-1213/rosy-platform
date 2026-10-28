---
module: core_api_web
owner: CORE
last_verified: { commit: "4e99d92e", date: 2026-10-02 }
gates:
  SOURCE:
    state: GO
    evidence: "70 passed, 13 skipped (2026-09-28 Windows); D-316 optional CORE navigation correlation request is backward-compatible."
    cmd: "python tools/remote/remote_pytest.py -- middleware/core/api/test -q"
  LOCAL:
    state: GO
    evidence: "70 passed, 13 skipped (2026-09-28 Windows); source-only request contract coverage."
    cmd: "python tools/remote/remote_pytest.py -- middleware/core/api/test -q"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-61, D-147, D-168, D-283, D-411, D-472]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-10-02-d411-pilot-recording-controls-plan.md
---
## 지금 상태

- 라이브러리·계약 등급(D-168 P2)이다. 프로세스가 없으므로 ROS-SIM~FIELD는 N/A이며, 그 판정은 이 패키지를 싣는 `core` 모듈의 gate가 소유한다.
- 2026-09-22 harness에 처음 등록했다. 이전 이력은 `git log -- src/runtime/api_web`를 본다.
- 자체 `test/`가 있다.

## 다음 gate

1. 시험 범위를 공개면(패키지 경계) 계약으로 넓힌다.

## 현재 유효한 금지사항

- v1 routers reach `core_features` only through `api/deps` (`test_v1_import_boundary.py`).

## 2026-10-16 D-772 finish 인계 v1.283 (origin #92 v1.252)

station-return/finish의 terminal navigation→IDLE 동작을 공유 계약·SRS·9개 live pin에 반영했다. 첫 인계의 명시적 standstill 409는 완료가 아니며 새 측정 dwell 이후에만 ACK/BOUND를 반환한다. 활성·불명 navigation은 전환 없이 거절한다. 50a6ef719 원격 35개 통과, NEW 0. 운영 자동 활성화·전체 lifecycle·장치 수용은 미완료다.

## 2026-10-16 D-772 세션 한정 접안 중단 v1.284 (origin #92 v1.253)

station-stop은 고정 Fleet principal과 session/boot/native generation 및 수락된 run/correlation이 일치할 때만 해당 접안 권한을 닫는다. 근거가 만료되어도 중단할 수 있으며 ACK는 물리 정지나 자원 해제가 아니다. API/SRS/9개 live pin과 실제 HTTP 소비자를 갱신했다. c3ac314b5 CORE/HTTP 144개 통과, NEW 0/skip 0. 운영 활성화와 장치 수용은 미완료다.
