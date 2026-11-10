## D-999 카메라 연결 승인은 사용 중인 자리를 명시적으로 교체할 수 있고 옛 자격은 새 폰이 확인할 때 같이 폐기한다

**Status:** Accepted (2026-11-09, 사용자 요청). [D-341](D-341-overhead-console-approved-pairing.md) 6항의 "폰 교체는 먼저 회수, 그 다음 새 승인이다"만 바꾼다. 나머지(이름 있는 운영자, 6자리 코드, 120 s 확인 기한, digest만 저장)는 그대로다.

### Context

2026-11-09 같은 폰(SM-G991N)이 저장한 자격을 잃고 다시 요청했다. 운영자는 `ceiling_north`의 옛 자격을 먼저 폐기해야만 승인할 수 있었다. 폐기하면 새 연결이 끝나기 전까지 그 자리에 카메라가 없고, 새 연결이 실패하면 그대로 비어 있다.

### Decision

| 항목 | 결정 |
|---|---|
| 승인 본문 | `replace_credential_id`(선택)를 더한다. 사용 중인 자리로 승인하려면 이 값이 그 자리의 활성 자격 ID와 같아야 한다. 화면이 낡았을 때 엉뚱한 자격을 바꾸지 못한다. |
| 거절 | 값이 없으면 `409 SOURCE_HAS_CREDENTIAL`(점유 자격 ID를 알려 준다). 값이 현재 점유자와 다르거나 이미 폐기·만료됐으면 `409 REPLACE_TARGET_CHANGED`. 다른 승인이 폰 확인을 기다리는 자리는 `409 SOURCE_PENDING_CONFIRM`. D-456 기억 연결이 가진 자리와 peer 자격은 교체하지 않는다. |
| 옛 자격 | 새 폰이 confirm할 때까지 활성이다. 승인 뒤 확인이 없으면(120 s) 새 자격만 회수되고 옛 자격은 남는다. |
| confirm | 새 자격 활성화와 옛 자격 폐기(`revoke_reason=replaced`)는 한 SQLite 트랜잭션이다. 감사에 `confirm`과 `replace`(대상=옛 자격) 행을 남긴다. 그 사이 옛 자격이 이미 폐기됐으면 그 기록(이유·주체)을 덮지 않는다. |
| 목록 | `GET /pending`의 `paired_sources[]`에 `credential_id`·`device_label`·`replaceable`을 더한다(기존 `has_credential` 유지). 콘솔은 빈 자리를 먼저, 그 뒤에 "교체 · 자리 — 기기 이름 (자격 ID)" 항목을 보인다. 자리는 여러 개일 수 있다. |
| 로그인 복귀 | 설치 화면의 카메라 구역 anchor(`#camera-link` 등)를 복귀 허용 목록(JS `login-return.js`, Python `account_receiver.py`)에 더한다. 허용 목록 밖 경로·fragment는 그대로 `/console`로 떨어진다. |

### Consequences

- 이 경로는 API 참조(`ROSY API & Protocol Reference`)에 실리지 않은 Fleet 내부 pairing v1 경로라 API 버전을 올리지 않는다.
- D-456 수신 화면(v2 `decision`)에는 교체가 없다. 거기서 자리가 찬 경우는 위 카메라 승인 구역의 교체나 기억 연결 해제를 쓴다(후속).
