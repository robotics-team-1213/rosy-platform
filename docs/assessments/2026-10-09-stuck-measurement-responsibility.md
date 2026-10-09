# 막힘 측정은 한 운행일에 겹치되, 주인은 나뉜다

- 날짜: 2026-10-09 (Asia/Seoul)
- 기준: 로컬 main `c91b4c9cd`에서 읽은 ADR과 소스
- 상태: 검토 정리. Accepted·Proposed ADR을 대체하지 않는다. 자격 발급, `--stuck-resolver` 가동, 로컬 복귀 승격, VLM 구현, 일반 World State 계약을 승인하지 않는다.
- 범위: [D-407](../adr/D-407-lane-stuck-recovery-console-then-local.md), [D-422](../adr/D-422-line-follow-body-referenced-obstacle-stop.md), [D-430](../adr/D-430-safety-as-a-separate-concern.md), [D-435](../adr/D-435-work-orchestration-fleet-and-device-authority.md), [D-438](../adr/D-438-fleet-stuck-resolver-rules-model-human.md), [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md), [D-495](../adr/D-495-lane-junction-bounded-turn-and-junction-defaults.md), [D-503](../adr/D-503-autonomy-chain-facts-and-exception-queue.md), [D-516](../adr/D-516-offline-decision-model-replay-boundary.md), [D-523](../adr/D-523-ai-pc-ask-returns-facts-or-candidates.md), [D-541](../adr/D-541-core-fleet-trip-lease.md), [D-356](../adr/D-356-perception-learning-loop-and-model-delivery.md)
- 제외: 코드 변경, 현장 DB 건수 조회, 배포·장치 수용

판단 기준은 D-435다. 한 결정에는 주인, 다음 역할에 넘기는 것, 그 결정만으로는 생기지 않는 효과가 따로 있다. 같은 설명 안에 구현 소유자, 목표 책임, 실행 권한, 호스트를 섞지 않는다. 같은 날의 「재구분」이 아래 첫 표를 결정, 입력, 증거로 가른다. 첫 표와 「이미 있는 층」은 그 재구분의 출발로 남긴다.

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

## 재구분 (2026-10-09, 같은 날)

첫 표의 여섯 칸은 한 운행일에 겹치는 조각을 나눈 것이다. 칸 안에는 결정, 그 결정이 읽는 입력, 호스트 배치가 함께 들어 있다. 2026-10-03 검토는 구현 소유자, 목표 책임, 실행 권한, 호스트 배치, 폴더 분류를 한 설명에 섞지 말라고 한다. D-435 §8은 결정마다 권한 주인, 다음으로 넘기는 것, 그 결정만으로 생기지 않는 효과를 요구한다. D-435 §1과 §9는 그 구분이 새 서비스나 두 번째 저장이 아니라고 말한다. 같은 프로세스의 두 결정도 권한은 다를 수 있고, 한 사람이 두 결정을 맡더라도 근거는 남는다. D-435는 Proposed다. 이 절은 그 렌즈로 적은 검토이며, D-407의 시간초과 경로를 지우거나 D-430의 안전 체인을 옮기지 않는다. 재독은 워크트리 `docs/stuck-responsibility`의 ADR 본문이다.

### 결정

막힘 답을 고르거나, 고른 후진을 멈추는 권한만 측정 표의 결정이다.

| 결정 | 주인 | 넘기는 것 | 이것만으로 생기지 않는 것 |
|---|---|---|---|
| 규칙 | Fleet 판단기 (D-438) | R1이면 `WAIT`. 로컬 복귀가 켜져 있을 때만 R2·R3의 후진 | `MANUAL`, 영상 저장, 미션 완료 |
| 운용자 | 예외 큐의 사람 | 다섯 답. `MANUAL`은 여기 | 정체 라벨 |
| 시간초과 | CORE, D-407 §3 | `recovery_ask_s`(기본 15 s)가 비거나 관제 연결이 없으면 짧은 후진을 고름 | 이 고르기를 새 감독자에게 넘기는 일 |
| 스킬 | CORE 차선 추종 | 후진을 실행한다. 뒤 여유, 오래된 스캔, 몸 치수 없음, 지나온 길 만료면 스스로 거절한다 (D-407 §4) | 막힘 답, 정체 |
| 장치 가드 | Safety Guard (D-430 층 3) | 비상정지 래치, 속도 clip | 막힘 답. 링크가 없어도 장치에 남는다 |
| 교통 게이트 | 로봇의 traffic gate | 정책이 ENFORCED이고 HOLD면 후진 속도도 0 (D-407 구현 메모) | 막힘 답 |

뒤 여유 거절의 주인은 후진 스킬이다. D-438은 그 확인을 CORE의 뒤쪽 재검사라고 부른다. 장치 가드가 맡는 것은 이미 고른 뒤의 래치와 clip이다. 교통 게이트의 HOLD는 또 다른 0이고, D-430의 안전 층이 아니다. [D-422](../adr/D-422-line-follow-body-referenced-obstacle-stop.md)의 몸 기준 근접 정지는 차선 추종에만 있고, D-407 §4의 뒤 여유와 다른 판정이다.

시간초과는 혼재로 남는다. 답을 고르는 쪽과 후진을 내는 쪽이 같은 CORE다. 뒤 여유를 스킬 칸에 두어도 이 혼재는 그대로다. CORE 안에 감독자를 새로 두면, 구분을 이유로 서비스를 하나 더 만드는 일이 된다.

### 입력

입력이 어느 규칙을 쓰게 해도, 그 입력의 주인은 막힘 답을 고르지 않는다.

- 막힘 원인은 CORE 차선 추종이 `obstacle_ahead` 또는 `lane_lost`로 연다. `middleware/perception`은 픽셀과 `perception/learned/shadow`를 둔다. 제어는 그 섀도를 읽지 않는다 (D-356 Proposed).
- 동료 자세는 Fleet `MapPose`다. 자세를 모르면 R1을 쓰지 않아 `obstacle_ahead`에 R2가 열릴 수 있다. 그때도 뒤 확인은 CORE에 남는다 (D-438).
- 몸 치수 `body_lidar_x_m`, `body_rear_x_m`은 커미셔닝 사실이다. 없으면 후진은 시작되지 않는다. 그 사실을 적는 일이 `recovery_local_enabled`를 켜는 일은 아니다.
- `trip_busy`는 작업 오케스트레이션이 넘기는 값이고 §9 분모에서 빠진다. 판단기가 트립을 끝내 분모를 맞추지 않는다. [D-541](../adr/D-541-core-fleet-trip-lease.md)(Proposed)의 trip lease는 안전 층이 아니다.
- 관제 연결이 없음은 시간초과 결정의 입력이다.
- `recovery_local_enabled`는 측정 스위치가 아니다. 첫 표의 승격 규칙을 유지한다. 승격 전 로봇에서 §9 분모가 비면 게이트는 닫힌 채로 있다.

모델 PC와 AI PC는 호스트 배치다 (D-516). 배치 이름은 막힘 권한을 만들지 않는다. 일반 World State는 이 표의 결정이 아니다. 나이를 가진 현장 사실은 `MapPose`다. 분기 회전은 다른 스킬이라 이 경계 밖에 둔다.

### 증거와 사람

녹화기, CORE 사건 기억, 수확은 세 주인이다. 녹화기는 bag만 만든다. CORE `GET /api/v1/events`는 메모리라 재시작 전의 막힘을 잃는다. 수확 도구가 시각으로 겹쳐 `stuck_markers.json`을 쓴다. 셋을 한 프로토콜로 잇는 면은 D-407이 거절한 것이다.

원장 작성과 분모 판독은 `fleet_line_stuck_episodes` 하나의 두 결정이다. 작성은 D-503 §7의 열만 쓴다. 판독은 `share`와 `n`만 읽고, 그 숫자만으로 D-492가 열리지는 않는다. 같은 에피소드의 두 번째 저장은 D-435 §9의 이중 claim이다. 정체 10건은 그 테이블 밖의 오프라인 검수다.

발급자, 운용자, 검수자는 한 사람이어도 된다. 토큰과 화면이 다르다. 발급은 7일마다 `stuck_resolver`를 다시 낸다. 운용은 예외 큐다. 검수는 정체를 알았다면 규칙이 바뀌었을지를 나중에 본다. 등록 행에 판단기 열을 붙이면 운용자 세션과 판단기 401이 한 행을 나눈다. D-503이 그 합침을 거절한다.

### 첫 표에서 거둔 칸

안전은 한 칸으로 두지 않는다. 자리는 스킬의 뒤 여유, 장치 가드의 래치와 clip, 교통 게이트의 HOLD로 나뉜다. 물리 E-stop은 원칙만 있어 측정 표의 주인이 아니다 (D-430). Fleet 정지는 링크가 있어야 장치에 닿으므로, 링크가 없는 막힘에서는 장치 가드와 스킬의 확인이 남는다. 모델 도구 한계는 D-492가 Proposed인 동안 이 표 밖에 둔다.

몸 치수, 자세, 미션, 연결 없음은 결정 칸이 아니라 입력이다. 발급·운용·검수, 녹화·사건·수확, 원장 작성과 분모 판독은 칸이 많아도 유지한다. 사람은 한 명일 수 있고, 저장은 하나고, 프로토콜은 늘리지 않는다.

이 재구분은 자격 발급, `--stuck-resolver` 가동, 로컬 복귀 승격, VLM 구현, 일반 World State 계약을 승인하지 않는다.
