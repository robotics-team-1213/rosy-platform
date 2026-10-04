# 중앙 Fleet 1단계 설계 — §10.1 로봇·페어링 레지스트리 뷰 (D-454 결정 2)

**Status:** 설계 rev 1 (2026-10-04). 실행 계획은 `2026-10-04-central-fleet-step1.md`.

**목적:** API Ref §10.1의 9개 경로 중 이 단계가 여는 것 — 중앙 프로파일 마운트와 읽기 2경로(`GET /api/v1/fleet/robots`, `GET /api/v1/fleet/robots/{id}`). 나머지 7경로(변경·해제·페어링 토큰·승인 대기·폐기)는 실행 계획의 뒤 작업이 같은 모듈에 더해진다.

## 1. 프로파일

- 시드 앱(`operations/fleet/fleet/server/app.py`)은 그대로다. `fleet console --central`(cli 플래그)이 같은 FastAPI 앱에 `/api/v1/fleet/*` 라우터를 마운트한다. 사이트 프로파일(:8090)은 오늘과 동일하게 `/api/fleet/*`만 담는다.
- `/api/v1`은 CORE 외부 API의 버전 관례(PRT-006)와 같은 이름공간이다 — 중앙 Fleet은 로봇 계약과 같은 버전 문화로 말한다.
- 인증은 시드의 `site_auth` 가드를 그대로 쓴다: 읽기=Viewer 이상, 변경=Admin(SEC-201~203 대응).

## 2. 읽기 모델 — `CentralRegistry`

한 곳에서 세 출처를 합친다(새 저장소 없음, 전부 기존 객체):

| 출처 | 기존 객체 | 제공 것 |
|---|---|---|
| 정적+등록 로스터 | `SiteRoster`(roster.py) | robot_id 목록, source(`static`/`enrolled`) |
| hub 온라인 | `console.hub.registry`(D-447a) | online 여부, 마지막 `StateSnapshot` |
| 주소 관측 | `discovery.rows()` | 최근 주소(표시 전용) |

행 모양(REG-002 "상태·Capability 포함"):

```json
{"robot_id": "rosy_01", "source": "enrolled", "online": true,
 "state": {…StateSnapshot…} | null,
 "capabilities": [...] | null,
 "address_last_seen": "10.0.0.7" | null}
```

- `state`는 hub 스냅샷이 있으면 그 값(증거 필드 그대로, D-309), 없으면 `null` — Fleet이 다시 계산하지 않는다.
- `capabilities`는 스냅샷 안 `capabilities` 키에서 읽는다(없으면 null).
- 목록은 `robot_id` 오름차순. 정렬·페이지는 이 단계에 없다(요구에 없다).

## 3. 경로

- `GET /api/v1/fleet/robots` → `{"robots": [행…]}`
- `GET /api/v1/fleet/robots/{id}` → 행 하나, 미등록 id는 404(`{"code": "UNKNOWN_ROBOT"}`)
- 오류 문화는 시드 `http_errors`와 같다.

## 4. 범위 밖(뒤 작업이 소유)

- `PATCH …/{id}`(이름·그룹, REG-003) — 그룹 개념은 등록 저장소에 아직 없다: 뒤 작업에서 스키마 확장.
- `POST /pairing-tokens`(1회용 발급, SEC-201) — D-341 승인 흐름과의 관계(발급↔승인 한 몸)를 뒤 작업 설계가 정리한다.
- pending-robots/approve(SEC-202) — D-361 등록 게이트와 잇는다.

## 5. 검증

- ROS 없는 fleet 시험(fakes): 정적+등록+hub-offline 섞인 로스터의 목록/상세/404/권한(Viewer 읽기 가능, 미인증 401).
- 계약: 경로·응답 뼈대를 시험이 고정한다(D-18 — 문서는 §10.1 표가 이미 정본).
