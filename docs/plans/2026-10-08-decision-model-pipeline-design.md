# Decision 모델 파이프라인과 실행 구조

**상태:** D-516·D-527 Accepted의 구현 설계. 이 문서는 배포 또는 현장 활성화 기록이 아니다.

## 한 장 구조

```text
데이터/승격: 로봇 사건 + Fleet 결과 → 검수·사람 정답 → 모델 PC L0 평가
                                               → 고정 ModelProfile 후보 → 승인·배포 → AI PC 적재

검증: 개발 로컬 PC 계약·pytest → 모델 PC 독립 L0 → AI PC 고정 버전 스모크
                                          → 현장 Fleet 그림자 → CORE 장치 수용

운영/피드백: 로봇 CORE/센서 → 현장 PC Fleet → 제한된 질의 → AI PC 추론
                               ↑                             │
                               └──── 정체 사실 또는 제안 ─────┘
                     Fleet 규칙·admission·사람 확인 → CORE 재검사 → 결과 기록
                                                        │
                                                        └→ 다음 오프라인 사건
```

두 작업은 같은 GPU를 쓸 수 있어도 입력·출력·승격을 공유하지 않는다.

| 작업 | AI PC가 내는 것 | 현장 PC 소비자 | 현재 상태 |
| --- | --- | --- | --- |
| 막힘 정체 관측 | LiDAR가 연 `obstacle_ahead` 사건에 맞는 프레임의 `wall/object/robot/person/unknown` 사실 | Fleet `stuck_resolver` 옆의 VLM adapter → D-492 규칙표 | D-492 Proposed. adapter·R4·V0/V1 미구현; 지금은 규칙·사람 |
| 숙고형 Mission/Task | Fleet이 제한한 상태와 허용 후보에 대한 제안 또는 기권 | 목표 `operations/decision` → Fleet admission | 목표 모듈·모델 연동 미구현; 자동 policy dispatch 꺼짐 |

`WAIT` 같은 오프라인 choice 값은 평가용 후보이며 로봇 명령이 아니다. VLM도 막힘 답을 고르지 않는다. 현장 Fleet이 규칙·admission·사람 확인으로 선택하고, 로봇 CORE가 실행 직전 다시 검사한다. AI PC에는 Fleet 원장, ROS, 장치 Action, 취소·정지·재무장, `/cmd_vel` 권한을 주지 않는다. [D-516](../adr/D-516-offline-decision-model-replay-boundary.md), [D-429](../adr/D-429-five-concerns-control-port-and-site-devices.md).

## 호스트, 코드 소유, 권한

| 위치 | 실제 역할 | 저장소 소유 경로 | 입력 → 출력 | 쓰기 권한 |
| --- | --- | --- | --- | --- |
| 모델 PC | 사건 검수, 학습 또는 프롬프트 선택, 독립 L0 평가, 승격 증거 | `learning/curation`, `learning/training`, `learning/evaluation`, `learning/registry`; 실행 안내 `deploy/model_pc` | 비식별 사건·사람 정답 → 평가 receipt·고정 산출물 후보 | 학습 산출물과 평가 기록만 |
| AI PC | 승인된 digest/revision 적재, 배포 스모크와 추론 | `deploy/ai_pc`; 공급자 adapter의 목표 소스 위치는 `integrations/models/<provider>` | 고정 산출물·최소 스모크 질의 → 적재·GPU·timeout readback; 운영 시 정체 사실 또는 Mission/Task 후보 | 추론 결과만; 산출물·승격 판단 변경 불가 |
| 현장 PC | 사실의 출처·나이 검증, 규칙, 사람 큐, Mission admission, 실행 요청과 결과 원장 | `operations/fleet`; 숙고형 목표 `operations/decision` | CORE 사건·AI PC 결과 → 허용된 답·의미 행동 또는 사람 상승 | Fleet 원장·허용된 CORE 요청 |
| 로봇 | 센서·카메라 관측, 장치 지역 규칙, 안전과 최종 명령 | `middleware/perception`, `middleware/core/gateway` | 현장 요청 → 재검사·수락/거절·실행 상태 | CORE만 최종 `/cmd_vel` |

표의 **소스 경로는 호스트 배치나 설치 권한을 자동으로 뜻하지 않는다**(D-315). 실제 배포 이미지와 프로세스 배치는 구현 시 `deploy/`에서 확인한다. 현재 `operations/decision`과 `integrations/models/<provider>`는 목표 경계이고, `operations/fleet/fleet/ai`가 기존 숙고형 코드 자리다. `learning/registry`는 증거 원장이며 AI PC가 실시간 조회하는 서버가 아니다([D-427](../adr/D-427-platform-three-parts-middleware-operations-learning.md)).

## 1. 사건에서 사람 정답까지

1. CORE 사건·카메라·LiDAR와 Fleet 결과를 같은 사건 ID 및 시각으로 묶는다. 막힘 존재와 거리는 LiDAR/CORE 사실로 유지한다. 현장의 episode 기록과 resolver 자격부터 완성해 사람이 받은 사건의 분모를 잰다([D-503](../adr/D-503-autonomy-chain-facts-and-exception-queue.md) §7–9).
2. 필요한 사건만 모델 PC로 export한다. 원본 영상과 사람 정보는 승인된 로컬 store에 두고, 텍스트 Decision 재생에는 비밀·개인 정보를 제거한 제한 상태만 쓴다. VLM용 프레임은 별도 세트로 보관한다.
3. 사람이 정체 또는 적절한 후보를 라벨링하고, 수집 세션 기준으로 개발·독립 평가를 나눈다. 모델 출력, CORE 수락, Fleet 답을 사람 정답으로 복사하지 않는다. 정답이 없으면 연결 시험만 보고한다.

**현재 증거:** 개발 로컬 PC의 재생 도구 계약 시험과 AI PC의 Laya CPU 합성 2건은 각각 SOURCE와 DEPLOY 연결 확인이다. AI PC의 1/2 일치값을 모델 PC L0 정확도로 해석하지 않는다. 모델 PC의 사람 정답 독립 세트와 Laya/Kev 비교, 실제 막힘 사람 정답 세트는 아직 없다([D-527](../adr/D-527-decision-test-host-boundaries.md), [후보 조사](../reference/jev-local-decision-alternatives-2026-10-08.md)).

재검증에서는 전체 입력 선검증과 세트 SHA-256 기록, 서버 오류 시 실패 종료 코드를 더하고 AI PC CPU 호출·서버 중단을 각각 확인했다([2026-10-08 결과](../validation/decision-model-replay-2026-10-08/result.md)). 이는 배포 스모크의 과거 증거다. 모델 PC L0, AI PC GPU·Kev·현장 경로는 아직 검증되지 않았다.

## 2. 오프라인 비교와 승격

1. 모델 PC에서 작업별 입력·출력 계약을 고정한다. 텍스트 후보는 같은 사건·질문·허용 선택지·세트 hash를 Laya, Kev, 규칙 기준선에 재생한다. VLM은 D-492의 LiDAR 거리와 정지 프레임으로 정체만 평가한다. 서로 다른 작업의 점수를 합쳐 한 모델을 선정하지 않는다.
2. 모델 PC에서 사람 정답 대비 위험 혼동, 기권·미응답, 지연 p95, GPU 동시 점유, 선택지 순서 민감도를 기록한다. AI PC에서는 승인된 고정 버전의 실제 GPU 지연·timeout·watchdog만 다시 확인한다. D-492 VLM은 V0 사람 라벨 50장 이상과 V1 현장 그림자 정답 30건 등 해당 ADR의 별도 관문을 따른다. 막힘 VLM 구현 착수 자체도 D-503 §9 트리거가 먼저 충족돼야 한다.
3. 통과한 경우에만 모델 PC가 **고정 ModelProfile 후보**를 낸다. 최소 기록은 작업 계약 버전, 모델·토크나이저·서버 revision/digest, 질문/프롬프트 버전, 평가 세트 hash, 평가 receipt, timeout·fallback, 승인 단계다. D-427의 `profiles/`와 release lock이 전달 경계다. 현재 Decision용 `ModelProfile`의 실제 wire/schema와 배포 절차는 구현 계약이 없어 이 문서에서 필드를 API로 확정하지 않는다.
4. 설치별 주소·인증 정보는 비공개 설정에 둔다. AI PC는 승인된 프로파일과 실제 적재 digest가 같은지 확인하고, 현장 Fleet도 같은 프로파일 ID를 참조해야 한다. 불일치하면 모델 결과를 쓰지 않는다. 운영 중 가중치·프롬프트를 조용히 바꾸지 않고 이전 승인 프로파일을 보존한다.

## 3. 현장 추론과 결과 회수

### A. 막힘 정체 VLM: D-492가 허용될 때만

`CORE obstacle_ahead + 앞 LiDAR 거리` → Fleet이 사건/프레임 촬영 시각 확인 → AI PC가 정체만 추론 → Fleet이 형식·confidence·나이 검증 → `person/robot`이면 R4 `WAIT`, 그 외는 기존 R1–R3/사람 경로 → CORE 재검사 → Fleet 결과 기록. `lane_lost`나 앞 거리 없음에는 VLM을 부르지 않는다. 프레임 누락·낡음·낮은 confidence·타임아웃은 `unknown`이다. `unknown`에서 새 복구 권한이 생기지 않는다. D-492의 구체 규칙표와 수치가 이 흐름보다 우선한다.

### B. 숙고형 Decision: 별도 문제의 후보 경로

`Fleet 상태·capability·허용 후보` → AI PC의 Laya/Kev 등 고정 프로파일 추론 → `operations/decision`의 제안 검증 → Fleet allowlist/admission·필요 시 사람 확인 → CORE 의미 행동과 장치 재검사 → Fleet 결과 기록. 현재는 오프라인 L0 재생까지만 있다. 이 경로를 막힘 VLM의 R4로 우회하지 않는다. 자동 policy dispatch는 `False`이며, 제안이 있다고 자동 실행으로 바뀌지 않는다([D-392](../adr/D-392-provider-neutral-model-tool-contract.md), [D-427](../adr/D-427-platform-three-parts-middleware-operations-learning.md)).

### 오류와 되돌리기

| 조건 | 현장 처리 |
| --- | --- |
| AI PC 부재·시간 초과·프로파일 불일치 | 해당 모델 결과 폐기; 승인된 기존 규칙과 사람 경로 사용 |
| VLM 프레임/거리 누락, 사건보다 오래된 프레임, 형식 오류 | 정체 `unknown`; Fleet의 기존 규칙 또는 사람 상승 |
| 늦은 Decision 후보, 사건 세대 변경, 정지·장치 거절 | 후보 무효; CORE 거절을 우회하거나 성공으로 기록하지 않음 |
| 새 프로파일 성능 저하 | 해당 작업 모델 사용 중단 후 이전 승인 프로파일로 복귀; 모델 없이도 규칙·사람 경로 유지 |

판단 결과, CORE 수락, 실제 과제 성공은 서로 다른 증거다. 현장 결과와 사람 수정은 다음 오프라인 사건으로 모델 PC에 되돌아갈 뿐, AI PC가 스스로 학습·승격하지 않는다.

## 다음 구현 순서와 완료 증거

| 순서 | 구현·판정 | 완료 증거 |
| --- | --- | --- |
| 0 | Fleet episode 기록, resolver 자격/규칙의 한 로봇 검증, D-503 §9 분모·트리거 측정 | 현장 원장과 CORE readback; 미충족이면 VLM 구현 보류 |
| 1 | 모델 PC에서 사람 정답 세트, Laya/Kev 동일 텍스트 L0, VLM 별도 V0 | 세션 분리·세트 hash·모델 digest·실패/지연 receipt |
| 2 | AI PC에서 고정 프로파일 적재·스모크와 GPU 동시 사용 측정 | 승인 프로파일과 서버 readback 일치, timeout·watchdog·되돌리기 검증 |
| 3 | 필요한 작업만 현장 adapter와 **출력 미적용** 그림자 연결 | 모델 결과와 실제 규칙/사람 결과가 분리된 V1 기록; D-492 관문 충족 |
| 4 | 작업별 활성화 판단과 한 로봇 장치 검증 | 별도 승인된 설정, Fleet 판단·CORE 재검사·거절/결과 readback |

전송 방식·인증·프로파일 스키마·활성화 설정은 2단계 구현 전에 기존 API reference와 배포 계약에 맞춰 별도로 확정한다. 이 설계만으로 새 REST 경로, 운영 모델 서버, 원격 GPU 사용권, 로봇 움직임은 생기지 않는다.
