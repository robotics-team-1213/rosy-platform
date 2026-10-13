## D-527 Decision 시험은 역할별 호스트에서 수행한다

**Status:** Accepted (2026-10-09, 사용자 결정). D-516의 "첫 시험은 AI PC" 문장 중 평가 위치를 이 결정으로 고친다. 이전 AI PC Laya CPU 2건은 연결 확인으로만 남는다.

### Context

D-434와 D-516은 모델 PC가 독립 평가와 승격 증거를 맡고 AI PC가 고정 버전 추론을 맡는다고 정한다. 그러나 D-516 3항과 AI PC 배포 안내는 오프라인 재생을 AI PC의 첫 평가처럼 적었다. 시험 결과의 소유 호스트가 불명확하면 연결 확인을 모델 채택 근거로 잘못 읽을 수 있다.

### Decision

| 단계 | 실행 호스트 | 시험과 산출물 | 통과 뒤 다음 단계 |
| --- | --- | --- | --- |
| SOURCE | 개발 로컬 PC와 CI | ROS 없는 계약 pytest, 입력 검증, lint, pre-push 검사 | 같은 코드·계약을 모델 PC로 전달 |
| L0 | 모델 PC | 사람 정답과 세션 분리된 고정 사건 세트로 Laya/Kev/규칙 기준선을 비교한다. VLM은 영상·LiDAR 사건의 별도 정답 세트로 평가한다. 세트 hash, 모델·토크나이저·서버 revision, 프롬프트, 오류·기권·위험 혼동·지연을 receipt로 남긴다 | 평가에 통과한 고정 ModelProfile 후보만 승격 심사 |
| DEPLOY | AI PC | 승인된 산출물 digest·프로파일 ID·서버 revision과 GPU readback을 확인한다. 작은 비식별 스모크 세트로 loopback 추론, 지연·timeout·복귀, watchdog을 확인한다 | Fleet 그림자 연결 심사; AI PC는 모델 재선정·승격 불가 |
| SHADOW/DEVICE | 현장 PC Fleet와 로봇 CORE | 사실의 나이·형식, 규칙·사람 판단, CORE 거절/수락, 장치 결과를 단계별로 확인한다 | 작업별 별도 활성화 결정 |

L0 입력 원본·사람 정답은 모델 PC의 승인된 저장소에 두고, AI PC에는 고정 산출물과 최소 스모크 입력만 전달한다. `tools/decision_replay.py`는 두 호스트에서 같은 loopback 계약을 검사할 수 있지만, AI PC 스모크의 1/2 같은 일치 수치는 정확도나 승격 증거가 아니다. 모델 PC에서 사람 정답 세트가 없으면 L0은 HOLD다. AI PC GPU가 고장 나면 DEPLOY는 HOLD이고 모델 PC 결과로 대신 통과시키지 않는다.

### Verification

로컬 계약 시험은 재생 입력과 loopback 제한을 확인한다. 모델 PC에서는 고정 revision과 세트 hash를 포함한 독립 평가 receipt가 필요하다. AI PC에서는 실제 적재 버전·GPU·watchdog·스모크 readback이 필요하다. 이 ADR은 평가 결과나 운영 활성화 자체를 증명하지 않는다.

**Related:** [D-434](D-434-model-pc-and-site-pc-roles.md), [D-516](D-516-offline-decision-model-replay-boundary.md), [파이프라인](../plans/2026-10-08-decision-model-pipeline-design.md).
