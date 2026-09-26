## D-288 사이트 Fleet API는 의도를 받고 서버 규약으로 해석한다

**Status:** Accepted (2026-09-26). API와 메시지 경계의 소스 계약이다. Ubuntu 현장 배포, 장비 동작 또는 자동 작업을 승인하지 않는다.

잇는 결정: D-18, D-59, D-170, D-177, D-257, D-267, D-268, D-269, D-271, D-276.

**Context:** 사용자는 웹/API에서 “어떤 로봇이 어떤 목표를 수행할지”를 요청하고, 관제 서버가 인증·입력·장비 상태·증거·우선순위를 계산해 적절한 장비 계약으로 전달해야 한다. 현재 구현에는 Site Fleet REST, 천장 카메라 WSS와 sighting REST, CORE Agent PRT WebSocket, 로봇별 CORE REST가 함께 존재한다. 이 계약을 한 종류의 메시지 봉투나 DDS 경로로 합치면 인증 범위, 데이터 크기, 완료 의미와 재전달 안전성이 뒤섞인다.

**Decision:**

1. **외부 제어 API는 의도(intent)를 받는다.** 브라우저와 사용자 API는 승인된 domain action, target, 목표·제약, idempotency key만 제출한다. goal 좌표는 유한한 숫자여야 하고, 선언되지 않은 입력 필드는 거절한다. principal은 인증에서, task `source`와 source identity는 인증된 API 경로/credential에서, 우선순위·작업 ID·시도 번호·실행 상태는 Fleet에서 결정한다. 클라이언트가 `priority_class`, worker, task `source`, DDS topic, `cmd_vel`, 원본 영상 또는 실행 완료 상태를 정하도록 허용하지 않는다.
2. **Fleet은 인터프리터이자 작업 원장이다.** 권한·스키마·대상 장비·좌표/map·현재 상태·필요한 증거를 검증하고 감사 시작 기록과 durable task를 남긴 뒤, 서버 정책으로 실행 가능성과 우선순위를 계산한다. Fleet은 작업 의도를 CORE의 기존 HTTPS REST 계약으로 변환한다. DDS와 최종 안전·속도·장치 동작은 CORE/장치 안에 둔다(D-12, D-59, D-269).
3. **전송 계약은 목적별로 유지한다.** Site console API는 HTTPS `/api/fleet/*`와 D-276의 개인별 Bearer 역할을 사용한다. 천장 카메라는 `rosy-overhead/1` WSS로 최신 JPEG만 전송하고, Vision은 `SiteSightingPayload` 파생 좌표를 source 인증 REST로 보낸다(D-257). CORE Agent는 기존 PRT WebSocket `Envelope`를 사용한다. 이 경로들은 서로 다른 credential·schema·권한을 가지며, Fleet/browser는 DDS participant가 되지 않는다. Site task status나 camera field를 PRT envelope에 끼워 넣지 않고 `protocol_version`은 `1.0`으로 유지한다.
4. **접수·수락·완료는 다른 사실이다.** idempotency 범위는 `(source, actor_id, request_key)`다. 같은 key와 같은 입력은 기존 task를 돌려주고 재발행하지 않는다. 다른 입력에 key를 재사용하면 `409 IDEMPOTENCY_CONFLICT`다. `QUEUED`는 Fleet 원장에 저장되어 아직 발행 전임을, `ACCEPTED`는 CORE의 명시적 receipt만을 뜻한다. `RUNNING`/`COMPLETED`는 상관관계가 검증된 CORE 실행/최종 결과 증거가 있어야 한다. 발행 후 결과가 모호하면 `UNKNOWN`으로 보존하고 자동 재시도하지 않는다(D-170, D-177, D-271).
5. **DB가 상태의 원장이고 브로커는 선택적 전달 계층이다.** 현재 SQLite task/history가 권위 있는 기록이다. 우선순위는 서버가 계산하며 운영자 요청이 승인된 policy·background 작업보다 앞선다. RabbitMQ는 독립 worker/backlog 필요가 실측되고 별도 ADR·운영 검증을 통과할 때만 추가한다. 이후에도 메시지는 task 식별자/시도/기한 같은 최소 참조만 전달하고 worker는 원장에서 최신 상태를 확인한다. durable 인수 전 ACK, outbox 또는 동등한 복구 절차, 중복 수신 안전성을 요구한다. 비디오 원본·DDS 스트림·비밀·물리 명령 내용을 일반 작업 큐에 넣지 않는다.
6. **자동 source는 같은 검증 경로를 사용하되 별도로 승인한다.** operator와 policy가 task service/상태 원장을 공유해도 policy source는 D-268 증거 계약·freshness·false-trigger 기준과 SITE/DEVICE/FIELD 수용 전까지 `HOLD`다. sighting은 지도 표시/대조 자료이며 단독으로 이동·집기 작업을 만들지 않는다. arm/Pinky 카메라와 manipulation은 별도 장비 계약을 통과해야 한다.
7. **계약 변경은 함께 버전 관리한다.** 외부 API path/body/response/status, 인증 권한, message field 또는 retry/ACK 의미를 바꿀 때는 이 ADR 및 해당 결정의 갱신 여부를 확인하고, `ROSY API & Protocol Reference.md`, 실제 typed schema/OpenAPI, 구현, contract tests를 같은 변경으로 맞춘다(D-18). 새 async consumer/broker 계약은 schema version, identity/correlation, expiry, duplicate/replay, ACK ownership, authorization와 recovery를 명시하기 전 구현하지 않는다. 문서 예시만으로 구현 계약을 확장하지 않는다.

**Consequences:** API Reference §10.6–10.9가 사이트 브라우저, camera-derived sighting, CORE event audit, task API의 외부 계약을 구분한다. `SiteSightingPayload`와 `FleetTaskStatus`는 기존 공유 타입을 유지하며, 이 ADR은 새 endpoint·public message field·RabbitMQ 의존성을 추가하지 않는다. API receipt는 물리 작업 성공 증거가 아니다.

**Alternatives:** 모든 장비를 DDS로 연결하는 방식은 CORE 단일 gateway·장치 인증 경계를 깨므로 기각한다. 모든 데이터를 하나의 WebSocket envelope로 합치는 방식은 영상과 명령의 권한·크기·수명 의미를 혼합하므로 기각한다. API 요청에 priority/dispatch 상태를 받는 방식은 클라이언트가 스케줄러 정책을 우회할 수 있어 기각한다.

**Validation / Transition:** `src/site/fleet/test/test_task_contract_docs.py`가 ADR·API Reference·`GoalRequest`·`SiteSightingPayload`·`FleetTaskStatus`·PRT version의 정렬을 검사한다. 이는 SOURCE/LOCAL contract evidence다. 실제 CORE ACK/final-result correlation(D-177), Ubuntu TLS/credentials, physical camera/robot, freshness와 false-trigger 수용은 별도 gate다. D-268 자동 작업은 계속 HOLD다.
