# pilot logs

## 2026-09-29 · 8f4ecfe2 · feat(hmi): pilot 골격과 /pilot 라우트 (실행 계획 T1)
- 변경: 패키지 `pilot`(ament_cmake)·`index.html`(ui-shell spatial)·`styles.css`·`core_api_web` `/pilot`·`/pilot/assets` 라우트와 MIME allowlist·`core_api_web` package.xml `pilot` 의존성. 실패 테스트 선행.
- 증거: `test_pilot_route.py` 2 passed(404→200 확인). api_web 전체 72 passed·web_common 3 failed 는 `known_failures.py` 판정 0 new(기존 fleet 카메라 코너 스타일·system.js 결함, 2026-09-29 Windows).
- gate 변화: SOURCE GO.
- 결정: D-323.
- 교훈: 없음

## 2026-09-29 · 434ceb0b · feat(pilot): stick.js 순수 입력 매핑 (실행 계획 T3)
- 변경: `stick.js` — `shapeAxis`(데드존·감도 곡선·클램프·원점 대칭), `mapInput`(pad·pedals·keys), `PRESETS`(low/mid/high 클라이언트 상한). 모듈을 `pilot_assets`·CMakeLists 에 등록.
- 증거: `test_stick.py` 8 passed(Node 서브프로세스, `_run_js` 패턴). 라우트 시험 포함 10 passed.
- gate 변화: 없음(SOURCE GO 유지).
- 결정: D-323.
- 교훈: 없음

## 2026-09-29 · uncommitted · docs(pilot): 원형 휠·동시 녹화 실현성 평가를 D-323에 보강
- 변경: D-323 본문에 '보강 평가' 단락 추가 — 원형 스티어링 휠(Pointer Events 각도→steer, v1 채택)과 조종 중 카메라 녹화(기존 JPEG 폴링+MediaRecorder 바운드 재사용, v1 채택)의 실현성과 후순환(WebRTC·HUD 합성·오디오) 기록. 설계 §5.2·실행 계획 T7 같이 갱신.
- 증거: 재사용 계약은 이미 시험화된 `{kind:"pedals"}` 매핑과 dashboard 녹화 실측 경로. 신규 브라우저 API 없음.
- gate 변화: 없음.
- 결정: D-323 보강(새 번호 아님).
- 교훈: 없음

## 2026-09-29 · uncommitted · docs(pilot): harness 등록과 문서 지도 (실행 계획 T2)
- 변경: `harness.yaml` 에 `pilot` 등록·`adr_gaps` 에 D-322 선점 기록(Isaac 세션 미착지 행). 모듈 `AGENTS.md`·`progress.md`·`logs.md` 신설. `src/AGENTS.md`·`src/hmi/AGENTS.md` 지도에 등재. D-323 ADR 본문·목차 행·설계·실행 계획 문서를 브랜치에 이식.
- 증거: 이 기록 아래 generate·lint·계약 시험으로 확인.
- gate 변화: 없음.
- 결정: D-323.
- 교훈: 없음

## 2026-09-29 · uncommitted · fix(pilot): design-system gate screen, mDNS entry path, browser contract
- 변경: 접속 게이트를 web_common 어휘로 재작성(ui-field 폼, 값 격자 사유 행, ui-empty 안내, 묶음 제목 줄 기계 값 WAIT/BLOCK/READY). 표면 CSS 를 스텝 척도(--space-N)·의미 역할(--gap-form)로 교정. dev_server 의 web_common 경로 버그 수정(parents[1]→parent/web — /common/* 404 로 스타일·ui.js 전체가 안 실렸던 원인). 설계 §3.1 mDNS 접속 경로 기록(호스트네임 `.local` 진입·QR 후보, 발견 규칙 v0.1 준거). 태블릿 뷰포트 브라우저 계약 시험 신설(2000×1200·1200×2000, 옵트인).
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest src/hmi/pilot/test -q` 27 passed — 토큰 단일 출처(--space-1 척도 확인), 가로 넘침 0, 잘못된 토큰 BLOCK 안내, 정상 토큰 READY·재로드 유지. 실기 태블릿(Lenovo TB-J606F) adb reverse 루프로 확인 예정.
- gate 변화: LOCAL 진행(브라우저 계약 첫 확보).
- 결정: D-323(T6 마무리 + §3.1 보강).
- 교훈: 개발 서버의 정적 자산 경로는 브라우저 시험 전에 리소스 응답 코드로 먼저 확인한다 — 스타일 붕괴가 마크업 결함이 아니라 404였다. 로그 항목을 끼워넣을 때 머리글 줄을 교체하지 않는다(이번 회차 2회 재발).

## 2026-09-29 · uncommitted · feat(pilot): record the served-path contract and add dashboard navigation
- 변경: 설계 §3 에 서빙 경로 계약 표(조종 /pilot·관제 /dashboard·역할 표면) 명시. pilot 상단에 관제 화면 조용한 버튼(data-goto) 추가, PWA start_url/scope 분리 원칙 기록. 브라우저 계약에 왕래 버튼 존재 검사 추가.
- 증거: ROSY_RUN_BROWSER_TESTS=1 pilot 전체 시험 통과(이 기록 커밋 시 결과 기록).
- gate 변화: 없음.
- 결정: D-323 §3 경로 계약.
- 교훈: 없음

## 2026-09-29 · uncommitted · fix(pilot): recompose the gate screen with the dashboard panel grammar
- 변경: 사용자 지적(구성 부족)을 받아 dashboard 패널 조립 문법으로 접속 게이트를 전면 재구성 — ui-head 패널 제목 + dl.ui-readout 사실 행(게이트·역할·수동 운전·구동) + ui-status 안내 + ui-actions 행동. 상단을 surface.html 서열(브랜드 ROSY·공지·역할 태그·관제 이동·비상 정지 irreversible)로 맞추고 e-stop 을 app.js 에서 /api/v1/safety/stop 로 연결. 표면 CSS 는 dashboard 규율(기둥 패널·스텝 척도)로 재작성.
- 증거: ROSY_RUN_BROWSER_TESTS=1 pilot 27 passed — 패널 조립·e-stop 존재·게이트 WAIT/BLOCK/READY·재로드 유지·가로 넘침 0(2000×1200·1200×2000).
- gate 변화: 없음(LOCAL 진행 중).
- 결정: D-323.
- 교훈: 계약 통과와 화면 구성은 별개다 — 조립 문법은 반드시 기존 표면 코드(overview.js·surface-panels.css)에서 직접 추출한다.

## 2026-09-29 · uncommitted · feat(pilot): PWA installation first — D-328 (실행 계획 T10)
- 변경: manifest.webmanifest(standalone·가로·scope /pilot)·sw.js(앱 셸 캐시, /api·/ws 네트워크 전용·오프라인 조종 금지)·토큰 색 아이콘(any 192/512+maskable)·SW 등록·connect 오프라인 안내. 새 ADR D-328 — 설치형은 PWA 우선, Capacitor 는 네이티브 전용 수요 실측까지 보류. 서버 두 곳에 sw.js 의 Service-Worker-Allowed: /pilot 헤더(scope 가 스크립트 디렉터리보다 넓어 필수). adr_gaps 에 D-324~327 타 세션 선점 선언.
- 증거: pilot+라우트 29 passed — manifest 링크·SW 등록(재시도 대기)·게이트 전 플로우·뷰포트 2종 넘침 0. lint 0 errors, architecture+harness 계약 136 passed.
- gate 변화: LOCAL 진행(설치형 계약 첫 확보).
- 결정: D-328 Accepted (설치 형식 결정; 구현·장치·현장 수용 별도 HOLD).
- 교훈: SW scope 가 스크립트 디렉터리보다 넓으면 서버가 Service-Worker-Allowed 를 내려줘야 한다. register() 실패를 조용히 삼키지 말고 console.warn 으로 남긴다.

## 2026-09-29 · uncommitted · feat(pilot): drive screen with round wheel, pedals and camera stage (실행 계획 T7)
- 변경: vision.js(인증 JPEG 폴링 팩토리), input-state.js(홀드 상태·stick 매핑·localStorage 설정), screens/drive.js(원형 휠 Pointer Events 각도→steer, 홀드 페달, 게임패드, 키보드, HUD readout, Wake Lock, 100ms hold-to-drive 루프, visibilitychange 즉시 0), link.js close(), connect 준비 화면 주행 시작 버튼, app.js 화면 전환, dev_server 에 robot/state·vision canned 엔드포인트.
- 증거: ROSY_RUN_BROWSER_TESTS=1 pilot+라우트 29 passed — 게이트→주행 시작→휠·페달·HUD 가시, 게이트 숨김, pageerror 0.
- gate 변화: 없음(LOCAL 진행).
- 결정: D-323.
- 교훈: 화면 전환 시 이전 화면 [hidden] 이 표면 display 규칙에 깨지지 않게 [hidden]{display:none!important} 를 표면 CSS 에 둔다. 콜백(onEnter)은 재호출 경로마다 다시 묶이지 않게 마운트 시 한 번 묶는다.

## 2026-09-29 · uncommitted · feat(pilot): multi-device roadmap and T8 inputs screen
- 변경: 새 ADR D-331 — 조종 대상 확장은 drivers/registry 로만 수용, 장치별 컨트롤(그리퍼·팔 조그 등)과 아이콘은 그 장치 계약이 열 때 프런트에 반영, Pinky 가제보 최우선. 설계 §10 반영. T8 입력 조정 칩(screens/inputs.js — 프리셋·데드존·곡선·반전·게임패드 실시간 미리보기, HUD 입력 버튼으로 열림). screens/inputs.js allowlist 누락 404 수정(4곳).
- 증거: ROSY_RUN_BROWSER_TESTS=1 pilot+라우트 29 passed(수정 후 재확인). ADR 번호 D-331 선점 확인(for-each-ref+Log).
- gate 변화: 없음.
- 결정: D-331 Accepted (로드맵·프런트 경계 결정).
- 교훈: 모듈 추가 시 allowlist 4곳(dev_server MIME·app.py pilot_assets·CMakeLists·route test)은 한 세트다 — 하나 빠지면 화면 전체가 404로 죽는다.
