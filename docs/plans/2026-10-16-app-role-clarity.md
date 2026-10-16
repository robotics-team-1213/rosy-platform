# App Role Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 실행은 이 계획 검토 후 별도 요청 시 시작한다.

**Goal:** 앱 이름을 유지하면서 사용자가 현장 운영·한 대 관리·직접 운전·카메라 송신·학습 검수의 작업 경계를 화면과 이동 흐름에서 이해하게 한다.

**Architecture:** 현재 앱과 CORE/Fleet 서버, 정적 자산 서빙을 유지한다. 작업별 화면·API·정본·실행·완료 증거를 먼저 대응하고, 안내와 탐색을 정리한 뒤 검증된 범위에서 중복 쓰기를 제거한다. 공통 인증은 기존 Account 계획을 소비한다.

**Tech Stack:** 기존 정적 HTML/CSS/JavaScript, Python/FastAPI, Kotlin Android, ROS 2 Jazzy, 원격 pytest/Chromium, 기존 설치·자산 manifest.

**Spec:** [앱 책임 정리 설계](2026-10-16-app-role-clarity-design.md).

## 상태와 범위

2026-10-16 실행: Task 1 업무 소유표, Task 2 앱 이동, Task 4 기존 완료 표현/권한 경계 확인을 구현·검증했다. Task 3은 아래 실기 증거 조건에 따라 전체 중복 제거를 유보하고 같은 로봇의 Pilot 진입을 제공한다. Task 5의 호스트·설치·구조 확인 및 별도 DEVICE/FIELD 범위는 [실행 기록](../validation/app-role-clarity-2026-10-16/result.md)이 정본이다.

선행 조정: D-766의 증가 금지에 따라 `devices/` 연결/발견 소유 단위를 분리했다. 아래 초기 파일 목록의 `enrollment.js`, `camera-pairing.js`는 현재 `operations/site_ui/console/devices/`가 원본이며 URL은 유지된다. 새 `device-discovery.js`가 읽기·주소 안내·승인 앱 이동을 소유한다. Learning은 독립 앱 등록이 없어 개발 표면 제목 규칙을 유지한다. 기존 제목 계약을 느슨하게 바꾸지 않는다.

최초 계획 기준 HEAD는 `436d52a55`이며, 이후 사용자 실행 승인으로 위 상태까지 진행했다. 사용자가 승인한 방향은 이름을 유지하고 책임을 선명하게 하는 것이다. 배포·새 실기 전환은 수행하지 않았다.

기존 `2026-10-03-app-ownership-shared-transport-and-layout-migration.md`의 미완료 항목을 현재 소스와 대조해 재사용한다. `2026-10-05-app-web-srp.md`의 완료된 import/패널 펜스는 다시 구현하지 않는다. D-741 공통 셸과 D-757 Account 후속도 별도 owner를 유지한다. 이번에 역사 ADR 본문을 현재 경로로 덮어쓰지 않는다.

## Global Constraints

- Rosy Fleet/Robot/Pilot/Cam 이름과 현재 URL·포트·패키지·아이콘·레지스트리 id를 유지한다. Fleet의 id는 `console`이다.
- 현재 source holder는 `docs/reference/platform-folder-responsibilities.md`와 `tools/harness/platform_parts.yaml`을 따른다.
- 외부 앱은 ROS에 참여하지 않는다. CORE 프로세스와 최종 주행 명령 owner를 유지한다.
- 앱 전환·재로그인·재연결은 조종·임무 자동 재개나 쓰기 재전송을 일으키지 않는다.
- Account 통합은 기존 계획의 계약을 소비한다. 새로운 로그인 프로토콜·API를 임의로 만든 뒤 화면에 연결하지 않는다.
- 정지 조작은 해당 운용 화면에 유지한다. Cam·Face·Vision에 조종·정지 권한을 추가하지 않는다.
- 문서·설치·브라우저·실기 수용을 구분한다. Pilot의 기존 DEVICE GO를 보존하되 현재 대상별 적용 범위를 확인한다.
- 제품 편집은 격리 worktree에서 수행한다. pytest·브라우저 시험은 committed HEAD를 원격 PC에서 실행하며 노트북에서 실행하지 않는다.

## Review Focus

| 실패 조건 | 기대 동작 | 검증 owner |
|---|---|---|
| 등록되지 않거나 신뢰할 수 없는 대상 주소 | 잘못된 로봇으로 이동하지 않고 연결 안내 표시 | Task 2 |
| 로그인 만료·권한 회수·사용자 전환 | 올바른 업무로 복귀, 이전 사용자 상태·자격 노출 없음 | Task 2, 기존 Account 시험 |
| Pilot으로 이동하거나 운전 중 탭 이탈·연결 상실 | 기존 종료·deadman 적용, 복귀 후 자동 운동 없음 | Task 3 |
| 정지 응답만 오고 물리 결과가 확인되지 않음 | 요청과 확인 상태 구별, 범위 유지 | Task 4 |
| checkout에서는 보이나 설치 후 자산이 누락됨 | 설치된 Robot/Pilot/Fleet 진입과 링크 정상 제공 | Task 5 |

## Task 1: 현재 업무 소유와 이행 항목을 한 표로 고정

**Files:** Create `docs/reference/app-responsibilities.md`; modify `shared/web/surfaces.yaml`, `docs/reference/developer-guide.md` only where current description disagrees; inspect `test/architecture/test_app_roles.py`, `test/test_app_ownership_contracts.py`, `operations/fleet/test/test_document_imports.py`.

**Interfaces:** 소비자는 사람과 후속 Task다. 업무별 `화면/API/정본/최종 실행/완료 증거/소비자/이행 조건` 표를 제공한다. wire schema는 추가하지 않는다.

- [x] 현재 레지스트리 전체를 읽고 앱·서비스·도구·공유 라이브러리를 분류한다. Learning은 작업 화면, Vision은 서비스, Face는 표시 전용으로 기록한다.
- [x] Mission, 현장 등록·보정, 로봇 설정, 로컬 목표·도킹, 직접 운전, 카메라 송신, 검수·export의 실제 진입·쓰기·결과 조회를 따라 표에 연결한다. 기존 기능이 없으면 현재 미구현으로 표시한다.
- [x] 완료된 펜스는 현행 시험과 증거를 연결한다. 선언이 실제 경로와 다를 때만 기존 테스트에 서버 거절·쓰기 owner 검사를 보완한다. 이미 통과한 선언을 복제한 테스트는 만들지 않는다.
- [x] 이름 설명은 Fleet `현장 운영`, Robot `한 대 관리`, Pilot `직접 운전`, Cam `카메라 송신`, Learning `학습 자료 검수`로 맞추고 현재 D-741 셸의 자리 규칙을 보존한다.
- [x] 원격 관련 계약 시험과 lint를 확인하고 이 Task의 경로만 커밋한다.

**출구:** 후속 변경 대상이 `유지/안내 수정/링크 연결/검증 뒤 제거`로 구분되고 각각 owner·근거가 있다. 새 API·제품 기능이 필요한 항목은 별도 작업으로 분리한다.

## Task 2: Fleet·Robot·Pilot의 앱 간 이동을 대상을 유지한 채 연결

**Files:** Inspect/modify `operations/site_ui/console/roster.js`, `operations/site_ui/console/index.html`, `middleware/robot_ui/robot/surface-navigation.js`, `middleware/robot_ui/robot/panels.yaml`, `middleware/robot_ui/pilot/index.html`; reuse `shared/web/ui.js`, `shared/web/workspace.js` and the existing Account client. Tests: `test/test_fleet_workflows_browser.py`, `test/test_role_menu_panels_browser.py`, `middleware/robot_ui/pilot/test/test_pilot_browser.py`.

**Interfaces:** 기존 roster/connection/account 정보를 소비해 등록된 대상 앱으로 이동한다. 새로운 URL parameter나 자동 실행 API를 추가하지 않는다.

- [x] 현재 호출자와 Account 계약에서 신뢰된 대상 주소·식별자와 복귀 경로의 제공 위치를 확인한다. 새 계약이 필요하면 이 Task에서 분리한다.
- [x] 기존 브라우저 fixture로 `Fleet에서 로봇 A 선택 → Robot A`, `Robot A → Pilot A`, `Pilot A → Robot A` 시나리오를 추가한다. 링크·대상 표시를 단언하고 이동만으로 조종/임무 쓰기 요청이 0건임을 확인한다.
- [x] 미등록·유효하지 않은 대상, 권한 부족, 로그인 복귀, 사용자 전환 시나리오를 같은 시험에 추가한다. 신뢰되지 않은 origin 이동과 URL 토큰 전달은 거절한다.
- [x] 기존 이동 처리를 보완한다. 링크를 만들 수 없는 상태는 실제 사유와 복구 경로를 보이며 포트 숫자로 목적지를 합성하지 않는다. 로그인은 Account owner의 현재 흐름을 소비한다.
- [x] 원격 브라우저 시험에서 대상 유지·잘못된 대상 거절·쓰기 0건을 확인하고 커밋한다.

**출구:** 사용자가 어느 앱·어느 로봇에 있는지 알 수 있고, 이동과 인증이 업무 실행을 시작하지 않는다.

## Task 3: Robot의 중복 수동 운전을 Pilot 진입으로 전환

**Files:** `middleware/robot_ui/robot/panels/console/teleop.js`, `middleware/robot_ui/robot/panels.yaml`, `shared/web/surfaces.yaml`; inspect `middleware/robot_ui/robot/teleop.js` callers before removal. Tests: `test/test_role_menu_migration.py`, `test/test_role_menu_panels_browser.py`, `middleware/robot_ui/pilot/test/test_pilot_browser.py`, `test/architecture/test_app_roles.py`.

**Interfaces:** `console.teleop`은 기존 패널 계약을 유지하는 `Rosy Pilot으로 조종` 진입 패널이 된다. CORE의 조종 API·프로토콜은 유지한다.

- [x] Pilot `progress.md`의 2026-10-05 DEVICE GO와 D-323 Validation을 대조해 대상·릴리스·운전/해제/정지/연결 상실 확인을 증거표에 연결한다. 기존 성공을 재구현하거나 무효화하지 않는다.
- [x] 대상별 전환 조건이 충족되지 않으면 해당 대상의 이행 예외와 부족한 증거만 기록하고, 다른 Task는 진행한다. 실기 확인이 필요한 조작은 기존 장치 운용 절차로 별도 수행한다.
- [ ] 조건 충족 범위에 대해 기존 Robot 패널 시험을 링크 패널 계약으로 바꾼다. 로드만으로 조종 스트림을 만들지 않고 Robot의 정지 버튼은 남음을 확인한다.
- [ ] 같은 CORE의 Pilot 진입을 연결한다. 기존 조종 구현 삭제는 import·다른 화면 소비자를 확인한 파일에 한정한다. 레지스트리의 transitional ownership은 실제 중복 제거와 같은 변경으로 갱신한다.
- [ ] Pilot의 탭 이탈·누름 해제·연결 상실과 재연결 뒤 자동 재개 금지 시험을 확인한다. Android·OMX SIM은 적용 범위를 따로 기록한다.
- [ ] 원격 패널/역할/조종 회귀 시험 뒤 변경 경로만 커밋한다.

**출구:** 검증된 범위에서 조종 UI의 정본은 Pilot 하나이며, Robot의 로컬 목표·도킹·설정은 유지된다.

## Task 4: Fleet·Cam·Learning의 업무 안내와 완료 표시 정리

**Files:** `operations/site_ui/console/{index,install,site-map,accounts}.html`, `operations/site_ui/console/shared/fleet-header.js`, `operations/site_ui/cam/app/src/main/res/values/strings.xml`, `learning/curation/perception/review_app_web/{index,learning,catalog,pixels}.html`; inspect matching JS handlers before changing meaning. Tests: `operations/fleet/test/test_console_roles_browser.py`, `operations/fleet/test/test_fleet_header_browser.py`, `test/learning/perception/test_review_app.py`, existing Cam Android unit tests.

**Interfaces:** 기존 상태·권한·신선도·결과 계약을 표시한다. 검수 export를 학습 실행 또는 모델 활성화로 승격하지 않는다.

- [x] Task 1 표의 실제 불일치만 수정 목록으로 만든다. 정상인 화면은 다시 만들지 않는다. Fleet 설치·계정·지도는 같은 앱의 업무로 유지한다.
- [x] Fleet의 작업 요청과 완료, 정지 요청과 확인, Cam의 송신과 사이트 승인, Learning의 검수 승인/export와 학습·활성화를 기존 시험에서 확인하고 누락된 동작만 추가한다. 서버가 물리 확인을 제공하지 않으면 UI가 확인됐다고 표시하지 않음을 단언한다. 이미 같은 동작을 검증하는 시험은 복제하지 않는다.
- [x] 안내·링크·상태 표현을 기존 컴포넌트와 API 필드로 맞춘다. Robot/Pilot으로 넘길 업무를 Fleet 안에 복제하지 않는다.
- [x] Cam과 Face에 로봇 조작이 생기지 않았음을 기존 역할 가드로 확인하고, 변경한 Android 문자열은 해당 모듈 빌드/단위 시험으로 검증한다.
- [x] 원격 관련 시험 뒤 모듈별 독립 커밋으로 나눈다.

**출구:** 각 앱의 주 작업과 다른 앱으로 넘길 작업이 분명하며, 요청/연결/검수 결과가 실제 실행 완료와 섞이지 않는다.

## Task 5: 설치·화면·수용 증거를 묶어 전환 종료

**Files:** inspect/update only as needed `middleware/robot_ui/robot/CMakeLists.txt`, `middleware/robot_ui/pilot/CMakeLists.txt`, `middleware/robot_ui/pilot/sw.js`, `operations/fleet/fleet/server/console/static_routes.py`, `shared/web/shared-assets.json`; add `docs/validation/app-role-clarity-<실행일>/result.md` and update affected module `logs.md`/`progress.md` only for proven gate changes.

**Interfaces:** Task 1–4의 산출물을 기존 설치 단위로 제공한다. 새 JS/CSS가 생겼을 때 해당 서빙·설치·캐시 목록을 같은 변경에서 갱신한다.

- [x] 기존 `test/test_remaining_platform_installed.py` 및 해당 자산/route 시험으로 checkout 밖 설치에서 실제 파일과 HTTP 진입을 확인한다. 새 자산이 없다면 불필요한 manifest 수정은 하지 않는다.
- [x] committed SHA로 권한 있는 사용자/보기 전용/만료/미등록/연결 상실 시나리오를 원격 Chromium에서 실행한다. 휴대폰 390px, 태블릿 1200px, 데스크톱 1366px에서 업무 이름·이동·정지 조작을 확인한다.
- [x] 기존 affected selector가 고른 시험을 실행하고 `known_failures.py`로 NEW 0을 확인한다. CI FULL 요구가 있으면 그 결과를 별도 확인한다.
- [x] 기존 증거와 새 검증 결과를 SHA·대상·릴리스별로 연결한다. 실행하지 않은 DEVICE/FIELD는 NOT RUN으로 남긴다. Task 3이 닫히지 않은 대상은 이행 예외를 유지한다.
- [x] 완료된 화면/API/정본/실행/결과 표와 개발 가이드 링크를 맞추고 커밋한다. main 착지·push·배포는 사용자가 요청할 때 수행한다.

**출구:** 실제 설치·탐색·권한·종료 경로가 확인된 범위만 완료로 보고한다.

## 실행 순서와 검증 명령

순서: Task 1 → Task 2 → Task 3 → Task 4 → Task 5. Task 3의 대상별 실기 증거 보완이 남아도 Task 4의 독립 안내 수정은 진행할 수 있다. 우선 구현 묶음은 Task 1–2이며, 이후 중복 제거와 앱별 정리를 각각 검토 가능한 커밋으로 나눈다.

원격 실행 예시(제품 변경을 커밋한 뒤 실행):

```powershell
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/app-role-contracts -- test/architecture/test_app_roles.py test/test_app_ownership_contracts.py test/test_role_menu_migration.py operations/fleet/test/test_document_imports.py -q
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/app-role-browser -- test/test_fleet_workflows_browser.py test/test_role_menu_panels_browser.py middleware/robot_ui/pilot/test/test_pilot_browser.py -q
```

브라우저 실행 환경은 각 모듈 AGENTS/fixture의 Chromium·브라우저 opt-in 조건을 확인한다. 원격 로그의 실제 경로를 `python test/known_failures.py <run-log>`에 넘기고 skip만 된 시험을 통과로 세지 않는다. 서로 충돌하는 fixture/동명 테스트는 모듈별 별도 실행으로 나눈다.

거버넌스 확인:

```powershell
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

## 계획 자체의 검토

- 앱 이름·현재 source holder·기존 Account/셸/펜스 작업과 충돌하지 않는지 확인한다.
- Task 1의 소유 표 → Task 2의 이동 → Task 3의 이행 조건 → Task 4의 결과 표시 → Task 5의 설치·수용을 연결한다.
- 검토 때 합의할 구체 결과는 Robot 중복 운전의 링크 전환 범위와 미수용 대상의 예외다. 제품 실행은 아직 시작하지 않는다.
