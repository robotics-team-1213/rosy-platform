# ROSY Monitoring API v1

설계 기준: [D-876](../adr/D-876-rosy-monitoring-independent-site-and-aggregate.md).
독립 `rosy-monitoring` 서비스의 계약이다. CORE/Fleet API 버전과 별도로 관리한다.
구현과 검증 상태는 [Monitoring 진행 기록](../../operations/monitoring/progress.md)을 확인한다.

## 조회와 권한

| 요청 | 응답 |
|---|---|
| `GET /health` | 프로세스 조회 가능 여부. 장치·원천 정상이나 현장 수용을 뜻하지 않는다. |
| `GET /api/monitoring/v1/snapshot` | 허용된 사이트의 `MonitoringSnapshot` v1 |
| `GET /api/monitoring/v1/sites/{site_id}/events?after=0&limit=100` | 해당 사이트의 상태 변경 이력. limit 1–200, 사이트별 단조 증가 sequence |

비공개 조회는 등록된 reader의 `Authorization: Bearer …`가 필요하다.
snapshot의 반복 `site_id` query는 reader 범위의 부분집합만 허용한다.
미지정이면 reader의 등록 범위 전체다. 권한 밖 사이트는 403이며 부분 성공하지 않는다.
모든 응답은 `Cache-Control: no-store`다. 401은 인증 실패, 403은 범위 밖,
400은 잘못된 query, 503은 보존 상태를 안전하게 조회할 수 없을 때다.
오류 응답은 `{"error":{"code":"MONITORING_…"}}` 형태의 고정 코드만 내보낸다.
요청 값·URL·토큰·원천 본문·예외 문자열을 반사하지 않는다. 쓰기·복구 API는 없다.

## 관측과 시각

스키마 정본은 `operations/monitoring/src/rosy/monitoring/models.py`다.
사이트·원천·수집기·표본 식별자, timezone-aware 원천 시각과 원천 나이,
원천 유효 시간과 보고 경로 유효 시간을 구분한다. 보고 경로는 최대 15초다.
host-guard 원천은 900초, host-state 원천은 2100초이며 그 외 원천은 15초다.
`reported_health`는 소유자 판정이다. `freshness=stale`인 OK는 과거 판정이다.
링크는 방향·등록 기대 여부·관측 결과·transport·확인된 실패 단계·응답 시간과
최근 성공 시각을 표현한다. `reported` 링크와 수집기의 `probe`는 별도 근거다.
`reported.reachable=true`는 응답 도달의 근거이며 인증 성공을 보장하지 않는다.
Fleet의 기존 `tls-refused`는 HTTP 401/`PAIRING_REQUIRED`이므로 `auth` 단계로 전달한다.
실제 TLS handshake 실패는 수집 probe의 `tls`다. `last_success_at`은 성공적인 읽기 시각이며
인증 거절로 갱신하지 않는다. 수집 작업이 종료되면 health/snapshot은 503을 반환한다.
이는 논리적인 관측 경로이며 물리 LAN 연결이나 PC 개수의 증명이 아니다.

peer는 등록된 ID와 사이트 전체가 일치해야 한다. generation/sequence와 원천 시각의
중복·역순·재전송을 검사하고 요청 시간 및 1초 시각 허용량을 수명에서 차감한다.
동일 capture의 건강 판정과 원천 만료 시각을 새 표본 이름으로 바꿀 수 없다.
수신 프로세스 재시작 시 저장된 보고 경로는 모두 stale로 복구한다. 원천 나이는
경과 시간만큼 증가하며 남은 수명은 늘지 않는다. 시각 역행·손상된 저장소는
정상 상태로 초기화하지 않고 조회/수집을 제한한다.

## 제한과 수집

등록 원천 최대 128개, 동시 요청 8개, 전체 원천 요청 제한 3초, 순회 간격 5초다.
겹친 순회나 실패 즉시 재시도는 없다. GET은 캐시를 읽으며 원천을 호출하지 않는다.
응답/원천 JSON은 1 MiB(원천 UTF-8·최대64단계), snapshot은 2048 nodes/4096 links,
기억 anchor는 8192개다. 저장소의 이전 등록까지 합해 최대64사이트의 이력 cursor를 유지한다.
동일 저장소는 단일 writer lease를 획득한 프로세스만 쓴다. 다른 writer의 실행은 거부한다.
상태 변경은 사이트별 최대 4096건/7일 보존한다. age/sequence만 변한 polling은
새 상태 변경을 만들지 않는다. 저장은 정규화 관측·역순 방지 metadata와 변경 이력에
한정한다. 원본 응답·업무 원장·시계열 DB를 복제하지 않는다.

CORE는 viewer `GET /api/v1/system/info`와 `/api/v1/diagnostics`, Fleet은
수동 캐시 `GET /api/fleet/monitoring`, 호스트는 기존 status.json을 읽는다.
CORE 명령·Fleet 운영 gather·host-guard 복구 루프를 호출하거나 복제하지 않는다.
HTTPS 인증서를 검증하며 loopback HTTP만 예외로 허용한다. redirect와 환경 proxy는
따르지 않는다. reader 자격과 원천별 upstream 자격은 별도로 등록한다.
