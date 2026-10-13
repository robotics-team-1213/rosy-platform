# Rosy Account Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rosy Account 하나로 모든 사용자 앱에 로그인하고, 권한이 있는 기능의 인증·세션 연결을 자동 완료하며 계정·권한·회수·감사를 한곳에서 관리한다.

**Architecture:** 하나의 논리적 Rosy Account authority를 기존 Fleet 프로세스와 SQLite에서 시작한다. 각 앱·CORE·학습 서버는 같은 사용자 신원을 검증하되 자기 자원의 권한과 작업 admission을 담당한다. 기존 비밀번호·프로필·세션 구현을 재사용하고, 앱별 비밀번호 저장소와 수동 토큰 전달을 없앤다.

**Tech Stack:** 기존 Python/FastAPI, SQLite, scrypt, 설치된 서명 라이브러리, 공통 web 모듈, Pilot/Cam Android, 원격 pytest/Chromium. 구체적인 앱 간 인증 protocol과 wire schema는 Task 1에서 계약으로 확정한다.

---

## 0. 상태와 확정된 사용자 요구

- 2026-10-14 구현 및 검증 진행. 아래 상태표를 기준으로 판단하며 push·배포·실계정 전환은 별도다.
- 기준 source: `62fbb5a13d`.
- 사용자 확정: Fleet에 한정하지 않고 로봇·Pilot까지 통합. 후속 요청으로 학습·리뷰 등 모든 앱을 하나의 Rosy Account로 연결한다.
- 사용자 확정: 각 앱 로그인 뒤 별도 인증 코드·토큰 붙여넣기·세션 연결 절차 없이 권한 내 기능을 바로 사용한다.
- 감사 결과: password/session/profile/site-users/server-app 131개 원격 시험 통과, NEW 0. 실제 최신 배포 및 개인 브라우저 수용은 미확인이다.
- D-757이 통합 신원/세션 architecture를 확정하고 D-549를 대체한다. D-519/683/686/689의 기존 구현과 D-755의 외부 계정·협업 계획을 이 문서의 출발점으로 한다.
- 계획 브랜치: `docs/rosy-account-plan`. 구현 브랜치: `feat/rosy-account-pipeline`. 기존 학습 계정 변경을 현재 main과 합쳐 보존한다.

## 1. 제품의 완료 상태

1. 어느 앱에서 들어와도 같은 Rosy Account 로그인으로 안내하고 로그인 후 원래 앱·업무로 돌아온다.
2. 같은 브라우저에 유효한 Account 세션이 있으면 다른 앱에서 비밀번호를 다시 묻지 않고 앱 세션을 연결한다. 브라우저/기기 간 쿠키를 복사하지 않는다. 새로운 기기는 한 번 인증한다.
3. 서버가 사용자·대상 사이트/로봇/프로젝트·허용 기능을 결정한다. 앱은 이 결과로 메뉴와 행동을 구성하고 모든 API·WebSocket도 재검증한다.
4. 필요한 인증 세션과 연결은 자동 갱신한다. 사용자는 만료·회수·네트워크 장애와 권한 부족을 구별할 수 있고 복구 후 초안을 유지한다.
5. 계정 발급·정지·권한 변경·비밀번호 초기화·세션 회수는 한 관리자 화면과 같은 서버 경로를 쓴다. 서비스 재시작이 적용 수단이 되지 않는다.
6. 모든 사람의 행위는 변경되지 않는 account identity로 기록한다. 이름·login·email 변경으로 과거 감사 이력이 다른 사람에게 넘어가지 않는다.
7. Rosy Account로 접근한 작업이 기존 CORE/OMX/학습 승인 경로를 통과한다. 인증 자동 연결은 임무 실행, 로봇 움직임, 데이터 외부 게시를 자동 승인하지 않는다.

### 인증 세션과 업무 세션의 구분

| 자동 처리 대상 | 별도 업무 의미를 유지하는 대상 |
|---|---|
| 로그인 확인, 앱 세션 교환, 대상별 접근 자격, 갱신, 재연결 | Pilot 운전석 점유, 수동 조작 deadman, 임무 실행 승인 |
| 허용 자원/기능 조회, 권한에 맞는 앱 진입 | 로봇 최초 현장 등록·신뢰 설정, 카메라 물리 보정 |
| 이미 연결한 외부 계정의 허용 scope 내 사용 | 외부 서비스 최초 동의·추가 scope, 검수 승인·외부 게시 |

업무 세션도 권한 내에서 불필요한 인증 확인을 반복하지 않는다. 다만 자동 로그인/재연결이 운전석을 빼앗거나 이전 명령을 재전송해서는 안 된다.

## 2. 접근 방식과 권장안

| 방식 | 장점 | 비용/한계 |
|---|---|---|
| **권장: 기존 Fleet 안에 공통 Account authority** | 기존 해시·SQLite·세션 재사용, 별도 운영 서버 없이 전 앱 통합 시작 | Fleet 가용성과 authority 장애 정책을 정해야 함 |
| 처음부터 별도 인증 서비스/외부 IdP | 다중 현장 federation·표준 SSO 확장에 유리 | 배포·복구·데이터 이전이 함께 늘어남 |
| 각 앱이 계정 복제 | 단기 수정량이 작아 보임 | 비밀번호/회수/권한 불일치가 남아 사용자 요구를 충족하지 못함 |

authority는 하나의 논리적 계정 원장이다. 사이트마다 같은 사람의 독립 계정을 만들지 않는다. 다중 현장 배치는 사용자 scope와 trust로 확장하며, 지금 승인되지 않은 별도 서비스나 동기화 복제 시스템은 추가하지 않는다.

## 3. 전 앱 적용 목록

정본은 `shared/web/surfaces.yaml` 및 실제 API/설치 진입점이다. 실행자는 아래 목록과 등록된 모든 surface를 대조하여 누락 0을 남긴다.

| 대상 | 현재 소스 경계 | 목표 |
|---|---|---|
| Fleet Console의 operate/map/install/cell/profile | `operations/site_ui/console`, `operations/fleet/fleet/server/auth` | 공통 Account 진입·관리·자동 세션 |
| 로봇 Dashboard | `middleware/robot_ui/robot`, `middleware/core/api/core_api_web/api` | 중앙 신원 검증, 로봇 scope·권한 검사 |
| Pilot web/PWA 및 Android shell | `middleware/robot_ui/pilot`, `middleware/robot_ui/pilot/android` | 한 계정 로그인, 대상 자격·연결 자동화, 좌석/종료 보호 |
| Rosy Cam | `operations/site_ui/cam` | 사용자 로그인 공통화, 카메라 등록 자격과 사용자 세션 분리 |
| 학습/검수/모델 작업 | `learning/curation/perception/review_app_web`, `learning/training/perception` 및 현재 서버 owner | 개인 식별과 프로젝트별 열람·편집·승인·관리 검사 |
| 외부 데이터/모델 연결 | D-755의 learning provider 구현 경계 | Rosy Account 소유 연결; 개인/팀 자격 분리 |
| Games 및 시뮬 도구 | `operations/apps/games/games/web`, `integrations/simulation/gazebo/scripts/lane_live_view.html` | 사용자 조작 진입점 인증; 공개 읽기라면 명시적 read-only 계약 |
| 진단·장치 Face·공통 라이브러리 | `middleware/perception/web/diagnostic.html`, `middleware/robot_ui/face`, `shared/web` | PARKED·비대화형 표면은 로그인 창을 강제하지 않음. 관리/조작 endpoint가 있으면 공통 권한 적용 |

비대화형 서비스·AI·장치 자격은 기계 신원으로 유지하고 사람 계정으로 자동 승격하지 않는다. Discord 등 연결 채널은 검증된 Account 연결과 해당 행위의 권한이 필요하며 메시지 수신 자체를 로그인 증명으로 삼지 않는다.

## 4. 설계에서 먼저 닫을 계약

- **권한 모델:** 현재 Fleet `operator`와 `policy-admin`은 다른 권한이다. 이름 순서로 상속시키지 않는다. 기존 역할을 명시적 capability 표로 옮기고 Account 관리자·로봇 조작·정책 수정·학습 승인 권한을 분리한다. 신규 wire 역할명은 ADR/API에서 먼저 확정한다.
- **자원 범위:** account + action + site/device/project 조합으로 허용을 결정한다. 다른 장치·프로젝트의 정상 자격은 거부한다.
- **앱 간 연결:** 같은 origin만 가정하지 않는다. HTTPS의 등록된 callback, 일회용 교환, 요청 결속/재사용 방지, native public client의 PKCE 등 필요한 표준 보호를 검토해 확정한다. 새 자체 인증 protocol을 즉석에서 만들지 않는다.
- **자격 보관:** 중앙 쿠키는 HttpOnly/Secure와 CSRF 보호. URL·로그·localStorage에 장기 bearer/refresh token을 전달하지 않는다. Android는 플랫폼 보안 저장소와 검증된 callback을 사용한다.
- **토큰 검증:** 서명·issuer·audience·만료·용도·허용 알고리즘을 고정 검증한다. unknown key, 잘못된 시간, 타 사이트/로봇 replay는 거부한다. 키 배포·회전·폐기와 오프라인 시계 조건도 포함한다.
- **권한 회수:** D-757의 목표 계약은 연결 중인 모든 앱/CORE에서 30초 이내 회수, 단절된 verifier의 접근 자격은 최대 5분 만료다. 이는 아직 구현된 SLA가 아니다. 영속된 계정/권한 revision과 갱신 시 재검증으로 증명하고, 무조건 즉시 회수라고 표현하지 않는다.
- **로그아웃:** 기본 사용자 로그아웃은 해당 로그인 session family의 전 앱 자격/갱신을 종료한다. 관리자의 계정 정지·비밀번호 초기화·전체 로그아웃은 모든 기기 세션을 회수한다. 이미 발급된 오프라인 자격의 잔여 시간은 위 한계를 따른다.
- **장애:** Account 장애 시 새 로그인/자격 갱신/관리 쓰기는 거부한다. 기존 제한 수명 자격의 허용 범위만 유지하고 만료 후 무인증으로 전환하지 않는다. Pilot은 기존 deadman/lease 종료를 따르고 CORE의 안전·정지 경로를 보존한다.
- **외부 서비스:** Rosy Account가 모든 외부 provider의 계정을 대체한다는 뜻은 아니다. 최초 연결/동의 뒤에는 권한 내 세션을 자동 처리하며 연결 해제·scope 축소·작업 중 회수를 D-755와 함께 처리한다.

## 5. 실행 순서와 단계별 완료 조건

각 Task는 관련 실패 시험 추가 → 커밋된 HEAD 원격 실행 → 최소 구현 → 원격 재검증/known_failures 비교 → 정확한 파일만 커밋 순으로 수행한다. 계획에 새 API 이름을 기정사실로 넣지 않는다. Task 1에서 API/스키마를 확정한 뒤 후속 세부 patch와 시험 이름을 고정한다.

### Task 1: 전체 진입점 및 권한 계약 확정

**Files:** `shared/web/surfaces.yaml`, `docs/adr/D-549-central-auth-service.md`(참조), `docs/adr/D-755-learning-data-and-collaborative-provider-accounts.md`(참조), `docs/spec/ROSY CORE SRS.md`, `docs/reference/ROSY API & Protocol Reference.md`, `contracts/foundation/core_common/protocol/schemas.py`.

1. surface→API/WS→인증 owner→runtime host→설치 이미지→권한→검증 시험 표를 만든다. CLI/다운로드/영상/worker 경로도 포함한다.
2. Architecture 결정은 [D-757](../adr/D-757-rosy-account-unified-app-sessions.md)로 완료했다. protocol·capability·migration schema의 상세 계약과 전체 진입점 매트릭스는 아직 남아 있다. 추가 ADR이 필요하면 파일 직전에 선점 도구를 사용한다.
3. 기존 역할의 허용/거부 표와 신규 관리 권한을 정의하고 default deny를 고정한다. 관리자라고 모든 조작/승인이 자동 허용되지는 않는다.
4. API reference와 shared schema에 확정된 protocol만 반영한다. 안전 경로 변경은 D-430 독립 검토를 계획한다.

**Done:** 모든 표면의 적용/비대화형/주차 상태에 사유가 있고, 미확정 protocol·역할·회수 수치가 구현 전에 해소됨.

### Task 2: 계정 원장과 기존 계정 이전

**Files:** `operations/fleet/fleet/server/auth/password_session.py`, `site_users.py`, `site_auth.py`(동일 auth holder), `operations/fleet/fleet/server/app.py`, `deploy/site/site_users.py`; tests `operations/fleet/test/test_password_session.py`, `test_self_profile.py`, `test_site_users.py`.

1. 계정/권한/세션 revision을 가진 durable 원장을 기존 DB에 추가하고 migration 버전을 기록한다.
2. YAML의 사람 계정과 SQLite의 **변경 완료 비밀번호**·프로필을 함께 이전한다. 초기 YAML 해시로 되돌리지 않는다. token/service/AI 행은 보존한다.
3. 중복 identity/login 충돌은 자동 합치지 않고 보고한다. 실행 재시도는 idempotent여야 한다.
4. 계정 존재·권한의 정본을 한곳으로 전환한다. YAML과 DB의 이중 편집을 막고 watcher의 사람 계정 재시작 의존을 제거한다.
5. transaction 실패, 재시작, 동시 관리자 수정, credential 세대 변경과 세션 cache race를 시험한다.

**Done:** 기존 비밀번호가 유지되고 계정 정지/권한 변경이 재시작 없이 적용됨. 임시 관리자 bootstrap·마지막 관리자 보호·복구가 검증됨.

### Task 3: 공통 로그인과 자동 앱 세션

**Files:** `operations/site_ui/console/shared/password-login.js`, `authorization.js`(동일 shared holder), `shared/web`, Fleet auth holder; tests `operations/fleet/test/test_password_login_browser.py`, `test_fleet_account_browser.py`, `test_password_session.py`, `test_self_profile.py`.

1. 기존 첫 비밀번호 변경·내 프로필·로그인 복귀를 공통 Account 흐름으로 연결한다.
2. 앱 시작 시 상태 확인→필요 시 Account 로그인→일회용 교환→사용자/권한 재조회→허용 화면 진입을 구현한다.
3. 갱신은 동시 요청을 합치고 실패를 무한 반복하지 않는다. 401/403/네트워크 불명을 구별하고 권한 없는 polling을 멈춘다.
4. 로그아웃·정지·다른 탭의 계정 전환 때 캐시와 표시 신원을 갱신한다. A 사용자의 응답/초안이 B 사용자에게 보이지 않게 한다.
5. 권한 축소 후 서버 API 거부와 UI 변경, 허용되지 않은 return URL 거부, 재연결 시 명령 재실행 금지를 실브라우저로 시험한다.

**Done:** 같은 브라우저에서 다른 앱으로 이동할 때 재로그인/코드 복사 없이 접근. 새 기기는 한 번 로그인하고 이후 자동 갱신.

### Task 4: 관리자 계정·권한 화면

**Files:** `operations/site_ui/console`, Fleet auth holder, `operations/fleet/fleet/server/app.py`, `shared/web/surfaces.yaml`; tests는 Task 2 서버 시험과 Task 3 browser harness를 확장.

1. 계정 발급·정지/재개·권한/자원 scope 변경·초기화·전체 세션 회수를 제공한다.
2. 모든 관리 쓰기에 actor·target·변경 전후 권한·revision·결과 감사를 남긴다. 비밀은 기록하지 않는다.
3. 저장 뒤 원장을 재조회하여 적용 상태를 표시한다. 단절된 장치의 회수 대기를 완료로 표시하지 않는다.
4. self-escalation, 타 프로젝트 수정, 마지막 관리자 제거, stale revision 쓰기를 거부한다.

**Done:** UI 변경→서버 저장→기존 세션 권한 변화/거부→감사 재조회가 하나의 시험에서 증명됨.

### Task 5: CORE·Dashboard·Pilot·Cam 통합

**Files:** `middleware/core/api/core_api_web/api/deps.py`, `api/v1/auth.py`, `middleware/core/gateway/test/test_auth_pairing.py`, `middleware/robot_ui/robot`, `middleware/robot_ui/pilot`, `middleware/robot_ui/pilot/android`, `operations/site_ui/cam`, `deploy/robot/pinky_pro`, `deploy/site`.

1. CORE에 중앙 사용자 자격 검증을 연결하고 기존 장치 복구 인증을 명시적으로 구분한다.
2. 실제 등록된 사이트/로봇/앱 audience와 신뢰 키를 signed 배포·설정 경로로 전달한다. 장치 최초 등록은 사용자 로그인이 대신하지 않는다.
3. Dashboard/Pilot/Cam은 Account 신원을 받아 필요한 자격과 연결을 자동 준비한다. app마다 사람 비밀번호 DB를 만들지 않는다.
4. REST뿐 아니라 WS handshake/재연결/기존 장기 연결/영상·다운로드 경로의 권한·만료를 검사한다.
5. Android 브라우저 로그인 복귀, PWA 새로고침, 다중 로봇 이동, 만료/회수 중 좌석 해제·명령 중단을 시뮬에서 검증한다.

**Done:** 같은 사람이 Fleet→Dashboard→Pilot→Cam을 수동 토큰 없이 사용하고, 타 로봇 자격·회수된 사용자·잘못된 서명은 거부. 물리 동작 수용은 Task 8에서 별도.

### Task 6: 학습·리뷰·외부 계정·기타 앱 연결

**Files:** `learning/curation/perception/review_app_web`, `learning/training/perception/review_authority.py`, D-755의 현재 provider/worker 구현, `operations/apps/games/games/web`, `shared/web/surfaces.yaml`.

1. 진행 중인 학습 계정 구현을 재사용하고 Account subject를 사용자 정본으로 연결한다. 외부 provider identity를 Rosy 사용자 identity로 오인하지 않는다.
2. 프로젝트 열람/가져오기/편집/검수/구성원 관리/게시를 서버에서 구분한다. Fleet operator 역할을 학습 관리자로 자동 승격하지 않는다.
3. worker는 요청한 account·project·connection·credential generation을 보존하고 실행 시작/민감한 단계에서 권한을 재검사한다.
4. provider 최초 연결·동의 후 허용 범위 내 갱신/사용을 자동화한다. 해제/회수 시 새 작업과 대기 작업을 차단하고 실행 중 작업은 정해진 checkpoint에서 중단한다.
5. 전체 surface 목록을 다시 대조한다. Games/진단/개발용 경로의 우회나 공유 토큰만 남은 사람 쓰기 경로를 없앤다.

**Done:** 같은 계정으로 학습 작업까지 처리하고, 타 사용자/provider/project 자격 혼용과 비밀 노출이 없음. 외부 provider 실제 연결 수용은 따로 기록.

### Task 7: 전 경로 회귀와 장애/회수 시험

**Tests:** 기존 auth/profile/browser suites, `middleware/core/gateway/test/test_auth_pairing.py`, 각 앱의 기존 시험 holder와 Task 1 매트릭스의 추가 회귀.

필수 시나리오:
- 계정 발급→첫 변경→앱 이동→허용 행동→결과 재조회→로그아웃.
- viewer/operator/정책/계정관리/학습 권한별 허용과 거부, 수동 API 호출 우회 거부.
- 권한 변경 중 요청/WS/갱신 경쟁, 계정 정지, 전체 로그아웃, 비밀번호 초기화, 오프라인 접근 만료.
- 중앙 서비스 중단, DB 잠금/쓰기 실패, 재시작, key rotation, 시계 오차, 네트워크 복구.
- 320px·키보드·오류/로딩·계정 전환·초안 격리·자동 명령 재실행 금지.
- 설치된 wheel/ARM64/native/Android 자산 closure와 runtime config/overlay별 동일 계약.

노트북 pytest 금지. 커밋 후 원격 실행 예:

```powershell
python tools/remote/remote_pytest.py --sha <commit> --log-dir X:/DevTemp/projects/rosy-platform/<session>/logs/account -- operations/fleet/test/test_password_session.py operations/fleet/test/test_self_profile.py operations/fleet/test/test_site_users.py operations/fleet/test/test_server_app.py -q
python test/known_failures.py X:/DevTemp/projects/rosy-platform/<session>/logs/account/run-1.txt
```

브라우저 시험은 원격 runner의 실제 opt-in/Chromium 설치 절차를 확인하고 활성화한다. skip을 PASS로 세지 않는다. CORE와 동명 basename이 있는 suite는 별도 호출한다. 문서 계약 검사는 `test/test_network_topology_contracts.py`, `test/test_harness_contracts.py`를 별도 원격 실행한다.

**Done:** 정확한 최종 SHA별 결과, NEW 0, 독립 안전/인증 리뷰, 온라인 회수/오프라인 만료 실측, 적용 목록의 누락 0.

### Task 8: 배포·전환·실사용 인수

**Files:** `deploy/site/README.md`, `deploy/site/site_users.py`, 실제 site/robot/native/Android 배포 manifest, `docs/validation`의 새 날짜 기록.

1. 운영 계정·effective password·프로필·기계 자격·공개키·runtime overlay의 비밀 비노출 inventory와 rollback 자료를 만든다.
2. 격리 계정/DB에서 migration과 복구를 실행하고 기존 운영 데이터 보존을 재조회한다. 구 버전으로 되돌려 정지 계정이나 옛 비밀번호가 부활하는 rollback은 거부한다.
3. verifier 호환 배포→authority/관리 경로→앱 연결→기존 사람 로그인 경로 종료 순으로 단계 전환한다. 혼합 버전에서는 지원 여부를 표시하고 무인증 fallback을 두지 않는다.
4. 설정 watcher를 저장소의 관리 경로로 인수하거나 사람이 쓰는 원장에서 제거한 뒤 실제 현장 유닛 상태를 읽어 확인한다.
5. TLS/DNS·서명된 정확한 이미지/native/Android 버전·CI·설치 SHA를 확인한다. 원격 회귀 통과를 배포 증거로 대체하지 않는다.
6. 실제 사용자와 관리자 각각으로 모든 앱 로그인/허용 작업/거부/회수를 실행하고 서버 readback과 감사 이력을 확인한다. 사용자 대신 최종 비밀번호를 정하지 않는다.
7. 로봇 운전 시험은 별도 허가된 현장 수용 절차로 한다. E-Stop 해제·운동 명령을 인증 시험 편의로 실행하지 않는다.

**Done:** 계정 관리자와 실제 사용자가 전 앱 흐름을 확인하고, 운영자가 장애·회수·복구 절차를 실행할 수 있음.

## 6. 의존 순서와 최종 판정

`Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8`을 기본 순서로 한다. 앱 adapter 작업은 공통 계약과 시험 fixture가 안정된 뒤 나눈다.

완료표는 SOURCE / REMOTE TEST / CI / INSTALLED / RUNTIME / USER ACCEPTANCE를 각각 기록한다. 한 앱의 성공으로 전체 완료를 선언하지 않는다. 전체 사용 앱에서 **로그인→자동 세션 연결→권한 내 업무→영속 결과 확인→회수/로그아웃**을 재현하고, 남은 예외가 있으면 해당 앱/기능을 미완료로 표시한다.

이번 계획에서 추가하지 않는 것: 앱별 계정 복제, 자체 암호 알고리즘, 범용 플러그인 framework, 별도 IdP 운영, 사용자에게 보이는 토큰 복사 절차. 외부 provider 동의와 물리 등록·업무 안전 조건은 생략하지 않는다.

## 7. 2026-10-14 구현·검증 기록

상세 wire·설치 계약은 [Account protocol](../reference/rosy-account-protocol.md)이다.
원격 로그는 X: `account-pipeline--063948/logs` 세션에 둔다.

| 등록 surface | 로그인/권한 owner와 구현 | 검증·남은 경계 |
|---|---|---|
| console | Fleet durable ledger, 계정 CRUD/CAS/감사, same-origin 쿠키, 명시적 site capability | 실제 SQLite 원장·HTTPS Chromium 관리 화면 검증; 운영 이전 별도 |
| robot | CORE AccountClient, 보호 쿠키, robot.read/operate/admin 분리 | 실제 authority→callback→API·갱신·회수·열린 WS 종료 검증 |
| pilot | 같은 CORE 앱 쿠키, 자동 복귀·재접속·계정 교체 격리 | HTTPS Dashboard→Pilot 재로그인 없는 복귀; 물리 조작 미실행 |
| pilot-shell | external browser PKCE, 검증 app link, Keystore 보관, native Bearer proxy | JVM·APK 및 서명 fixture 검증; 기기 app-link 수용 별도 |
| cam | 같은 native Account, camera.manage와 기계 스트림 자격 분리 | 관리 작업 회수/지연 응답 fence; 실제 폰 수용 별도 |
| pinky-review | 중앙 subject→기존 owner 고정, 프로젝트 capability, worker 재검증 | 공유 연결 owner 회수, 기존 provider 연결, 계정별 쓰기 CSRF·늦은 응답 차단 |
| game-board | 같은 receiver, site games.operate와 HTTPS Origin으로 /stop 보호 | 원격 114개 Games 시험; 미설정 보드는 공개 읽기 전용 |
| lane-live-view | /status.json·graph·run 기록 GET만 사용 | 비제품 시뮬 읽기 표면, 사용자 명령 발행 없음 |
| control-diagnostic | D-266 PARKED 비제품 개발 도구 | 운영 활성화·중앙 로그인 표면으로 승격하지 않음 |
| robot-face | 부팅·이름·일회 코드 표시 LCD | 입력/명령/사용자 세션 없음 |
| web-common | 공유 UI 라이브러리 | 독립 로그인·API owner 없음 |

검증 묶음: CORE web/account 관련 141개, Fleet·learning 연결 61개,
owner/client 재검증 32개, Games 114개가 각각 원격 통과했다(중복 포함, 합산하지 않음).
`3788d7696`의 통합 묶음 10개는 HTTPS 로그인 UI→Dashboard→Pilot SSO,
갱신→원장 회수→WS 15초 이내 종료, Fleet 관리자 UI, learning 계정·권한·장애 복구를
검증했다. 기존 공유 학습 연결은 소유자의 재연결로 현재 중앙 승인 session에 결속한다.

Native 최종 소스 `57243be29`는 Cam 431개, Pilot 107개 JVM 시험과 설정 포함 APK 빌드가 통과했다.
APK 공개 설정과 정확한 HTTPS callback/autoVerify manifest를 읽어 확인했다. 검증 로그는
X: `account-native--1143d2/logs`에 보관하며 원격 shell assets 4개도 통과했다.
배포 설정 회귀 31개와 실제 Caddy 설정 검증은 통과했으나 서비스 reload는 하지 않았다.

실계정 변경은 하지 않았다. 기존 계정 목록·사이트 TLS 이름·tailnet 이름을 읽기 전용으로
확인했으며 실제 주소/계정/인증서는 공개 저장소에 기록하지 않는다. 기존 LAN 인증서는
tailnet HTTPS 이름을 포함하지 않고 443 listener·Account 설정이 없으므로 설치 수용은
미완료다. 최종 native/착지 결과는 Git과 추가 검증 기록을 따른다. 최종 SHA CI·배포·
Android 실제 app-link 검증·사용자 수용을 SOURCE/원격 시험으로 대체하지 않는다.
