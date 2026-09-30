# Rosy Pilot Teleop App Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pinky 1대를 브라우저(휴대폰 포함)에서 same-origin으로 직접 조종하는 정적
PWA **Rosy Pilot**(패키지 `pilot`)를 만든다. OMX 조종·Fleet 중계는 만들지
않는다.

**Architecture:** 설계 `docs/plans/2026-09-29-rosy-pilot-teleop-app-design.md`
(D-323). `src/hmi/pilot` 정적 자산을 `core_api_web`이 `/pilot`로 서빙한다. 앱은
`/api/v1`·`/ws/*`만 말하고 ROS를 모른다(CORE SRS §1.3). dashboard 패턴(바닐라
ES 모듈, 번들러 없음, CSP 인라인 금지, 단방향 import)을 계승한다.

**Tech Stack:** vanilla ES modules, web_common(`tokens.css`·`components.css`·
`ui.js`·`template.html`), Gamepad API, MediaRecorder, service worker. 시험:
pytest + Node.js 서브프로세스(JS 순수함수, `src/hmi/dashboard/test/test_camera_capture.py`의
`_run_js` 패턴), Playwright(가짜 CORE). **1차 기기는 현장 연결 태블릿(Lenovo
1200×2000, 브라우저)** — 가로 모드를 기준 레이아웃으로 잡는다(2026-09-27
UI/UX 검증 기록의 실측 기기).

**이 계획이 아닌 것:** OMX 조종 UI 활성화(레지스트리 슬롯만), Fleet 중계·인터넷
노출, 새 영상 전송 경로(MJPEG/WebRTC), dashboard 패널 매니페스트 통합, 실기
G4·DEVICE/FIELD 승격.

**Windows:** 호스트 pytest·Node·Playwright는 Windows에서 돈다.
`python -m pytest src/hmi/pilot/test src/runtime/api_web/test -q`.

---

### Task 1: 패키지 골격과 /pilot 라우트

**Files:**
- Create: `src/hmi/pilot/package.xml`, `src/hmi/pilot/CMakeLists.txt`,
  `src/hmi/pilot/index.html`, `src/hmi/pilot/styles.css`
- Modify: `src/runtime/api_web/core_api_web/api/app.py`
- Create: `src/runtime/api_web/test/test_pilot_route.py`

- [ ] **Step 1: 실패하는 테스트** — `test_pilot_route.py`를 `test_ui_route.py`
  패턴으로 작성: `GET /pilot` 200 + `text/html`, `GET /pilot/assets/app.js`가
      등록된 MIME로 200, 미등록 자산 404. pilot 자산 사전에 없는 이름 → 404.
- [ ] **Step 2:** `python -m pytest src/runtime/api_web/test/test_pilot_route.py -q` FAIL
- [ ] **Step 3:** `app.py`에 `_pilot_root()`(설치 share 우선, 소스 트리 폴백 —
  `_dashboard_root()` 미러), `pilot_assets` MIME 사전, `/pilot`·
  `/pilot/assets/{asset_name:path}` 라우트를 추가. `index.html`은 web_common
  `template.html` 기반 `ui-shell`(grammar `spatial`) + `ui-topbar`, tokens 링크.
  `CMakeLists.txt`·`package.xml`은 dashboard 것을 미러(ament_cmake → share/pilot).
- [ ] **Step 4:** PASS 확인 + `python -m pytest src/hmi/web/test -q` — pilot
  `index.html`이 `test_shared_controls.py`의 자동 탐색(`rglob("*.html")`)에
  걸려 ui-shell·버튼 kind·색 규칙을 통과하는지 확인.

### Task 2: harness 등록과 문서 지도

**Files:**
- Modify: `tools/harness/harness.yaml` (dashboard 항목 형식으로 `pilot` 등록)
- Create: `src/hmi/pilot/AGENTS.md`, `src/hmi/pilot/progress.md`, `src/hmi/pilot/logs.md`
- Modify: `src/hmi/AGENTS.md`, `src/AGENTS.md` (pilot 행 추가)

- [ ] **Step 1:** harness에 등록 뒤 `python tools/harness/rosy_harness.py generate`
  로 `index.md` 생성, `lint` 0 errors.
- [ ] **Step 2:** `python -m pytest test/architecture/ -q` — folder_layout·
  module_structure(D-168 방향·줄수 예산)·document_placement 통과.

### Task 3: stick.js 입력 매핑(순수)

**Files:**
- Create: `src/hmi/pilot/stick.js`, `src/hmi/pilot/test/test_stick.py`

- [ ] **Step 1: 실패하는 테스트** — Node `_run_js` 패턴. 대상: 데드존(경계
  안은 0, 경계 밖 연속), 감도 곡선(선형/지수), 최대 스케일 clamp, 축 반전,
  원점 대칭(`f(-x) == -f(x)`), 홀드 페달(전진/후진 이산 → linear), 키보드
  축, 속도 프리셋(저/중/고) 곱. `mapInput(raw, config) -> {linear, angular}`.
- [ ] **Step 2:** FAIL 확인 → 구현 → PASS. 기본 프리셋은 저속·넓은 데드존.

### Task 4: link.js 세션 상태머신

**Files:**
- Create: `src/hmi/pilot/link.js`, `src/hmi/pilot/test/test_link.py`

- [ ] **Step 1: 실패하는 테스트** — 가짜 WebSocket·주입 시계로: 연결 뒤 첫
  송신이 `{"type":"auth","token":...}`, close 4401 → whoami 재확인 후 재접속,
  4403 → 재시도 없음, 그 외 close → 백오프 1s→30s 단조 증가, 재연결 시 0
  발행 후 채널 정리, `visibilitychange` hidden → 즉시 `{linear:0,angular:0}`.
- [ ] **Step 2:** FAIL → 구현(dashboard `client.js` 토큰 저장 규칙 D-193 그대로:
  만료 없는 토큰은 sessionStorage) → PASS.

### Task 5: drivers/registry와 pinky_core

**Files:**
- Create: `src/hmi/pilot/drivers/registry.js`, `src/hmi/pilot/drivers/pinky_core.js`,
  `src/hmi/pilot/test/test_drivers.py`

- [ ] **Step 1: 실패하는 테스트** — registry: 미등록 kind 거부, 등록된
  driver만 반환. pinky_core: whoami 역할이 operator 미만이면 게이트 사유
  반환, capabilities(v1.21) `teleop` 플래그·`runtime.drive` 판정,
  `withheld.reasons` 전달, WS `{type:"teleop",linear,angular}` 발행,
  409 `CAPABILITY_WITHHELD` 수신 → 조종 중단 상태로 전환, e-stop API 호출.
- [ ] **Step 2:** FAIL → 구현 → PASS. 드라이버 인터페이스는
  `{kind, gate(session), channel(session), stop(session)}`로 고정(OMX 확장점).

### Task 6: screens/connect 게이트 화면

**Files:**
- Create: `src/hmi/pilot/screens/connect.js`
- Modify: `src/hmi/pilot/index.html`, `src/hmi/pilot/styles.css`

- [ ] **Step 1:** 역할(viewer 차단 안내)·capability·runtime 이유를 운용자
  문구로 표시. 차단 사유는 한 줄 배지 + 상세(triage식 — "전원 차단" 표현 금지).
- [ ] **Step 2:** 수동 확인 + Task 11 브라우저 시험으로 검증.

### Task 7: screens/drive 주행 화면

**Files:**
- Create: `src/hmi/pilot/screens/drive.js`, `src/hmi/pilot/vision.js`
- Modify: `src/hmi/pilot/index.html`, `src/hmi/pilot/styles.css`

- [ ] **Step 1:** `vision.js`는 dashboard `vision.js` 팩토리 패턴(시퀀스·
  abort·generation 가드)을 그대로, 표시만 풀블리드. stale 프레임은 HUD에
  STALE 배지. HUD: 상단 상태 배지(연결·역할·배터리), 좌하단 속도 readout,
  우상단 e-stop(`ui-button kind=irreversible`). 입력: 좌측 **원형 스티어링 휠**
  (Pointer Events — 터치점 각도→`steer`, 각도 클램프, 뗄 때 0), 우측 전진/후진
  홀드 페달, Gamepad API 폴링(끊김 → 0), 키보드. 모든 경로가
  hold-to-drive(~100ms)·`stick.js` 매핑을 공유.
- [ ] **Step 2:** Task 11 Playwright로 페달 hold→프레임→해제→0 검증.

### Task 8: screens/inputs 입력 조정

**Files:**
- Create: `src/hmi/pilot/screens/inputs.js`, `src/hmi/pilot/test/test_inputs_store.py`

- [ ] **Step 1: 실패하는 테스트** — localStorage 저장·로딩·무결성(알 수 없는
  키 무시), 기본값(저속·넓은 데드존), 프리셋 복원.
- [ ] **Step 2:** UI: 게임패드 축 매핑·반전·데드존·곡선·스케일, 가상 컨트롤
  크기·좌우 배치, 키 바인딩, 실시간 입력 미리보기 readout. 조정 즉시 반영.

### Task 9: 카메라 증거 — web_common 승격과 pilot 적용

**Files:**
- Create: `src/hmi/web/evidence.js` (dashboard `camera-capture.js`에서 승격)
- Modify: `src/hmi/dashboard/camera-capture.js` (재수출, 동작 불변),
  `src/hmi/web/CMakeLists.txt`, `src/hmi/pilot/screens/drive.js`
- Create: `src/hmi/pilot/test/test_evidence.py`

- [ ] **Step 1:** 승격은 dashboard 시험(`test_camera_capture.py`)이 그대로
  통과하는 상태에서 이동. 증거 본문 형식(4바이트 프리픽스)·바운드(5분/60MB)·
  운용 타임라인은 서버 `vision_evidence` 계약과 짝이므로 수치를 바꾸지 않는다.
- [ ] **Step 2:** pilot 스냅샷(PNG 다운로드)·클립 녹화(MediaRecorder)·증거
  업로드를 승격 모듈로 연결. 조종 화면에서 녹화 중 표시.

### Task 10: PWA 매니페스트와 서비스 워커

**Files:**
- Create: `src/hmi/pilot/manifest.webmanifest`, `src/hmi/pilot/sw.js`
- Modify: `src/hmi/pilot/index.html`, `src/runtime/api_web/core_api_web/api/app.py`
  (MIME 사전에 webmanifest·sw.js 추가)

- [ ] **Step 1:** manifest: name "Rosy Pilot", standalone, scope `/pilot`.
  sw.js: 앱셸 캐시, 캐시 키 = 이미지 버전. **오프라인에서 조종 경로를 열지
  않는다** — 캐시 히트 시에도 세션 게이트를 다시 통과해야 조종 활성.
- [ ] **Step 2:** 등록·갱신·오프라인 안전 거동을 Task 11 브라우저 시험에 포함.

### Task 11: Playwright 종단 시험과 게이트 기록

**Files:**
- Create: `src/hmi/pilot/test/test_pilot_browser.py` (가짜 CORE FastAPI fixture)

- [ ] **Step 1:** 시나리오: 접속 → 게이트 통과 → 페달 press → WS
  `{type:"teleop"}` 프레임 캡처 → 해제 → 0 프레임 → 409 주입 → 조종 중단+
  사유 표시 → e-stop 호출 확인 → viewer 역할 차단 → 오프라인 캐시 안전.
  뷰포트: 태블릿 2000×1200(기준)·1200×2000·협창 390px 회귀.
  `test_dashboard_browser.py` 패턴, wall-clock sleep 금지.
- [ ] **Step 2:** 게이트 기록: progress.md에 SOURCE GO(호스트 시험)·LOCAL
  GO(Playwright)만. ARTIFACT(이미지 closure에 pilot 포함 확인)·DEVICE(실기
  Pinky 주행 확인, 증거 `docs/validation/pilot-<date>/`)·FIELD는 HOLD.
  logs.md 기록, `rosy_harness.py generate`·`lint`, 루트 계약 시험
  (`test_harness_contracts.py` 포함) 통과.

---

**수용 기준 요약:** ① 호스트·브라우저 시험 전부 통과 ② 실기 Pinky에서 페달
hold-해제가 실제 정지로 이어지는 것을 육안·기록으로 확인(DEVICE) ③ 그 전까지
어떤 게이트도 승격으로 표기하지 않는다. host 통과는 기기·현장 수용이 아니다.
