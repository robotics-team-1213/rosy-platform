## D-170 PRT-004 명령 추적 확장은 중앙 Fleet 착수와 함께 간다 — 그 전까지 correlation_id는 계약 전용 필드

**Status:** Accepted (2026-09-22).

**Context:** 통신·프로토콜 평가(2026-09-22 §5)가 확인한 드리프트: API Ref §7.5와
FLEET SRS FAT-03은 `correlation_id` 기반 3단계 추적(ACCEPTED→STARTED→COMPLETED|FAILED)을
계약하고, `Envelope.correlation_id` 필드도 `core_common.protocol.schemas`에 존재한다.
그러나 **어떤 런타임 경로도 이 필드를 설정하거나 소비하지 않는다** — 로봇의
`FleetAgent`(잠자는 구현체), SiteHub, `HttpRobotClient` 어디도 닿지 않는다. `AckPayload`도
문서 §9.5(`TIMEOUT`·`issued_by`·`ts_issued/ts_final`)보다 얇다. 계약만 앞서가는 코드
부재는 반대 방향 드리프트(구현은 있고 계약이 없음)만큼 위험하다 — 소비자은 문서를 읽고
추적을 기대한다.

**Decision:** PRT-004의 로봇 측 구현(ack 송신, `correlation_id` 설정·소비, `AckPayload`
확장)은 **중앙 Fleet 서버 착수(FLEET SRS Phase 4)와 같은 변경**에 담는다. 그 전까지
`correlation_id`는 계약 전용 필드로 남고, API Ref §7.5(v1.15)가 이 상태를 명시한다.
명령 추적은 현재 REST 요청/응답과 이벤트 `seq`로 대체된다.

**Alternatives:** 지금 로봇 측에 correlation_id 생성·ack 송신을 먼저 넣는 안 — 받아주는
중앙 서버가 없어 증명할 수 없고, 잘못된 형태로 먼저 굳으면 중앙 Fleet 착수 시 계약을 코드에
맞춰 고치는 역방향 정합이 생긴다. 계약 문서에서 correlation_id를 제거하는 안 — envelope은
안정 계약이고 제거는 breaking(API-002)이며, 중앙 Fleet 착수 시 반드시 필요한 필드다.

**Consequences:** `schemas.py`의 `correlation_id` 주석이 이 결정을 가리킨다. 중앙 Fleet
착수 시 이 ADR을 언급하며 확장을 같은 변경에 담는다(별도 합의 불필요). v1 시드(콘솔 폴링,
SiteHub)의 명령 경로는 이 결정으로 완전하다 — 부족한 것이 아니라 아직 올 때가 아닌 것이다.

**Validation:** `python -m pytest src/core/core/test/test_protocol_schemas.py
src/site/fleet/test/test_hub.py -q` · API Ref v1.15 §7.5 상태 표기.

**References:** D-5(outbound WS), D-10(early envelope 고정), D-18(스키마 단일 원천),
[communication-protocol remediation plan](../plans/2026-09-22-communication-protocol-remediation-plan.md) §G2,
`communication-protocol-report.md`(2026-09-22, 저장소 상위 폴더) §5.

---
