# ADR 책임 모델·용어·Fleet 범위 재검토

- 날짜: 2026-10-03 (Asia/Seoul)
- 기준: 로컬 main HEAD `58b56171fe7fd4ea220c032e1fb410048d964fd6`에서 읽은 ADR·용어집·현재 소스
- 상태: 검토 및 후속 결정 제안. Accepted ADR을 대체하지 않는다.
- 범위: D-12, D-21, D-55, D-290, D-296, D-298, D-326, D-333, D-358, D-369, D-392, D-399, D-413, D-427, D-429, D-430, CONCEPTS.md, 플랫폼 설계 v0.2
- 제외: 코드 이전, 패키지·API 개명, 실행 밸브 변경, 배포·장치 수용

## 검토 결론

문제는 Fleet이라는 단어 하나가 아니다. 현재 구현 소유자, 목표 기능 책임, 실행 권한, 호스트 배치, 폴더 분류가 같은 설명 안에 섞여 있다. 이 상태에서 이름과 폴더만 바꾸면 같은 혼합을 새 경로로 옮긴다.

추천은 작업 실행의 범용 책임과 다중 로봇 조정 책임을 논리적으로 구분하는 것이다. 미션 실행·원장은 하나의 소유자를 유지하고, Fleet coordination은 그 실행에 필요한 로봇 배정·교통·공유 자원·협업 기능으로 좁힌다. 논리적 구분이 프로세스 분리나 새 DB를 요구하지는 않는다. 장치 안의 유한한 복합 실행과 최종 제어 권한은 장치에 남긴다.

이 결론은 후속 ADR 후보이며, 현재 계약은 여전히 Fleet Mission 소유권을 정한다. 검토 문서의 추천을 구현된 계약으로 읽지 않는다.

## 관찰과 변경 제안

### R1. 기존 Fleet 서비스와 목표 Fleet 책임을 구분해야 한다

- 근거: [D-12](../adr/D-12-mission-fleet.md)는 Mission DSL을 Fleet에 둔다. [D-21](../adr/D-21-.md)은 Fleet을 formation 오케스트레이터로 쓴다. [D-296 §4](../adr/D-296-device-middleware-and-site-orchestration-terminology.md)는 사이트 미션·인계·우선순위·이력까지 Fleet으로 정의한다.
- 판정: 기존 ADR들이 모두 같은 범위를 말하는 것은 아니다. Fleet은 현재 구현에서 군집제어만 담당하지 않는다. 동시에 이 구현 범위를 범용 플랫폼의 영구 책임 이름으로 삼을 필연성도 없다.
- 변경 제안: `legacy Fleet service`(기존 API·패키지·서비스), `Fleet coordination`(다중 로봇 기능), `작업 실행 소유자`를 문서에서 구분한다. 공개 API 이름은 호환 이름으로 유지하고 의미를 조용히 바꾸지 않는다.

### R2. D-290의 선택지를 후속 ADR에서 명시적으로 닫아야 한다

- 근거: [D-290 §2](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md)는 고정 OMX까지 조정할 때 Fleet을 확장할지, 기존 실행기·기록을 Operations로 이행하고 D-12를 대체할지 결정하도록 남겼다. [D-429의 기존 결정 표](../adr/D-429-five-concerns-control-port-and-site-devices.md)는 D-12를 유지한다. [설계 v0.2](../reference/ROSY_Platform_Architecture_Design_v0.2.md)는 현 fleet/server를 execution/site와 앱 조합으로 추출한다.
- 판정: 엄밀한 정면 모순이라기보다, 후속 구조가 Fleet 확장 쪽으로 기울면서 선택 근거와 책임 이행의 의미가 충분히 설명되지 않은 상태다. 소스 추출과 Mission 소유권 변경도 별개의 결정이다.
- 변경 제안: 후속 ADR에 D-290 선택지의 처분, D-12·D-296의 부분 대체 범위, 유지되는 단일 원장 원칙을 명시한다.

### R3. 관심사 표를 실제 실행 계층도로 읽게 해서는 안 된다

- 근거: [D-429 §1](../adr/D-429-five-concerns-control-port-and-site-devices.md)은 숙고형·조정·장치 지역 규칙·중재/안전·반응형·판정기·사람을 층으로 나열한다. 같은 문서는 concern을 읽기 전용 view로 정의한다. [D-430](../adr/D-430-safety-as-a-separate-concern.md)의 safety 태그에는 별도 불변식과 변경 통제가 있다.
- 판정: 역할, 알고리즘 방식, 명령 출처, 안전 책임이 같은 표에 있다. 유용한 분류표지만 단일 상하 실행 계층이나 동일한 태그 권한으로 해석하기 어렵다.
- 변경 제안: 기능 책임도, 실행 요청 흐름, 호스트 배치도, 권한표, 소스 소유 view를 분리한다. Safety는 여러 경계의 책임이며 하나의 중앙 안전 서버가 아니다. MANUAL은 명령 출처이고 Learning은 산출물 흐름이다.

### R4. 작업 실행과 로컬 실행의 경계를 다시 명시해야 한다

- 근거: [D-55](../adr/D-55-mobile-manipulation-is-a-robot-local-mission-capability.md)는 접근·파지·운반·배치를 장치 로컬 상태기계로 제안한다. [D-298 §1](../adr/D-298-mission-action-and-stop-evidence-terminology.md)은 이를 Local Transaction으로 해석하고 사이트 Mission과 구분한다.
- 판정: 모든 다단계 작업이 사이트 Mission인 것은 아니다. 반대로 로컬 트랜잭션을 일반 사이트 Workflow 실행기로 확대해도 안 된다. 로봇 수나 PC 수만으로 어느 실행 소유자가 맡을지 정할 수 없다.
- 변경 제안: 사이트 작업은 장치 사이 순서·자원·인계·전체 목표를, 장치는 수락한 Device Action 내부의 유한한 진행·로컬 중재·제어를 소유한다. 단일 장치 작업에도 작업 원장이 필요할 수 있으나 그 이유를 Fleet 보유 여부로 설명하지 않는다.

### R5. ER2의 자리와 후보 수락 권한을 분리해야 한다

- 근거: [D-326](../adr/D-326-agent-loop-boundary.md)·[D-392](../adr/D-392-provider-neutral-model-tool-contract.md)는 모델을 제한된 조회·제안 소비자로 둔다. [D-358 §4](../adr/D-358-er2-feedback-outbox-and-replan-fencing.md)는 후보 가시화와 stop/generation 확인의 원자성을 요구한다. 현재 `fleet/ai/tool_dispatch.py`와 `fleet/server/proposal_store.py`는 직접 연결되어 있다. [D-429 §5](../adr/D-429-five-concerns-control-port-and-site-devices.md)는 주입 저장 포트로 이 결합을 줄이는 방향도 기록한다.
- 판정: 원자적 fence와 단일 수락 권한은 유지해야 한다. 이것이 ER2가 Fleet coordination에 논리적으로 종속되어야 한다는 증거는 아니다. 최상위 decision 폴더나 별도 프로세스를 기각하는 결정과, Decision을 독립 책임으로 설명하는 일은 양립한다.
- 변경 제안: 후보 저장·수락·stop fence의 소유자를 작업 실행 권한으로 설명하고, Decision은 그 공개 제안 계약만 사용한다. 같은 프로세스·DB를 유지하면서도 이 책임을 분리할 수 있다. 모델은 미션 수락·장치 실행·정지·rearm 권한을 얻지 않는다.

### R6. 용어집과 API 호환 설명을 함께 정합화해야 한다

- 근거: `CONCEPTS.md`의 Task는 원자 REST action이고, 현 `/api/fleet/tasks/*`의 task는 영속 이동 요청이다. D-298과 D-369는 Mission Step, Device Action, Local Transaction, 메시지·attempt·증거의 차이를 보강한다.
- 변경 제안: 아래 작업 어휘의 의미·소유자·ID·상태·다중성 표를 정본으로 정한다. 레거시 TaskKind·task_id와 새 도메인 어휘를 구분해 대응시킨다. 모든 상태 문자열이 현 wire enum이라고 주장하지 않는다.

## 책임 모델 대안

| 대안 | 장점 | 비용·문제 | 검토 판단 |
|---|---|---|---|
| A. 작업 실행 소유자 + Fleet coordination | 단일 팔·로봇 한 대·다중 로봇을 같은 실행 계약으로 설명. Fleet 범위를 분명히 함 | 기존 이름·참조의 정합화 필요 | 추천. 기능 책임부터 구분하고 기존 프로세스·원장을 보존 |
| B. Fleet을 범용 Operations로 통째로 개명 | 기존 단일 구현·원장 보존이 단순함 | 미션 실행·군집·AI·신호·API 혼합을 그대로 옮길 수 있음 | 이름 변경만으로는 불충분 |
| C. Decision·Orchestration·Execution·Fleet을 즉시 별도 서비스로 분리 | 서비스별 이름이 명시적 | 트랜잭션·세대·claim·복구가 분산되고 새 운영 비용 발생 | 현재 요구로는 근거 부족. 채택하지 않음 |

Orchestration은 우선 작업 실행 책임 안의 단계·의존성·자원 조정 기능으로 설명한다. 별도 실행 컴포넌트가 필요한지는 소비자·상태·장애 경계로 판단한다. 논리 역할마다 폴더·wheel·프로세스 하나를 만들지 않는다.

## 작업 어휘 후보

| 어휘 | 제안 의미 | 소유·경계 |
|---|---|---|
| Process / Recipe | 공정 규칙·작업 절차·완료 조건 | 공정 모듈. 실행 상태의 원장이 아님 |
| Proposal | 검증 전 작업·재계획 후보 | Decision/사람/규칙이 생산. 후보는 실행 허가가 아님 |
| Mission | 달성할 목표와 승인된 작업 계획의 실행 인스턴스 | 작업 실행 소유자. 다중 로봇에 한정하지 않음 |
| Step | Mission 내부의 진행 단위 | 작업 실행 소유자. 필요 시 자원·장치와 연결 |
| Device Action | 장치가 수용·진행·종료하는 유한 요청 | 장치 owner. Mission Step과 ROS goal의 일대일 관계를 가정하지 않음 |
| Skill | 장치가 제공하는 재사용 행동 계약·구현 | 장치 실행 경계. capability와 실행 인스턴스를 구분 |
| Local Transaction | 수락된 Device Action 내부의 유한 복합 진행 | 장치 로컬. 사이트 Mission 원장을 복제하지 않음 |
| Task | 기존 API마다 의미가 다른 호환 어휘 | 새 공통 의미를 추가하기 전에 기존 의미 대응표 확정 |

이 표는 제안이며 새 schema나 wire 필드를 정의하지 않는다. 단일 Action Mission 허용 여부, Step에서 복수 Action의 관계, 중첩 실행의 취소·결과 집계 규칙은 후속 계약에서 확정한다.

## 사례로 검증하는 경계

| 사례 | 책임 배치 후보 | 이 모델이 충족해야 할 조건 |
|---|---|---|
| 고정 OMX 한 대의 Pick&Place | 공정/Decision → 작업 수락·원장 → OMX Device Action → 로컬 트랜잭션·제어 → 독립 목표 증거 | 다중 로봇 Fleet 기능 없이 설명 가능. 수락·제어기 성공·배치 완료 증거 구분 |
| Pinky 두 대의 운송 | 작업 실행이 장치 작업을 진행하며 Fleet coordination의 배정·교통·공유 자원 grant 사용 | formation 미사용 시 군집 추종 기능은 불필요. 자원 grant와 원장의 정본이 이중화되지 않음 |
| Pinky+OMX 이동 조작 | 상위 작업은 인계·전체 목표를, 미래 로컬 복합 트랜잭션은 수락 범위의 베이스·팔 절차를 담당 | 베이스·팔 writer 유지. 물체 보유/팔 상태 불명은 로컬 HOLD. 상위 ER2가 실시간 구동 순서를 대체하지 않음. 현재 운영 수용을 주장하지 않음 |
| ER2 응답 직전에 stop | 작업 실행 측 fence가 늦은 후보를 거부하고 장치가 자체 정지를 수행 | 후보 삽입·stop 세대 확인의 원자성 보존. 재연결·모델 응답·rearm만으로 작업을 자동 재실행하지 않음 |
| 사이트 링크 상실 | 각 장치의 승인된 링크 상실 정책 적용, 상위 원장은 불명 결과를 보존·조정 | 전체 Mission 중단과 모든 로컬 Action의 즉시 중단을 동일시하지 않음. 장치별 정책·증거로 판단 |

각 사례는 설계의 반례 검사이며 실행 시험 결과가 아니다.

## 후속 ADR에서 결정해야 할 최소 묶음

1. **역할·작업 어휘·단일 실행 소유자.** A/B/C 중 처분, Mission·Step·Action·로컬 트랜잭션의 관계, Fleet coordination/formation 범위, 현재 구현과 목표 역할 대응을 한 책임 모델 ADR로 결정한다. D-12, D-290 §2, D-296 §4, D-298 §1과 CONCEPTS.md에 미치는 범위를 명시한다.
2. **역할 간 계약.** 후보 수락, 작업 원장, 자원 grant, 장치 Action, 취소·stop·rearm, UNKNOWN 조정, 독립 목표 증거의 생산자·소비자·권한·세대·원자성을 결정한다. 기존 D-333/D-358/D-369/D-392의 불변식을 보존하고 역할명만 바뀌는 조항과 실제 책임 변경을 구분한다.
3. **이행 및 구조도 정합화.** 위 결정 뒤 D-399/D-413/D-427/D-429/D-430의 기능 그림·배치·태그·목표 경로를 정렬한다. 공개 API·DB·프로세스·Python import·소스 경로 변경을 별도 이행 단위로 나눈다. 지금 목적지 폴더부터 확정하지 않는다.

기존 Accepted 본문을 덮어쓰지 않는다. 후속 ADR과 명시적 부분 대체 안내로 이력을 남긴다. D-399는 Proposed 상태이므로 수용할 새 모델과의 관계를 명시한다. 새 ADR 번호·Accepted 승격은 이 검토에서 수행하지 않는다.

## 유지해야 할 불변식과 검토 완료 기준

- 작업 실행 원장은 논리적으로 하나이고, 장치 Action 원장은 장치가 소유한다. 원장 분리는 서로 다른 사실의 소유이며 이중 Mission 실행기가 아니다.
- 모델은 후보/허용 조회만 한다. `POLICY_DISPATCH_ENABLED=False`와 현재 활성화·장치 게이트를 유지한다.
- 베이스·팔의 최종 명령은 각 장치 owner 하나만 낸다. Fleet coordination·작업 실행·Decision은 ROS/driver writer를 넘겨받지 않는다.
- 안전은 모델·학습에 기대지 않는다. 분산된 장치 안전 책임과 독립 물리 E-stop의 증거를 보존한다.
- 요청 접수, 수락, Action 종료, 목표 확인, 물리 정지는 서로 다른 증거다. UNKNOWN을 자동 성공·재실행으로 변환하지 않는다.
- 정본 용어집·ADR·책임표·상태/ID 대응표가 위 사례들을 같은 용어로 설명해야 한다. 폴더/import 시험 통과만으로 의미 정합성을 완료 처리하지 않는다.

## 검증 범위

문서·현재 소스 정적 검토다. 호스트 계약 검사와 harness 결과는 문서 형식·기록 정합성에 대한 검증이며, 추천 책임 모델의 Accepted 상태나 구현·시뮬레이션·실물 수용을 뜻하지 않는다.

- `python tools/harness/rosy_harness.py generate`: docs/index.md 갱신.
- `python tools/harness/rosy_harness.py lint`: 0 errors, 26 warnings(기존 last_verified 이력 경고).
- 로컬 문서 링크: 14개, 누락 0개. `git diff --check`: 통과.
- 문서/구조 계약 시험: `test_folder_layout.py`, `test_module_structure.py`, `test_module_scorecard.py`, `test_network_topology_contracts.py`, `test_harness_contracts.py` 합계 128 passed, 1 skipped, 1 failed.
- 실패: `test_baseline_covers_workspace_packages_set_equality`. 시험은 `src/**/package.xml`만 스캔하지만 Isaac 패키지는 현재 `learning/envs/isaac/package.xml`에 있고 기준선에는 `isaac_sim`이 남아 있다. 해당 시험·패키지·기준선은 이번 변경에서 수정하지 않았다. 이 실패를 감추거나 전체 통과로 표기하지 않는다.

## 2차 검토 — 2026-10-03, 첫 추천의 반례와 보정

기준: HEAD `8dda13eecb46d609176e410207ca4e0b3b73008e`. 위 1차 검토·시험 수치는 당시 기록으로 보존한다. 아래 내용이 추천 모델을 보강하며, 새로운 검증 결과는 별도로 기록한다.

### 첫 검토에서 부족했던 점

1. **단일 원장의 범위가 모호했다.** 동일 Mission의 정본 하나와 플랫폼 전체 DB 하나는 다르다. D-413 §2대로 장치 Action 원장과 사이트 작업 원장은 서로 다른 사실을 소유한다. 독립 셀의 새 실행 소유·인계·failover를 이번 문서로 열지 않는다.
2. **공유 자원을 Fleet에 과하게 남겼다.** 로봇 교통·배정·formation은 Fleet 범위지만 문·컨베이어·셀 인터록을 전부 Fleet으로 넘기면 같은 범용화 문제가 재발한다. 미래 자원 계약은 충돌 집합별 claim 정본·grant·해제 증거의 소유자를 명시해야 한다. 범용 자원 서비스 신설은 필요 조건이 아니다.
3. **모든 요청이 상위 실행기를 거쳐야 하는 것처럼 보였다.** D-369 §7·D-399 §5의 허용된 사람 장치 API 경로는 유지한다. Pilot 조작과 정지에 Mission 생성·상위 서버 가용성을 새로 요구하지 않는다. 장치 중재·claim·안전을 우회하는 허가는 아니다.
4. **Decision은 실행권이 없다는 문장을 일반화할 위험이 있었다.** 이는 숙고형 모델의 후보 권한이다. Fleet 배정·장치 지역 규칙·승인된 스킬은 각자 허용된 범위에서 결정과 실행을 한다. ER2, 고전 플래너, 반응형 정책을 같은 권한·시간 척도로 설명하지 않는다.
5. **Orchestration/Execution 분리가 이름만 늘릴 수 있었다.** 작업 오케스트레이션은 operations의 Mission 수락·원장·단계 진행 역할, 장치 실행은 middleware의 Action/attempt·로컬 제어 역할로 설명한다. Orchestration과 Execution을 각각 새 범용 서비스로 만들지 않는다.
6. **원장 일관성과 물리 자원 해제를 더 분명히 해야 했다.** 정지 요청·링크 상실·Action 결과 불명은 자원이 비었다는 증거가 아니다. 늦은 결과를 차단하고 기존 점유/결과 readback·운영자 조정 근거로 해제를 판단해야 한다.

### 보정한 결론

역할 분리 방향은 유효하지만 첫 문서를 그대로 확정하는 것은 부적절하다. Work Orchestration은 모든 운영 책임을 떠안는 중앙 실행기가 아니다. 공정은 작업 의미를, 숙고형 Decision은 후보를, 작업 오케스트레이션은 해당 Mission 수락·진행을, Fleet은 로봇 집합의 조정을, 장치는 로컬 Action과 최종 명령을 소유한다. 안전·관측·학습은 이 역할들을 잇는 별도 책임/산출물 흐름이며 단일 상하 계층으로 강제하지 않는다.

이를 [D-435 Proposed 초안](../adr/D-435-work-orchestration-fleet-and-device-authority.md)으로 구체화했다. 초안은 역할표, 원장·자원·정지 범위, 작업/수동/안전 경로, 작업 어휘, 기존 결정별 수용 시 부분 대체 범위, 대안, 아홉 가지 반례를 포함한다. 기존 Accepted ADR과 API·코드·활성화 상태는 계속 유효하다. D-435 추가는 책임 모델의 수용이나 구현 완료가 아니다.

### 2차 검증 결과

- 문서 계약: test/test_network_topology_contracts.py + test/test_harness_contracts.py, 83 passed/26 warnings. full lint와 generated record 정합성 검사 포함. 경고는 기존 last_verified 이력이다.
- D-435 제목·Proposed 상태·ADR Log 행 일치, 로컬 링크 16개 누락 0, 반례 9개 확인. git diff --check 통과.
- 이전 전체 문서/구조 시험의 isaac_sim 기준선 실패는 별도 미해결이다. 이번 문서 계약 통과로 그 실패를 해결했다고 주장하지 않는다.
- 테스트·임시 산출물은 X:/DevTemp/rosy-d435-doc-tests 및 rosy-d435-doc-cache에 두었다. 코드·배포·실기 검증은 수행하지 않았다.
