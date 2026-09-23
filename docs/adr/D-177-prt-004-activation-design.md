## D-177 correlation_id 3단계 추적과 AckPayload 확장은 중앙 Fleet 착수와 같은 변경에서 함께 구현한다 — 활성화 시의 설계를 선기록한다

**Status:** Proposed (2026-09-23). D-170이 정한 편입 조건(FLEET SRS Phase 4 중앙
Fleet 서버 착수)이 아직 없다. 이 ADR은 활성화 시의 설계를 선기록하여, 착수 시 별도
합의 없이 같은 변경에 담을 수 있게 한다. 조건 충족 시 Status를 `Accepted`로 바꾸고
착수 커밋을 증거로 남긴다 — 새 번호를 발급하지 않는다.

**Context:** API Ref §7.5/§9.5와 FLEET SRS FAT-03은 `correlation_id` 기반 3단계
추적(ACCEPTED→STARTED→COMPLETED|FAILED)과 `AckPayload`의 `TIMEOUT`·`issued_by`·
`ts_issued`/`ts_final`을 계약하지만, 어떤 런타임 경로도 이 필드를 설정·소비하지 않는다
(D-170 Context). D-170은 이를 "중앙 Fleet 착수와 같은 변경"까지 유예 판정했다. 유예가
길어지면 활성화 시마다 설계가 다시 갈리고 역방향 정합(계약을 코드에 맞춰 고치는 일)이
반복되므로, **무엇을/how 언제** 바꿀지를 지금 못박아 둔다. API Ref §10(v1.16)의
PRT-004 미구현 표기가 이 ADR을 가리킨다.

**Decision (활성화 시 적용):**

1. **발행 주체 고정** — `correlation_id`는 명령 발행자(중앙 Fleet)만 생성한다. 로봇은
   절대 발급하지 않는다 — 로봇의 역할은 수신 명령의 ID를 보존하여 ack에 되돌려주는
   **소비**뿐이다.
2. **로봇 측 경로** — `FleetAgent`(현재 잠자는 구현체)가 수신 명령의 `correlation_id`를
   보존하고 ack에 되돌려준다. SiteHub/`HttpRobotClient` 수신부도 같은 ID를 소비한다.
3. **상태기** — ACCEPTED → STARTED → COMPLETED|FAILED (API Ref §7.5, FLEET SRS
   FAT-03). 각 전이를 outbound WS envelope(`correlation_id` + `seq`, D-5/D-10)로 보낸다.
4. **AckPayload 확장** — §9.5의 `TIMEOUT`, `issued_by`, `ts_issued`/`ts_final`을 실측
   UTC ISO 8601로 채운다(chrony가 이미지 전제, CORE SRS §25).
5. **갱신 단위** — `core_common.protocol.schemas`(D-18 단일 원천) + API Ref
   §7.5/§9.5/§10 + fleet_agent 구현을 **한 변경**에서 함께 바꾸고, API Ref 버전은
   PRT-006에 따라 minor 상향한다 — 버전 고정 시험(`test_line_follow_contract_docs`,
   `test_protocol_version_alignment`)도 같은 변경에서 움직인다.
6. **호환** — 확장은 **additive only**: `correlation_id`가 없는 구 v1 클라이언트 요청은
   계속 유효하다(API-002 준수). 필드 제거·이름 변경은 이 ADR의 범위 밖 breaking이며
   새 ADR이 필요하다.

**Alternatives:** 지금 로봇 측에 먼저 넣는 안 — 받아주는 중앙 서버가 없어 증명 불가, D-170
기각 사유 그대로. 활성화 때 다시 설계하는 안 — 역방향 정합 반복, 유예의 비용이 사라지지
않는다. 지금 Status를 Accepted로 바꾸는 안 — 구현 증거가 없는 Accepted는 계약만 앞서가는
기존 드리프트(D-170 Context)를 ADR 층위에서 재현하는 것이므로 기각.

**Consequences:** Status가 Accepted가 되는 날까지 어떤 코드도 `correlation_id`를
설정하지 않는다 — D-170의 "계약 전용 필드" 상태가 유지된다. 활성화 시 §10 미구현
표기·`schemas.py` 주석·이 ADR의 Status를 같은 변경에서 갈아끼운다. v1 시드(콘솔 폴링,
SiteHub)의 명령 경로는 그때까지 D-170대로 완전하다.

**Validation:** 활성화 시 — `python -m pytest src/core/core/test/test_protocol_schemas.py
src/core/core/test/test_protocol_version_alignment.py src/site/fleet/test/test_hub.py -q` +
계약 시험 변이 증명(로봇이 correlation_id를 발급하는 형태를 주입하면 적색). 현 시점
(Proposed) — 본문이 D-170/API Ref §7.5·§9.5와 모순 없이 정합하는지만 확인한다.

**References:** D-170(부모 — 유예 판정), D-5(outbound WS), D-10(envelope 고정),
D-18(스키마 단일 원천), PRT-004/PRT-006(추적 계약/버전 규칙), FLEET SRS FAT-03,
API Ref §7.5·§9.5·§10(v1.16),
[communication-protocol remediation plan](../plans/2026-09-22-communication-protocol-remediation-plan.md) §G2,
`communication-protocol-report.md`(2026-09-22, 저장소 상위 폴더) §5.

---
