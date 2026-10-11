# D-696 — 비식별 사건 인수 근거 export

**Status:** Accepted (2026-10-12, source contract).

### Context

최종 검토 대기, 알림 제공자의 접수, 이름을 기록한 사람 인수는 서로 다른 사건이다.
기존 모델 feedback는 이를 포함하지 않으며 원장에 없는 기록을 성공으로 추정할 수 없다.

### Decision

- `snapshot(..., include_handoff=False)`와 CLI `--include-handoff`로 선택한다.
  기본값은 기존 `rosy.incident.model_feedback/1`을 유지한다. 선택하면 `/2`의
  `case.handoff`를 같은 SQLite read snapshot 안에서 생산한다.
- 전체 사건 scope SHA와 claims/outbox/queues 테이블 존재 여부를 결속한다.
  테이블 부재와 빈 테이블을 구분한다. queue, FINAL_REVIEW 행, claim을 각각 기록한다.
- claim은 원래 기록의 `CASE_ONLY` 결속이며 검증된 사람 신원이 아니다.
  알림 `SENT`는 제공자 접수이며 사람이 읽거나 인수했다는 증거가 아니다.
- 원본 principal, endpoint, provider ID, payload, console link, 계정과 키는 export하지 않는다.
  제한된 시각·상태·횟수와 원본 행 digest만 보존한다.
- scoped facts·원장 counters·original revision·시각 불일치는 거절한다.
  공통 ROS-free 계약 validator를 exporter와 recording binder가 재사용한다.
  learning 계약은 production Fleet의 새 의존성이 아니다.
- 자료는 계속 `UNREVIEWED`다. 독립 품질, 사람 신원, 재발 없음, 정상 명령 0건,
  모델 기여와 물리 성공을 증명하지 않는다. 실제 호출과 발송을 수행하지 않는다.

### Verification

기존 `/1`, 선택 `/2`, 테이블 부재와 빈 기록, queue/SENT/claim의 분리,
scope·시각·counters·revision 위조 거절, 비식별 projection과 recording/failure binder를
원격 시험한다. 내용 hash는 자료의 진본성이나 독립 정답 승인을 대신하지 않는다.

**Related:** D-681, D-684, D-694.
