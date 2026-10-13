## D-523 AI PC 질의는 정체 사실 또는 허용 후보만 반환한다

**Status:** Accepted (2026-10-08, 사용자 계획 승인). 내부 파서 규약이다. 현장 연결, Laya 상시 기동, Qwen 설치, 공개 REST, D-492 Accepted, D-503 9항 충족을 승인하지 않는다.

### Context

[D-516](D-516-offline-decision-model-replay-boundary.md)은 모델 PC, AI PC, 현장 Fleet, CORE의 권한을 나눴다. [설계](../plans/2026-10-08-decision-model-pipeline-design.md)는 현장 질의의 wire를 구현 계약으로 미뤘다. [D-503](D-503-autonomy-chain-facts-and-exception-queue.md) 대안 B는 일반 World State 계약을 데이터 없이 만들지 않기로 했다. 막힘 답은 [D-438](D-438-fleet-stuck-resolver-rules-model-human.md) 규칙과 사람이 고르고, 정체 모델은 [D-492](D-492-d438-vision-tier-local-qwen-ai-pc-gated.md)가 Proposed인 동안 호출하지 않는다. 동료 로봇의 교차로는 `fleet.meet`가 로봇마다 주문 하나를 낸다.

AI PC 디스크에는 Laya 0.4.0 다국어 체크포인트가 있으나 `rosy-decision-laya.service`는 꺼져 있다. 그 가중치는 승인된 `ModelProfile`이 아니다.

### Decision

1. **작업은 둘이다.** 정체 작업과 후보 작업의 입력, 출력, 프로파일, 점수를 섞지 않는다. 일반 관측 버스는 만들지 않는다. 코드 자리는 `operations/fleet/fleet/ai/decision_pipeline.py`다. `operations/decision`으로의 이동은 [D-429](D-429-five-concerns-control-port-and-site-devices.md)의 별도 carve다.
2. **정체 작업은 `obstacle_ahead`만 받는다.** 앞 거리, 막힘이 열린 시각, 프레임 촬영 시각, 승인된 프로파일 ID가 맞을 때만 `{thing, confidence}`를 읽는다. `thing`은 `wall`·`object`·`robot`·`person`·`unknown`이다. 그 외 키, 명령 단어, 프로파일 불일치, 촬영 시각 없음, 막힘 이전 프레임, 나이 8초 초과, 신뢰도 0.7 미만, 빈 응답은 `state=UNKNOWN`이다. `lane_lost`로 이 파서를 호출하면 오류다. 낮은 신뢰도나 모델이 말한 `unknown`은 이름을 남기지 않는다. 이 파서는 `WAIT`·`YIELD`·`RESUME`·`ABORT`·`MANUAL`을 만들지 않는다. 규칙표는 D-492가 허용되기 전에는 이 사실을 막힘 답에 넣지 않는다.
3. **후보 작업은 Fleet가 적어 준 허용 목록 안에서만 고른다.** 목록은 설명이 있는 문자열 2개 이상이고 명령 단어를 키로 두지 않는다. 응답에서 읽는 값은 `answers.decision.choice` 하나다. 목록 안이고, 프로파일과 사건 세대가 같고, 경과가 timeout 안이면 그 문자열만 후보로 남긴다. 아니면 기권(`choice` 없음)이다. 기권은 실행 후보가 아니다. [D-392](D-392-provider-neutral-model-tool-contract.md)의 admission과 자동 policy dispatch 꺼짐을 유지한다. 막힘 R4로 이 경로를 우회하지 않는다.
4. **파서는 네트워크와 원장을 열지 않는다.** 공개 REST, systemd enable, AI PC 소켓, SQLite 열, 콘솔 문구, CORE, `stuck_resolver.Answer` 연결은 이 결정에 없다. 그림자 기록은 D-503 7항 에피소드와 9항 트리거를 확인한 다음 계획이다.
5. **없는 모델은 없는 응답이다.** AI PC 부재, 시간 초과, 프로파일 불일치는 정체 `UNKNOWN` 또는 후보 기권이다. 그 뒤는 기존 규칙과 사람 경로다.

### Consequences

- Fleet 코드는 모델 문장을 막힘 답이나 meet 주문으로 바로 쓸 수 없다. 검사기를 통과한 값만 이후 규칙의 입력이 될 수 있고, 그 연결은 아직 없다.
- D-492와 D-503은 Proposed로 남는다. Laya revision `7b928d828b7b0e022f929d9bd2e44165aa270148`는 오프라인 후보 가중치이며 이 결정으로 현장 프로파일이 되지 않는다.
- 전송, 인증, `ModelProfile` wire는 활성화 전에 기존 API reference의 별도 변경으로 정한다. 주소와 비밀은 `private/`에만 둔다.

### Verification

- `operations/fleet/test/test_decision_pipeline.py`가 정체 다섯 값, 낮은 신뢰도, 여분 필드, 오래된 프레임, `lane_lost` 거절, 허용 목록 안팎, 명령 단어, 기권이 막힘 답 타입이 아님을 확인한다.
- 호스트 시험은 장치, 현장 그림자, V0/V1을 대신하지 않는다.

**Related:** [D-392](D-392-provider-neutral-model-tool-contract.md), [D-429](D-429-five-concerns-control-port-and-site-devices.md), [D-438](D-438-fleet-stuck-resolver-rules-model-human.md), [D-492](D-492-d438-vision-tier-local-qwen-ai-pc-gated.md), [D-503](D-503-autonomy-chain-facts-and-exception-queue.md), [D-516](D-516-offline-decision-model-replay-boundary.md), [질의 규약](../plans/2026-10-08-ai-pc-ask-contract.md).
