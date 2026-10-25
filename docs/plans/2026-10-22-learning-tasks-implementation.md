# 공통 로봇·과제와 학습 계보 구현

## 승인된 목표와 범위

여러 종류·여러 개체를 기존 중앙 Account 프로젝트 안에서 등록하고, 참여 구성·과제·자료·학습·평가를 연결한다. 사용자 지시로 기존 D-840과 학습센터 구현을 계속한다. 신규 권한 부여, 장치 등록의 권위, 제어 실행 권한은 추가하지 않는다. 이번 등록은 기존 device identity를 참조하는 학습 메타데이터이며 검증된 장치 연결로 표시하지 않는다.

별도 제품·새 DB 서비스를 만들지 않고 기존 검수 SQLite에 불변 학습 대상·과제·자료 결속을 추가한다. Model/AI는 서버의 비공개 `host_id` 설정으로 식별하고 실행 요청의 호스트와 다르면 거절한다. 계산 호스트는 과제 정의가 아닌 매 실행의 속성이다. 미설정 호스트는 과제 학습을 시작하지 않는다. 기존 OMX 경로와 과거 작업은 유지한다.

## 모델과 계약

- 학습 대상: UUID 요청 identity, 이름, 종류, 모델 revision, 기존 device ID. 작성 신원은 기존 인증 세션에서 받는다. 실제 device 확인은 별도다.
- 불변 과제: 이름, 목적·성공·실패·초기화, 개별/협동, 참여 로봇과 component/role, 어댑터. OMX는 저장 프로필 ID와 revision을 서버가 결속하며 팔 identity 전체와 참여 구성이 일치해야 한다. 참여 순서·device/component/role을 함께 보존한다. 같은 요청 identity를 다른 내용으로 재사용하면 거절한다.
- 지원 범위: 임의 종류를 등록할 수 있으나 현재 실행 어댑터는 OMX다. OMX 종류·저장 프로필·행동 서명·개별/협동 구성이 맞아야 실행한다. 다른 어댑터는 준비 안내를 제공한다.
- 자료 결속: dataset identity와 revision을 과제에 영속 결속한다. 다른 과제·참여 구성으로 암묵적으로 재사용하거나, 과제와 다른 프로필/행동 서명을 실행하지 않는다. 같은 과제에서 ACT/HIL-SERL 비교는 가능하다.
- 역사 자료의 최초 결속은 명시적 사후 연결로 기록하며 원래 수집 시 그 과제로 촬영했다는 주장을 하지 않는다. source/review/conversion revision을 기존 자료 receipt와 함께 보존한다. 전용 수집 provenance는 향후 장치 수집 연결에서 추가한다.
- 호스트 간 과제 전달: manage 사용자가 JSON 메타데이터를 명시 export/import한다. 같은 프로젝트와 canonical 과제 revision·로봇/device/component 매핑·프로필을 검증하고 같은 과제 identity를 보존한다. 가져오기는 실제 로컬 관리자를 기록하며 원본의 작성 신원을 인증한 것으로 복제하지 않는다. 세션·키·HF 연결·장치 권한은 전달하지 않는다. 자동 동기화는 하지 않는다.
- 실행 계보: 선택적 `task_id`를 기존 run 요청에 추가한다. 과제 실행은 서버에서 자료·프로필·참여 범위·host를 검증하고 run 및 artifact에 불변 과제 정보를 보존한다. 기존 task 없는 기록은 과거 비결속 작업으로 남긴다. 지속 경험의 추가 입력에도 같은 과제 결속 검사를 적용한다.
- 두 SQLite의 순서: 자료 검증 → review DB의 불변 과제/자료 결속 commit → center DB의 요청 identity 예약과 worker request 저장 → worker 실행. 결속 후 중단은 안전한 예약으로 남아 같은 요청으로 재시도한다. 실패한 실행 때문에 다른 과제에 자료를 재결속하지 않는다. 동일 request의 기존 실행은 새 worker를 시작하지 않는다. 구버전 rollback 전 과제 결속 지속 worker를 중단하고 입력 게시를 차단한다. task-aware 코드가 돌아오기 전 재개하지 않는다.
- worker request와 run에 같은 불변 lineage snapshot을 보존한다. 결과 조회·모델 ZIP의 `learning-task.json`에 과제/참여 구성/선택 component/자료 revision/프로필 revision/실제 host 및 평가 파일 해시를 함께 제공한다. 기존 정책 weights 검증을 유지하며 평가 bytes가 lineage receipt와 맞는지 확인한다.
- HTTP: 기존 `/api/learning/` 아래 학습 대상·과제 조회/생성. GET view, POST manage·CSRF·Origin·본문 크기 제한을 그대로 사용한다. 등록은 소스 경로·명령·자격을 받지 않는다. 기존 review-app 로컬 HTTP 문서가 계약을 소유한다.

## 화면

공통 `/learning/tasks`에서 학습 대상 → 과제 → 자료·방법·실행 → 결과를 진행한다. 프로필·리더/게임패드·카메라 설정은 기존 OMX 설정 화면으로 연결한다. 빈 상태는 다음 준비 행동을 제시한다. 미지원 어댑터·호스트 불일치·실행기 미설정을 실행 가능으로 표시하지 않는다. 기존 `/learning` 홈에서 이 흐름을 우선 제공한다. 중앙 로그인·HF 관리는 기존 `/accounts`를 사용한다.

## 작업·검증

1. 불변 SQLite registry 및 충돌/프로젝트/그룹/서명/호스트/자료 혼합 거절 단위 회귀를 먼저 추가한다.
2. 기존 run·지속 입력·artifact와 결속하고 HTTP ACL 회귀를 추가한다.
3. 과제 중심 웹 화면과 홈 연결, 브라우저 시나리오를 구현한다. 서명 코드 의존 폐쇄와 browser scope를 갱신한다.
4. 커밋 SHA를 원격 시험하고 기존 실패와 비교한다. 모의 환경의 두 개체 개별/협동·호스트 불일치·서명/그룹 거절·재접속 보존을 확인한다. 모의 정책 시험은 실제 학습 품질·실물 연결 수용으로 표시하지 않는다.
5. 독립 검토 후 배포 계획의 보호 서비스·서명 이미지·AI 자원 격리를 확인한다. 운영 활성화·실물 실행은 그 증거 없이 완료로 선언하지 않는다. 게시와 착지는 현재 Git 규약을 따른다.

시험 산출물: `test_learning_tasks.py`의 두 host metadata 왕복·불일치 거절,
`test_learning_tasks_http.py`의 권한·CSRF/Origin·지속성,
`test_experiment_tasks.py`의 개별/협동 run·추가 경험·artifact 평가 해시,
`test_learning_tasks_browser.py`의 로봇→과제→실행→재접속 흐름을 제공한다.
`test_model_pc_autoupdate.py`와 `test_browser_scope.py`는 새 파일의 배포/검사 폐쇄를 확인한다.
모두 커밋 후 `tools/remote/remote_pytest.py`로 실행하고 각 로그를 `known_failures.py`와 비교한다.
실제 Fleet/두 보호 origin의 수용은 기존 [배포 계획](2026-10-22-fleet-learning-entry-deployment.md)을 별도 gate로 따른다.

독립 검토 1회: architecture는 경계 적합/세 가지 구체 불변식 요구, critic은 호스트 중립 과제 전달·두 DB 복구·평가/ZIP 계보·명시 회귀 모음을 요구했다. 위 항목으로 보완했다. 구현 검토에서 이 조건을 다시 확인한다.

## 복구와 대안

불변 신규 테이블만 추가하며 기존 라벨·계정·작업은 수정하지 않는다. 기존 릴리스로 전환해도 등록 기록을 삭제하지 않는다. 별도 공통 서버는 동기화/인증/배포 부담이 크고, OMX 프로필을 범용 robot ID로 재사용하는 방법은 종류·개체·구성 요소를 혼동하므로 사용하지 않는다. 현재 호스트별 원장은 자동 동기화하지 않는다.
