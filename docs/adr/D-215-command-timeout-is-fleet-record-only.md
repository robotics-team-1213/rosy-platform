## D-215 명령 추적 `TIMEOUT`은 Fleet 기록 전용 상태다 — 로봇 ack enum에 넣지 않는다

**Status:** Accepted (2026-09-25). API Ref §9.5에 Fleet-전용 주석 추가됨.

**Context:**

1. API Ref §9.5(`ROSY API & Protocol Reference.md:703-704`)는 명령 추적 레코드 상태로
   `ACCEPTED|STARTED|COMPLETED|FAILED|TIMEOUT` 5개를 적고, §7.5(`:504-513`)는 Fleet 타임아웃을 다룬다.
2. `schemas.py:70-74`의 `AckStatus`는 4개(`TIMEOUT` 없음)다. 로봇이 `TIMEOUT`을 보내거나 받는 경로는 없다.
3. D-170은 PRT-004 로봇 측 구현(ack 송신·`correlation_id`·`AckPayload` 확장)을 중앙 Fleet 착수와 같은 변경에 묶었다.

**Decision:**

1. `TIMEOUT`은 Fleet이 자기 추적 레코드에 적는 상태로만 둔다. Fleet은 REST 명령 후 ack 없이
   타임아웃(기본 10초)이 지나면 자기 레코드를 `TIMEOUT`으로 마감한다(PRT-004, `COMMAND_TIMEOUT`).
2. 로봇이 WS로 보내는 ack의 상태 집합은 4개(`ACCEPTED|STARTED|COMPLETED|FAILED`)로 유지하고,
   `AckStatus`에 `TIMEOUT`을 추가하지 않는다. 로봇은 타임아웃을 선언하는 쪽이 아니다.
3. API Ref §9.5에 한 줄을 추가한다: "`TIMEOUT`은 Fleet 측 레코드 전용이며 로봇 ack에는 나타나지 않는다."

**Alternatives:** 스키마에 `TIMEOUT`을 지금 추가하는 안 — 보내는 쪽도 받는 쪽도 없어 검증할 수 없고,
D-170이 미룬 PRT-004 확장과 같은 함정(계약만 앞서가기)에 빠진다. §9.5에서 `TIMEOUT`을 지우는 안 —
중앙 Fleet 착수 시 반드시 필요한 상태이므로 breaking 삭제가 된다.

**Consequences:** `schemas.py`는 그대로다. 중앙 Fleet 착수 시 PRT-004 확장과 함께 이 ADR을 언급한다.

**Validation:** 문서 결정이다. `python -m pytest src/core/core/test/test_protocol_schemas.py -q` 기존 통과 유지.
