## D-435 작업 오케스트레이션·Fleet·장치 실행을 역할과 권한으로 구분한다

**Status:** Proposed (2026-10-03, 기존 ADR 책임 모델의 재검토 초안). 아직 수용되지 않았으며 기존 Accepted 계약은 계속 유효하다. 역할·용어의 목표 경계를 제안한다. 코드·폴더·패키지·공개 API·DB·실행 밸브·배포·장치 gate를 변경하지 않는다.

### Context

D-12는 초기 Mission DSL을 Fleet 서비스에 두었다. D-21은 Fleet을 formation 오케스트레이터로, D-296은 사이트 Mission·인계·이력의 소유자로 부른다. D-290 §2는 고정 OMX까지 조정할 때 Fleet 확장과 범용 작업 운영으로의 단일 이행 중 하나를 결정하도록 남겼다. D-413과 설계 v0.2는 execution/site와 execution/local을 구분하지만 기존 Fleet 역할 이름도 유지한다. D-427/D-429는 폴더 책임을 정리하면서 이 넓은 Fleet 정의를 계승했다.

그 결과 현재 서비스 구현 이름, 다중 로봇 기능, 범용 작업 실행 책임이 같은 단어로 읽힌다. ER2·사람·반응형 정책·안전도 한 층 표에 들어가면서 역할, 명령 출처, 알고리즘 종류와 권한을 혼동할 수 있다.

첫 검토는 범용 작업 실행과 Fleet coordination을 구분하자고 했다. 그러나 그 안도 아래 반례에는 불충분했다.

- 단일 팔 작업에도 작업 실행은 필요하지만 다중 로봇 조정은 필요하지 않다.
- 문·컨베이어·셀 점유까지 모두 Fleet 자원으로 보면 Fleet을 다시 범용 사이트 조정자로 확대한다.
- Pilot 수동 조작·로컬 정지까지 Mission을 요구하면 현행 사람의 장치 API 경로를 좁힌다(D-369 §7, D-399 §5).
- 단일 원장을 플랫폼 전체 DB 하나로 해석하면 장치 Action 사실의 정본을 중앙화한다(D-413 §2).
- 모든 판단을 ER2 같은 제안자로 제한하면 Fleet 배정 규칙·장치 지역 규칙·승인된 반응형 스킬의 정당한 실행 권한까지 부정한다.

근거: [1차 검토 및 2차 보강](../assessments/2026-10-03-adr-role-and-terminology-review.md). 이 ADR은 후속 결정을 위한 초안이며 현재 구현을 새 역할명으로 개명했다고 주장하지 않는다.

### Decision — 수용 후보

#### 1. 역할, 권한, 배치, 소스 분류를 따로 설명한다

- **역할:** 어떤 규칙·사실·수명주기를 소유하는가.
- **권한:** 무엇을 수락·배정·발행·취소·정지할 수 있는가.
- **배치:** 어느 호스트·프로세스·설치 프로파일에서 실행되는가.
- **소스 분류:** 어떤 파트·모듈·패키지가 그 역할을 구현하는가.

역할 하나가 반드시 서비스 하나는 아니고 같은 프로세스의 두 역할도 같은 권한은 아니다. D-427의 middleware·operations·learning 파트는 유지한다. 이 ADR은 새 최상위 파트·폴더·공통 서버를 만들지 않는다.

#### 2. 작업 오케스트레이션을 범용 운영 역할로, Fleet을 로봇 집합의 조정 역할로 정의한다

| 역할 | 소유 | 소유하지 않는 것 |
|---|---|---|
| 공정(Process) | 레시피·공정 제약·작업 단계와 완료 predicate의 의미, 계획 산출 | 실행 수락 권한, 장치 writer, 범용 실행 원장 |
| 숙고형 판단(Deliberative Decision) | 관측 해석·작업/재계획 후보·기권, 허용된 조회/제안 도구 | Mission admission, 장치 발행·정지·rearm, 자원 점유 정본 |
| 작업 오케스트레이션(Work Orchestration) | 권한·정책을 적용한 Mission 수락, 계획의 단계 진행·취소·복구·결과 연결, 해당 Mission 원장 | 공정 규칙 자체, 모든 자원 규칙, 로컬 폐루프, 최종 물리 명령 |
| Fleet coordination | 로봇 집합의 가용성 기반 배정·교통·로봇 관련 공유 자원·협업 조정 | 모든 공정의 Mission 실행, 모든 사이트 장치 정책, 팔/베이스 writer |
| Formation / Swarm control | 대형 지정·참조·동기 협업의 계약과 장치별 추종 | 일반 공정 실행, 모든 Fleet 기능, 안전 우회 |
| 장치 실행(Device Action owner) | 수락한 Action/attempt의 로컬 진행·취소·복구·중재, 장치 상태, 단일 writer | 상위 Mission 원장, 다른 장치의 writer, 임의 재계획 권한 |
| 검증(Goal verification) | 등록된 근거와 predicate에 따른 완료 확인 | 실행 허가, 안전 reset, 모델 문장을 물리 성공으로 간주 |

ER2는 숙고형 판단 제공자 중 하나다. Fleet은 formation/swarm만을 뜻하지 않지만, 모든 작업을 실행하는 플랫폼 전체의 이름도 아니다. 군집 기능의 현재 배치는 D-21의 Fleet 지정·Leader 참조·Follower 로컬 추종을 유지한다.

Work Orchestration은 operations 안의 논리 역할명이다. `execution/site`의 작업 수락·원장·진행 책임이 출발점이다. **Orchestration과 Execution을 별도 범용 서비스로 이중 신설하지 않는다.** 장치 로컬 execution과 구별하기 위해 문서에서 범위를 붙인다. 호스트를 기준으로 미션 소유권을 결정하지 않는다.

#### 3. 원장·자원·정지 권한을 범위별로 단일화한다

“단일 소유자”는 플랫폼 전체의 서버·DB·writer 하나를 뜻하지 않는다.

- **Mission:** 동일 Mission identity의 수락·진행 원장에는 하나의 논리 소유자만 있다. 현재 Fleet MissionStore에서 출발하고 두 번째 Mission 실행기를 병행하지 않는다. 여러 독립 셀/사이트의 새 실행 소유자·인계·failover는 이 ADR로 열지 않는다.
- **Device Action:** 장치 owner가 Action/attempt·로컬 결과를 소유한다. 상위 Mission 원장은 그 사실을 상관관계로 연결하며 대체하지 않는다.
- **공유 자원:** 로봇 교통·대형·로봇 할당은 Fleet coordination이 맡는다. 셀·문·컨베이어 등 로봇 외 자원의 정책을 자동으로 Fleet 책임으로 승격하지 않는다. 필요해지는 자원은 충돌 집합·claim·grant·해제 증거의 권한 소유자를 명시하는 별도 계약으로 연다. 지금 범용 ResourceManager 서비스는 만들지 않는다.
- **정지:** 상위 발행 차단 세대, 장치 로컬 stop 래치, 물리 E-stop은 서로 다른 범위의 권한이다. 승인·grant는 해당 범위의 현재 세대에 묶이고 어느 하나의 rearm이 다른 래치나 불명 작업을 자동 해제하지 않는다.
- **해제:** 장치 응답이나 연결을 잃었다고 진행 중 점유를 다른 작업에 넘기지 않는다. 해제는 기존 계약의 실행 결과·점유 readback·운영자 조정 근거로 판단한다. 이 ADR은 만료·임대만으로 물리 자원이 비었다고 보지 않는다.

Mission·자원·장치 원장 간 상태 전이를 하나의 분산 exactly-once 보장으로 설명하지 않는다. 현재 단일 DB의 필요한 원자성을 보존한다. 다른 프로세스/DB로 나누려면 별도 실패·재시작·늦은 결과 계약이 필요하다.

#### 4. 실행 경로는 작업·수동·안전을 구분한다

```text
사람/공정/허용된 자동화 ─── 인증·인가된 작업 요청 ─┐
숙고형 Decision(ER2 등) ─── 비실행 후보 ─ 검토/정책 ├─ 작업 오케스트레이션
                                               │   Mission 수락·원장·Step 진행
                                               └─ 필요 시 Fleet/자원 조정 계약
                                                      │ 승인된 Device Action
                                                      v
사람의 장치 직접 조작 ────────────────────────> 장치 로컬 수락·중재·안전
                                                      │ 스킬/로컬 트랜잭션
                                                      v
                                               장치별 단일 최종 writer
```

이 그림은 논리 권한 흐름이며 새 endpoint·process·wire 정의가 아니다.

- 일반 요청자는 기존 인증·인가된 작업 수락 경로를 쓸 수 있다. 모든 정상 공정 실행을 모델 후보나 매번 사람 확인으로 바꾸지 않는다. 사람 확인이 필요한 범위는 기존 정책을 따른다.
- 모델은 조회·후보 경로에만 있다. 모델 credential에는 일반 실행·수락·정지 권한이 없다. `POLICY_DISPATCH_ENABLED=False`, 사이트 장치 후보의 사람 승인 규칙 및 provider egress 게이트를 유지한다.
- 수동 조작은 기존 허용된 장치 API와 MANUAL 중재 경로를 유지한다. Mission 생성이나 상위 서버 가용성을 새 선행 조건으로 만들지 않는다. 장치의 현재 모드·선점·claim 계약을 우회하거나 새 OMX 원격 티칭 경로를 열지 않는다.
- 정지 요청은 Mission 생성·모델 판단·정상 작업 queue를 기다리지 않는다. 현재 인증된 software stop과 독립 물리 E-stop 경로를 유지한다.
- 장치의 Local Transaction은 수락된 Action 내부에서만 진행한다. 상위 작업은 그 내부 제어 주기를 원격으로 지휘하지 않는다. 실시간 협조가 필요한 복합 로봇은 로컬 인터록·writer·복구 계약이 선행하며 현재 OMX/Pinky+OMX 수용을 의미하지 않는다.

#### 5. 계획, 실행 인스턴스, 제공 능력, 메시지를 구분한다

| 용어 | 정의 후보 | 구분 |
|---|---|---|
| Proposal | 검증 전 후보 | 실행 권한·grant 아님 |
| Recipe / PlanBundle | 공정 규칙/버전 고정 계획 산출물 | 생성만으로 실행하지 않음. 현재 Recipe·Job·PlanBundle을 하나의 타입으로 합치지 않음 |
| Mission | 목표와 계획에 결속된 운영 작업 실행 인스턴스 | 한 장치 작업에도 가능. 모든 로컬 조작이 Mission을 요구하지 않음 |
| Step | Mission의 진행·결과 연결 단위 | 현 PlanStep·Mission Step의 대응은 별도 이행 계약. 복수 Action 병렬 지원을 가정하지 않음 |
| Device Action / attempt | 장치가 수락하고 종료하는 유한 요청/그 실행 시도 | Step·ROS goal·메시지와 동일 ID로 합치지 않음 |
| Skill | 호출·전제조건·한계·결과의 재사용 행동 계약과 구현 | 특정 실행은 Action/attempt에 연결. capability 광고만으로 실행 권한을 부여하지 않음 |
| Local Transaction | 수락된 Device Action 내부의 유한한 복합 상태 흐름 | DB ACID transaction과 다름. 그 자체가 물리 rollback을 보장하지 않음 |
| Task | 기존 API별 의미를 가진 호환 용어 | 새 범용 단위로 추가 정의하지 않음. 기존 TaskKind·task_id 대응표 유지 |

정형 공정은 승인된 Recipe/PlanBundle으로 작업을 구성하고, ER2는 허용된 Skill/capability를 참조한 후보를 낸다. 둘은 수락된 뒤 같은 장치 실행·증거 경계를 사용하지만 계획 생성 방식까지 같게 만들지는 않는다.

재계획은 기존 실행을 조용히 수정하거나 실패 동작을 replay하는 것이 아니다. D-358의 successor proposal/Mission 결속, stop/generation 무효화와 기존 admission 규칙을 유지한다.

#### 6. 판단·인식·학습·안전은 서로 다른 축이다

- 숙고형 판단은 후보를 낸다. Fleet 조정 규칙과 장치 지역 규칙은 각각 자신의 승인된 권한 범위에서 결정을 실행할 수 있다. “판단에는 실행권이 없다”를 모든 판단 로직에 일반화하지 않는다.
- 반응형 정책은 승인된 엔벌로프 스킬 안에서만 동작을 생성하는 별도 종류다. 현재 필요한 엔벌로프·장치 수용 계약은 없으며 이 ADR이 이를 구현하거나 열지 않는다. ER2의 제안 규칙을 그대로 반응형 제어 루프의 시간 척도로 사용하지 않는다.
- 인식은 출처·시각·좌표·revision에 결속된 관측 evidence를 제공한다. Learning은 데이터·학습·평가·승격 산출물을 소유하며 운영 중 모델 자체에 실행 허가를 부여하지 않는다.
- 안전은 장치·사이트·물리 경계마다 동작하는 독립 책임이다. 안전을 하나의 단계 상자에 가두지 않는다. D-430의 모델 도구 제한·발행 fence·로컬 Guard·failsafe·물리 E-stop과 기존 상태/한계를 유지한다.
- 독립 완료 판정은 제안 모델의 성공 주장이나 driver 수락 응답을 그대로 승인하지 않는다. 동일 프로세스 사용 여부와 판정 근거의 독립성을 혼동하지 않는다.

#### 7. ER2 후보 fence와 현재 등록·신호 소유권을 보존한다

Decision은 주입된 제안 저장 계약을 사용하고 수락·stop/generation 확인은 기존 운영 권한 소유자가 수행한다. D-358 §4의 후보 가시화·세대 확인 공유 트랜잭션은 현재 DB 안에 유지한다. 역할 구분을 이유로 이를 네트워크 건너 분리하지 않는다.

현 등록/identity 소유권과 로봇 capability 출처, Fleet의 신호 순서 결정, 사이트 장치 owner/펌웨어·읽기 전용 관측, 로봇 도킹 책임은 그대로다(D-361/D-347/D-337/D-429). Fleet 범위를 명확히 한다는 이유로 다른 모듈에 이 책임을 지금 이전하지 않는다. 미래 문·컨베이어·PLC 자원 정책은 §3의 별도 계약 대상이다.

### 기존 결정과의 관계 — 수용 시 적용할 범위

Proposed 동안 아래 부분 대체는 발효되지 않는다. 수용 시 해당 ADR에 명시적 부분 대체 안내와 용어집·설계 정렬을 같은 변경으로 적용한다.

| 기록 | 수용 후보의 영향 | 유지 |
|---|---|---|
| D-12, D-70, D-74의 workflow 소유 표현 | 범용 Mission/Workflow 책임을 Work Orchestration으로 설명. 기존 Fleet 서비스는 초기 구현 | Mission 이중 실행기 금지, CORE API·장치 writer |
| D-290 §2, D-296 §4, D-298 §1 | D-290의 단일 이행 방향 선택. Fleet coordination과 Mission 역할 이름 구분 | 현재 단일 Mission 원장, 로컬 Action/Transaction·증거 구분 |
| D-326, D-333, D-358, D-369, D-392 | 범용 Mission 조항의 Fleet은 작업 오케스트레이션 구현으로 대응. 배정·교통·formation의 Fleet은 그대로 | 모델 allowlist·egress·정지 fence·UNKNOWN·독립 검증·장치 권한 |
| D-399 (Proposed) | 단일 Fleet 띠에 함께 있던 작업 실행과 로봇 집합 조정을 기능적으로 구분 | 장치마다 명령 파이프라인, same-host 반응형 추론 제약 |
| D-413, D-427, D-429 | operations 안의 책임 설명 보강. 역할 분리가 폴더·서비스 신설이 아님을 명시 | 세 파트·공용 계약·한 흐름씩 이전, 기존 import/설치 규칙 |
| D-430 | 안전 체인 중 Mission 발행 권한 설명에 범위를 붙임 | safety 불변식·정지 증거·독립 물리 안전 경로 |

API Reference·CONCEPTS.md·설계 v0.2의 의미 대응은 수용 단계에서 정렬한다. `/api/fleet/*`, 기존 Python import·schema·원장·제품 이름은 이 ADR만으로 개명하지 않는다. 이름이 Fleet인 모든 문자열을 일괄 교체하지 않는다.

### Alternatives

1. **Fleet을 범용 작업 플랫폼으로 유지:** 기존 구현과 가까우나 단일 팔·비로봇 자원·공정 실행의 책임을 군집/로봇 집합 기능과 혼동한다.
2. **Fleet 전체를 Operations/Execution으로 개명:** 이름은 넓어지지만 책임 혼합과 권한 문제를 남긴다.
3. **역할별 새 서비스/DB 즉시 분리:** 원자적 fence·claim·복구가 분산된다. 현재 소비자·부하·운영 요구로 정당화되지 않는다.
4. **장치가 모든 Mission을 실행:** 사이트 인계·공유 자원·전체 목표 원장을 장치마다 복제한다. 수락된 Action 안의 로컬 트랜잭션과 구분해야 한다.

추천은 역할·범위·권한을 먼저 정하고 기존 단일 구현을 단계적으로 위임하는 것이다. 새 기능·서비스·배포는 후속 근거가 있을 때 정한다.

### Consequences

- 고정 팔·단일 로봇·다중 로봇 작업을 Fleet 보유 여부와 무관하게 설명할 수 있다.
- 작업 원장·로봇 조정·로컬 실행의 정본을 분리하면서 기존 프로세스·DB·상호운용을 보존한다.
- 문서상 책임 이전은 다수 ADR·용어집·SRS·설계·실행 계약에 걸친다. Proposed 초안을 추가한 것만으로 정합화가 완료되지 않는다.
- 폴더 구조와 import 시험은 의미·권한·실패 시 동작의 정합성을 대신하지 않는다.

### Validation and follow-up

수용 전 다음 반례를 같은 용어·소유자·권한으로 설명하고 연결된 기존 계약과 대조한다.

| 사례 | 설계가 충족해야 할 조건 |
|---|---|
| OMX 한 대의 정형 팔레타이징 | ER2·다중 로봇 Fleet 없이 공정 계획·Mission 원장·장치 Action·독립 배치 증거를 설명 |
| Pilot 수동 조작/장치 stop | Mission 생성과 상위 서버 가용성을 새 선행 조건으로 만들지 않고 로컬 중재·안전을 통과 |
| 로봇 두 대 운송, formation 없음 | Fleet 배정·교통은 필요하되 군집 추종은 필요하지 않음 |
| Leader/Follower formation | 상위 지정·참조 스트림·로컬 추종의 권한과 시간 척도 분리 |
| 팔 한 대와 미래 컨베이어의 같은 셀 자원 | Fleet에 모든 자원을 몰지 않으며 해당 충돌 집합의 claim 정본이 하나. 지금 지원됨을 주장하지 않음 |
| 미래 Pinky+OMX 복합 작업 | 상위 원장·로컬 트랜잭션·베이스/팔 writer가 분리. 불명 보유 상태에서 HOLD |
| stop 직전 ER2 응답·이전 세대 grant | 후보 가시화/발행을 fence로 차단. 재연결·새 메시지 ID·rearm만으로 재실행하지 않음 |
| Action 수락 직후 응답 상실 | UNKNOWN 보존·조회/조정. 중복 발행과 점유의 성급한 해제 금지 |
| 독립 셀의 병행 작업 | 단일 정본이 전체 플랫폼 단일 DB를 뜻하지 않음. 새로운 분산 소유/인계 지원을 주장하지 않음 |

수용 문서 검사는 번호·Log 행·상태·링크·harness 정합성이다. 이행 전에는 각 현재 API/원장/호출자를 논리 역할과 대응시키고, 의미 변경 여부·claim/fence 원자성·수동 선점/취소·읽기 권한·독립 증거를 확인한다. SOURCE/LOCAL, ROS-SIM, ARTIFACT, DEVICE, FIELD는 각각 별도 증거다.

**현재 미결정:** Work Orchestration의 실제 모듈 추출 경로·설치 단위, 미래 비로봇 자원의 계약, 복수 Action/병렬 Step, 복합 로봇 운영 수용, 독립 셀 실행 소유자와 failover. 이 초안은 이 기능들을 새로 승인하지 않는다.

### 3차 보강 후보 — 2026-10-03: 책임 사이의 연결과 현재 구현 대조

**상태:** D-435는 계속 Proposed다. 아래는 같은 초안의 §2–§5를 구체화·정정하며, 해석이 충돌하면 이 보강을 우선한다. 기존 Accepted 계약·활성화 상태는 바꾸지 않는다. 기준 HEAD `0bdfaa34220dad224fa49945e8db07dc1c2572cc`다.

#### 8. 제안·배정·발행·장치 수락은 다른 결정이다

역할표만으로는 Fleet 배정과 Mission 진행이 같은 장치에 서로 다른 동작을 내릴 수 있다. 따라서 연결을 다음과 같이 고정하는 것을 제안한다.

| 결정 | 권한 소유자 | 다음 역할에 넘기는 것 | 단독으로 만들 수 없는 효과 |
|---|---|---|---|
| 목표/작업 후보 선택 | 사람·공정 요청자, 모델은 제한된 제안자 | 목표·근거·제약·계획 참조 | Mission 수락·장치 실행 |
| Mission 수락·계획 고정 | 작업 오케스트레이션의 기존 정책/원장 | 승인된 계획·작업 범위·상관 identity | 임의 장치 제어·물리 완료 |
| 로봇 배정·교통 자원 결정 | Fleet coordination의 해당 정책/claim 권한 | 배정 결과·가용성/자원 근거 | 별도의 중복 Mission 원장·이미 발행된 Action의 임의 대상 변경 |
| Step의 실행 대상/요청 고정 및 발행 | 작업 오케스트레이션의 dispatch 권한 | 대상·Action/attempt·권한 세대·revision에 결속된 요청 | 장치 수락 강제·장치 안전 우회 |
| Device Action 수락·실행 | 해당 장치 owner | 상관된 접수·진행·terminal/readback | 상위 Mission 완료를 독자 확정 |
| 작업 목표 확인·다음 Step 진행 | 등록 verifier의 증거 + 작업 원장의 전이 규칙 | 검증 근거와 실행 상태 연결 | 모델 주장/driver 성공만으로 목표 확정 |

배정 결과는 배정 권한의 결정이며 모델 후보와 같은 무권한 텍스트가 아니다. 동시에 배정 결정이 곧 물리 실행 허가는 아니다. 발행 권한은 그 결과와 현재 자원·장치 조건을 검증해 요청에 고정한다. 특정 OMX workcell처럼 대상이 설치 구성에 고정된 작업에는 Fleet 로봇 선택을 억지로 끼우지 않는다.

발행 뒤 재배정은 기존 Action 대상 필드를 바꾸는 일이 아니다. 기존 실행의 미발행/취소/종료/UNKNOWN과 자원 점유를 조정한 뒤 새로 권한을 검증해야 한다. 새 자동 재배정·attempt 재실행 정책은 이 ADR로 열지 않는다. 하나의 역할이 승인과 배정을 구현하더라도 각 결정과 근거는 구분한다.

#### 9. 현재 claim·dispatcher를 새 책임으로 이중화하지 않는다

현재 [dispatch_admission.py](../../src/site/fleet/fleet/server/dispatch_admission.py)는 `robot`, `workcell`, `object`, `pallet` 자원을 같은 `fleet_action_claims`에서 예약한다. 따라서 §3의 비로봇 자원 서술을 **모든 비로봇 claim이 미래에 새로 필요하다**는 뜻으로 읽으면 틀리다. 이미 존재하는 workcell·object·pallet claim은 현재 공용 admission 경계에 유지한다. 미래 문·컨베이어의 상태/인터록·claim 계약이 별도라는 뜻이다.

- Fleet의 로봇 배정·교통 정책과 공용 claim 저장은 다른 책임이다. 저장소 이름이 Fleet이라는 이유로 모든 자원 정책을 Fleet 기능으로 정의하지 않는다.
- 역할을 구분하며 동일 자원에 Fleet claim과 Mission claim 저장소를 병렬 신설하지 않는다. 현재 공용 DB/예약 트랜잭션을 사용한다. 저장을 분리할 경우는 다른 결정이다.
- 현재 [mission_dispatcher.py](../../src/site/fleet/fleet/server/mission_dispatcher.py)와 [step_dispatcher.py](../../src/site/fleet/fleet/server/step_dispatcher.py)는 서로 다른 지원 작업을 진행한다. “단일 발행 권한”은 dispatcher 객체 하나로 모두 합친다는 뜻이 아니다. 동일 실행 identity에 상충하는 발행 권한을 만들지 않고 현재 claim·세대·원장 fence를 공유한다는 뜻이다.
- 예약 실패·발행 직전 stop·장치 거절·응답 상실을 모두 동일 실패로 취급하지 않는다. 발행 전 실패는 아무것도 실행하지 않았다는 근거가 있을 수 있지만, transport 호출 뒤 응답 상실은 UNKNOWN이며 조회·조정 대상이다.
- 자원 해제는 현재 작업의 **전체 진행 이력**을 본다. [CellJobStore](../../src/site/fleet/fleet/server/cell_job_store.py)의 `release_before_send`는 처음 Step에서 아무것도 발행하지 않은 경우만 해제하고, 앞선 진행이 있으면 HELD로 둔다. “현재 Step 미발행”만으로 팔레트/물체/셀 상태가 원래대로라고 판단하지 않는다.

이 정적 대조는 현재 구현을 범용 자원·재배정·병렬 작업 수용으로 확대하지 않는다.

#### 10. Skill 정의와 실행 identity를 분리한다

현재 [SkillInvocation](../../contracts/skill/src/rosy/contracts/skill/invocation.py)은 `skill_id`, `version`, `inputs`를 담는다. Action/attempt identity와 권한은 다른 계약이다. §5의 Skill 서술을 다음으로 보강한다.

- **Capability:** 해당 장치가 현재 제공한다고 광고하는 능력과 revision. 가용성·모드·프로파일·준비 상태로 제한되며 권한은 아니다.
- **Skill 정의/Invocation:** 재사용 행동의 버전·입력·전제·한계·결과 계약 및 특정 호출 내용. Invocation만 생성해도 장치가 실행하지 않는다.
- **Device Action/attempt:** 장치가 수락한 유한 실행의 identity·진행·종료·readback. 현재 지원 범위에서 Skill 호출을 이 실행과 연결한다.
- **ROS goal/driver 명령:** 장치 내부의 구체 실행. Skill 하나가 반드시 ROS goal 하나이거나 Mission Step 하나라고 가정하지 않는다. 현재 1 Step → 1 Action 제약은 유지하며 복수·병렬 동작을 구현됐다고 표현하지 않는다.

단일 장치에 Mission이 필요할지는 목표·진행 원장·재시작 복구 요구로 정한다. 허용된 수동 조작은 Mission을 요구하지 않는다. 장치 밖에서 만든 SkillInvocation은 로컬 Action 수락·중재·안전 경계를 생략하는 지름길이 아니다.

#### 11. 장치 파이프라인의 안전 위치를 명확히 한다

§4 그림은 역할 연결을 줄여 그린 것이며, `로컬 수락·중재·안전 → 스킬 → writer`라는 실제 실행 순서로 읽으면 잘못이다. 동작 출처가 만든 출력은 단일 writer **전에** 중재·안전을 통과해야 한다. D-399의 목표 내부 경로를 다음과 같이 읽는다.

```text
장치 요청 수락 → 승인된 스킬/Local Transaction → 동작 의도 ─┐
허용된 MANUAL 입력 ────────────────────────────────┤
                                                 v
                                         장치 명령 중재(Arbiter)
                                                 v
                                         안전 제한/정지(Guard)
                                                 v
                                      로컬 실행·장치별 단일 writer
```

이것은 공통 Motion Intent schema나 새 실행기를 구현했다는 뜻이 아니다. 현재 Pinky와 OMX의 실제 graph는 각각 검증한다. 최종 출력 검사는 스킬/정책/수동의 출처와 무관하게 적용되며, 진입 시 검증 한 번으로 실행 중 안전을 대체하지 않는다. 장치의 기존 watchdog·stop·상한·모드·링크 상실 정책은 그대로다.

Safety는 이 출력 경계 외에도 모델 도구·운영 발행·사이트 failsafe·물리 회로에 있다. 중앙 Orchestration/Decision이 끊겨도 장치 안전을 그 서버가 대신 판단하는 구조로 만들지 않는다.

#### 12. 수용 판단을 형식 검사와 의미 검증으로 나눈다

문서 시험·lint는 제목·상태·참조·기록 형식을 검사한다. 역할이 옳다는 증거는 아니다. 수용 전에는 §8의 각 결정에 대해 현재 생산자·소비자·권한·원장·실패 후 상태를 대응시키고 다음 질문에 답해야 한다.

1. 고정 OMX 작업에 로봇 배정 없이 현재 Mission/Step→Action→독립 목표 증거를 연결할 수 있는가?
2. Fleet가 다른 로봇을 선택해도 이미 발행된 Action을 수정/중복하지 않는가?
3. 한 작업의 admission이 다른 Mission·direct Action과 동일 자원의 claim에서 충돌하는가?
4. transport 호출 전 미발행 실패와 호출 후 UNKNOWN의 해제·재시도 정책이 구별되는가?
5. MANUAL 선점 뒤 상위 작업이 스스로 재개하지 않고 로컬 상태·현재 권한을 다시 확인하는가? OMX의 미수용 선점은 미수용으로 남는가?
6. 목표 실패 시 공정/재계획 후보와 운영 원장 전이를 구분하고, 고정 PlanBundle 밖의 공정 분기를 임의로 만들지 않는가?
7. 동작 출력이 안전을 통과하며, 공통 내부 스키마/엔벌로프의 미구현 부분을 명확히 표시하는가?

**수용 기준:** 목표 역할의 논리적 일관성과 현재 계약 대응이 설명되면 명명·책임 결정은 수용 후보가 된다. 실기·분산 실행·재배정·정책 자동화는 각 별도 gate다. 이 초안은 전체 플랫폼의 최종 계층 설계나 구현 수용 완료를 선언하지 않는다.

#### 13. Fleet와 실행 분리는 ROSY의 책임 모델 선택이며 보편적 금지 규칙이 아니다

2026-10-03 공식 자료를 대조했다.

- [Open-RMF rmf_demos — task allocation](https://github.com/open-rmf/rmf_demos/blob/main/README.md#task-allocation): Dispatcher가 여러 fleet의 입찰을 비교하고 선택한 fleet에 작업을 배정한다.
- [Open-RMF rmf_task — Usage](https://github.com/open-rmf/rmf_task#usage): 작업 정의/모델과 실제 로봇에 명령하는 Active 구현을 구분하며, Active 구현은 fleet adapter에 있다. 따라서 Fleet와 관련된 구현이 작업 실행을 맡는 구조 자체가 오류라는 주장은 성립하지 않는다.
- [ROS 2 Actions 설계](https://design.ros2.org/articles/actions.html): 서버는 goal 수락/거절·진행·취소·result를 소유한다. ROSY Mission/Action과의 대응은 ROSY 계약이 결정하며, ROS action이라는 이름만으로 상위 작업 정본이나 물리 목표 증거를 정의하지 않는다.

이 자료로부터의 **ROSY 설계 판단**은 다음이다. 고정 셀·다중 로봇·사이트 장치까지 다루는 플랫폼에서는 전체 Mission의 정본과 로봇 집합의 조정을 구분하는 것이 유용하다. 이것이 업계 유일 구조이거나 모든 실행 코드를 Fleet 밖으로 옮겨야 한다는 뜻은 아니다.

Fleet가 배정된 로봇 작업의 순서·진행을 실행할 수 있다. 이때 상위 Mission과 Fleet가 맡은 범위가 달라야 하며, 동일 Mission을 두 소유자가 승인·진행·완료 처리하지 않는다. 실제 Fleet 구현 안에 작업 오케스트레이션 역할이 함께 있어도 역할·권한·원장 계약을 구분하면 된다. 따라서 §2/기존 결정 표의 책임 분리는 **논리 정본의 분리**이며 실행 코드의 물리적 격리 명령이 아니다. 현재 지원하지 않는 위임·중첩 작업 계약을 새로 열지는 않는다.

기존 허용된 장치 직접 요청도 MANUAL에 한정하지 않는다. SDK/대시보드 등 인증·인가된 클라이언트가 기존 장치 API로 유한 작업을 요청할 수 있으며, 플랫폼 차원의 Mission을 새로 만들 필요는 없다(D-74/D-369/D-399). 장치 수락·중재·안전·상충 작업 선점 정책은 적용되고 모델 credential에는 이 경로를 주지 않는다. 새 운영 OMX API나 티칭 경로를 허용한다는 뜻은 아니다.

따라서 최종 수용 후보는 **전체 Mission 정본 / 로봇 집합의 조정·해당 범위 실행 / 장치 로컬 Action·최종 제어**의 경계를 명시하는 것이다. “Fleet는 군집 추종뿐”, “Fleet는 플랫폼 전체 실행기”, “모든 요청은 중앙 오케스트레이터를 거친다”의 어느 문장도 목표 구조의 공통 정의로 사용하지 않는다.

### 최종 수용 후보 요약 — 2026-10-03

이 절은 D-435의 수용 대상 조항을 하나로 정리한다. 앞부분은 검토 이력과 근거로 보존한다. Proposed 초안 안의 표현이 충돌하면 이 요약을 우선한다. **아직 Accepted는 아니며, 아래에서 유지한다고 명시한 기존 계약은 계속 유효하다.** 수용 범위는 용어·논리 역할·권한 경계이고 서비스/코드 이전·공개 API 변경·자동화 활성화·실물 수용은 별도다.

#### S1. 역할별 소유 사실과 권한

| 역할 | 소유하는 사실·규칙 | 허용되는 결정 | 얻지 않는 권한 |
|---|---|---|---|
| 공정(Process) | 레시피·공정 제약·계획 산출·완료 조건의 의미 | 공정 계획 구성·검증 | 이름만으로 Mission 승인·장치 발행 |
| 숙고형 판단(Deliberative Decision) | 관측 해석·작업/재계획 후보·기권 | 허용된 조회·후보 제출 | Mission 승인·직접 구동·stop/rearm |
| 작업 오케스트레이션(Work Orchestration) | 해당 Mission의 승인된 계획·진행·취소·복구·전체 결과 원장 | principal 권한·정책·필요한 승인을 적용한 수락, Step 요청 발행·결과 연결 | 공정 의미의 임의 변경·장치 제어 루프·모든 자원 정책 |
| 로봇 집합 조정(Fleet coordination) | 로봇 배정·교통·협업·해당 범위 자원 정책 | 로봇/자원 배정, 맡겨진 로봇 작업의 범위 내 진행 | 같은 전체 Mission의 두 번째 정본·다른 장치 writer |
| 장치 실행(Device Action owner) | 수락한 Action/attempt의 진행·취소·복구·장치 상태·최종 명령 | 로컬 수락/거절·중재·제어·정지 | 전체 Mission 승인/정본·다른 장치 writer |

Formation/Swarm는 Fleet 지정·Leader 참조·Follower 로컬 추종의 협업 기능이다(D-21). Fleet 전체나 범용 공정 실행과 같은 이름으로 쓰지 않는다. 역할 하나가 반드시 모듈·서비스·DB 하나는 아니다. 현재 Fleet 서비스가 여러 역할을 구현하는 것은 허용하며, 그 역할과 권한은 문서에서 구별한다.

안전·목표 검증·관측·학습은 위 다섯 역할의 상하 실행 계층이 아니다. 각 경계의 안전 제한, 등록된 완료 근거, 출처가 있는 관측, 승격된 산출물 흐름으로 설명한다. ER2는 숙고형 판단의 제공자이지 플랫폼 전체 판단/제어 계층의 이름이 아니다.

#### S2. 작업·조정·장치 계약의 흐름

```text
요청/모델 후보 → 권한·공정 계획 검증·필요한 사람 승인 → Mission 수락/원장
                                                       │
                     필요 시 로봇 배정·교통/공유 자원 결정│
                                                       v
                     Step의 대상·Action/attempt·권한 세대·revision 고정
                                                       │
                     발행 직전 재검사 → Device Action 요청 → 장치 수락/거절
                                                       │
               장치 스킬/로컬 트랜잭션 → 동작 출력 → 중재 → 안전 → 단일 writer
                                                       │
                    Action readback + 등록된 독립 목표 증거 → Step/Mission 전이
```

고정 OMX workcell에 Fleet 로봇 선택은 필수가 아니다. 로봇 배정은 해당 정책 권한의 결정이지만 장치 실행 허가/수락/완료와 동일하지 않다. 발행된 Action의 대상은 조용히 바꾸지 않는다. 재배정·재시도는 이전 실행·점유·UNKNOWN을 조정하고 새 권한 검증이 필요한 별도 동작이다. 현재 자동 재배정·다중 attempt·병렬 Step을 새로 열지 않는다.

#### S3. 승인과 principal은 역할 이름에서 추론하지 않는다

“공정 요청자”, “일반 클라이언트”, “Decision” 같은 역할명은 credential에 새로운 권한을 주지 않는다. 요청·제안·해석·admission·장치 발행·stop·rearm의 허용 여부는 기존 인증·인가와 해당 작업 정책을 따른다.

- D-403의 **Rosy Cell 사이트 서비스 principal은 제안·resolve만** 한다. 운영자 credential을 갖지 않는다. **이름 있는 사람 운영자가 Job 실행을 승인**하며 simulation 범위·같은 호스트 UDS·실물 hold를 유지한다. 정형 레시피/PlanBundle 생성은 이 승인을 대신하지 않는다.
- ER2/provider credential은 기존 scoped 조회·제안 allowlist만 사용한다. `POLICY_DISPATCH_ENABLED=False`, provider egress gate, 사이트 장치 후보의 사람 승인 규칙을 유지한다.
- 기존 장치 API에 허용된 SDK/대시보드/사람의 유한 요청·MANUAL·정지는 Mission 생성이나 상위 서버 가용성을 새로 요구하지 않는다. 로컬 모드·상충 claim·선점·안전은 적용하며, 미수용 OMX API/티칭·자동 선점·재개는 열지 않는다.
- 소프트웨어 정지는 Mission 정상 queue·모델·감사 성공을 기다리는 경로로 바꾸지 않는다. 물리 E-stop은 독립 경로다.

#### S4. 정본과 점유의 범위

동일 Mission identity의 승인·진행 정본은 하나다. 장치 Action/attempt의 정본은 장치 owner이고, 상위는 그 사실을 연결한다. Fleet가 맡은 로봇 작업의 진행과 전체 Mission 원장은 범위를 구별한다. 위임·중첩 작업의 새 wire/운영 경로는 이 결정으로 활성화하지 않는다.

현재 robot/workcell/object/pallet claim은 공용 `dispatch_admission`과 기존 DB 트랜잭션에 유지한다. Fleet 조정 정책과 claim 저장 책임을 구분하되 동일 자원의 경쟁 저장소를 만들지 않는다. 미래 문·컨베이어·PLC는 자기 정책·claim·인터록 계약이 필요하며 모두 Fleet 기능으로 간주하지 않는다.

발행 전 실패는 전체 이력에 실행 효과가 없다는 근거가 있을 때만 기존 규칙에 따라 해제할 수 있다. 이전 Step 효과·진행 중/UNKNOWN Action은 미발행 또는 연결 상실만으로 해제하지 않는다. 조회·readback·운영자 조정은 재실행과 구분한다. 단일 정본은 전체 플랫폼 서버/DB 하나나 분산 exactly-once 보장이 아니다.

#### S5. 명령과 증거

Capability는 제공 능력과 현재 revision, Skill 정의는 행동 계약, SkillInvocation은 버전/입력 호출 내용, Action/attempt는 장치 실행 identity다. Mission/Step·grant·메시지 ID·ROS goal과 합치지 않는다. 현재 1 Step→1 Action 제약을 보존하며 Local Transaction은 Action 내부의 유한한 동작 절차이고 물리 rollback 보장이 아니다.

요청 접수·승인·Action 수락·terminal result·GOAL_CONFIRMED·software stop latch·물리 정지는 다른 사실이다. Step 진행은 현재 등록된 predicate/증거 규칙으로 판단하며 driver 성공·모델 문장만으로 목표를 확정하지 않는다. 안전·stop 세대·로컬 래치·상한·watchdog·링크 상실 정책은 별도 권한이고 어느 하나의 rearm/재연결도 불명 작업의 자동 재개를 허가하지 않는다.

#### S6. 기존 결정의 부분 대체 범위와 현재 구현 대응

**수용 때 부분 대체할 의미:** D-12/D-70/D-74의 범용 workflow 소유 표현, D-290 §2의 이행 선택지, D-296 §4·D-298 §1의 전체 Mission 역할명. 범용 작업 정본을 Work Orchestration으로 설명하며 현재 Fleet 서비스를 초기 구현으로 대응한다. CORE에 별도 사이트 workflow 실행기를 추가하지 않는다.

**유지할 의미:** D-21의 formation 역할, D-333/D-358/D-369/D-392의 allowlist·fence·UNKNOWN·증거·장치 writer, D-403의 Cell 서비스 principal/사람 승인/simulation 경계, D-427의 세 파트·의존 방향, D-429의 등록/신호/사이트 장치/로봇 도킹 책임, D-430의 독립 안전 불변식. 전체 Mission 설명에서 Fleet이라는 이름을 정리하는 것이 이 권한을 다른 주체로 넘기거나 활성화하는 승인은 아니다.

| 현재 구현/계약 | 대응 역할과 검증 범위 |
|---|---|
| `fleet/ai/tool_dispatch.py`, `proposal_store.py` | scoped 후보·effect 저장, stop/generation 원자적 확인. 후보는 실행 허가가 아님 |
| `mission_service.py`, `mission_store.py`, `cell_job_store.py` | 현재 지원 Mission/Cell Job의 수락·진행 원장. Cell service와 operator 권한 구분 |
| `dispatch_admission.py`, Fleet 배정/traffic/formation | 공용 claim 저장과 로봇 조정 정책. 고정 OMX 대상과 미래 범용 배정 구분 |
| `mission_dispatcher.py`, `step_dispatcher.py`, 장치 transport | 지원 작업별 대상·grant 결속·발행 직전 fence·UNKNOWN readback. 별도 객체가 동일 실행의 중복 정본을 뜻하지 않음 |
| CORE/OMX 장치 owner, local stop/runner | 각 제품의 Action/제어/정지 권한. 목표 공통 파이프라인과 실제 수용 graph를 구분 |
| `goal_evidence_service.py`, `cell_goal_evidence_service.py`, 등록 verifier | 실행 결과와 독립 목표 근거의 연결. 실제 provider·device·field 수용은 별도 |

현재 대응표는 역할의 출발점이며 모든 기능의 구현 완료표가 아니다. 기존 서비스/API·Python namespace·schema·DB·소스 루트는 지금 바꾸지 않는다. 수용 시에는 Accepted ADR의 부분 대체 안내·CONCEPTS·설계/SRS의 관련 의미를 같이 정렬하고, 그 후 호출자·상태/ID·권한·claim 원자성·설치 경로를 보존하는 이행 단위를 별도로 정한다.

#### S7. 이번 결정의 완료 조건

역할별 정본·권한, 위 흐름, 유지/부분 대체 범위가 같은 용어로 설명되고 기존 producer/consumer 및 실패 상태와 충돌하지 않으면 **책임·명명 결정**의 수용 후보로 충분하다. API/모듈 이전·범용 자원·위임·failover·복합 로봇·반응형 정책 자동화·실기 성능/안전은 별도 구현·수용 과제이며 이 결정의 완료를 그 기능들의 완료와 동일시하지 않는다.

문서 형식 검사와 역할/권한 정적 대조는 기록하되 아키텍처의 유일 정답·물리 성공·현장 안전의 증거로 사용하지 않는다. 수용 때 새 추상화/서비스를 더 늘리기보다 S1–S6의 계약 범위를 먼저 고정한다.

#### S8. ROSY Platform 이름과 D-427 소스 이전의 관계

이 조항은 S1–S7을 진행 중인 [D-427 이전 계획](../plans/2026-10-03-d427-source-migration.md)과 연결한다. **ROSY Platform은 제품 이름, middleware/operations/learning은 소유 파트, Work Orchestration/Fleet coordination은 논리 역할**이다. 이 세 분류를 같은 계층 목록으로 사용하지 않는다. ROSY Site는 설치 범위, Console/Pilot은 화면, 모델 PC/관제 PC는 배치 역할이다. 어느 이름도 단독으로 principal 권한·프로세스 수·설치 closure를 정하지 않는다.

| D-427 이전 대상 | D-435 해석 | 이전 때 유지할 경계 |
|---|---|---|
| `modules/execution` → `operations/execution` (3a) | 작업 계획·제출 경계의 현재 추출 부분 | 현재 Cell submission 검증은 설명 데이터를 만들 뿐 admission·원장·장치 실행이 아니다. 폴더 이름을 근거로 새 실행기/DB를 만들지 않는다 |
| `apps/gateway` → `operations/apps/fleet` (3a) | 현재 Fleet 사이트 앱의 조합 | `rosy_gateway.compose`는 기존 Fleet factory/CLI를 호출한다. 새 Operations 서버가 아니라 같은 실행 조합의 소스 이전이다 |
| `src/site/fleet` → `operations/fleet` (3c) | 현재 Work Orchestration과 Fleet coordination을 함께 구현한 패키지 | Mission/Cell Job 정본·공용 claim·admission·dispatch·신호 순서의 현재 owner를 유지한다. 역할명 정리와 구현 추출 완료를 구별한다 |
| `fleet/ai` → `operations/decision` (3c carve) | 숙고형 판단 제공자 | D-429 §5의 명시적 namespace 예외를 따른다. import·설치와 proposal/stop fence의 같은 트랜잭션을 보존하며 별도 모델 서버로 바뀌었다고 해석하지 않는다 |
| `execution/local` → `middleware/execution/local` (2c), 장치 패키지 (4a–4e) | 장치 실행 쪽 코드 | 기존 import identity·Action 사실·로컬 stop·단일 writer를 유지한다 |
| `fleet/server/web` → Console 후속, Robot/Pilot UI 이전 | 화면 책임 | D-425의 기능/인증/설치 조건을 유지한다. 화면 이전이 서버·원장 이전을 뜻하지 않는다 |

매니페스트 `path`는 현재 소스 위치, `d427_target`은 승인된 목표 위치, `wave`는 이전 묶음, `part`는 소유 파트, `concern`은 주 관심사다. `concern: decision`은 ER2 권한이나 Work Orchestration/Fleet 세부 역할표가 아니다. `deferred`도 실제 경로 일치·후속 작업을 확인해야 하며 그것만으로 추출 완료를 주장하지 않는다. 역할 대응은 위 표와 현재 코드 근거로 설명하고 기존 매니페스트 schema에 새 권한 필드를 넣지 않는다.

**권고 이행:** D-427 목표 경로와 wave를 유지하며 역할 설명을 정렬한다. `operations/orchestration` 같은 새 이전 목적지나 두 번째 앱/원장은 지금 추가하지 않는다. 범용 작업 코드의 물리 추출은 D-435 수용 뒤 호출자·상태·claim 원자성·설치·재시작/UNKNOWN 증거를 갖춘 별도 단위로 판단한다. 현재 Fleet 패키지에 함께 있는 책임을 문서에서 구별하는 것은 이 과제를 이미 끝냈다는 뜻이 아니다.

검증 출구도 구별한다. D-427의 SOURCE_CANDIDATE/ARTIFACT_EQUIVALENT는 경로·설치 동등성, D-435는 용어·책임 결정, Cell 종단 시험과 DEVICE/FIELD는 작업/장치 수용이다. 이름 변경이나 host pytest로 이 출구들을 서로 대신하지 않는다. D-434의 모델 PC·관제 PC 배치 결정은 별도이며 ER2의 실제 추론 호스트는 배포 증거 없이 이 표에서 확정하지 않는다.
