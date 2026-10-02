## D-413 ROSY는 modules·integrations·apps·profiles로 책임을 나누고 고정 셀 한 흐름부터 이전한다

**Status:** Accepted (2026-10-02, 사용자 요청에 따른 목표 구조·단계적 이전 결정). 코드 이동·패키지 설치·공개 API 변경·시뮬레이션·실물 수용은 이 기록으로 완료되지 않는다.

## 배경

[플랫폼 설계 v0.2](../reference/ROSY_Platform_Architecture_Design_v0.2.md)는 기능 규칙, 외부 기술 연결, 실행 조합, 설치 구성을 구별한다. 현재 저장소는 `src/{contracts,runtime,products,drivers,site,hmi,sim}`로 분류하지만 분류와 실제 책임이 일치하지 않는 곳이 있다.

- `runtime/services/core_features`에는 실행 중재·안전·상태와 navigation·docking·decision이 함께 있다.
- `site/fleet/fleet/server`에는 HTTP 조합과 Mission 원장·권한·dispatch·판단 워커가 함께 있다.
- `products/omx/adapter`에는 vendor 연결뿐 아니라 Action journal·owner·조작 절차·계획이 들어 있다.
- `contracts/foundation/core_common`에는 wire schema·사이트 계약·장치 설정·identity와 공유 규칙이 섞여 있다.
- `site/cell/rosy_cell`은 이미 ROS 없는 레시피·패턴·Job 컴파일러다. 첫 공정 추출에 사용할 수 있다.

새 폴더만 만들면 이 혼합이 그대로 이동한다. 반대로 전면 패키징·API 개편을 한 번에 하면 실행 권한과 설치 경로의 회귀를 구분하기 어렵다. 따라서 실제 소비자와 작업 흐름을 기준으로 이전한다.

## 결정

### 1. 네 영역은 책임 기준이다

| 영역 | 소유 책임 | 갖지 않는 책임 |
|---|---|---|
| `modules` | 실행·관측·판단·Skill·공정·학습의 데이터와 규칙, 소유 모듈의 공개 API | 모델 SDK, 장치 연결, 앱 기동 |
| `integrations` | 모델·행동 정책·로봇·계획기·시뮬레이터·저장소 연결 | 공정 규칙과 별도 실행 권한 |
| `apps` | 필요한 모듈과 연동의 조합, API·UI·프로세스 수명주기 | 공정·권한 정책의 중복 구현 |
| `profiles` | 장치·셀·모델·설치의 선언형 선택과 버전 참조 | 임의 코드 실행, 비밀값, 권한의 자체 발급 |

`deploy`, `tools`, `tests`, `docs`, `firmware`는 각각 배포·개발·검증·문서·MCU 수명주기를 유지한다. 모든 하위 폴더를 별도 wheel이나 서비스로 만들지 않는다. 존재하는 책임과 소비자가 확인된 단위만 생성한다.

### 2. 실행의 사이트와 장치 소유권을 유지한다

`modules/execution/site`는 Fleet의 Mission·Step·공유 자원·장치 배정·전체 결과를 맡는다. `modules/execution/local`은 장치 owner의 Action·attempt·취소·재시작 복구와 로컬 실행 규칙을 맡는다.

사이트 MissionStore와 장치 ActionStore는 서로 다른 사실의 정본이다. 공통 중앙 DB나 하나의 범용 상태 기계로 합치지 않는다. Mission/Step/Action/attempt/ROS goal, grant digest, authority epoch와 dispatch generation의 상관관계를 보존한다. 사이트 접수, 장치 수락, 제어기 결과, 독립 완료 증거는 구분한다.

Pinky CORE는 로컬 `apps/agent`의 구성으로 이어진다. 이름이 gateway였다는 이유로 사이트 `apps/gateway`로 옮기지 않는다. D-1의 단일 프로세스와 D-2/D-38의 최종 cmd_vel writer를 유지한다. OMX도 로컬 owner를 유지하고, 사이트가 ROS goal을 직접 제출하지 않는다. 장치별 상태·정지 규칙을 공유하는 것은 실제 동등성이 확인된 범위에 한한다.

### 3. 계약을 소유 모듈에 둔다

`world.api`는 관측 참조·좌표·보정 revision·Snapshot을, `skills.api`는 Skill 호출·전제조건·결과를, `execution.api`는 내부 계획·수락·결과 연결을 소유한다. `world`의 실행 표시는 각 원장의 사건을 반영한 projection이며 스트림별 watermark를 가진다. 슬롯·층 완성 규칙은 팔레타이징 공정에 남긴다.

첫 PlanBundle은 고정 셀에 필요한 Step·Skill 버전·레시피/셀 해시·허용 한계·완료 조건·검증 참조만 담는다. 공정 구현을 import하지 않고 공정 산출물을 버전·digest로 참조한다. 기존 Job은 승인된 실행 권한이 아니다.

새 내부 타입을 만든 뒤 기존 wire schema를 무조건 대체하지 않는다. D-18의 정본에서 각 타입을 실제 이전할 때 소유자·생산자·소비자·호환 import·직렬화를 함께 전환한다. 기존 schema와 새 API에서 같은 의미의 타입을 독립 정의하지 않는다. 공개 메시지를 바꾸는 작업은 API Reference·schema·양 끝 시험을 함께 변경한다.

### 4. 공정·Skill·제품 연동을 나눈다

Cell 레시피·패턴·적층·순서는 `modules/processes/palletizing`, 조작 절차·전제조건·결과 증거는 `modules/skills/manipulation`, OMX 관절·그리퍼·FK/IK·ROS 연결은 `integrations/robots/omx`에 둔다. 계획기는 Skill이 정의한 포트를 구현한다. 현재 OMX 해석 IK는 제품 연동에 남기며 MoveIt 도입을 구조 이전의 선행 조건으로 삼지 않는다.

D-403의 `CELL_TRANSFER`는 pick+place 한 쌍이다. 내부 계획을 도입해도 독립 PICK/PLACE 동작이나 새 실행 경로를 열지 않는다. `pallet_done`은 사이트 원장 표지로 처리한다. 계획은 로컬의 최신 상태와 다시 대조한 뒤 owner를 통해 제출한다.

### 5. 판단과 학습은 실행 권한을 갖지 않는다

판단 계약·컨텍스트·모델 선택은 `modules/decision`, 공급자 SDK는 `integrations/models`, 승인된 행동 정책 연결은 `integrations/policies`에 둔다. 학습·추론·시뮬레이션 worker의 산출물은 제안 또는 정책 아티팩트다. D-392의 도구 allowlist와 기존 재판단 비활성 경계를 유지한다. 이번 이전은 모델 활성화·원격 추론·물리 dispatch 승격을 포함하지 않는다.

### 6. 기존 진입점을 단계적으로 전환한다

Fleet API 조합은 사이트 gateway, Pinky·OMX 실행 조합은 각 agent로 이어진다. Dashboard·Pilot·Cam·얼굴 화면은 기존 제공 서버·인증·설치 대상을 유지한다. 기존 서버와 같은 역할의 새 서버를 병렬로 만들지 않는다.

책임 추출 → 기존 진입점의 위임 → 설치 산출물 전환 → 호출자 전환 → 호환층 제거 순서로 진행한다. 임시 호환층은 단방향이며 제거 조건과 범위를 기록한다. 폴더 이동·Python 네임스페이스·wheel·ROS 패키지 이름·외부 타입 변경을 한 작업에 묶지 않는다.

### 7. 최소 설치를 산출물로 검증한다

Python 기능 모듈은 필요한 단위의 `rosy.*` 네임스페이스 wheel, ROS/C++ 코드는 기존 빌드 체계를 사용한다. 이 ADR은 특정 빌드 도구를 새로 도입하지 않는다. wheel과 ament가 같은 파일을 이중 소유하지 않도록 한다.

Pinky에는 불필요한 팔·학습·GPU 의존성이, OMX에는 Pinky 드라이버와 전체 학습 환경이 따라오지 않아야 한다. 프로파일은 선언하고 deploy는 release lock과 실제 설치 집합을 검증한다. 저장소·개발 PYTHONPATH 없이 설치 후 진입점과 정적 자산을 확인한다.

### 8. 첫 전환 단위는 고정 셀이다

첫 흐름은 AI 없는 Recipe/Cell → Job → PlanBundle → Fleet 승인·grant → OMX Action → 독립 결과 확인이다. D-401~D-404와 [Cell 완성 계획](../plans/2026-10-01-rosy-cell-completion.md)의 기존 구현·시험을 재사용한다.

첫 ROS-SIM 시나리오는 2층·슬립시트 1장·팔레트 2개다. Gazebo 제어기 완료만으로 물품 배치 성공을 확정하지 않는다. 단절·늦은 ACK·취소·재시작과 불명 결과의 HOLD/reconcile을 함께 시험한다. SOURCE, LOCAL, ROS-SIM, ARTIFACT, DEVICE, FIELD는 각각 기록한다. 실물, Pinky 인계, AI 폐루프는 첫 전환 밖이다.

## 기존 결정의 변경 범위

| 결정 | 처리 |
|---|---|
| D-231·D-310·D-317 | 네 영역을 목표로 채택한다는 범위에서 현 소스 배치의 영구 유지 결정을 대체한다. 아직 전환하지 않은 패키지는 기존 경로·시험을 유지한다. 실제 경로 허용표는 계획의 단계별 전환과 함께 변경한다. |
| D-315 | 유지. 폴더가 package·process·writer·host·설치 단위를 대신하지 않는다. |
| D-18 | 현재 schema 정본 유지. 타입별 새 정본으로의 이관은 호환 및 producer/consumer 검증이 끝난 시점에만 적용한다. |
| D-1·D-2·D-38·D-296·D-333·D-336·D-369 | 유지. Pinky 단일 프로세스, 장치별 owner, 같은 호스트 OMX UDS, 수락·실행·정지 증거 구분. |
| D-340 | `apps`가 실행 조합 전반을 담는 목표는 이 결정을 따른다. 기존의 선택적 앱 셸 구상은 개별 화면 배포 책임 안에서 검토하며 셸 구현을 새로 요구하지 않는다. |
| D-399·D-401~D-404 | 기능/장치 경계와 기존 Cell 작업을 이어받는다. Proposed 상태나 개별 실행 개방 조건을 이 ADR로 승격하지 않는다. Cell 기능은 공정 모듈, 화면·서버는 앱 조합으로 분리한다. |
| D-392 | 유지. 모델 도구 호출이 실행 권한이 되지 않는다. |

역사 ADR 본문을 덮어쓰지 않는다. 이 ADR과 실행 계획이 목표 배치와 전환 순서를 설명하며, 이전하지 않은 현재 코드의 사실은 기존 모듈 기록을 따른다.

## 대안과 판단

- **현재 구조 유지:** 변경 비용은 작지만 Fleet server·OMX adapter·core_common에 섞인 책임과 설치 의존성 문제를 남긴다.
- **전면 이동과 이름 변경:** 새 트리는 빨리 얻지만 기능·설치·프로토콜 회귀를 분리하기 어렵다. 채택하지 않는다.
- **작업 흐름별 추출:** 기존 동작과 식별자를 보존하며 최소 설치를 확인할 수 있다. 이 방식을 채택한다.

## 수용과 실행 계획

[실행 계획](../plans/2026-10-02-platform-architecture-v02-migration.md)의 Task 0~9를 따른다. 각 task는 기존 파일·새 산출물·시험·출구·되돌리기 조건을 명시한다. 본 ADR/계획 기록은 문서 단계이며 해당 task들의 구현 완료를 의미하지 않는다.

구조 수용 기준은 설계 v0.2의 A01~A15다. 첫 흐름의 완성으로 모든 플랫폼 모듈 이전을 완료 처리하지 않는다. 후속 범위는 검증된 기능과 설치 필요에 따라 별도 계획으로 구체화한다.

**관련:** [설계 v0.2](../reference/ROSY_Platform_Architecture_Design_v0.2.md), [D-317](D-317-control-and-shared-contract-source-boundaries.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-392](D-392-provider-neutral-model-tool-contract.md), [D-403](D-403-fleet-cell-job-route-cell-transfer.md).
