## D-332 사람 확인은 고정 단계가 아니라 조건이다 — 사전 등록 승인, 예외 조정, 자율 재발의 승인에만 둔다

**Status:** Accepted (2026-09-29, 위치·의미 결정만). 밸브 개방·자동 실행·구현·UI 변경 없음.

## Context

D-326 Decision 3은 재판단 폐루프(`POLICY_DISPATCH_ENABLED`)를 열려는 별도 ADR의 전제 세 가지를 요구했다: (a) D-268의 처분, (b) Mission/Step 단일 원장, (c) **사람 확인 단계의 위치(제출 전·실행 전·결과 수용 전)**. (a)는 처분 기록([2026-09-29](../plans/2026-09-29-d268-policy-evidence-disposition.md))으로, (b)는 D-328/D-330의 실행기로 각각 진행 중이다. 이 ADR이 (c)를 고정한다.

세 후보(제출 전·실행 전·결과 수용 전 전수 확인)는 각각 이미 다른 결정과 충돌한다. 제출 전 전수 확인은 D-268 Decision 5의 사전 등록 기준(정답 데이터·허용 오류·표본 규모를 미리 등록)과 역할을 중복한다. 결과 수용 전 전수 확인은 D-328 Decision 4(사전 정의 predicate와 독립 증거로 목표 성공 판정)를 무의미하게 만든다. 어떤 단계에든 전수 확인을 두면 확인은 판단이 아니라 루틴이 되고, 사람은 습관적으로 승인하게 된다 — 안전의 겉모습만 만드는 실패 양상이다. D-326 증보본도 "모든 정상 성공에 일률적으로 요구하지 않는다"고 이미 좁혔다.

## Decision

1. **1차 사람 확인은 등록 시점이다.** `policy-admin` 권한이 사전에 승인하는 대상: 목표 predicate, 증거 출처와 자격, 작업 종류별 기준(신선도·허용 오류·오탐), 유효기간. 등록 안에서 운영 판정은 증거가 내리고, 등록 밖의 것은 다시 등록 절차로 돌아간다(D-268 Decision 5·6, D-276 역할).
2. **제출 전·실행 전·결과 수용 전 전수 확인을 두지 않는다.** 등록된 조건을 통과한 정책 발의의 수용은 증거 검증으로, 정상 성공의 판정은 사전 등록 predicate의 독립 증거로 각각 수행한다. 사람 클릭이 어느 쪽에도 필수 단계로 끼어들지 않는다.
3. **사람 확인이 개입하는 예외 조건은 넷뿐이다.** (i) 증거 불명·충돌 — `UNKNOWN`, 목표 증거 거절, 관측과 장치 readback 불일치의 조정. (ii) 등록 범위 밖 — 새 predicate·새 출처·기준 변경은 등록 절차로 회수. (iii) **자율 재발의** — 실패 뒤 정책이 스스로 재발의하는 호흡은 사람 승인이 기본값이며, 그 승인 권한의 개방은 D-326 Decision 3의 밸브 ADR이 별도로 다룬다. (iv) 안전 이벤트 — 정지 뒤 복구와 불명 상태의 장애 물체는 운영자 복구 전까지 HOLD(D-55, D-298).
4. **확인은 감사 가능한 이벤트여야 한다.** 확인 행위는 확인 주체(actor)·시각·대상·근거를 기존 감사 경로에 남기고, 권한은 나눈다 — 등록·변경·재발의 승인은 `policy-admin`, HOLD 해제 등 운영 조정은 `operator`. 뷰어는 확인할 수 없다(D-268 Decision 6).
5. **현행 코드는 그대로다.** 지금 사람 확인의 유일한 형태는 operator 수동 발의 경로와 HOLD 조정이며, 이 ADR은 그것을 바꾸지 않는다. 이 결정은 밸브 개방 ADR이 참조할 위치 정의일 뿐, `POLICY_DISPATCH_ENABLED`나 어떤 endpoint도 열지 않는다.

## Alternatives

- **제출 전 전수 확인(현재 HOLD의 일반화):** 가장 보수적이지만 사전 등록 기준과 역할이 겹치고, 자동화가 없으며, 확인이 루티화된다.
- **실행 전 전수 확인:** 수용은 자동·발행 직전 사람 클릭. 발행 지연과 시간 촉박 판단 오류를 만들고 확인 품질이 가장 빨리 무너진다.
- **결과 수용 전 전수 확인:** 실행은 자동·결과만 사람. 정상 케이스 대부분이 의미 없는 승인이 되어 독립 증거 판정과 이중이 된다.
- **채택(등록 승인 + 예외 조정 + 재발의 승인):** 사람 판단이 필요한 곳(범위 설계, 불일치 조정, 실패 뒤 재시도 허락)에만 사람을 둔다.

## Consequences

밸브 개방 ADR의 전제 (c)가 채워졌다. 그 ADR은 여전히 D-268의 승격 전제(측정 5종)와 Mission/Step 원장 확정을 함께 요구하며, 재발의 승인 권한의 개방 범위를 이 ADR의 조건 (iii) 안에서 정한다. 확인 UI·감사 필드·권한 endpoint의 구현은 별도 실행 계획이고, D-18 사이클을 따른다. 이 ADR은 문서 결정만 바꾼다.

**Related:** [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-268](D-268-policy-eligible-vision-evidence-for-fleet-tasks.md), [D-276](D-276-site-fleet-per-principal-api-authorization.md), [D-290](D-290-rosy-platform-naming-and-site-intent-boundaries.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-326](D-326-agent-loop-boundary.md), [D-328](D-328-model-proposed-missions-and-independent-goal-evidence.md).

---
