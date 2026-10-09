# 막힘 측정은 한 운행일에 겹치되, 주인은 나뉜다

- 날짜: 2026-10-09 (Asia/Seoul)
- 기준: 로컬 main `c91b4c9cd`에서 읽은 ADR과 소스
- 상태: 검토 정리. Accepted·Proposed ADR을 대체하지 않는다. 자격 발급, `--stuck-resolver` 가동, 로컬 복귀 승격, VLM 구현, 일반 World State 계약을 승인하지 않는다.
- 범위: [D-407](../adr/D-407-lane-stuck-recovery-console-then-local.md), [D-435](../adr/D-435-work-orchestration-fleet-and-device-authority.md), [D-438](../adr/D-438-fleet-stuck-resolver-rules-model-human.md), [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md), [D-495](../adr/D-495-lane-junction-bounded-turn-and-junction-defaults.md), [D-503](../adr/D-503-autonomy-chain-facts-and-exception-queue.md), [D-516](../adr/D-516-offline-decision-model-replay-boundary.md), [D-523](../adr/D-523-ai-pc-ask-returns-facts-or-candidates.md), [D-356](../adr/D-356-perception-learning-loop-and-model-delivery.md)
- 제외: 코드 변경, 현장 DB 건수 조회, 배포·장치 수용

판단 기준은 D-435다. 한 결정에는 주인, 다음 역할에 넘기는 것, 그 결정만으로는 생기지 않는 효과가 따로 있다. 같은 설명 안에 구현 소유자, 목표 책임, 실행 권한, 호스트를 섞지 않는다.

## 결론

일반 World State는 지금 만들 계약이 아니다. D-503은 쓰는 쪽 없는 `ObservationSnapshot`을 먼저 키우는 안을 거절한다. 현장 사실은 Fleet `MapPose`(`state`, `source`, `age_s`)다. `operations/world`의 `ObservationSnapshot`은 패키지로 있고, Fleet 코드는 그 타입을 가져오지 않는다.

D-503 §9를 열려면 등록 로봇 한 대의 3 운행일 동안 아래 증거가 겹쳐야 한다. 그 겹침을 한 모듈이나 한 표가 처리하면 책임이 섞인다. 에피소드 행만 쌓는 것으로는 게이트가 열리지 않는다.

## 이미 있는 층

| 층 | 주인 | 지금 하는 일 |
|---|---|---|
| Perception | `middleware/perception` | 사실을 만든다. 학습 차선 `perception/learned/shadow`는 섀도다 (D-356 Proposed) |
| 나이 | Fleet `MapPose` | 위치 사실의 상태와 나이를 붙인다 |
| Supervisor | Fleet `stuck_resolver` | 규칙이 막힘 답을 고르고, 사람은 예외 큐로 받는다 (D-438) |
| Skill | CORE `line_follow` 복귀 | 짧은 후진을 실행하고 스스로 멈춘다 |
| CORE | `middleware/core/gateway` | 답을 재검사하고 최종 `/cmd_vel`을 낸다 (D-2) |

막힘 원장 `fleet_line_stuck_episodes`와 `GET /api/fleet/line-stuck/episodes`는 트리에 있다. 행에는 원인, 자세, 상승 코드가 있고 프레임은 없다. 프레임은 D-379 녹화와 수확 도구 `stuck_markers.json`이 막힘 시각과 겹칠 때만 남는다. CORE 사건 이력은 메모리라, 재시작 전에 수확하지 않은 막힘은 나중에 볼 수 없다.

D-523 파서(`operations/fleet/fleet/ai/decision_pipeline.py`)는 정체 사실과 허용 목록 안의 선택 후보만 받는다. 호출자는 시험뿐이다. 공개 REST, 네트워크, `stuck_resolver` 연결은 없다.

## 책임 표

| 조각 | 주인 | 넘기는 것 | 이것만으로 생기지 않는 것 |
|---|---|---|---|
| 판단기 자격 | Fleet 등록. CORE `stuck_resolver` 역할 | 막힘 답과 읽기 | 모드 변경, 비상정지 해제, 보정 lease, `MANUAL` |
| 로컬 복귀 | CORE 설정. D-495 승격(모델 PC 한 바퀴와 실제 차선 한 바퀴) | 짧은 후진의 실행과 거절 | 측정용으로 켜는 일, VLM을 여는 일 |
| 녹화·마커 | 학습 수확. D-379, `stuck_markers.json` | 막힘 시각과 겹친 프레임 | 판단기가 영상을 저장하거나 에피소드 행에 프레임을 넣는 일 |
| 정체 10건 | 오프라인 검수 | `wall` · `object` · `robot` · `person` 사실 | 콘솔의 막힘 답 |
| 분모 SQL | Fleet 원장 읽기 | `share`와 `n` | World 계약, D-492 구현 |
| World | 만들지 않음 | — | 나이·정체·막힘 답을 한 서비스에 모으는 일 |

`recovery_local_enabled`는 측정 스위치가 아니다. 저장소 기본값 `contracts/foundation/config/rosy_default.yaml`은 켜져 있다. 로봇에 들어가는 조건은 D-495 승격이다. 승격 전 로봇에서 §9 분모가 비면 게이트는 열리지 않는 것이 맞다. 로봇별 롤백은 `~/.rosy/rosy.yaml`의 `line_follow.recovery_local_enabled: false`다.

8kcn·9dfk는 등록 로봇이라 막힘이 `no_resolver_token`으로 빠진다. §9 SQL은 그 행을 세지 않는다. `robot_enrollment_credentials`는 D-503 본문에만 있고 이 기준의 파이썬 소스에는 없다. `robots.yaml`의 `resolver_token`은 등록 로봇과 같은 id에서 `ROBOT_ID_CONFLICT`다. 표를 만들더라도 `robot_enrollments`에 칸을 더하지 않는다. 운영자 세션과 판단기 401이 한 행에 섞인다. 표를 만들어도 발급과 `--stuck-resolver`는 별도 승인이다. D-503은 Proposed다.

정체 10건은 예외 큐의 답 버튼이 아니다. 수확한 프레임에 대해, 정체를 알면 규칙이 다른 답을 냈을지를 오프라인으로 본다. D-503 §9는 3 운행일, 3단계, `share` ≥ 0.20, `n` ≥ 20, 그리고 앞 장애물 10건 이상에서 그 비율이 절반 이상일 때만 D-492 구현을 연다.

## 이미 있는 혼재 하나

D-407에서 관제 답이 `recovery_ask_s`(기본 15 s) 안에 없으면 CORE가 후진을 고르고 실행한다. D-503은 고르기를 Supervisor에, 실행과 재검사를 CORE에 둔다. 타임아웃 후진은 CORE가 답을 고르는 경로다. 이 검토는 그 경로를 측정 묶음으로 넓히지 않는다. World나 정체 라벨을 그 타임아웃에 붙이지 않는다.

## 닫아 두는 것

| 나중 | 여는 조건 |
|---|---|
| `operations/world`를 Fleet에 연결하는 일반 사실 계약 | 두 번째 소비자가 생길 때 |
| VLM 정체 사실 (D-492 Proposed) | §9 트리거. 그 전에는 Qwen을 설치하거나 호출하지 않는다 |
| D-523 파서를 판단기에 연결 | 위 트리거와 별도 연결 승인. 파서는 `WAIT` · `YIELD` · `RESUME` · `ABORT` · `MANUAL`을 내지 않는다 |
| 학습 차선을 주행에 쓰기 | D-356은 Proposed다. 섀도 출력을 제어가 읽지 않는다. 로봇 승격은 나중 ADR |
| 승인 모델의 현장 그림자, 그다음 한 로봇 활성화 | [파이프라인](../plans/2026-10-08-decision-model-pipeline-design.md) 1–4. 모델 PC의 사람 정답 세트와 L0이 먼저다 |

모델 PC는 배우고 평가한다. AI PC는 승인된 고정 버전으로 사실 또는 후보만 돌려준다. Fleet이 고르고 CORE가 재검사한다 (D-516). 점선은 목표 연결이다.

현장 DB의 에피소드 건수는 이 문서에서 확인하지 않았다.
