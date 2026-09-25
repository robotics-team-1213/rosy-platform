# 역할별 메뉴와 화면 이관 Implementation Plan

> **For implementers:** Execute one task at a time in an isolated worktree. Review the changed paths and tests before each commit.

**Goal:** D-263의 메뉴 원칙과 D-204의 화면 조립을 현재 `hmi`/`runtime` 구조에 맞춰 구현하고, 새 기능을 기존 화면의 패널로 계속 추가할 수 있게 한다.

**Architecture:** `src/hmi/dashboard`가 화면·셸·패널 자산을 소유한다(D-243). `src/runtime/api_web`은 화면/패널 레지스트리를 검증하고 현재 역할·CAP-001·inventory를 읽어 매니페스트를 제공한다. 상단 탐색은 화면 메타데이터 한곳에서 생성하고, CORE API가 명령 권한을 계속 판정한다.

**Tech Stack:** ROS 2 Jazzy 작업공간, FastAPI, Python/pytest, 정적 ES module·CSS, 선택적 Playwright. Node 서버·번들러를 추가하지 않는다(D-75).

**결정:** [D-263](../adr/D-263-role-based-menu-extension.md), [후속 D-265](../adr/D-265-base-surfaces-and-stop-access.md), [기존 D-204 설계](2026-09-24-role-surfaces-panel-composition-design.md).

---

## 시작 전 기준선과 충돌 처리

- 기준은 `Rosy OS` 로컬 `main`의 최신 커밋과 `git status --short`다. 현재 `feat/role-surfaces-s1`에는 D-204 S1 구현이 있지만 `src/core/core_api_web` 경로를 쓰고, 그 worktree에는 다른 control 변경이 있다. 그 worktree의 전체 diff를 가져오거나 브랜치를 그대로 병합하지 않는다. **관련 커밋의 계약·테스트를 읽고 현재 경로로 이식한다.**
- 새 작업은 저장소의 `.worktrees/<짧은이름>`에 `git worktree add --relative-paths`로 만든다. `.worktrees/`가 ignore 상태인지 먼저 확인한다. 시험 로그·브라우저 캡처는 `X:\DevTemp\`에 둔다.
- 현재 대시보드의 미커밋 `app.js`·`vision.js`·`ros-network.js`·`CMakeLists.txt`·`api/app.py` 작업과 겹치므로, 이관 전에 해당 작업의 소유자/커밋 상태를 확인하고 기준선에 포함한다. 기존 화면 동작을 덮어쓰지 않는다.
- 출발점 명령: `python -X utf8 -m pytest src/hmi/dashboard/test src/runtime/api_web/test src/runtime/gateway/test/test_dashboard.py src/runtime/gateway/test/test_dashboard_no_bundler.py -q`. Windows에서 실행 가능한 ROS 비의존 시험만 기준선으로 삼는다. 브라우저·Pi 수용은 별도다.

## Task 1 — SRS·API·ADR 계약 맞추기

**Files:** `docs/spec/ROSY CORE SRS.md`, `docs/reference/ROSY API & Protocol Reference.md`, `docs/architecture/16_ROSY_Interface_Design_Principles.md`, `docs/adr/D-265-base-surfaces-and-stop-access.md`.

1. D-265에서 갱신한 WEB-002의 화면/내부 항목 표를 구현 기준으로 확인한다. 기존 Dashboard/Control/Navigation/Map/Sensors/Devices/Diagnostics/Network/ROS/System/Settings/Events/Waypoints 각각의 새 위치를 기능 이관 시험에서 추적한다.
2. `/console`, `/setup`, `/device`, `/api/v1/ui/surfaces/{surface}`의 직접 URL·역할·401/403/404·자산 경로·매니페스트 필드를 API Ref에 고정한다. 프로토콜 필드가 새로 생기므로 `src/contracts/foundation/core_common/protocol/schemas.py`와 함께 변경한다(D-18). 경로/스키마를 계약 없이 먼저 구현하지 않는다.
3. D-265의 기반 화면·E-Stop 접근 결정을 계약에 반영한다. D-204 별도 브랜치의 "보이는 패널이 하나 이상일 때만 화면 노출" 규칙과 달라진 이유를 이관 기록에 남긴다.
4. `python -X utf8 -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`와 `python -X utf8 tools/harness/rosy_harness.py lint`를 실행한다. 문서/계약 커밋을 기능 코드와 분리한다.

## Task 2 — 레지스트리와 매니페스트를 현행 소유 경계에 이식

**Files:** `src/hmi/dashboard/panels.yaml`, `src/runtime/api_web/core_api_web/api/ui_registry.py`, `ui_manifest.py`, `v1/ui.py`, `v1/routes.py`, `app.py`, `src/contracts/foundation/core_common/protocol/schemas.py`; tests in `src/runtime/api_web/test/test_ui_registry.py`, `test_ui_manifest.py`, `test_surface_pages.py`.

1. D-204 브랜치의 registry/manifest 시험을 현행 경로로 옮긴다. 먼저 `python -X utf8 -m pytest src/runtime/api_web/test/test_ui_registry.py src/runtime/api_web/test/test_ui_manifest.py -q`의 의도한 실패를 확인한다.
2. 레지스트리가 화면 ID/제목/URL/역할/문법/슬롯/순서와 패널 ID/역할/CAP-001/자산을 검증하게 한다. 중복 ID·예약 경로·파일 누락·경로 순회는 기동 시 거부한다. 화면 메타데이터 밖에 메뉴 배열을 만들지 않는다.
3. 매니페스트는 `whoami` 역할, CAP-001, inventory를 분리해 읽는다. 기반 화면 세 개의 탐색 노출은 역할로 정하고 패널 수에 종속시키지 않는다(D-265). `not_provided` 패널은 생략하고, blocked 패널은 이유를 유지한다.
4. 알려진 화면+낮은 역할은 403, 없는 화면은 404, 미인증은 401로 확인한다. Viewer/Operator/Administrator × core/motor/hardware capability 매트릭스를 시험한다. 통과 후 해당 파일만 스테이징해 커밋한다.

## Task 3 — 공통 셸과 첫 패널

**Files:** `src/hmi/dashboard/shell/surface.html`, `shell.js`, `store.js`, `mount.js`, `shell.css`, `panels/system/events.js`, `panels/system/events.css`, `src/hmi/dashboard/CMakeLists.txt`, `src/runtime/api_web/core_api_web/api/app.py`; tests in `src/hmi/dashboard/test/`, `src/runtime/api_web/test/test_surface_pages.py`, `test/test_surface_shell_browser.py`.

1. 셸은 인증·현재 위치·공통 연결 상태·E-Stop만 소유한다. 패널이 자기 폴링/구독을 정리하도록 `mount → unmount` 계약을 시험으로 고정한다. 자산은 명시적 허용목록에서만 서빙하고 설치된 `share/dashboard`와 소스 폴백 모두 확인한다.
2. `/device`에 최근 이벤트 패널 하나를 붙여 전체 경로를 증명한다. `/dashboard`는 그대로 동작하게 둔다. 동일 탭 토큰 처리와 만료 뒤 재로그인 흐름을 확인한다.
3. 패널/매니페스트 실패에서 셸이 전체를 성공처럼 표시하지 않고, E-Stop 버튼의 API 전송 경로는 패널 조립에 의존하지 않는지 브라우저에서 확인한다. 네트워크 단절 때 전송 실패를 명확히 알리고 실제 정지를 주장하지 않는다.
4. `python -X utf8 -m pytest src/hmi/dashboard/test src/runtime/api_web/test src/runtime/gateway/test/test_dashboard.py -q` 및 opt-in 브라우저 시험을 실행한다. 실제 브라우저가 없으면 그 증거는 HOLD로 남긴다.

## Task 4 — 장치·정비 화면 이관

**Files:** `src/hmi/dashboard/index.html`, `app.js`, `settings.js`, `panels/host/*`, `panels/ros/*`, `panels/system/*`, `panels.yaml`; dashboard/API tests and `test/test_dashboard_browser.py`.

1. 호스트·네트워크·ROS 그래프·릴리스·신원·토큰·안전 한계·하드웨어 상태·이벤트를 `/device` 패널로 옮긴다. 각 패널의 호출 API와 Administrator 조건을 먼저 특성 시험으로 고정한다.
2. 화면의 빈 값·지연·단절·권한 부족을 실제 응답에 따라 표시한다. 패널 이관이 확인된 뒤에만 같은 카드를 기존 `점검` 뷰에서 제거한다.
3. Viewer/Operator의 `/device` 직접 접근 403과 Admin의 200을 확인한다. 패널 실패가 다른 패널과 정지 경로를 막지 않는지 브라우저로 확인한다. 단계별 커밋을 남긴다.

## Task 5 — 작업 준비 화면 이관

**Files:** `src/hmi/dashboard/settings.js`, `map.js`, `app.js`, `index.html`, `panels/nav/*`, `panels/docking/*`, `panels/traffic/*`, `panels.yaml`; `src/runtime/api_web/core_api_web/api/v1/docking.py`와 해당 테스트는 권한 계약 확인용.

1. 초기 위치, SLAM, 웨이포인트, 도크 준비, 교통 정책을 `/setup`의 절차 순서로 옮긴다. 도크 유형/등록/삭제는 기존 API대로 Admin에만 보이고 실행되는지, 도크 teach/운행은 Operator 권한인지 각각 확인한다.
2. `settings.js`의 해당 이벤트 처리와 API 호출이 새 패널에서 실제로 동작한 뒤 옛 핸들러를 제거한다. 복수 클릭·요청 실패·새로고침·뒤로가기에서 중복 명령이 없는지 확인한다.
3. `/setup`의 capability가 전부 빠져도 역할상 허용된 화면은 빈 이유와 함께 남는지 확인한다(D-265). 해당 시험과 브라우저 경로를 통과한 단위만 커밋한다.

## Task 6 — 운용 화면 전환과 메뉴 추가 계약

**Files:** `src/hmi/dashboard/app.js`, `index.html`, `shell/*`, `panels/safety/*`, `panels/drive/*`, `panels/nav/*`, `panels/vision/*`, `panels.yaml`, `src/runtime/api_web/core_api_web/api/app.py`, `src/hmi/dashboard/test/`.

1. 현재 운용 상태·지도·카메라·텔레옵·모드·도킹 실행을 `/console`로 옮긴다. 정지와 안전 해제의 역할·위치를 분리한다. 텔레옵 홀드·포커스 이탈·연결 끊김 시 zero 전송 및 UI 피드백을 기존 시험과 브라우저로 확인한다.
2. `/dashboard`의 호환 처리, `/` 진입, 딥링크 새로고침, 브라우저 뒤로가기를 확인한 뒤 기존 두 뷰를 폐기한다. API 경로와 사용자 토큰 저장 규칙은 보존한다.
3. 정적 계약 시험에 새 화면 추가 예제를 넣는다. `panels.yaml`의 화면/패널 선언 한곳에서 메뉴와 자산이 파생되는지, 패널 한 개 추가가 상단 메뉴를 늘리지 않는지 검증한다.

## 수용 기준과 중단 조건

- 세 화면의 메뉴·직접 URL·권한·CAP-001·inventory 조합이 API/브라우저 양쪽에서 일치한다. WEB-002의 기존 항목은 새 위치가 추적된다.
- 화면 전환/새로고침/390px 모바일/키보드에서 현재 위치와 E-Stop이 접근 가능하다. 패널이 0개이거나 하나가 실패해도 셸은 유지된다.
- `/dashboard` 이관 전후의 운전·지도·설정·인증 계약 시험이 통과한다. 첫 로드/파일 예산은 D-262 판정 이후 합의된 게이트를 따른다.
- 호스트 pytest나 브라우저는 Pi 설치·실제 정지·현장 운용 증거가 아니다. E-Stop의 물리적 응답은 별도 허가된 장치 시험으로만 승격한다.
- 다른 브랜치가 같은 경로를 먼저 바꾸거나 D-204가 새 구조로 병합되면, 새 diff를 비교하고 중복 작업을 제거한 뒤 다음 task를 시작한다. 충돌을 덮어쓰지 않는다.

## 구현 진행 상태 (2026-09-26)

- **완료:** Task 1~3 — API Ref/REST 응답 모델, 역할별 기반 화면 레지스트리, 공통 셸·E-Stop·`/device` 이벤트 패널. 권한별 메뉴와 빈 패널 접근 정책을 브라우저에서 확인했다.
- **초기 화면 단위 연결:** `/console` 상태 요약, `/setup` 웨이포인트 현재 위치 저장, `/device` 이벤트·진단 요약을 독립 패널로 등록했다. 웨이포인트 저장은 서버 판정 pose freshness가 `fresh`일 때만 API를 호출한다.
- **Task 4 첫 단위 완료 (2026-09-26):** `/device`에 관리자 보드 장치 관측 패널을 추가했다. 기존 `GET /api/v1/host/hardware` 응답의 장치별 상태·근거·측정 시각을 표시하고, 재점검은 관리자 API 요청으로만 전달한다. API 오류 뒤 마지막 값은 남기되 stale로 바꿔 최신 상태처럼 보이지 않게 한다.
- **추가 이관 단위 (2026-09-26):** `/device`에 시스템/기능 인벤토리, 네트워크·릴리스·커미셔닝 읽기, 토큰·안전 정책 패널을 등록했다. `/setup`에는 Operator API 계약을 따르는 초기 위치와 capability-gated SLAM 및 도킹 상태·teach/운전 조작 패널을 등록했다. 기존 `/dashboard`는 호환 화면으로 유지한다.
- **추가 이관 단위 (2026-09-26):** `/device` Host Agent 네트워크 모드/프로파일/Wi-Fi 연결 및 release rollback/recovery-hold 해제를 확인·재확인 후 요청하게 했다. ROS 그래프는 현재 구현된 `/api/v1/system/runtime` 응답의 ROS snapshot에서 읽으며 `/api/v1/ros/*`는 API Ref에 미구현이라 호출하지 않는다.
- **남은 이관:** `/setup`의 도크 종류·도크 등록 관리와 기존 설정 카드 정리, `/console`의 운전·지도·카메라·모드·도킹 실행 이전이 남아 있다. 텔레옵 hold/포커스/연결 해제 zero 전송 동등성을 확보하기 전까지 기존 운전 화면을 제거하지 않는다.
- **Task 4 카드 정리 남음:** 새 장치 화면의 readback은 추가됐지만 기존 `점검` 뷰 카드와 완전 동등하지 않으므로 기존 카드를 제거하지 않았다.
- **수용 범위:** 현재 테스트는 Windows 호스트·로컬 Chromium까지다. ROS 2/Pi 설치·실기 운전과 물리 E-Stop은 확인하지 않았다.
