## D-326 자율 판단 루프는 네 역할로 분리 배치하고 재판단 밸브는 별도 승격으로만 연다

**Status:** Accepted (2026-09-29, 경계·자리 결정만). 구현·폐루프 개방·AI 승격은 별도 HOLD.

## Context

외부 회의 노트가 하나의 상자로 그리는 자율 루프 개념(사용자 목표 → 상위 판단 에이전트의 장면 이해·작업 분해·로봇/Skill 선택·진행 상태 판단 → Robot Skill 또는 VLA → Controller/Robot → 센서·실행 결과 → 상위 판단 에이전트가 다시 판단)을 현행 소스와 대조했다([갭맵 2026-09-29](../plans/2026-09-29-er2-agent-loop-gap-map.md)). 결과: 아래 절반은 실재한다 — CORE가 유일 게이트웨이이고 Command Manager가 유일 `cmd_vel` 퍼블리셔(D-2)이며, 학습된 정책조차 Policy 플러그인으로서 `cmd_vel`을 내지 않는다(D-99). 위 절반은 FLEET SRS §14 AIV-001(`LLM/VLA → Mission Planner → Fleet API → Rosy API → Nav2`)이 이미 예약했으나 구현은 0%다 — Fleet 작업은 `navigate` 단일 종류이고 Mission/Step 원장이 없다. 재판단 마디는 `task_service`의 `POLICY_DISPATCH_ENABLED = False`가 정책 발의 작업을 즉시 `HOLD(POLICY_NOT_ACCEPTED)`로 내리는, 코드화된 의도적 밸브다.

위험은 그림의 모양 자체다. 하나의 상자가 루프를 직접 닫는 그림을 소스에 옮기면 판단 주체를 CORE 옆, ROS 토픽, `cmd_vel` 게이트 근처에 두는 변형이 된다. 11_AI 문서(AI 출력은 후보/관측이며 검증·안전 경계 통과 전 물리 동작을 만들지 않는다), 비전 가속기 설계(검출→`cmd_vel` 지름길 High 거부), D-209(VLA는 `backend_learned`, 로봇 이미지 밖), D-71(concept 10–12는 v1 미들웨어가 아님)이 전부 거부해 온 경로다.

## Decision

1. 개념의 네 인지 역할의 자리를 기존 예약 지점에 고정한다. **장면 이해 = 증거 생산자**(장치 탑재 perception과 사이트 관측; 정책이 쓸 수 있는 증거의 자격은 [D-268](D-268-policy-eligible-vision-evidence-for-fleet-tasks.md)의 수용 상태를 따른다). **작업 분해 = Fleet 측 Mission Planner**(AIV-001, MSN-001 DSL). **로봇·Skill 선택 = Fleet 작업 스케줄러**(사람 발의 우선순위 유지). **진행 판단·재판단 = 작업 결과 원장과 사람 확인**. 사전에 승인된 목표 predicate의 증거 기반 성공 판정은 Fleet이 수행할 수 있다(D-328). 사람 확인은 불명·충돌 증거의 조정과 향후 자율 재발의의 승인 위치에 필요하며 모든 정상 성공에 일률적으로 요구한다는 뜻은 아니다.
2. 상위 판단 에이전트(외부 명칭 "ER2")는 **실행권 없는 후보 제출·관측 요청·상태 조회를 위한 Fleet API의 소비자로만** 존재한다(AIV-002 function calling). 모델 credential로 Fleet의 기존 즉시 실행 API, Device Action API, CORE, ROS 토픽 또는 driver를 직접 호출하지 않는다. 모델에 물리 tool을 보이게 할 미래 설계도 Fleet이 인증·수락·원장 기록 후 장치에 발행하는 중개 경로와 별도 승격 결정을 필요로 한다. CORE 내부나 `cmd_vel` 게이트에는 에이전트 자리를 만들지 않는다. VLA는 `backend_learned`(D-209)에서 평가를 거친 고정 모델 산출물로만 운영 추론에 들어오고, 그 출력도 제안/관측으로 시작한다.
3. 재판단 폐루프(정책 발의가 결과를 보고 스스로 재발의하는 호흡)는 닫힌 채 유지한다. `POLICY_DISPATCH_ENABLED`(또는 그 후속 계약)를 여는 것은 **별도 ADR**이며, 그 ADR은 최소한 (a) D-268의 처분, (b) Mission/Step 단일 원장, (c) 사람 확인 단계의 위치(제출 전·실행 전·결과 수용 전)를 먼저 정한다.
4. "ER2"는 프로젝트 공통 어휘로 채택하지 않는다. 회의·비교 문서와 특정 공급자 adapter의 파일명에는 외부 제품 식별자로 표기할 수 있다. 공유 구현·계약은 역할 이름(증거 생산, 미션 계획, 스케줄링, 재판단)을 사용하고 벤더 이름을 공통 Action/Mission 필드나 capability로 승격하지 않는다.

## Consequences and rollout

개념 그림을 소스에 옮기는 구현에서 네 역할의 배치가 이 결정과 어긋나면, 이 ADR이 거부 근거가 된다. 남은 간극은 [갭맵](../plans/2026-09-29-er2-agent-loop-gap-map.md)의 다섯 항목(D-268 처분, Mission/Step 원장, 역량 기반 매칭, 밸브 개방 ADR, VLA 파이프라인)으로 추적하며, 각 항목은 자체 ADR·설계 문서로만 진다. 지금 새로 만드는 구현은 없다 — 이 ADR은 자리와 개방 조건의 기록이다.

**Related:** [D-2](D-2-cmd-vel.md), [D-71](D-71-concept-05-09-12-15-apt-v1.md), [D-99](D-99-policy-cmd-vel.md), [D-209](D-209-perception-folder-and-learned-backend.md), [D-268](D-268-policy-eligible-vision-evidence-for-fleet-tasks.md), [D-290](D-290-rosy-platform-naming-and-site-intent-boundaries.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-308](D-308-intent-and-device-action-interpretation-boundary.md).

---
