# ROSY Platform
# 통합 아키텍처 설계안

**하나의 플랫폼 · 기능별 소유권 · 선택적 설치**

**문서 ID** ROSY-ARCH-2026-002  
**설계 버전** v0.2 · **개정일** 2026-10-02  
**연결 범위** 팔레타이징 · Embodied AI · Pinky Pro · OMX · 학습 · 시뮬레이션

**적용 상태** 목표 구조와 단계적 이전 설계. 현재 코드의 배치·설치 완료 상태는 15장에 별도로 기록한다.

**결정과 실행:** [D-413](../adr/D-413-platform-modules-integrations-apps-profiles.md) · [단계적 이전 계획](../plans/2026-10-02-platform-architecture-v02-migration.md).

## 설계의 중심

ROSY는 `rosy_*` 프로그램을 나열한 묶음이 아니라, 작업의 의미와 실행 책임을 공유하는 하나의 플랫폼이다. 내부 기능은 책임에 따라 분리하고, 외부 모델·로봇·시뮬레이터는 연동 계층으로 연결한다. 장치에는 필요한 기능만 설치한다.

**공정이 작업을 정의하고, AI가 대안을 제안하며, 실행기가 권한을 확인하고 수행한다.** 실제 관측과 실행 증거는 별도로 대조한다. 어떤 모델·장치·공정을 선택해도 이 책임 경계는 유지한다.

## 이번 개정의 핵심

`rosy_domain` 중심의 공통 데이터 모음과 `runtime` 아래의 기능 혼합을 해소한다. `modules / integrations / apps / profiles`를 기준으로 구조를 정렬하고, 공개 API·의존 방향·설치 프로파일·이전 절차를 함께 규정한다.

팔레타이징은 ROSY 전체를 정의하지 않는 정식 공정 모듈이다. Gemini 계열 판단 모델과 학습형 행동 정책은 다른 계약으로 연결한다. Pinky와 OMX는 별도 장치이며 작업 수준에서 협업한다. [B01][B02]

## 문서 적용 관계

이 문서는 기존 `ROSY_Embodied_AI_Integration_Addendum_v0.1.md`의 플랫폼·패키지 설계를 계승·개정한다. 이전 제안과 패키지 경로·기능 책임이 충돌하면 목표 설계는 본 v0.2를 따른다. 저장소의 목표 배치 전환은 D-413에 기록했고, 기존 결정과의 관계는 15.3절에 둔다. 타입별 공개 API·설치 전환은 실행 계획의 해당 검증 뒤에 적용한다. 문서 개정만으로 실행 권한·통신 계약·배포 상태를 바꾸지 않는다.

2026-10-02 저장소 대조를 반영해 사이트와 장치의 실행 소유권, 실제 코드 기준 이전표, 최소 설치 검증, 고정 셀의 첫 전환 범위를 구체화했다. 먼저 하나의 작업 흐름을 연결하고, 검증된 경계부터 옮긴다.

**검토 경로:** 구조·소유권은 1~5장, 패키징·실행은 6~8장, AI·배포는 9~12장, 복구·시험·이전은 13~16장을 참조한다.

<!--PAGE-->
# 1. 제품·모듈·패키지·프로세스를 구별한다

## 1.1 명명 기준

| 구분 | 의미 | ROSY 기준 |
|---|---|---|
| 플랫폼 | 사용자에게 제공하는 전체 제품 | ROSY |
| 기능 모듈 | 데이터와 규칙을 소유하는 영역 | execution, world, decision |
| 코드 네임스페이스 | 개발자가 사용하는 공개 이름 | rosy.execution, rosy.world |
| 배포 패키지 | 독립 설치·업데이트 산출물 | rosy-execution, rosy-world |
| 실행 프로그램 | 모듈과 연동을 조합하는 진입점 | agent, gateway, worker, studio |
| 설치 프로파일 | 장치별 패키지·설정·권한의 조합 | pinky_pro, omx_cell, gpu_worker |

배포 패키지 이름은 사내 설계 이름이며 공개 저장소의 이름 확보나 배포 완료를 뜻하지 않는다. 문서 버전 v0.2와 실제 소프트웨어 패키지 버전은 별도 관리한다.

## 1.2 반복 접두어를 줄이되 외부 식별자는 보존한다

내부 책임 폴더는 `modules/execution`처럼 표현한다. ROS 2의 평면 패키지 이름에는 필요한 접두어를 남긴다. REP-144는 패키지 이름의 고유성과 관련 패키지의 공통 접두어를 권고한다. 따라서 `rosy_msgs`, `rosy_bridge`, `rosy_bringup`은 내부 이름 중복과 다른 문제다. [S03]

기존 배포된 ROS 메시지 타입·토픽·서비스 이름은 내부 폴더 이동과 동시에 임의 변경하지 않는다. 바뀌어야 하는 통신 계약은 별도 마이그레이션으로 처리한다.

## 1.3 분리의 기준

별도 설치가 필요하거나, 의존성이 무겁거나, 다른 장치·모델로 교체되거나, 장애 격리가 필요한 부분을 배포 경계로 삼는다. 하위 폴더가 생겼다는 이유만으로 패키지나 서비스를 추가하지 않는다.

초기 운영은 모듈형 단일 프로세스를 기본으로 하되 장치 실행과 GPU 작업은 분리한다. 플랫폼 통일은 하나의 거대한 바이너리나 전역 단일 실행기를 의미하지 않는다.

**새로운 `domain`, `common`, `core/core` 통합 저장소를 만들지 않는다.** 재사용 계약은 소유 모듈의 공개 API에 두고, 정말 공통인 작업 계약만 좁게 정의한다.

<!--PAGE-->
# 2. 저장소 구조

## 2.1 ROSY가 소유하는 기능

다음은 책임 기준 경로다. Python의 실제 `src/rosy/...` 배치는 6장에 따르며, 전체 소스 언어를 Python으로 제한하지 않는다.

```text
rosy/
  modules/
    execution/
      api/                 # plan, command, receipt, record
      site/
        admission/         # mission admission and grants
        scheduling/        # task graph and shared resources
        persistence/       # mission and step journal
      local/
        admission/         # device authority and current preconditions
        lifecycle/         # action, cancel, restart and reconcile
        persistence/       # action attempts and controller receipts
        guards/            # application checks, not certification
    world/
      api/                 # snapshot, frames, profiles
      observations/        # evidence and object association
      catalog/             # versioned product/cell references
      projections/         # reconciled read views
    perception/
      api/                 # observation proposals
      pipelines/           # sensor interpretation
    decision/
      api/                 # proposals and provider ports
      context/
      routing/
      evaluation/
    skills/
      api/                 # manifest, result, provider ports
      manipulation/
      navigation/
      inspection/
    processes/
      palletizing/
        api/               # recipe and pattern contracts
        patterns/
        validation/
        compilation/
        recovery/
    learning/
      api/                 # dataset and policy artifacts
      datasets/
      training/
      evaluation/
      promotion/
```

`execution`이 모든 기능을 포함하는 상위 폴더가 아니다. 실행 책임을 가진 하나의 모듈이다. `skills/api`도 범용 도메인 저장소가 아니라 작업 호출·결과·전제조건에 한정된 계약이다.

`execution/site`와 `execution/local`은 서로 다른 실행 사실을 소유한다. 사이트의 작업 조정 역할은 Fleet으로 유지하고, 각 장치의 최종 명령은 로컬 owner가 맡는다. 이 책임 분류가 하위 폴더별 wheel이나 공통 제어 프로세스를 요구하지는 않는다. 두 장치에서 같은 의미가 확인된 규칙만 공유한다.

공정이 늘어날 때 `processes` 아래에 추가하되, 실제 독립 규칙이 없는 기능을 미래 예상만으로 빈 모듈로 만들지 않는다.

<!--PAGE-->
## 2.2 외부 연동·실행 진입점·설정

```text
rosy/
  integrations/
    models/                # reasoning/perception model adapters
      gemini/
      local_vlm/
    policies/              # learned action-policy adapters
      lerobot/
    robots/
      pinky_pro/
      omx/
    planning/
      moveit/
    simulation/
      gazebo/
      isaac/
    enterprise/
      wms/                 # customer-specific connectors
    storage/               # DB/object-store implementations
    ros2/
      rosy_msgs/
      rosy_bridge/
      rosy_bringup/
  apps/
    studio/                # existing operator frontend
    gateway/               # existing backend/API composition
    agent/                 # local execution composition
    worker/                # inference/training/simulation jobs
  profiles/
    devices/
    cells/
    models/
    installations/
  deploy/                  # builds, release locks, services and install
  tools/                   # developer and verification entrypoints
  firmware/                # MCU sources with their own build lifecycle
  tests/
    architecture/
    contracts/
    profiles/
    replay/
    simulation/
    hardware/
  docs/
```

`integrations/robots/pinky_pro`는 ROSY 계약을 Pinky에 연결하는 코드이고, `profiles/devices/pinky_pro`는 센서·역할·지원 기능 설정이다. 업스트림 Pinky·OMX 소스를 복사하거나 브랜드 이름을 바꾸는 위치가 아니다.

`apps`는 조합과 수명주기 진입점이다. 공정 규칙·판단 정책·권한 정책을 새로 구현하지 않는다. 현재 관제와 백엔드는 이 구조에 매핑하고 동일 역할 서버를 중복 생성하지 않는다.

고객별 URL·비밀번호·인증서·토큰은 코드나 레시피에 넣지 않는다. 프로파일에는 비밀값의 참조만 두고 실제 값은 별도 비밀 관리로 공급한다.

## 2.3 프로파일과 배포 도구의 책임

`profiles`는 무엇을 설치하고 어떤 기능을 허용할지 선언한다. `deploy`는 프로파일과 release lock을 해석해 패키지·이미지·서비스·OS 권한을 설치하고 검증한다. 제품 소스의 네 영역과 함께 `deploy`, `tools`, `tests`, `docs`, `firmware`의 독립 수명주기를 유지한다.

저장소에는 공개 기본값·스키마·템플릿을 둔다. 실제 설치별 설정과 보정 산출물은 기존 비공개 설정·배포 데이터 경계에서 관리하고 버전 또는 digest로 참조한다. 프로파일 파일을 수정하는 행위만으로 실행 권한이나 실물 capability가 활성화되지 않는다.

<!--PAGE-->
# 3. 기능 소유권과 금지 책임

| 모듈 | 소유하는 책임 | 소유하지 않는 책임 |
|---|---|---|
| execution | 실행 접수·권한·자원·취소·저널·재개 | 팔레트 패턴, Gemini SDK, 모델 학습 |
| world | 관측·좌표·보정·버전별 환경 상태 | 물리 동작 승인, AI 출력의 무조건 확정 |
| perception | 영상·센서를 관측 후보로 변환 | 작업 완료 확정, 실행 권한 부여 |
| decision | 의도 해석·후보 판단·모델 선택·기권 | 원시 장치 명령, 안전 한계 변경 |
| skills | 조작·이동·도킹·검사의 재사용 행동 | 고객 주문 규칙, 전역 작업 스케줄링 |
| processes/palletizing | 제품 적재 규칙·패턴·순서·공정 복구 | 특정 로봇 SDK, 별도 실행기 |
| learning | 데이터·실험·평가·승인 정책 산출물 | 생산 실행기와 병행하는 직접 제어 |

## 3.1 world는 생성형 world model이 아니다

`world`는 관측과 확정 사건을 대조하는 상태 모듈이다. 물리 상태의 예측·설명·관측·확정을 구분한다. 모델이 “박스가 놓였다”고 설명해도 실행 완료 사실을 자동 덮어쓰지 않는다. 기존 보완안의 원칙을 유지한다. [B02, §5]

첫 추출 범위는 관측 참조·좌표·보정 revision·Snapshot·읽기 상태다. 팔레트 슬롯과 층의 완성 규칙은 공정이, 실행 상태 전이는 `execution`이 소유한다. `world`에 모든 설정과 공정 객체를 모으지 않는다. Snapshot은 필요한 관측의 참조·시각·유효성·누락·충돌을 담으며, 원본 영상이나 모든 센서 데이터를 매번 복사하지 않는다.

## 3.2 상태 기록의 중복을 막는다

실행 사실마다 단일 기록 주체를 둔다. 사이트 원장과 장치 원장은 서로 다른 사건을 기록하며, 하나의 중앙 DB나 범용 상태 기계로 합치지 않는다.

| 범위 | 기준 사실과 기록 주체 | 다른 영역과의 관계 |
|---|---|---|
| `execution/site` | Fleet의 Mission·Step 순서, 자원 예약, 장치 배정, 전체 작업 결과 | 장치의 수락·실행 결과와 독립 완료 근거를 연결해 작업을 조정 |
| `execution/local` | 장치 owner의 Action·attempt, 제어기 goal, 취소 확인, 재시작 복구 | 사이트 grant를 확인한 뒤 로컬에 기록하고 결과를 반환 |
| `world` | 관측·객체 연결·좌표·보정과 실행 사건의 읽기 projection | 사이트·장치의 실행 기록을 덮어쓰지 않음 |

현재 Fleet `MissionStore`와 OMX `ActionStore`의 분리는 이 경계의 출발점이다. Mission·Step·Action·attempt·제어기 goal의 상관관계와 authority epoch·dispatch generation을 보존한다. 사이트가 수락한 작업이 장치에서도 실행됐다고 간주하지 않는다. 각 projection은 사건 스트림별 마지막 반영 ID 또는 watermark를 기록한다.

관측 원본·객체 연결·캘리브레이션은 `world`가 소유한다. 기존 WMS가 제품 마스터의 원천이라면 `world/catalog`은 원천 ID와 개정번호가 있는 검증된 참조 사본만 보유한다. 제품별 적재 제약은 레시피에서 그 버전을 참조한다.

## 3.3 조회와 실행 API를 구별한다

상태 조회가 가능하다고 동작 권한이 생기지 않는다. 운영자 화면, WMS, AI는 서로 다른 인증 주체이지만 동일한 실행 접수·검증 경계를 사용한다. 인증 주체·실행 권한·승인 기록은 신뢰된 실행 경계에서 부여한다.

<!--PAGE-->
# 4. 공개 계약과 데이터 모델

## 4.1 계약은 소유 모듈에 둔다

| 계약 | 소유 API | 핵심 항목 |
|---|---|---|
| ObservationSnapshot | world.api | 시각·객체 ID·좌표·관측 근거·상태 revision |
| CellProfile / CalibrationRecord | world.api | 장치·좌표 관계·오차·버전·측정 근거 |
| ProductProfile | world.api | 원천 ID·치수·중량·취급 정보·개정번호 |
| SkillManifest / SkillResult | skills.api | 입력·전제/완료조건·자원·취소·증적 |
| DecisionProposal | decision.api | 관측 참조·후보 작업·대상·근거·기권 |
| Recipe / Pattern | processes.palletizing.api | 제품 참조·층·회전·배치·공정 제약 |
| TaskGraph / PlanBundle | execution.api | 작업 단계·의존성·검증 참조·버전 해시 |
| ExecutionRecord / Receipt | execution.api | 접수·진행·확정·취소·재개·중복 방지 |
| PolicyArtifact / DatasetManifest | learning.api | 데이터·가중치·행동 공간·평가·승인 |

서로 다른 모듈이 동일 계약을 별도로 정의하지 않는다. `apps/studio`의 폼 스키마와 ROS/HTTP 표현은 공개 계약에서 생성하거나 명시적으로 매핑하고 round-trip 시험으로 대응을 확인한다.

## 4.2 모든 경계에 필요한 의미

시간과 공간에는 단위를 붙인다. 내부 길이·질량·각도는 m·kg·rad를 기본으로 하며 UI 변환은 경계에서 수행한다. 관측에는 캡처 시각과 수신 시각, 좌표계, 보정 revision을 함께 둔다. 시뮬레이션 시각과 실물 시각도 구별한다.

`request_id`, `job_id`, `step_id`, `expected_revision`, `deadline`, `actor`를 목적에 맞게 사용한다. 모델이 반환한 ID나 권한 필드를 신뢰된 실행 식별자로 그대로 수용하지 않는다.

## 4.3 범용 계획과 공정 자료의 연결

`PlanBundle`은 특정 공정의 클래스를 import하지 않는다. `process_kind`, `process_revision`, `artifact_ref`, `artifact_digest`로 공정별 산출물을 참조한다. 각 단계는 등록된 Skill의 ID·버전과 검증된 입력을 담는다.

공정 컴파일러는 이 계획을 생성할 수 있지만 실행 권한을 발급할 수 없다. `execution`은 권한·현재 상태·자원·검증 증적의 유효성을 확인하고 접수한다. 승인된 계획의 입력이 변경되면 새 계획과 새 승인을 요구한다.

첫 `PlanBundle`은 고정 셀 작업의 Step·Skill 버전·레시피/셀 해시·허용 한계·완료 조건·검증 증적을 연결하는 데 필요한 범위로 정의한다. 현재 Cell의 `Job`을 곧바로 승인된 `PlanBundle`로 취급하지 않는다. 관절 궤적과 이동 경로는 로컬 Skill이 최신 상태를 대조해 생성·검증하며, 사전 도달성 검사는 실행 직전 검사를 대신하지 않는다.

목표·Recipe·CellProfile과 ObservationSnapshot은 판단의 병렬 입력이다. 판단 컨텍스트는 승인 범위와 관측 revision을 함께 고정한다. 모델이 없어도 승인된 결정적 계획은 실행할 수 있다.

<!--PAGE-->
# 5. 의존 방향과 순환 참조 방지

## 5.1 정적 코드 의존 규칙

아래 표는 공개 API의 import 방향이다. 런타임 메시지가 양방향으로 흐른다는 이유로 코드 의존도 양방향으로 만들지 않는다.

| 소비 모듈 | 허용하는 내부 API 의존 | 금지하는 직접 의존 |
|---|---|---|
| world | 표준 타입·자체 API | execution 구현, ROS, 모델 SDK |
| skills/api | world.api | 실행기·장치 SDK·학습 프레임워크 |
| perception | world.api | 실행 권한 구현 |
| decision | world.api, skills.api | execution 구현, 원시 장치 드라이버 |
| skill 구현 | world.api, skills.api | execution 구현, 특정 공정 |
| execution | world.api, skills.api | decision, 공정 구현, 모델 SDK |
| palletizing | world.api, skills.api, execution.api | 특정 로봇·모델·UI·DB 구현 |
| learning | world.api, skills.api | 생산 실행기의 직접 구동 경로 |

`execution`이 `skills/api`만 사용하도록, 공통 작업 계약을 가벼운 배포 단위로 분리한다. 이 패키지를 설치했다고 manipulation·navigation·GPU 패키지가 따라오면 안 된다.

## 5.2 연동은 안쪽 인터페이스를 구현한다

MoveIt 연동은 manipulation의 계획기 인터페이스를, Gemini 연동은 decision의 판단 제공자 인터페이스를 구현한다. 저장소 연동은 소유 모듈의 저장소 인터페이스를 구현한다. 그 반대 방향 import를 금지한다.

실행 시 필요한 구현은 `apps/agent`, `apps/gateway`, `apps/worker`의 조합 지점에서 주입한다. 플러그인 이름은 명시적 허용 목록으로 해석하며 임의 모듈 경로·임의 스크립트를 프로파일에서 실행하지 않는다.

## 5.3 사건 projection의 순환을 끊는다

실행 사건을 world에 반영하는 조합 코드는 앱의 이벤트 연결부에 둔다. `world`가 `execution` 구현을 import하지 않고, `execution`도 world의 저장소 구현을 직접 변경하지 않는다. 사건 ID와 projection watermark로 재반영을 멱등 처리한다.

문서화된 의존 그래프는 CI에서 정적 import 규칙과 설치 의존성으로 동시에 검사한다. 소스 import만 정리하고 배포 메타데이터에 불필요한 의존성을 남기지 않는다.

## 5.4 조작 Skill과 제품 연동의 경계

| 책임 | 위치 | 현재 코드에서 분리할 대상 |
|---|---|---|
| 집기·이송·놓기 절차, 전제조건, 완료 근거, 중단 처리 | `modules/skills/manipulation` | OMX의 phase 실행에서 제품과 무관하게 설명할 수 있는 작업 절차 |
| 권한 확인, 실행 시도·취소·재시작 기록 | `modules/execution/local` | OMX Action journal과 owner 정책의 실행 책임. 장치별 규칙은 보존 |
| 계획기 호출과 결과 변환 | `integrations/planning` | 계획기 포트를 구현하는 MoveIt 등 선택 연동 |
| OMX 관절·그리퍼·ROS Action·기구학 | `integrations/robots/omx` | vendor 계약, 관절 매핑, OMX 해석 IK와 드라이버 연결 |

OMX 전용 FK/IK와 관절 한계를 범용 조작 규칙으로 승격하지 않는다. Skill은 계획기 포트와 장치 기능 계약을 사용한다. `execution/local`의 권한 검증 뒤에도 장치 owner의 최종 제출 검사는 유지하며, 제품별 제약을 같은 이름의 범용 검사로 대체하지 않는다.

<!--PAGE-->
# 6. 실제 패키징과 네임스페이스

## 6.1 Python 네임스페이스

PEP 420 방식으로 별도 배포 패키지가 하나의 `rosy` 네임스페이스를 공유하도록 한다. 공유 부모 `rosy`에는 `__init__.py`를 두지 않고, 실제 소유 하위 패키지에는 둔다. 여러 배포 단위가 공유하는 `rosy.skills`, `rosy.processes`, `rosy.integrations`도 같은 규칙을 적용한다. [S01][S02]

```text
modules/world/
  pyproject.toml                  # distribution: rosy-world
  src/rosy/                       # no __init__.py
    world/
      __init__.py
      api/
      observations/
      catalog/
      projections/

modules/skills/api/
  pyproject.toml                  # distribution: rosy-skill-api
  src/rosy/skills/                 # shared namespace parents
    api/
      __init__.py
```

빌드 시 include 범위를 소유 패키지로 제한한다. `rosy*` 전체를 무차별 수집하지 않는다. wheel 파일 목록 검사로 다른 패키지 파일의 중복 소유를 차단한다. Setuptools는 namespace discovery와 include/exclude 설정을 제공한다. [S05]

## 6.2 ROS 2와 다언어 코드

ROS 2 전송형식은 `integrations/ros2/rosy_msgs`에, 내부 API와의 변환은 `rosy_bridge`에 둔다. ROS 공식 문서는 커스텀 인터페이스를 별도 `ament_cmake` 패키지로 구성해 Python·C++에서 사용하도록 안내한다. [S04]

이 전송 패키지는 도메인 비즈니스 로직을 소유하지 않는다. 기존 `rosy_interfaces` 등 배포된 타입명이 있다면 호환 기간 동안 유지하고, 내부 경로 변경과 외부 타입 변경을 분리한다.

기존 ROS/C++ 제어·드라이버를 Python으로 재작성하지 않는다. Python 배포물은 wheel, ROS 구성은 해당 ROS 빌드 방식으로 관리한다. 하나의 파일을 wheel과 ROS 설치가 동시에 소유하지 않게 한다.

## 6.3 릴리스 기준

호환성 manifest에 Ubuntu·ROS 배포판·Python ABI·CPU 아키텍처·드라이버·툴·모델 산출물 버전을 고정한다. 단순 import 성공이 실기 호환을 뜻하지 않는다. 사내 인덱스와 아티팩트 해시를 사용하고, 선언된 패키지 이름을 공개 인덱스에서 무조건 내려받지 않는다.

## 6.4 패키징 전환을 분리한다

현재 사이트 Fleet은 `deploy/site/Dockerfile.fleet`에서 소스를 복사하고 `PYTHONPATH`로 로드하며, ROS 패키지는 colcon/ament 설치를 사용한다. 목표 wheel 설치가 이미 동작한다고 가정하지 않는다.

책임 추출, 소스 경로 이동, Python import 전환, wheel 설치, ROS 패키지·외부 타입 변경을 한 번에 수행하지 않는다. 먼저 기존 진입점이 추출된 모듈을 호출하게 하고, 패키징 단계에서 저장소 경로와 개발용 `PYTHONPATH` 없이 설치 산출물만으로 실행한다. Python 파일의 wheel/ament 중복 소유와 정적 자산 누락도 검사한다. 배포 메타데이터와 잠금 파일로 최소 설치의 전이 의존성을 확인한다.

<!--PAGE-->
# 7. 제안부터 실행까지의 공통 경로

```text
Operator / WMS / AI draft
          |
          v
Process API -> Recipe revision
          |
          v
Process compilation + injected skill preflight
          |
          v
TaskGraph + validation artifacts -> PlanBundle
          |
          v
Required approval -> execution admission
          |
          v
Site grant -> local admission -> Skill provider
          |
          v
Authorized local device adapter -> controller
          |
          v
Device receipt + independent evidence
          |
          v
Local action journal -> site reconciliation -> world projection
```

## 7.1 AI는 다른 진입점일 뿐 다른 실행기가 아니다

AI의 제안은 gateway의 의미 검증을 거쳐 레시피 초안 또는 제한된 Skill 요청으로 변환한다. 모델이 반환한 `approved=true`·confidence·도구 호출을 실행 승인으로 인정하지 않는다. 운영자와 WMS도 권한과 현재 상태 검사를 생략하지 않는다. [B02, §8]

## 7.2 자원별 단일 권한

동일 로봇 또는 같은 충돌 구역에 대해 상충하는 실행자가 동시에 권한을 갖지 않게 한다. 이는 전체 공장을 하나의 실행 프로세스로 직렬화한다는 뜻이 아니다. 독립 자원은 병행할 수 있다.

범용 작업 그래프와 자원 예약은 `execution/scheduling`이 소유한다. 팔레타이징이나 AI가 별도 범용 스케줄러를 만들지 않는다. 로컬 agent는 자기 장치의 권한을 집행하고, 상위 gateway는 명령을 우회 발행하지 않는다.

## 7.3 계획과 현재 상태를 다시 대조한다

실행 직전에 툴·보정·장치 capability·대상 객체·슬롯 점유·계획 버전을 확인한다. 이전에 충돌 검사에 통과한 계획도 현장 조건이 바뀌면 사용하지 않는다. 진행 중 재계획은 현재 행동의 확인된 경계에서만 전환한다.

<!--PAGE-->
# 8. 팔레타이징 공정과 무티칭 UX

## 8.1 공정 모듈은 화면도 로봇팔도 아니다

`modules/processes/palletizing`이 제품 적재 규칙·층 패턴·순서·완성 조건을 소유한다. 화면은 `apps/studio`의 기능으로 제공하며, 동일 API를 WMS와 AI 초안에도 사용한다.

공정은 `PickPlace`, `Inspect`, `Navigate`, `Dock` 등의 등록된 작업을 참조한다. 지원 기능과 제약은 장치 프로파일 및 Skill 사전 검증에서 확인한다. 공정 코드 안에 OMX·UR 등의 분기문을 쌓지 않는다.

## 8.2 최초 셀 등록과 신규 제품 등록

엔지니어는 장치·툴·TCP·공급부·팔레트 좌표와 보호 대책을 등록하고 검증한다. 운영자는 그 셀의 승인 조건 안에서 제품·수량·층·라벨·허용 회전을 설정한다. 제품마다 로봇 좌표를 가르치지 않아도 되는 것이 목표이지, 초기 계측을 생략하는 목표가 아니다. [B01, §2·16]

레시피에는 제품 마스터 revision과 팔레트 기준 상대 배치를 기록할 수 있다. 설치별 절대 관절 경로·드라이버 설정·API 토큰은 넣지 않는다.

## 8.3 실행 흐름 예시

제품 확인 → 공급 준비 → 물품 식별 → 집기·확인 → 운반 → 배치·확인 → 슬롯 확정 → 다음 단계로 구성한다. 배치 순서와 제품 규칙은 공정이 결정하고, 실제 궤적은 조작 Skill의 계획기 구현이 생성한다.

| 공통 기능 | 공정별 기능 |
|---|---|
| 집기·도킹·검사·상태 기록·명령 권한 | 층 패턴·제품 회전·라벨 방향·완성 판정 |
| 중복 요청 차단·취소·증거 연결 | 부분 팔레트 재구성과 공정별 복구 후보 |
| 센서·장치 연결 및 capability 검증 | 제품별 지지·허용 돌출·접근 순서 제약 |

## 8.4 고객별 확장

바코드 대조·라벨 발행·출하 검사 등은 공개된 확장 지점에서 실행한다. 각 확장에 입력 스키마·시간 제한·실패 정책·멱등성 키를 둔다. 생성된 경로를 수작업으로 고쳐 유지하는 방식은 사용하지 않는다.

팔레타이징을 제거해도 이동·조작·검사 기능은 유지되어야 한다. 반대로 Pinky가 없어도 고정 셀 팔레타이징을 독립 시험할 수 있어야 한다.

<!--PAGE-->
# 9. AI 판단·행동 정책·학습의 분리

## 9.1 모델 이름이 플랫폼 구조를 결정하지 않는다

`integrations/models/gemini`는 공급자 API를 판단 제공자 계약에 맞춘다. ER2 같은 모델 식별자는 승인된 model profile에서 관리한다. 모델 버전이 바뀔 때마다 최상위 모듈을 늘리지 않는다.

본 설계에서 모델은 연결 후보이며 특정 버전의 공개성·성능·장비 호환성을 승인하지 않는다. 실제 endpoint·입출력·사용 조건·지연은 설치할 조합의 승인 항목으로 관리한다. 기존 공급자 조사 자료는 보완안 v0.1을 참고한다. [B02]

| 역할 | 내부 소유 | 외부 연결 |
|---|---|---|
| 인식 후보 | perception | 선택한 비전·멀티모달 모델 |
| 작업·복구 제안 | decision | Gemini·로컬 VLM·기존 판단 제공자 |
| 제한된 행동 구간 | skills/manipulation | 승인된 학습형 정책 어댑터 |
| 데이터·학습·평가 | learning | LeRobot·기타 학습 도구 연동 |

JEV는 현재 구현 역할을 확인해 기존 계약에 연결한다. 이름만으로 별도 공개 모델이나 또 하나의 실행기로 취급하지 않는다.

## 9.2 학습 산출물과 생산 실행을 분리한다

학습 모듈은 데이터 수집·실험·평가·정책 승격을 관리한다. 생산 실행은 승인된 `PolicyArtifact`만 참조한다. 런타임 설치에 전체 학습 프레임워크가 따라오지 않도록 정책 추론 환경을 격리할 수 있다.

정책 승인 단위는 가중치만이 아니다. 장치 구성, 관절 순서, 카메라 배치, 정규화, 행동 공간, 실행 구간, 제어기·툴 버전과 평가를 함께 고정한다. 운전 중 가중치를 교체하거나 서로 다른 정책의 명령을 섞지 않는다.

## 9.3 모델 호출의 경계

정상 반복은 승인된 계획으로 진행한다. 새 지시·관측 불일치·작업 경계에서 모델을 호출한다. 응답이 늦거나 조건이 달라지면 폐기하며 미확인 상태에서 새로운 동작을 시작하지 않는다.

모델에는 관측·제품 조회·레시피 초안·허용 작업 제안만 노출한다. 셸·임의 코드·원시 관절 명령·보호 설정 변경은 노출하지 않는다. 장면 속 문구는 데이터로 취급한다. 물리 실행 적용 전 공급자 조건과 현장 승인 절차를 별도로 충족해야 한다.

<!--PAGE-->
# 10. 관제·백엔드·장치 실행의 경계

## 10.1 studio와 gateway

Studio는 레시피·장면·작업·판단 근거를 보여준다. 프론트엔드의 검사는 사용자 안내이며 최종 검증은 소유 모듈 API에서 다시 수행한다. UI 전용 데이터 모델이 공정의 정답이 되지 않도록 한다.

Gateway는 인증·요청 검증·API 조합·이벤트 전달을 담당하고 `execution/site`의 Fleet 조정을 조합한다. 작업 권한 정책은 `execution`에, 공정 의미 검사는 해당 공정 모듈에 둔다. gateway가 직접 로봇 토픽을 발행하는 별도 제어 경로는 만들지 않는다.

현재 `src/runtime/gateway`의 CORE는 Pinky 장치 프로그램이므로 목표 `apps/gateway`로 이름만 대응시키지 않는다. CORE의 로컬 API·ROS executor 조합은 `apps/agent`의 Pinky 구성으로 이어지고 단일 프로세스 계약을 보존한다. Fleet 서버 조합은 사이트 gateway로 이어진다. Dashboard·Pilot·Cam·얼굴 화면도 각각의 제공 서버·인증·설치 대상을 유지하며 Studio 하나로 강제 통합하지 않는다.

## 10.2 agent와 worker

Agent는 `execution/local`과 필요한 Skill·장치 연동을 조합한다. Pinky와 OMX의 구성은 분리하며 모든 장치를 담당하는 중앙 agent를 만들지 않는다. Worker는 추론·학습·재생·시뮬레이션 작업을 실행한다. Worker가 생성한 결과는 제안 또는 산출물이며 생산 장치의 권한이 아니다.

고주파 제어 루프는 적합한 로컬 제어기에 남긴다. 클라우드 모델 응답·웹 요청·모듈식 Python 호출을 하드 실시간 제어 주기로 간주하지 않는다.

## 10.3 구조 분리는 보안 집행을 대신하지 않는다

폴더를 분리해도 임의 프로세스가 같은 로봇 통신망에 접근하면 우회 경로가 생길 수 있다. 배포 시 OS 권한·네트워크 경계·ROS 통신 접근·허용된 장치 실행 주체를 함께 검증한다.

모든 장치 명령은 유효한 작업·자원·권한 문맥과 연결한다. 학습 도구의 자체 실행 스크립트나 디버깅 노드가 이 경계를 우회하지 못하도록 운영 환경에서 제한한다. 학습·시뮬레이션은 물리 구동 권한이 없는 환경으로 분리한다.

## 10.4 보호 기능은 독립적으로 유지한다

`execution/guards`는 데이터·명령·작업 전제조건을 확인하는 애플리케이션 검사다. 인증된 비상정지·보호정지·하중 유지 기능을 대신하지 않는다. 모델이 안전 기준을 바꾸거나 보호정지 후 자동 재개하도록 만들지 않는다.

정지 시 물체를 유지할지, 내려놓을지, 어느 동작을 허용할지는 장치·툴별 승인 정책이다. 모든 장치에 동일한 “즉시 릴리스”를 적용하지 않는다.

<!--PAGE-->
# 11. 장치별 최소 설치

| 대상 | 기본 구성 | 기본 제외 |
|---|---|---|
| Pinky Pro | agent, execution/local, world의 필요한 범위, skill API, navigation, Pinky/ROS 연동 | manipulation, 학습 도구, 모델 가중치 |
| OMX 셀 | agent, execution/local, world의 필요한 범위, skill API, manipulation, OMX/필요 계획기·ROS 연동 | Pinky 드라이버, 대형 학습 환경 |
| 현장 서버 | gateway, studio, execution/site, world 조회, 공정 구성·검증, 작업·증적 집계 | 사용하지 않는 장치·GPU SDK |
| GPU 워커 | worker, 선택한 모델/정책, 필요한 perception·learning·시뮬 연동 | 생산 장치의 직접 구동 권한 |

표는 책임 기준 선택이다. 설치물에는 직접 선택한 모듈뿐 아니라 허용된 전이 의존성을 모두 포함해야 한다. 실제 패키지 집합은 검증된 release manifest로 해석한다.

## 11.1 로컬 실행에 필요한 것을 남긴다

OMX agent는 승인된 PlanBundle과 필요한 Skill을 로컬에 보유한다. 공정 편집기 전체를 설치하지 않아도 기본 실행은 가능하도록 한다. 오프라인에서 새 공정 계획을 생성하려면 해당 컴파일러와 검증 기능을 명시적으로 추가 설치해야 한다.

장애 후 공정별 재계획이 필요한데 관련 기능이 없으면 HOLD 상태로 전환하고 상위 기능 또는 작업자 확인을 기다린다. “컴파일러 미설치”를 “검증 없이 재시작 가능”으로 해석하지 않는다.

## 11.2 Ubuntu를 설치 기준으로 고정한다

초기 배포 대상은 Ubuntu다. 실제 버전·ROS 배포판·Python ABI·CPU 아키텍처는 장치별로 확인한 호환 집합에 고정한다. 하나의 설정을 ARM 장치와 GPU 서버에 무조건 동일 적용하지 않는다.

장치 agent와 학습·모델 워커는 의존 환경을 분리한다. ROS의 Python ABI와 맞지 않는 임의 환경을 제어기에 덮어씌우지 않는다. 모델 가중치·원본 영상·학습 데이터는 소스 패키지나 장치 기본 이미지에 포함하지 않는다.

## 11.3 성능·장애 범위

GPU 자원은 추론·학습·시뮬레이션별 예약과 우선순위로 관리한다. 한 GPU에서 모든 모델을 동시 상주시킨다고 가정하지 않는다. GPU 장애가 장치의 실행 권한·정지·보유 정책을 함께 제거하지 않게 한다.

<!--PAGE-->
# 12. 설치·모델 프로파일과 릴리스 잠금

## 12.1 프로파일은 실행 코드가 아니다

장치 정의·셀 연결·모델 연결·설치 구성을 별도 파일로 둔다. 프로파일은 선언형 데이터이며 해석 가능한 provider ID와 스키마만 허용한다. 임의 Python 경로·셸 스크립트 실행을 허용하지 않는다.

```yaml
schema_version: "0.2"
profile_id: "omx_cell"
platform: "rosy"
target_os: "ubuntu"
execution_mode: "simulation"
components:
  - "world"
  - "skill_api"
  - "execution"
  - "manipulation"
entrypoint: "agent"
adapters:
  - "ros2"
  - "omx"
  - "moveit"
features:
  ai_reasoning: false
  learned_policy: false
  process_compilation: false
permissions:
  physical_dispatch: false
release_lock_ref: null
```

동봉 예시는 구성 검토용이다. simulation 모드의 로봇 어댑터는 모델·기능 참조이며 물리 드라이버를 열지 않는다. `physical_dispatch=true`만으로 실기 권한이 생기지 않으며 별도 승인·장치·보호·잠금 조건을 모두 검증해야 한다.

## 12.2 배포에 필요한 잠금 정보

release lock은 패키지 버전·해시, 지원 OS/ABI, 장치·툴·보정, 필요한 모델 산출물, 정책·시험 참조를 포함한다. 승인자는 빈 값·미확정 참조를 포함한 배포를 거절한다. 비밀값은 참조로만 전달한다.

모델의 구체적인 `model_id`는 후보 프로파일의 확정 필드다. 이름이 비슷하다는 이유로 대체 모델을 자동 실행하지 않는다. 모델을 비활성화해도 결정적 작업은 독립적으로 사용할 수 있어야 한다.

설치 프로파일·release lock·셀 보정 중 어느 것이 바뀌었는지 구분해 영향받는 계획만 재검증한다. 모든 변경을 단일 “ROSY 버전”으로 뭉개지 않는다.

<!--PAGE-->
# 13. 복구와 Pinky–OMX 인계

## 13.1 물리 동작과 데이터 기록은 동시에 완료되지 않는다

기존 설계의 복구 원칙을 유지한다. 놓기 직후 기록이 유실될 수 있으므로, 요청 중복 차단이 물리적 정확히 한 번 실행을 보장한다고 설명하지 않는다. [B01, §18]

```text
RESERVED -> PICK_INTENT -> PICK_CONFIRMED
         -> PLACE_INTENT -> PLACE_CONFIRMED -> COMMITTED

Ambiguous interruption -> HOLD -> RECONCILE
                      -> approved recovery or human resolution
```

`execution`은 상태 전이·영속 저널·권한을 관리한다. 팔레타이징은 슬롯·층·제품 규칙을 반영한 복구 후보를 생성한다. 관측은 `world`에 연결하고, 채택한 재개는 다시 공통 실행 경계를 통과한다.

## 13.2 취소의 의미

모델 응답 생성 중단, 웹 요청 취소, Skill 취소 요청, 제어기의 정지 확인은 서로 다른 사건이다. `cancel_requested`와 `cancel_confirmed`를 구별하며 중간 응답만으로 물리 정지를 확정하지 않는다.

파지·진공·툴 상태를 확인할 수 없는 경우 성공 기록이나 임의 릴리스 대신 장치별 승인된 보유·정지 정책을 사용한다. 재부팅 후에도 남는 저널과 최신 관측을 대조한다.

## 13.3 이동 로봇과 팔의 인계

Pinky와 OMX는 별도 장치로 유지한다. 이동·도킹·인계·집기·출발 허용을 작업 수준에서 연결한다. [B01, §13][B02, §9]

| 단계 | 필요한 근거 |
|---|---|
| 도킹 확인 | 위치·정지·센서·대상 장치 식별 |
| 구역 점유 | 상충 작업 없음·유효 권한·실제 점유 확인 |
| 물품 확보 | 그리퍼 또는 승인된 확인 수단의 결과 |
| 소유권 인계 | 송신·수신 장치와 물품 ID가 연결된 사건 |
| 출발 허용 | 팔 이탈과 인계 완료 조건 충족 |

예약 시간이 만료됐다고 물리 구역을 빈 것으로 처리하지 않는다. 통신 단절이나 상태 불일치가 있으면 미확인 점유로 남기고 충돌 작업을 금지한다.

<!--PAGE-->
# 14. 검증 기준과 증적

## 14.1 구조가 지켜지는지 먼저 시험한다

| ID | 시험 | 통과 기준 |
|---|---|---|
| A01 | 내부 의존성 | 선언된 그래프와 실제 import에 순환 없음 |
| A02 | 공정 격리 | execution에 palletizing·모델 SDK 직접 의존 없음 |
| A03 | namespace 소유권 | 공유 부모 충돌·wheel 파일 중복 소유 없음 |
| A04 | 최소 설치 | Pinky 환경에 팔·GPU·학습 의존성 유입 없음 |
| A05 | 외부 모델 제거 | 승인된 결정적 작업의 기본 실행 유지 |
| A06 | 공정 제거 | 이동·조작·검사 API가 공정 없이 로드됨 |
| A07 | 계약 변환 | ROS/HTTP 표현 왕복 시 단위·ID·revision 보존 |
| A08 | 모델 권한 | 금지 도구·원시 명령·허가 필드 위조 차단 |
| A09 | 변경 무효화 | 툴·보정·계획 변경 후 구 승인 실행 차단 |
| A10 | 중복·정지·복구 | 중복 실행·미확인 완료·잘못된 재개 차단 |
| A11 | 인계 장애 | 만료·단절 후 실제 점유 구역이 해제되지 않음 |
| A12 | 시뮬/실물 격리 | 시뮬 worker가 실물 명령에 접근하지 못함 |
| A13 | 사이트·장치 원장 연결 | 사이트 수락과 로컬 실행을 구별하고 단절·늦은 응답·재시작에도 Action/attempt 상관관계와 UNKNOWN/HOLD 유지 |
| A14 | 설치 후 실행 | 저장소 경로 없이 실제 설치 산출물로 진입점 실행, ROS/HTTP 변환과 정적 자산 로딩 성공 |
| A15 | 기존 진입점 호환 | 구 진입점의 단방향 위임, 외부 타입·식별자 보존, 장치 자원별 최종 writer 중복 없음 |

위 표는 구현 수용 기준이다. 시험 수량·장치 조합·오차·속도는 각 테스트 계획에서 고정하고 결과와 함께 기록한다.

## 14.2 세 종류의 검증 결과를 섞지 않는다

**문서·설정 검사:** 프로파일 문법, 참조 이름, 선언 의존 그래프를 검사한다. **코드·설치 검사:** 실제 import, wheel, ROS 타입·빌드, 최소 환경을 검사한다. **실기 검사:** 장치·툴·보호·취소·복구와 물리 결과를 시험한다.

첫 번째 통과를 두 번째나 세 번째 통과로 표시하지 않는다. 수용 시험의 오류 0건도 모든 상황의 안전 보증이나 인증으로 확대하지 않는다.

## 14.3 증적 묶음

각 시험에 코드 revision, release lock, 레시피·셀·보정·정책 버전, 입력과 기대 결과, 실행 로그, 영상·센서 참조, 실제 결과, 승인·기각자를 연결한다. 실패를 재시도 성공으로 덮지 않고 최초 실패와 복구 경로를 함께 보존한다.

<!--PAGE-->
# 15. 기존 구조에서의 이전 계획

## 15.1 실제 코드 기준 책임 이전

2026-10-02 작업 트리에서 확인한 경로다. `runtime/rosy_runtime`, `runtime/rosy_decision`, `contracts/rosy_domain`은 과거 설계 표현이며 현재 구현 경로로 취급하지 않는다. 아래 목표 열은 책임 배치이고, 이동 또는 공통 패키지 구현 완료를 뜻하지 않는다.

| 현재 경로와 구현 | 목표 책임 | 보존할 경계와 첫 작업 |
|---|---|---|
| `modules/processes/palletizing` — Recipe/Cell/Job compiler와 Job→PlanBundle 변환; `src/site/cell/rosy_cell`은 단방향 호환 facade | `modules/processes/palletizing` | 단일 공정 구현을 유지. 변환 시 현재 Recipe/Cell로 Job을 재컴파일해 Step·carry_z·해시 일치를 확인하고 `pallet_done` 원장 표지를 보존 |
| `src/site/fleet/fleet/server` — `mission_service.py`, `mission_store.py`, `mission_dispatcher.py`, task 서비스 | `modules/execution/site` + `apps/gateway` | Mission/Step·grant·결과 상관관계 유지. 업무 규칙을 추출하고 HTTP·lifespan은 앱 조합으로 유지 |
| `src/site/fleet/fleet/ai` 및 server의 `mission_model_turn_*` | `modules/decision` + `integrations/models` + 앱의 워커 조합 | 판단 제공자·도구 계약과 SDK/전송 분리. 기존 제안 권한과 재판단 비활성 경계 보존 |
| `src/runtime/gateway/core` — `services.py`, `node.py`, `bridge` 및 `src/runtime/api_web` | Pinky `apps/agent` 조합 + ROS/API 연동 | rclpy와 FastAPI의 단일 프로세스, 기존 API와 최종 cmd_vel owner 유지 |
| `src/runtime/services/core_features` — command·state·safety·navigation·docking·decision | `modules/execution/local`, 개별 Skill, 필요한 로컬 판단 규칙 | 장치 규칙별 소비자를 확인해 추출. ROS 없는 로컬 규칙에 원격 모델 의존성을 추가하지 않음 |
| `src/contracts/foundation/core_common` — protocol·domain·config·identity·profile | 각 소유 모듈의 `api`와 설정 계약 | 타입별 생산자·소비자·wire 버전 지정. 기존 schema를 호환 매핑 없이 복제하지 않음 |
| `src/products/omx/adapter/omx_adapter` — `action_store.py`, `command_owner.py`, phase runner·planner·ROS runtime | `execution/local` + `skills/manipulation` + `integrations/robots/omx` | 로컬 journal·세대 검증·최종 제출 owner 보존. OMX FK/IK는 제품 연동에 유지 |
| `src/runtime/sensing`, `src/site/vision` | 관측 해석은 `modules/perception`, 센서/모델 연결은 연동, 서버는 앱 | control 패키지 전체를 perception으로 이름만 바꾸지 않음. 센싱 외 보정·계획·레거시 publisher를 별도 분류 |
| `src/products/pinky_pro`, `src/drivers`, 제품 profile 설정 | `integrations/robots/pinky_pro`, 재사용 드라이버 연동, `profiles` | C++/ROS 드라이버와 장치 권한 보존. 실행 코드와 선언형 설정을 구분 |
| `src/hmi`, Fleet web, `src/site/cam` | 화면별 앱 조합·자산 | 제공 서버·인증·설치 대상 보존. Android Cam과 로봇 얼굴 화면을 Studio 웹으로 치환하지 않음 |
| `src/sim`, OMX demonstration·export 및 `tools/perception` | 시뮬 연동, `modules/learning`, 선택 worker | 실제 존재하는 기능부터 분류. 시뮬/학습 도구의 물리 권한 격리 유지 |
| `deploy/robot`, `deploy/site` | `deploy` + `profiles/installations` | 설치기·서비스·릴리스 잠금은 deploy, 구성 선택은 profiles. 실제 설치 경로 검증 |

현재 [palletizing progress](../../modules/processes/palletizing/progress.md)와 [Cell progress](../../src/site/cell/progress.md)는 SOURCE GO, ROS-SIM HOLD를 기록한다. [OMX adapter progress](../../src/products/omx/adapter/progress.md)는 SOURCE/LOCAL GO·전체 ROS-SIM HOLD를 기록한다. 이 표의 나머지 경로는 단계적 이전 후보이며, 현재 상태는 각 progress와 [STATUS](../../STATUS.md)를 확인한다.

## 15.2 적용 순서

**M0 기준선:** 15.1절의 각 대상을 파일·소유자·호출자·배포 대상에 연결한다. 패키지·실행 프로세스·ROS 인터페이스·원장 스키마와 기존 시험의 성공·실패를 기록한다. 전체 미래 디렉터리를 먼저 생성하지 않는다.

**M1 첫 작업 계약:** 고정 셀의 Recipe/Cell → Job → PlanBundle → Fleet grant → OMX Action → 결과에 필요한 계약만 확정한다. 작은 world/Skill API와 사이트·장치 원장 소유권을 함께 정한다. 기존 Job·grant·receipt와 새 계약 사이의 단위·ID·revision 변환을 시험한다.

**M2 한 흐름의 기능 추출:** Cell 공정 코어와 OMX의 작업 절차를 활용한다. 고정 셀의 계획·접수·로컬 실행·증거 대조 흐름을 연결하면서 필요한 실행 규칙과 연동만 분리한다. 범용 world나 모든 장치용 실행 프레임워크 완성을 선행 조건으로 삼지 않는다.

**M3 기존 진입점 연결과 설치:** Fleet·Pinky CORE·OMX의 기존 진입점이 추출된 모듈을 호출하도록 전환한다. 같은 역할의 새 서버를 병렬로 만들지 않는다. wheel/ament 파일 소유권, 실제 설치 후 실행, 최소 설치와 모델 제거를 확인한다.

**M4 회귀·전환:** 오프라인 재생 → 고정 셀 Gazebo 작업 → 승인된 제한 실기 순으로 비교한다. 첫 ROS-SIM 수용 범위는 16.2절이다. 구 진입점은 전환된 구현으로 향하는 단방향 호환층만 허용하며 같은 장치의 실행기를 중복 기동하지 않는다. 취소·단절·늦은 ACK·재시작·불명 결과의 기록과 동작도 비교한다.

**M5 정리와 확장:** 호출자 전환과 호환 시험 뒤 종료 버전을 명시한 호환층을 제거한다. 이후 Pinky 인계와 AI 제안을 별도 작업으로 연결한다. 사용하지 않는 모델·학습·미래 공정의 빈 패키지는 생성하지 않는다.

롤백 시 진행 중 물리 상태와 저널 스키마를 먼저 확인한다. 바이너리만 이전 버전으로 되돌린 뒤 같은 작업을 무조건 재실행하지 않는다.

## 15.3 기존 결정과의 전환 관계

| 기존 결정 | 이번 목표 설계와의 관계 | 구현 전 명시할 사항 |
|---|---|---|
| D-231·D-310·D-317의 현 소스 배치 | D-413이 네 영역을 목표로 채택. 미전환 패키지는 현재 경로 유지 | 실제 소비자·독립 시험·설치 묶음·호환층·롤백. 단계별로 경로 검사 전환 |
| D-315의 소스·실행·설치 구분 | 유지 | 폴더가 권한이나 배포 단위를 결정하지 않는 원칙 유지 |
| D-18의 공유 schema 기준 | 계약을 소유 모듈 API로 이전할 때 영향 있음 | 타입별 새 정본·호환 import·직렬화 대응·호출자 전환 순서. 두 정본을 동시에 유지하지 않음 |
| D-1·D-2·D-38의 Pinky 실행·writer | 유지 | CORE 단일 프로세스와 최종 cmd_vel owner의 동등성 확인 |
| D-296·D-333·D-336·D-369의 작업·장치·정지 경계 | 유지 | Fleet 작업 수락과 장치 Action 수락·완료·정지 증거를 계속 구분 |
| D-392의 모델 도구 경계 | 유지 | 모델 제공자 교체나 폴더 이동으로 실행 도구·자율 하달을 활성화하지 않음 |

목표 구조와 단계적 이전은 D-413으로 기록한다. 이 결정은 과거 ADR 본문을 소급 수정하거나 다른 Proposed 결정을 Accepted로 승격하지 않는다. 문서 내 16.1절 번호는 본 설계의 항목 번호이며 저장소 `D-*` 번호가 아니다.

<!--PAGE-->
# 16. 설계 결정과 구현 범위

## 16.1 이번 개정의 결정 기록

| 설계 항목 | 결정 | 거절한 대안 |
|---|---|---|
| 001 | 하나의 ROSY, 책임별 내부 모듈 | 모든 기능을 하나의 실행 패키지에 포함 |
| 002 | 소유 모듈의 공개 계약 | 거대한 domain/common 통합 객체 모음 |
| 003 | 공정·Skill·장치 연동 분리 | 팔레타이징을 UI 또는 장치 드라이버로 취급 |
| 004 | 모델·정책·학습 계약 분리 | 모든 AI를 같은 입력/출력 인터페이스로 통합 |
| 005 | 자원별 단일 실행 권한 | AI·공정·worker별 독립 직접 구동 |
| 006 | 장치별 최소 설치 | 모든 장비에 전체 모델·학습·팔 패키지 설치 |
| 007 | 외부 타입명 별도 마이그레이션 | 내부 폴더 이동과 ROS 타입 일괄 변경 |
| 008 | 문서·코드·실기 승인 구별 | 선언 검사나 시뮬 통과를 실기 완료로 표시 |
| 009 | 사이트 원장과 장치 원장의 사실별 소유권 | 하나의 중앙 DB·상태 기계로 모든 실행을 확정 |
| 010 | 고정 셀 한 작업 흐름부터 단계적으로 이전 | 전체 폴더·네임스페이스·패키징 동시 변경 |

## 16.2 구현의 첫 완료 단위

첫 구현 수용은 **AI 없이 고정 셀의 Cell → 계획 → OMX 실행 → 결과 확인을 Gazebo에서 연결하는 것**이다. [계층 아키텍처 로드맵](../plans/2026-10-01-rosy-layered-architecture-roadmap.md)의 2층·슬립시트 1장·팔레트 2개 시나리오를 재사용한다. 제품·레시피와 셀을 고정하고 전 슬롯의 사전 검증을 거친 뒤 승인된 범위에서 실행한다. 이 문서가 해당 시뮬레이션의 성공이나 실물 수용을 주장하지는 않는다.

| 확인할 동작 | 첫 완료 조건 |
|---|---|
| 계획과 접수 | Recipe·Cell 해시, Skill 버전, 검증 증적을 연결하고 변경·만료된 입력을 거부 |
| 실행 경계 | Fleet의 grant와 로컬 Action/attempt를 연결하고 동일 자원의 최종 writer를 하나로 유지 |
| 실제 결과 대조 | 제어기 수락·종료와 물품/그리퍼 관측을 구별. 독립 근거가 없으면 작업 완료로 확정하지 않음 |
| 중단과 복구 | 취소·단절·재시작 뒤 원장과 관측 대조. UNKNOWN/HOLD인 동작은 자동 재제출하지 않고 확인된 경계에서만 재개 |
| 설치 | OMX 셀에 Pinky·학습 의존성이 유입되지 않고 저장소 경로 없이 진입점이 실행됨 |
| 모델 제거 | 모델 제공자·가중치 없이 같은 결정적 작업이 동작 |

통과한 코드·설치·ROS-SIM 증거를 각각 기록한 뒤 제한 실기 검증을 별도로 진행한다. Pinky 인계와 AI 판단은 이 흐름 이후에 연결한다.

AI의 첫 연결은 읽기 전용 평가와 shadow 분석이다. 실제 명령에 영향을 주는 범위는 공급자 조건과 현장 검증이 충족된 이후 별도로 승인한다. 학습형 행동 정책은 검증된 좁은 Skill 하나부터 적용한다.

## 16.3 새 기능을 넣을 때의 판단 기준

작업 규칙이면 `processes`, 재사용 행동이면 `skills`, 관측 해석이면 `perception`, 다음 행동 판단이면 `decision`, 실행·자원·기록이면 `execution`이 소유한다. 외부 제품·SDK 연결이면 `integrations`, 실행 조합이면 `apps`, 현장 차이면 `profiles`에 둔다.

어느 곳에도 들어가지 않는 기능은 즉시 새 최상위 패키지로 만들지 않는다. 데이터의 기준 원장, 허용 의존성, 설치 대상, 실패 시 책임을 정의한 뒤 경계를 추가한다.

**ROSY가 소유하는 것은 특정 로봇이나 모델이 아니라, 작업의 의미·검증 가능한 실행·추적 가능한 결과다.**

<!--PAGE-->
# 부록 A. 출처와 관련 문서

## 기존 설계 근거

**[B01] ROSY_Palletizing_Benchmark_Report_v1.0.md.** 2026-10-01 작성본. 13~14장 작업·데이터 책임, 16장 무티칭 UX, 18장 물리 상태 복구, 19~21장 보호·배포·시험 원칙을 계승한다. 동봉 v1.1은 구조 적용 장을 본 설계와 동기화한 개정본이다.

**[B02] ROSY_Embodied_AI_Integration_Addendum_v0.1.md.** 2026-10-01 작성본. 판단·행동 정책의 분리, 관측과 확정 상태, 모델의 권한 제한, 인계·복구 원칙을 계승한다. 패키지와 경로 제안은 본 설계가 대체한다.

**[U01] ROSY 플랫폼 구조에 대한 사용자 확인.** 본 대화에서 합의한 `modules / integrations / apps / profiles` 구분, 내부 ROSY 네임스페이스, 기능별 데이터 소유권과 최소 설치를 반영한다.

## 공개 기술 근거

공개 기술 문서의 확인일은 2026-10-02이다. 아래는 패키징·ROS 인터페이스에 대한 근거이며 ROSY의 실기 검증이나 제3자 모델의 성능 승인을 의미하지 않는다.

**[S01] PyPA — Packaging namespace packages.** 네임스페이스를 복수 배포 패키지로 나누는 방식과 공유 부모의 규칙. [공식 문서](https://packaging.python.org/en/latest/guides/packaging-namespace-packages/)

**[S02] Python — PEP 420, Implicit Namespace Packages.** 암시적 네임스페이스의 동작과 패키징 원리. [공식 제안](https://peps.python.org/pep-0420/)

**[S03] Open Robotics — REP-144, ROS Package Naming.** ROS 패키지 이름의 고유성 및 공통 접두어 권고. [공식 제안](https://reps.openrobotics.org/rep-0144/)

**[S04] ROS 2 Jazzy — Creating custom msg and srv files.** 커스텀 인터페이스 패키지와 ament_cmake 구성. [공식 저장소 원문](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Beginner-Client-Libraries/Custom-ROS2-Interfaces.rst)

**[S05] Setuptools — Package Discovery and Namespace Packages.** namespace discovery·include/exclude·src layout과 산출물 확인. [공식 문서](https://setuptools.pypa.io/en/stable/userguide/package_discovery.html)

## 첨부 구성

이 저장소에서 이번 개정 대상으로 확인한 산출물은 본 Markdown이다. 별도 Word·PDF·벤치마킹 보고서·프로파일 묶음은 제공되거나 재생성됐는지 개별 확인해야 하며, 이번 문서 수정으로 동기화됐다고 간주하지 않는다. 문서의 예제 설정은 설치 도구나 실제 ROSY 구현을 대신하지 않는다.
