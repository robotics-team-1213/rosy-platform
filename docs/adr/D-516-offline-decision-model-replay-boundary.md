## D-516 AI PC의 Decision 후보는 동일한 오프라인 사건으로 비교하고, VLM 관측과 실행 권한을 분리한다

**Status:** Accepted (2026-10-08, 사용자 결정: 모델 PC는 학습·평가, AI PC는 추론만, Fleet이 판단·승인, CORE가 실행 전 재검사). 이 구조 결정은 현장 그림자·실시간 활성화나 로봇 동작 승인이 아니다. AI PC의 오프라인 Laya CPU 연결 시험은 정확도 수용과 별개다.

### Context

Jev, Laya, Kev는 `POST /v1/systemone`의 typed choice를 공통으로 제공한다. 영상 모델은 같은 입력을 받지 않는다. D-492의 Qwen3-VL은 LiDAR가 이미 감지한 장애물의 `wall/object/robot/person/unknown` **정체 사실**을 만들고, Fleet 규칙이 막힘 답을 고른다. D-427·D-429의 `operations/decision`은 숙고형 Mission·Task 후보의 목적지다. 현재 그 디렉터리는 실사용 모듈이 아니고 Fleet 막힘 판단기의 rule/human 경로만 있다. 사람 정답이 붙은 사건도 부족하다.

### Decision

1. **호스트와 권한을 나눈다.** D-434의 모델 PC는 데이터셋·학습·독립 평가·승격 증거와 모델 산출물 관리를 맡는다. AI PC는 승인된 고정 모델 버전의 추론만 수행하고, 제한된 관측 사실 또는 숙고형 후보를 반환한다. AI PC에는 Fleet 원장 쓰기, Mission admission, 장치 Action, 취소·정지·재무장, ROS·`cmd_vel` 권한을 주지 않는다. 관제 PC의 Fleet이 후보를 검증하고 규칙·admission·사람 확인을 적용하며, CORE가 실행 직전 장치 상태를 다시 확인한다(D-392·D-427·D-429·D-492). 폴더 이름은 실행 호스트를 정하지 않는다(D-315); 배포에서 이 호스트 배치를 명시한다.
2. **모델 PC → AI PC 전달은 고정된 승격 산출물이다.** learning의 평가·registry가 L0 재생 결과와 함께 모델 digest/revision, 모델·토크나이저·서버 버전, 작업별 입력·출력 계약, 프롬프트/질문 버전, 평가 세트 hash, 지연·실패 결과, timeout·fallback을 묶은 `ModelProfile` 후보를 만든다(D-427 §4). 정확한 wire/schema는 별도 계약 변경으로 정한다. AI PC는 허용된 프로파일만 적재하고, Fleet은 같은 프로파일 ID를 참조한다. 실행 중 가중치·질문을 조용히 바꾸지 않고 이전 승인 프로파일로 되돌릴 수 있게 보존한다. AI PC가 학습하거나 자체 판단 기준을 승인하지 않는다.
3. **첫 시험은 AI PC의 오프라인 재생이다.** 저장된 사건에서 개인·비밀 정보를 제거한 제한된 상태를 입력한다. 모델은 로봇·Fleet API에 접근하지 않는다. Jev 호환 서버는 `127.0.0.1`에만 묶고 `tools/decision_replay.py`도 loopback HTTP만 받는다. Laya 다국어를 첫 후보, Kev 0.8B를 비교군으로 삼되, 실제 승자는 독립 사람 정답으로 정한다. 장치의 다른 GPU 작업과 충돌하면 시험을 중단한다. 2026-10-08 Laya CPU 시험은 합성 2건의 호출 확인이며 독립 정답 평가가 아니다.
4. **교체 단위는 모델 이름이 아니라 문제 계약이다.** 한 재생 행은 사건 `id`, 제한된 `state`, 질문 `instructions`, 설명이 붙은 허용 후보 `criteria`, 사람 또는 권한 있는 검토자의 `expected`를 담는다. 도구는 이 행을 하나의 `choice` 질문으로 보내고 `id`·정답·예측·지연·오류만 결과로 남긴다. 원래 상태를 결과에 복사하지 않는다. 동일 세트·후보·질문 문구를 고정하고 모델 ID·정확한 revision/digest·세트 hash·시험 호스트·GPU 사용량을 별도 실행 기록에 남긴다. confidence는 측정 정확도가 아니므로 그것만으로 자동 채택하지 않는다.
5. **VLM은 별도 관측 계약이다.** 같은 AI PC를 써도 영상과 LiDAR의 원시 입력을 Jev/Laya/Kev의 텍스트 choice에 섞지 않는다. D-492의 막힘 정체 VLM은 Fleet 판단기 옆에서 `wall/object/robot/person/unknown` 사실만 내며, D-429의 `operations/decision`에 들어가는 숙고형 Mission·Task 제안 모델과 다르다. 두 작업 모두 AI PC 추론 결과에 실행 권한은 없다. 정체 사실에는 프레임 시각·출처·나이를 붙이고, 누락·낡음·형식 오류는 `unknown`으로 처리한다. 공급자를 바꾸면 해당 작업의 독립 평가 관문을 다시 통과한다.
6. **Fleet·CORE 권한을 유지한다.** 이 재생의 `WAIT` 같은 문자열은 정답 비교용 후보일 뿐 CORE 명령이나 Fleet 수락 답이 아니다. 실제 막힘 답은 D-492의 Fleet 규칙표와 CORE 재검사가 결정한다. Mission·Task 후보의 장래 공급자를 바꿀 때만 D-429의 Decision API와 D-392의 Fleet allowlist 포트를 구현한다. 첫 시험을 위해 `operations/decision`, 공개 REST, 범용 provider framework를 만들지 않는다.
7. **승격은 별도 결정이다.** Decision 후보가 규칙+VLM+사람 기준선보다 어떤 사건을 개선하는지, 위험 혼동·미응답·p95 지연·GPU 동시 사용량을 독립 세트로 확인한다. D-492의 막힘 VLM V0 50장·V1 30건과 D-503 9항 트리거는 그대로 적용한다. 오프라인 결과만으로 그림자나 실시간 경로를 켜지 않는다.

### Consequences

- D-434의 모델 PC·관제 PC 역할은 유지하고, AI PC를 그 사이의 제한된 **추론 호스트**로 명시한다. `learning/registry`는 승격 증거 원장이지 AI PC가 실시간 조회하는 서버가 아니다(D-427).
- 배포 경로는 `모델 PC 평가·프로파일 → 고정 산출물 전달 → AI PC 추론 → Fleet 사실/후보 검증·판단 → CORE 재검사`다. 각 화살표의 실제 전송·인증·프로파일 스키마와 활성화 절차는 별도 구현 계약으로 검증한다.
- AI PC 장애·시간 초과·프로파일 불일치는 승인된 기존 규칙과 사람 경로로 처리한다. 모델 서버 응답이나 재생 정답은 Fleet admission·장치 수용 증거가 아니다.

### Verification

- `tools/decision_replay.py`의 가짜 loopback 서버 시험은 공통 choice 요청·집계와 외부 URL 거부를 확인한다. 이것은 실제 Laya/Kev 추론이나 로봇 수용 증거가 아니다.
- AI PC에서는 모델·GPU 상태·정확한 revision을 기록한 뒤 같은 사람 라벨 세트를 Laya와 Kev에 각각 재생한다. 사람이 붙인 정답이 아직 없으면 연결 시험만 보고 정확도 결론을 내리지 않는다.
- 코드 및 문서 lint와 영향을 받는 호스트 시험을 통과해도 V0/V1, 장치, 현장 수용은 각각 따로 남는다.

**Related:** [D-315](D-315-source-folder-responsibility-and-runtime-authority.md), [D-392](D-392-provider-neutral-model-tool-contract.md), [D-427](D-427-platform-three-parts-middleware-operations-learning.md), [D-429](D-429-five-concerns-control-port-and-site-devices.md), [D-434](D-434-model-pc-and-site-pc-roles.md), [D-492](D-492-d438-vision-tier-local-qwen-ai-pc-gated.md), [D-503](D-503-autonomy-chain-facts-and-exception-queue.md), [후보 조사](../reference/jev-local-decision-alternatives-2026-10-08.md).
