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

## 2026-09-29 · uncommitted · feat(pilot): camera evidence promotion and drive capture (실행 계획 T9)
- 변경: dashboard camera-capture.js 를 web_common evidence.js 로 승격(git mv, 바운드 5분/60MB·운용 타임라인 불변)하고 dashboard 는 /common/evidence.js 재수출, Node 시험 MODULE 경로 갱신. pilot drive 에 촬영(PC 저장)·바운드 녹화 버튼과 조종 사실(teleop 200)의 타임라인 기록 연결, /common/evidence.js 서빙(web_common CMake·core_api_web common route·dev_server) 추가, dev_server 에 canned /api/v1/front/evidence 201.
- 증거: pilot+라우트+dashboard camera+web 109 passed — 잔여 3 failed 는 known 기존 결함(재확인). 로봇 SD 업로드(storeOnRobot)는 dashboard 경로 확인 후 후속.
- gate 변화: 없음.
- 결정: D-323.
- 교훈: 승격 모듈의 서빙 3세트(web_common CMake·core_api_web common route·dev_server)도 새 모듈 allowlist 세트다.

## 2026-09-29 · uncommitted · feat(pilot): sim camera live, drive fullscreen, in-screen speed presets (T7 시뮬 루프)
- 변경: 가제보 카메라 경로 해결 — gz camera raw 브리지(GZ→ROS 단방향) + sim_jpeg_relay.py(cv_bridge → format 'jpeg; width;height;source=gz' CompressedImage, parse_preview_format 계약 준수) = CORE /api/v1/vision/front 가 시뮬 영상을 서빙. 주행 화면 풀블리드(max-width 해제·100dvh 스테이지), 속도 프리셋 칩 저/중/고 화면 내 조정, SW 캐시 갱신(-2). client.js POST Content-Type 누락 수정(422 원인).
- 증거: CORE vision status available:true·source:GZ·1280x720·seq 증가. API teleop 실측 — 0.1m/s·포즈 14cm 이동. pilot+라우트 29 passed. API 직접 teleop 실측(accepted·velocity·pose) 병행.
- gate 변화: 없음(ROS-SIM 진행 — DEVICE/FIELD 별도).
- 결정: D-323.
- 교훈: pkill 패턴이 내 파이프라인을 죽인다(원시 브리지+republish 동시 사망 2회). 카메라 스택은 한 스크립트로 일괄 기동하고 상태를 CORE status로 확인한다. SW 캐시는 배포 때마다 이름을 올려야 클라이언트가 새 JS를 받는다.

## 2026-09-29 · uncommitted · feat(pilot): fullscreen game-style drive + vision 409 retry + browser tests (구현 개선)
- 변경: 게임식 풀스크린 주행 레이아웃 — 카메라가 화면 전체를 채우고 HUD·휠·페달이 반투명 오버레이(blur·color-mix), 휠 중심 크로스헤어, 페달 활성 글로우, 속도 대형 계기. vision.js 409(CAMERA_FRAME_ADVANCED)를 오류가 아닌 다음 틱 재시도로 처리(hasFrame 플래그). 브라우저 시험을 새 레이아웃에 맞게 갱신(풀스크린 검증·프리셋 변경·카메라 프레임). width:100% 명시로 headless Chromium 풀스크린 해결.
- 증거: ROSY_RUN_BROWSER_TESTS=1 pilot+라우트 30 passed — 게이트 2뷰포트 + 차단 + 풀스크린 카메라 + 속도 프리셋 변경.
- gate 변화: 없음(LOCAL 진행).
- 결정: D-323.
- 교훈: headless Chromium에서 grid 요소가 width:0으로 붕괴할 수 있다 — width:100%를 명시한다. color-mix()는 Chrome 111+에서만 지원되므로 폴백을 고려한다.

## 2026-09-29 · uncommitted · feat(pilot): game-style "Continue" UX with recent connections (D-323)
- 변경: recent.js(localStorage 최근 접속 관리) + connect.js 재구성 — 최근 접속한 로봇을 원터치로 재접속(게임 "계속하기" 패턴), 새 연결은 접기 폼. 삭제 버튼(✕)으로 목록 정리. 서빙 4곳에 recent.js 등록.
- 증거: ROSY_RUN_BROWSER_TESTS=1 pilot+라우트 30 passed.
- gate 변화: 없음.
- 결정: D-323.
- 교훈: 없음

## 2026-09-29 · uncommitted · fix(pilot): 가제보 실조종으로 입력 부호·송신 타이밍·제자리 회전·카메라 교정
- 변경: `stick.js` 를 REP-103 부호 규약(오른쪽 입력 = angular 음수)·원형 데드존·제자리 스냅(±12°)·CORE 한도 비율 프리셋(저 0.4/중 0.7/고 1.0)·정밀(×0.3)로 재작성. `input-state.js` 2 축 스틱·제자리 회전 상태. `link.js` 발행 시작 기준 100 ms 주기·단일 비행·최신 명령 합치기·400 ms 시한·놓을 때 0 재덮기·유휴 0 3 회 후 정지·409 뒤 `resume()`. `screens/drive.js` 원형 휠(x 한 축)을 2 축 스틱으로, 제자리 회전 홀드 버튼(↺/↻, Q/E, LB/RB), 정밀 토글, HUD 실측 속도·회전율·동작 배지·상한·지연, 수동 모드 200 뒤에만 명령, 409 "수동 모드 다시 잡기", visible() 재개·키 리스너 해제 누수 수정. `vision.js` 주기를 CORE 하한 0.4 s 이상으로, 실패 프레임(409/429 JSON)을 이미지로 띄우지 않음. `screens/inputs.js` 데드존 슬라이더의 미정의 `refreshFacts()` 예외 수정. `screens/connect.js` 미정의 `addRecent`/`removeRecent` 호출 수정(연결 버튼이 죽어 있었다). `tools/sim_jpeg_relay.py` reliable·depth 1·640 폭 축소. 설계 §10.1(입력 모델·조작 프로필·팔 정밀 조작 원칙)·§10.2(송신 타이밍).
- 증거: 가제보(WSL, gz headless + CORE, Nav2 없음)에 실제 브라우저로 붙어 조작 — 스틱 오른쪽 yaw −16.9~−25.4°(시계), 왼쪽 +17.0~+21.0°, 제자리 회전 버튼·키보드 E 이동 0.000 m, 두 손가락(전진 페달+스틱 우) yaw −15.2°·+0.075 m, 놓은 뒤 마지막 명령 0. 명령 공백 최대 2.16 s → 0.5 s 안팎(스크린샷 캡처 구간 제외). 옛 매핑은 angular +0.5 가 yaw +18°(반시계)인데 휠 오른쪽에 angular + 를 보내 반대로 돌았다. `python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py`(ROSY_RUN_BROWSER_TESTS=1) 33 passed.
- gate 변화: ROS-SIM 진행(가제보 조종 방향·제자리 회전 실측 확보). DEVICE 는 여전히 HOLD.
- 결정: D-323(§10.1·§10.2 보강), D-331(팔 조작 프로필은 계약 대기).
- 교훈: 조종 부호는 시험 이름이 아니라 시뮬 yaw 로 확인한다 — 옛 시험은 "pad x+ → angular+" 를 정답으로 고정하고 있었다. 호스트가 포화(Windows CPU 100%, gz RTF 0.3~1.2)면 teleop 이 200 인데 로봇이 안 움직이는 것처럼 보인다 — cmd_vel·odom 을 rclpy 로 직접 재서 체인과 환경을 가른다.

## 2026-09-29 · uncommitted · feat(pilot): 실물 로봇 실주행·카메라 비율·배율 확대·ADR D-346~D-350
- 변경: 실물 rosy-pinky-8kcn(192.168.1.202)을 태블릿 설치 앱으로 실주행(PC 중계 `tools/pilot_device_bridge.py` + 로그인 코드 페어링). 카메라를 원본 비율(`contain`)로 전부 보이고 조작부·HUD 가 영상을 덮지 않게 배치(가로: 영상 좌우 띠, 세로: 영상 아래). 운전자 배율 맞춤→1.2×→1.4×→가득→전체화면, HUD 잘림 배지, 전체화면은 상태 표시줄까지 숨기되 비상 정지 상단 바 유지. 주행 중 머리(상단 바·HUD) 얇게. 세로 확대는 높이를 늘리고 좌우를 자름. ADR 번호 충돌(D-341 오버헤드 페어링, D-345 main)로 pilot ADR 을 D-346~D-350 으로 옮기고 adr_gaps 선언.
- 증거: 실물 실주행 녹화(명령·오도메트리 자막) `X:\DevTemp\rosy-pilot-evidence\2026-09-29-real-drive\`(공개 저장소 밖, D-226). 스틱 좌 +12.1°·우 −12.6°, 제자리 −20.8°, 페달 +11.6 cm, 놓으면 0. 놓음→0 명령 23~56 ms. 태블릿 설치 앱 스크린샷에서 영상 위 신호 띠(PINKY·YELLOW)와 STOP 선이 잘리지 않고 보임. 브라우저 시험이 네 화면 크기에서 영상 비율(±1%)·겹침 0 을 잰다.
- gate 변화: DEVICE 진행(실물 수동 주행 방향·정지 확인, 한도 L0). 영상 fps(2 fps)·좌석·로비는 D-346·D-348 구현 전.
- 결정: D-346(운전자 MJPEG), D-347(한도 계단), D-348(로비·좌석), D-349(보조 자율), D-350(카메라 비율·설치 앱·배율).
- 교훈: 태블릿 실측에서만 드러나는 결함이 있었다 — 안드로이드 자동 대문자(토큰 401), 길게 누르기 이미지 메뉴(터치 가로챔), 브라우저 탭 누적(한 로봇 동시 조종), `cover` 로 잘린 신호 띠. 헤드리스 브라우저 통과를 실기 통과로 보지 않는다. ADR 번호는 쓰기 직전에 모든 브랜치·worktree 에서 다시 확인한다(같은 날 두 번 충돌).

## 2026-09-29 · 72802f30·895786cf · feat: 실물 차선 자동 주행(D-349 보조 자율)
- 변경: CORE line-follow 요구 능력을 `mobility.move` 로(실물 `motor` 런타임에서 늘 거절되던 것), `hold_s`·`POST /line-follow/hold` 운전자 확인 만료(끊기면 CORE 가 스스로 OFF·nav 명령 즉시 삭제), API v1.46. 카메라 서비스가 `line_observer_node`(관측 전용)도 띄움. pilot "차선 자동" 토글 + "진행 ▶ 누르는 동안" 버튼, 스틱·페달·키·탭 이탈 시 즉시 수동 복귀, HUD 에 차선 신뢰도·오차·멈춤 이유와 자동 속도.
- 실물 반영: rosy-pinky-8kcn(release 2026.09.27-010)에 **현장 핫픽스**(사용자 승인) — 파일 4개 교체, `line_follow.cruise_speed: 0.04`(`/var/lib/rosy/core/.rosy/rosy.yaml`), rosy-core·rosy-camera 재시작. 원본 백업 `/var/lib/rosy-bench-backup/20260929133351-d349-hotfix/`. 정식 릴리스로 덮어야 한다.
- 증거(공개 저장소 밖): `X:\DevTemp\rosy-pilot-evidence\2026-09-29-lane-auto\`. 실제 차선에서 누르는 동안 TRACKING(신뢰 1.00), 오차 +0.33 → −0.04 로 수렴, 약 0.035 m/s, 4 s 에 12.8 cm. 떼면 0.47 s 안에 속도 0·MANUAL. 링크 끊김 모의(갱신 중단, release 없음): 0.50 s 에 `driver_released`, 0.73 s 에 속도 0, 이후 hold 409.
- gate 변화: DEVICE 진행(보조 자율 실차선 1 구간). 자동 중 각속도가 수동 한도(0.1 rad/s)보다 크다(최대 0.66 rad/s, nav 한도 0.8) — 차선 추종 `max_angular` 도 D-347 계단처럼 다룰지 결정 필요.
- 결정: D-349 §7~§10.
- 교훈: 실물 CORE 는 `ros2` CLI 로 볼 때 서비스와 같은 DDS 설정(`/etc/rosy/runtime.env` 의 `CYCLONEDDS_URI`, 루프백 전용)과 `--no-daemon` 이 필요하다 — 없으면 "토픽 없음"으로 보인다.

## 2026-09-29 · 35efb5ba · feat(core): 차선 추종 앞 물체 정지(LiDAR, D-349 §11)
- 변경: LiDAR 정면 ±20° 최소 거리로 0.20 m 정지·0.28 m 재출발(떨림 방지), LOST 로 굳지 않음, LiDAR 끊기면 정지. 장착 방향 `lidar_forward_deg`(Pinky 실물 180 — 정면 2.6 m·오른쪽 벽 0.14 m 가 카메라와 일치). 상태 `clearance_m`, pilot HUD "앞 N m"·"앞 물체 — 정지".
- 실물 반영: 사용자 승인 두 번째 핫픽스(CORE 6 파일 + `lidar_forward_deg: 180`), 백업 `/var/lib/rosy-bench-backup/20260929140539-d349-obstacle/`. 로봇의 옛 관리자에 `config` 속성이 없어 첫 재시작에서 LiDAR 콜백 AttributeError — 즉시 속성 추가 후 재시작, 오류 0.
- 증거(공개 저장소 밖): `X:\DevTemp\rosy-pilot-evidence\2026-09-29-obstacle-stop\`. 차선 위 물체로 다가가며 앞 거리 2.17→0.75→0.40→0.21 m; 다시 진행을 눌러도 0.198 m 에서 6 s 동안 이동 0.0 cm(`obstacle_ahead`); 물체를 치운 뒤 곧바로 출발해 15 s 연속 추종으로 50.3 cm 주행.
- 교훈: 핫픽스는 로봇 쪽 파일이 브랜치보다 오래됐을 수 있다 — 새 코드가 부르는 속성(`config`)이 로봇 사본에 있는지까지 확인하고, 재시작 직후 저널에서 Traceback 을 본다.

## 2026-09-29 · uncommitted · feat(core): 차선 추종 IR 이탈 감시(D-349 §12)
- 변경: CAMERA_LINE 중 `line_follow.ir_guard_enabled` 이면 CORE 가 IR_LINE 관측으로 경계를 감시 — 옆 센서 밑 경계면 반대로 비킴(`lane_edge_left/right`, 속도 절반), 가운데면 정지(`lane_departure`), IR 끊김·미교정이면 정지(`lane_guard_stale`). rosy-io 그래프에 `enable_ir` 로 `ir_adc_node` 추가. pilot HUD 문구 4개.
- 원인: 실물 녹화에서 경계선을 밟고 넘음 — 실물 `camera_lane_mode: line` 이 밝은 화소 무게중심을 목표로 삼아 한쪽 경계만 보일 때 선 위로 간다. 카메라 쪽 `between` 모드(ffc19a74)는 같은 회차에 병행.
- 실물 상태: `ir_adc_node` 는 설치돼 있으나 어느 launch 도 띄우지 않아 `/rosy_60/ir_sensor/range` 발행자 0. 교정 전이라 감시는 기본 꺼짐.
- 증거: `test_line_follow_ir_guard.py` 10 passed(비킴 부호·절반 속도·가운데 정지·LOST 미누적·IR 끊김/미교정/해시 불일치 정지·기본 꺼짐), `test/test_ir_source_exclusivity.py` rosy-io 만 `enable_ir:=true`. 실물 녹화 루프는 핫픽스 승인 뒤.
- gate 변화: SOURCE 통과. DEVICE 는 IR 발행·교정·녹화 전이라 HOLD.

## 2026-09-30 · uncommitted · feat(pilot): 자동 주행 의도 띠(D-353 §6)
- 변경: 자동 중 영상 아래에 겨누는 점(차선 오차 −1…+1 을 가로 위치로)과 CORE 가 실제로 낸 조향 방향·크기("◀ 왼쪽 N°/s", "오른쪽 N°/s ▶", "▲ 직진", 멈추면 "멈춤") 띠. 이탈 감시(`lane_edge_*`)·멈춤이면 경고색. 띠는 영상 틀이 아니라 실제로 그려진 영상 안에 맞춘다(옆 조작부·검은 띠를 넘지 않음). 표시만 하고 조향을 계산하지 않는다(`autonomy.intentView`). HUD 사유 `nominal_ground_requires_driver`. 가짜 CORE(dev_server)에 차선 추종 흉내 끝점.
- 증거: `test_autonomy.py::test_intent_view_maps_core_status_to_target_and_steer_direction`, 브라우저 `test_auto_intent_strip_shows_target_and_core_steer`(오차 +0.40 → 띠 70 % 위치, 각속도 −0.32 → "오른쪽 18°/s ▶", 앞 물체 HOLD → "멈춤", 떼면 숨김, 띠가 그려진 영상 안). 스크린샷은 저장소 밖.
- gate 변화: SOURCE 진행. 실물·가제보 표시 확인은 인식 v2·헤드리스 벤치 뒤.

## 2026-09-30 · uncommitted · docs(adr): pilot ADR 번호를 main 과 겹치지 않게 다시 매김
- 변경: main 이 D-346~D-353 을 다른 결정으로 먼저 썼다. 이 모듈 기록의 옛 번호는 다음으로 읽는다 — D-346→D-362(운전자 실시간 영상), D-347→D-342(수동 한도 계단), D-348→D-343(방·운전석), D-349→D-344(보조 자율), D-350→D-363(카메라 비율·설치 앱), D-353→D-364(차로 유지 인식·재생 벤치). 위 기록은 덧붙이기 전용이라 고치지 않는다.
- 증거: `docs/adr/` 파일 이름·ADR Log 행·코드 주석·시험이 새 번호를 쓴다. D-342~D-344 는 main 의 harness 가 이 pilot 초안용으로 예약해 둔 번호다.
- gate 변화: 없음(번호만).

## 2026-09-30 · uncommitted · docs(adr): pilot ADR D-328·D-331·D-332 번호도 main 과 겹치지 않게 다시 매김
- 변경: main 이 D-328·D-331·D-332 를 다른 결정(모델 제안 미션, ER 2 제안 어댑터, 사람 확인 위치)으로 먼저 썼다. 이 모듈 기록의 옛 번호는 D-328→D-365(PWA 우선), D-331→D-366(다기기 로드맵), D-332→D-367(체감 응답속도)로 읽는다. 위 기록은 덧붙이기 전용이라 고치지 않는다.
- 증거: `docs/adr/` 파일 이름·ADR Log 행·코드 주석·시험이 새 번호를 쓴다.
- gate 변화: 없음(번호만).

## 2026-09-30 · uncommitted · docs(adr): 운전자 실시간 영상 ADR 을 D-362 에서 D-368 로
- 변경: 다른 세션이 main 작업 트리에서 D-362(코드 유형별 파일 크기 예산)를 쓰고 있어, 이 모듈 기록의 D-362(운전자 실시간 영상, 옛 D-346)는 D-368 로 읽는다. 위 기록은 덧붙이기 전용이라 고치지 않는다.
- 증거: `docs/adr/D-368-pilot-live-driver-video.md`, ADR Log 행·코드·시험이 새 번호를 쓴다.
- gate 변화: 없음(번호만).

## 2026-09-30 · uncommitted · chore(pilot): main 병합 — 표면 등록과 D-370 이름표
- 변경: main 병합(2026-09-30)과 함께 pilot 을 D-329 표면 레지스트리에 등록(`rosy-pilot`, 역할·소유 `manual-drive`·`driver-video`·`drive-assist`·`estop`, 아이콘 `web_common/icons/pilot.svg`). D-370 이름표대로 제목 `Rosy 로봇 — 조종`, PWA `short_name` `Rosy Pilot`, 상단 버튼 "관제 화면" → "로봇 대시보드". CORE 이미지가 pilot 을 빌드한다. 공용 컨트롤·타이포 계약은 주행 HUD 재도색 때문에 아직 받지 않는다(surfaces.yaml 사유). PWA 아이콘 PNG 교체는 D-370 이행 회차.
- 증거: `test/architecture/test_app_roles.py`(pilot 이 `/api/fleet` 을 부르지 않음), `src/hmi/web_common/test` 114 passed, `test/test_core_image_closure.py`.
- gate 변화: 없음(등록·이름만).

## 2026-09-30 · uncommitted · refactor(pilot): D-374 stage 2 — registry id rosy-pilot → pilot

- 변경: `src/hmi/web_common/surfaces.yaml`의 레지스트리 id `rosy-pilot` → `pilot`. 폴더·패키지·아이콘(`src/hmi/pilot`, `pilot`, `icons/pilot.svg`)은 이미 규칙과 같다. `test/architecture/test_app_identity.py`의 pending 줄을 지웠다. 경로 `/pilot`, PWA `start_url`·`scope`, 저장소 키 `rosy.pilot.*`, SW 캐시 이름은 그대로(D-374 3항).
- 증거: `python -m pytest src/hmi/web_common/test src/hmi/pilot/test src/runtime/api_web/test test/architecture -q` 294 passed, 27 skipped (2026-09-30 Windows).
- gate 변화: 없음. 장치 절차 없음(계획 단계 2).

## 2026-09-30 · uncommitted · feat(pilot): 차선 자동 계단 거절 이유를 한국어로

- 변경: `screens/drive.js LF_REASON` 에 `limit_level_too_low`("수동 한도 L1 이상에서만 차선 자동")와 `angular_limit_zero`("조향 한도 없음 — 정지") 추가. 캐시 키 `sw.js` 를 `rosy-pilot-shell-2026-09-30-3` 으로 올렸다.
- 증거: `node --check`, `pytest src/hmi/pilot/test` 35 passed, 13 skipped (2026-09-30 Windows, 브라우저 시험은 opt-in 이라 skip).
- gate 변화: SOURCE. 태블릿 실화면 확인 전.
- 결정: D-344 §13(사용자 결정: 차선 자동은 L1 이상).

## 2026-09-30 · uncommitted · refactor(pilot): D-377 page title is the display name
- 변경: `index.html` `<title>` `Rosy 로봇 — 조종` → `Rosy Pilot`(D-377: 앱 제목은 표시 이름).
- 증거: `src/hmi/web_common/test/test_surface_titles.py` 통과(web_common 111 passed, 2026-09-30 Windows).
- gate 변화: 없음.

## 2026-09-30 · 47f814a6 · refactor(pilot): drive.js 를 drive-auto·drive-view 로 나눔
- 변경: `screens/drive.js`(708줄)를 입력·명령 루프만 남기고 `drive-view.js`(마크업·D-363 배치·배율)와 `drive-auto.js`(D-344 보조 자율·D-364 의도 띠)로 나눴다. 동작은 같다. 새 파일을 CORE `pilot_assets`·`dev_server`·`sw.js` 사전 캐시(이름 `-3`, 빠져 있던 `inputs.js` 도 더함)·`test_pilot_route`·동기화 스크립트에 등록. drive.js 예산 판정(`test_web_budgets.py`)은 예산 아래라 지웠다.
- 증거: `src/hmi/pilot/test` + `test_pilot_route.py` 51 passed(브라우저 포함).
- gate 변화: 없음.

## 2026-09-30 · uncommitted · feat(pilot): 공용 컨트롤·타이포 계약과 D-370 PWA 아이콘
- 변경: `surfaces.yaml` 의 pilot 이 `contracts: [shared_controls, typography_focus]` 를 받는다. 버튼 종류는 JS 에서 `setAttribute("kind", …)` 로 명시(페달·제자리·진행 `toggle`+`size="primary"`, 차선 자동 `toggle`, 속도·정밀·입력 조정 `segment`+`aria-pressed`). `styles.css` 는 공용 컨트롤의 면·글자·테두리를 다시 칠하지 않고, 영상 위 대비는 조작부 판이 가진다. HUD 글자는 크기 토큰(`--text-display`·`--text-value`·`--text-label`)만 쓴다. PWA 아이콘 192·512·192-maskable 을 `web_common/icons/pilot.svg` 에서 `tools/icons/render_png.py` 로 다시 그렸다(maskable 은 `--ground` 판에 합성). D-363 에 부록.
- 증거: `src/hmi/web_common/test` 계약 시험 통과, `test_pwa_icons.py`(PNG = 렌더 결과), 스크린샷 `X:\DevTemp\pilot-polish\after2-*.png`(가로 2000×1200·세로 1200×2000, 수동·자동).
- gate 변화: 없음(SOURCE 범위 안).

## 2026-09-30 · bf0fab99 · feat(pilot): 세로 조작부가 영상 아래 공간을 채운다
- 변경: below 배치에서 조작부 칸을 크기 컨테이너 두 칸으로 나눴다. 왼쪽 절반은 속도 줄·차선 자동·페달(2fr)·제자리(1fr, 둘 다 88px 이상)가 높이를 다 쓰고, 오른쪽 스틱 지름은 min(45cqw, 80cqh). 자동 모드면 진행 버튼이 페달 자리를 차지한다. 배치 규칙만 바꿨다(재도색 없음).
- 증거: ROSY_RUN_BROWSER_TESTS=1 pilot·web_common·test_pilot_route 161 passed; 스크린샷 X:\DevTemp\pilot-polish\after3-*.png(1200×2000·800×1280·390×844·2000×1200).
- gate 변화: 없음.

## 2026-09-30 · 7711cb84 · fix(pilot): 리뷰 수정 — 세로 전체화면·오프라인 셸·자동 모드 상태
- 변경: 세로 전체화면에서 조작부가 0px 이 되던 것을 아래 겹침(높이 min(40dvh, 28rem))으로 고쳤다(bb604a6f). `sw.js` SHELL 에 `/common/evidence.js` 를 넣고(drive.js 의 정적 import, bf7a8886), 쓰지 않던 `recent.js` 와 그 allowlist 행을 지웠다(0fd862fc, 캐시 `-5`). 다시 들어오면 자동 모드·배치 표시를 초기화한다(`drive-auto.js`·`view.close()`). 자동 요청에 1.5 s 시한, 진행 버튼은 도는 중이거나 켜는 중에 아직 누르고 있을 때만 채운다. 차선 자동은 `segment`, 진행은 공용 `toggle` `tone="good"`(12f322f9). `test_pwa_icons` 는 PIL 을 바로 import 한다. `render_png.py` docstring·`sync_pilot_files.sh` 경로·빈 줄 정리.
- 증거: 새 시험 `test_shell_assets.py`(모든 pilot 모듈의 import 를 /common 까지 따라가 SHELL·pilot_assets 대조), 브라우저 `test_go_releases_on_cancel_and_leave`·`test_stick_takes_over_auto`·`test_reenter_resets_auto_mode`, `test_zoom_cycles_and_always_reports_crop` 에 1200×2000(옛 CSS 에서 스틱 4px 로 실패 확인). 스크린샷 `X:\DevTemp\pilot-polish\after4-*.png`(세로 전체화면 `after4-drive-fullzoom-*`).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · D-390 Pilot OMX Gazebo practice
- Change: Select the OMX simulation driver from same-origin identity; render bounded arm and gripper jog, seat renewal, goal readback and cancellation. Keep Pinky routing behind a 404 target response.
- Evidence: rendered OMX pairing-to-jog 1 passed, Pinky gate browser 1 passed, driver/link/route 26 passed; Gazebo action evidence in docs/validation/pilot-omx-gazebo-2026-10-01/.
- Gate: sim control path observed; video, recording and physical OMX remain HOLD.

## 2026-10-01 · 5db3391d · feat(pilot): 보정 중 판과 비소유자 주행 잠금
- 변경: `calibration.js`(순수 판정) 추가. 상태의 `activity` 가 CALIBRATING 이면 영상 위 "보정 중 — <label>" 판과 HUD 칩. whoami id 가 owner 가 아니면 조작부 전체 disabled + 사유, 명령 루프는 아무것도 보내지 않는다. 상단 E-Stop 은 그대로. SW 셸 키 `2026-10-01-1`.
- 증거: test_calibration_view.py 5 passed; ROSY_RUN_BROWSER_TESTS=1 test_pilot_browser 전체 18 passed(새 `test_calibration_banner_locks_drive_for_other_tokens_and_keeps_estop` 포함, 배치 시험 유지). 스크린샷 X:\DevTemp\calibration-mode\pilot-calibration-locked.png·pilot-calibration-owner.png.
- gate 변화: 없음.

## 2026-10-01 · c04de23a · fix(pilot): 보정 주인의 모드를 끊지 않는다; whoami 재시도
- 변경: 나갈 때 `/mode` IDLE 은 이 화면이 MANUAL 을 잡았고(modeHeld) 남의 보정으로 잠기지 않았을 때만 보낸다. whoami 실패는 1→2→4→8 s(최대 15 s) 재시도, 대기 중에는 "보정 확인 중"으로 잠근다.
- 증거: ROSY_RUN_BROWSER_TESTS=1 pilot 전체 + dashboard 칩 70 passed(새: 잠긴 화면 이탈은 /mode 없음, 주인 이탈은 IDLE, whoami 대기 표시 후 조작 복귀). test_calibration_view 6 passed.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(pilot): main의 OMX 연습 화면·데드존을 D-359 공용 컨트롤 계약 아래로
- 변경: main이 Pilot에 `shared_controls`·`typography_focus` 계약을 켜면서 D-359 쪽 더 엄한 판정에 걸렸다. `screens/arm.js` 입력·선택은 `class="ui-field"`, 버튼은 `ui-button`(연결 primary, 나머지 quiet), 조그·그리퍼 비활성은 `reason`(조작 보류/명령 진행 중)을 단다. `screens/inputs.js` 데드존 range에 `ui-field`. `styles.css`의 arm 입력·버튼 재도색(2.75rem·0.4rem·0.5rem 1rem·opacity 0.5)을 지우고, 보정 잠금 흐림은 `var(--disabled-opacity)`.
- 증거: web_common 199 passed; `ROSY_RUN_BROWSER_TESTS=1` `src/hmi/pilot/test` 70 passed, `src/products/omx/adapter/test/test_pilot_sim_browser.py` 1 passed (2026-10-01 Windows).
- gate 변화: 없음.
- 결정: D-359 §5.1·§5.3·§5.5.
- 교훈: 없음.

## 2026-10-01 · uncommitted · D-398 장미색 범위·정지·어휘 정리

- 변경: 드라이브 스틱 활성/knob을 --brand-rose → --focus-ring으로(인터랙션 색, D-277). transition 2건(프레임 opacity·intent left) 제거로 D-220 회복. '대기'를 MODE_LABEL.IDLE로(screens/drive·drive-view·drive-auto), sw.js SHELL에 /common/core_ui_logic.js 추가(test_shell_assets가 따라감). vision.js '프레임 지연(STALE)' → '카메라 프레임 지연'(영어 열거값 노출 제거).
- 근거: D-398. pilot 시험 통과.
- gate 변화: 없음(LOCAL HOLD 그대로).

## 2026-10-01 · uncommitted · feat(omx): record SIM demonstrations and export LeRobot v3
- 변경: D-390 부록·API v1.69·Pilot 기록 패널·SIM 카메라·원본 recorder·오프라인 exporter. ROS 수락 전에 목표를 등록하고, recording I/O는 별도 writer로 분리.
- 증거: adapter/Pilot/network 259 passed, 28 skipped; quick tier 95 passed; Chromium recording retry/outcome/stale/dispose 1 passed; 실제 LeRobot 0.4.4 reader 3 passed. Gazebo 원본 15프레임 및 동일 원본 export 재독출 PASS. docs/validation/omx-demonstration-lerobot-2026-10-01/README.md 참조.
- gate 변화: 물리·ARTIFACT/FIELD 승격 없음. 짧은 SIM 시연/데이터 형식 증거만 추가.
- 결정: D-390 부록; D-18 typed API와 reference 동시 갱신.
- 교훈: LeRobot 0.4.4는 explicit timestamp를 거부; source ns를 int64로 유지. Windows shared recording mount는 프레임 누락을 만들 수 있으므로 Linux volume 사용.

## 2026-10-01 · uncommitted · fix(omx): fence recording closure and isolate storage faults
- 변경: 리뷰의 중요 문제 3개 해소 — recording 오류로 lease watcher 종료 금지, hidden 중 늦은 seat 획득 즉시 반납, 종료 저장 중 interruption을 manifest에 반영.
- 증거: 리뷰 수정 race/runtime/recorder 21 passed; Chromium 2 passed; 최종 adapter/foundation/assets/network 624 passed, 6 skipped. 최종 tree와 같은 해시의 실제 Gazebo 12프레임→LeRobot 재독출 PASS; 같은 실행 lease 만료 incomplete. 독립 리뷰 재검토 완료.
- gate 변화: 기존 gate 유지; DEVICE/FIELD 승격 없음.
- 결정: D-390 부록.
- 교훈: 파일 쓰기 완료 전 들어온 interruption과 logical closure 경계를 구분한다.

## 2026-10-01 · uncommitted · fix(pilot): preserve recording errors and reconcile API minor
- 변경: polling으로 시작/종료 오류가 지워지지 않게 유지. main D-395/v1.69와 충돌한 OMX 추가분은 v1.70. 양쪽 append-only 로그와 source를 보존.
- 증거: 전체 추가 실행 680 passed, 6 skipped, 2 failed; 원인/제한을 검증 문서에 기록. OMX polling 오류·hidden seat·Pinky calibration 실패 경로 재실행 3 passed.
- gate 변화: 전체 Pilot LOCAL HOLD 유지.
- 결정: D-390 부록, D-18.
- 교훈: 독립 기능 시험과 전체 부하 실행을 구분한다.

## 2026-10-02 · 4e99d92e · feat(pilot): D-411 A 로봇 녹화 토글과 "녹화본" 시트
- 변경: 순수 `recording.js`(경과·크기 서식, 토글 표시, 거부 코드 글자, 시트 행·차단 사유)와 DOM `screens/robot-recording.js`(1 s 폴링, 시작/정지, 시트 목록·새로고침·받기 — 409 는 사유만 보이고 다시 받지 않음, Content-Length 보다 짧으면 저장하지 않음, 나가기 때 이 기기가 시작한 녹화만 정지). 브라우저 녹화 버튼 이름을 "화면 녹화"로. `client.js` `apiBlob`. HUD 칩 `[data-drive-fact=recording]`, 휴대폰 폭에서 HUD 액션 줄바꿈. 자산 다섯 곳 등록, SW 캐시 `2026-10-02-1`. dev_server 가짜 녹화 API, `test_shell_assets` 에 CORE·SIM·dev 자산 동치 시험.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py src/products/omx/adapter/test/test_pilot_sim_api.py -q` → 89 passed (2026-10-02 Windows, Chromium; 새 브라우저 시험은 2000×1200·1200×2000·390×844).
- gate 변화: SOURCE 유지. ROS-SIM HOLD — 계획 Verification ROS-SIM 체크리스트(WSL Ubuntu) 미실행, DEVICE 증거 없음.
- 결정: D-411 A.

## 2026-10-02 · 58b01802 · fix(pilot): D-411 A 로봇 녹화 리뷰 반영 — 크기 상한, 끊을 수 있는 받기, 낡은 폴링
- 변경: 256 MB 를 넘는 녹화본은 Pilot 에서 받지 않고 `rosy_ml fetch <로봇> --http` 로 안내(blob 은 메모리에 통째로 든다). 받기마다 AbortController — 취소 버튼, 화면 나가기·dispose 때 끊음(끝까지 받지 않으면 CORE 가 fetched 로 두지 않는다), 10분 시한. 누를 때마다 epoch 를 올려 그 전에 떠난 폴링 응답을 버리고, 폴링은 한 번에 하나, 요청 시한 2 s. 403 문구는 정지(남의 녹화)·시작/받기(Operator 권한)로 나눔. 나가기는 보낸 시작이 끝나기를 기다린 뒤 이 기기 녹화만 멈춤. 비활성 토글에 reason, 알림·행 상태는 role=status aria-live=polite, 시트는 열 때 초점·Escape 로 닫힘·HUD 아래끝에 붙음(고정 오프셋 없음)·3 s 마다 새로 읽음. dev_server 시나리오(viewer·foreign·short·slow·conflict·big).
- 증거: `python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py src/products/omx/adapter/test/test_pilot_sim_api.py -q` → 63 passed, 35 skipped; `ROSY_RUN_BROWSER_TESTS=1` 브라우저 전체 35 passed(기존 23 + 녹화 12), 녹화 12개는 3회 반복 모두 통과 (2026-10-02 Windows, Chromium; 기계 부하로 Chromium 종료가 회당 20–50 s).
- gate 변화: SOURCE 유지. ROS-SIM HOLD — 계획 Verification ROS-SIM 체크리스트(WSL Ubuntu) 미실행, DEVICE 증거 없음.
- 결정: D-411 A.

## 2026-10-02 · 10daaae5 · feat(pilot): D-411 B 서술자로 조작부 조립, 팔 조이스틱
- 변경: 순수 `controls.js`(`rosy.controls/1` 읽기, 위젯 계획, 필드 없음 = 기존 프로필 대체, 빈 `items` = 조작부 없음, 모르는 autonomy 무시)와 `arm-stick.js`(축·데드존·우세 축 단계, 순차 조거 — 이전 목표 종결 뒤에만 다음, 실패·거절이면 멈춤, 남의 명령 종결은 무시). `screens/compose.js`(kind→위젯, 미지원 표시), `widgets/joint_jog.js`(2축 패드·축별 관절 선택·방향키·± 버튼·readout). `screens/arm.js` 를 세션 컨텍스트(`submitJog`·`onUpdate`·활성 목표 250 ms 폴링)로 재구성 — 떼면 새 목표만 멈추고 취소하지 않는다, 취소 버튼은 활성 목표가 있을 때만. 태블릿 가로는 왼쪽 작업 공간·오른쪽 조작부. 주행은 capabilities `controls` 의 `base_velocity` 로 프로필(차선 자동 토글은 `autonomy`), 미지원 조작부는 영상 왼쪽 위 표시. 자산 다섯 곳 등록, SW 캐시 `2026-10-02-4`. dev_server `/__test__/controls`.
- 증거: `python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py src/products/omx/adapter/test -q` → 351 passed, 49 skipped; `ROSY_RUN_BROWSER_TESTS=1` `test_pilot_browser.py` + `test_pilot_sim_browser.py` → 45 passed (2026-10-02 Windows, Chromium; 새 시험: 미지 kind, 구 CORE 대체, autonomy 토글, 빈 목록, 조이스틱 순차·떼면 취소 없음, 축 재지정·방향키·버튼 대기, 390×844 가로 넘침 없음).
- gate 변화: SOURCE 유지. ROS-SIM HOLD — OMX Gazebo 에서 조이스틱 미실행.
- 결정: D-411 B, D-411 구현 부록 1·2·6.

## 2026-10-02 · uncommitted · fix(pilot): D-411 B 리뷰 — 실제 SIM 소유자, 순차 조이스틱, 한계, 자리 잃음, 큰 스틱 잡기 구역
- 변경: 실제 SIM 은 목표 실행 중 `ready:false`·`owner_state:"active"` 라 첫 목표 뒤 조이스틱이 막혔다 → "active" 는 바쁨(기다림)이지 보류가 아니고, 목표가 끝나면 `/state` 를 다시 읽어 준비된 새 sequence 로 다음 목표. 세션 단일 비행(`submitting`), 스틱을 잡는 동안 ± 비활성. 단계는 관절 한계 안으로 잘리고 남은 여유가 0.001 rad 미만이면 보내지 않는다(409 대신 "관절 한계"). 409 `joint_state_sequence_mismatch`(GET /state 와 POST 사이 새 /joint_states — Gazebo 17개 중 1개)는 새 readback 으로 한 번만 다시 보낸다. 자리 반납·잃음·숨김은 진행 목표를 UNKNOWN_HOLD 로 놓고 폴링을 멈추며, 자리를 잃으면 페어링을 다시 보인다; `/goals/{id}` 404 는 종결. 위젯이 던지면 "그릴 수 없는 조작부". 주행: `fine:false` 면 정밀 없음·저장값 무시, `pivot:false` 면 Q/E·LB/RB 도 끔, 알린 `max_linear/max_angular` 로 상한, 0 이면 "정지로 제한됨"(stick.js 가 0 을 기본값으로 바꾸던 결함 수정). aria id 정리, 상태 live region 은 바뀔 때만 씀. 휴대폰: 작은 영상 → 스틱 → readback. 손잡이 중립색, 라벨이 손잡이 위. 주행 스틱: 보이는 링은 그대로, 보이지 않는 잡기 구역(링 반지름 ~1.8 배, 오른쪽 칸 안으로 잘림 — 왼쪽 버튼·영상은 훔치지 않음, 가로 태블릿은 오른쪽 띠에서 스틱 위로 칸을 키움). SW 캐시 `2026-10-02-6`.
- 증거: 아래 커밋 메시지와 보고의 실행 기록(2026-10-02 Windows, Chromium).
- gate 변화: SOURCE 유지. ROS-SIM HOLD — 수정 뒤 OMX Gazebo 조이스틱 재실행 필요. DEVICE: 실 태블릿에서 잡기 구역 확인 필요.
- 결정: D-411 B, 구현 부록 1.

## 2026-10-03 · uncommitted · D-411 녹화 버튼 kind 명시 + 표면 재칠 규칙 제거
- 변경: robot-recording.js 시트 행 버튼(취소·받기)을 const+setAttribute("kind","quiet") 정준형(settings.js 패턴)으로 만들고, styles.css의 ui-button[data-robot-record][data-state=starting] color·border 표면 규칙을 지웠다 — 준비 상태는 HUD 칩(data-drive-fact=recording)과 토글 눌림이 이미 말한다. drive.js 로봇 녹화 버튼은 기존 quiet 유지.
- 근거: D-194/D-359 공용 부품 계약. CI 실행 37041646414의 실패 2건(test_helper_created_buttons_name_their_kind, test_surfaces_do_not_repaint_shared_controls) 치유.
- gate 변화: 없음.
- 최종 증거: test_shared_controls + pilot test + pilot_route 86 passed 37 skipped.

## 2026-10-03 · uncommitted · fix(pilot): D-411 B 재리뷰 — 종결 뒤 readback 실패, 떠 있는 스틱 원점
- 변경: 팔 화면이 목표 종결을 `/state` 다시 읽기 **전에** 알린다 — 다시 읽기가 실패해도 조이스틱이 영원히 기다리지 않는다. 위젯은 마지막 오류를 다음 갱신까지 유지(stop/press 가 보류를 풀지 않음). 주행 스틱: 링 밖(잡기 구역 안)에서 누르면 그 자리가 0 — 닿자마자 최대 편향으로 출발하지 않는다; 링이 손가락 밑으로 옮겨와 원점을 보이고 놓으면 돌아간다. 링 안에서 누르면 링 중심이 0(그대로). 오른쪽 칸은 `overflow: clip` + 여백으로 손잡이 그림자·테두리를 자르지 않는다. 주행 화면이 수동 한도를 읽을 때 capabilities `controls` 도 다시 읽어 알린 최대값이 낡지 않는다. SW 캐시 `2026-10-03-1`.
- 증거: 보고의 실행 기록(2026-10-03 Windows, Chromium). 새 시험 두 개는 고치기 전 코드에서 실패, 고친 뒤 통과.
- gate 변화: SOURCE 유지. ROS-SIM HOLD, DEVICE: 실 태블릿에서 떠 있는 원점 확인 필요.
- 결정: D-411 B.

## 2026-10-03 · uncommitted · feat(pilot): D-411 C 그리퍼 위젯, 주행 링 위쪽 잘림
- 변경: `widgets/gripper.js` — 열기/반/닫기 버튼, 열림 % 슬라이더(손을 뗄 때 목표 하나), 상태 배지(열림·닫힘·쥐고 있음·이동 중·알 수 없음, `role=status` `aria-live=polite`). `controls.js` 순수 `gripperPercent`·`gripperPosition`·`gripperDuration`(전체 행정 2.0 s 비례, 최소 0.2 s)·`gripperStateLabel`. `screens/arm.js` 공통 `submitGoal` 로 `submitJog`·`submitGripper`(`POST /gripper`) — 같은 하나씩·재시도 1회·id/null/false 계약, 위젯 표에 `gripper`. 태블릿은 조작부 칸 2:1(오른손 그리퍼), 휴대폰은 아래로 쌓인다. 자산 다섯 곳 등록, SW 캐시 `2026-10-03-2`. Part B 후속: 링 밖에서 누를 때 링의 그림 이동만 `[data-drive-right]` 안으로 잘라(휴대폰 위쪽 잘림), 0 점은 손가락 위치 그대로.
- 증거: `python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py -q` → 85 passed, 58 skipped; `ROSY_RUN_BROWSER_TESTS=1` `test_pilot_browser.py -k "arm or gripper or zone or grabs"` → 13 passed(그 전 한 번은 13개 모두 실패 후 단독·재실행 통과 — 같은 시각 기계 부하/다른 에이전트의 브라우저 시험으로 보이며 원인은 확인하지 못함; 새: 프리셋·슬라이더·배지, 오른손 칸 2000×1200·390×844, 링이 칸 안 — 고치기 전 코드로는 실패 확인), `test_pilot_sim_browser.py` 3 passed (2026-10-03 Windows, Chromium). 화면 `X:\DevTemp\d411-c\pilot-arm-gripper-*.png`, `pilot-drive-zone-top-390x844.png`.
- gate 변화: SOURCE 유지. ROS-SIM HOLD — OMX Gazebo 에서 그리퍼 위젯 미실행.
- 결정: D-411 C, 구현 부록 10.

## 2026-10-03 · uncommitted · fix(pilot): D-411 C 검토 — 그리퍼 목표를 알린 속도로
- 변경: `controls.js` `gripperGoal(from, to, g)` — `max_velocity` 가 있으면 길이 = 거리/속도 올림(0.2–2.0 s), 2.0 s 로 못 가는 거리는 닿는 곳까지; 없으면 행정 비례. `widgets/gripper.js` 가 이를 쓴다. SW 캐시 `2026-10-03-3`.
- 증거: `python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py -q` 통과, `ROSY_RUN_BROWSER_TESTS=1 ... -k gripper` 4 passed (2026-10-03 Windows).
- gate 변화: 없음. ROS-SIM HOLD.
- 결정: D-411 구현 부록 10.

## 2026-10-03 · uncommitted · fix(pilot): D-411 C 관문 뒤 — 그리퍼 목표를 0.9 × max_velocity 로
- 변경: `controls.js` `GRIPPER_PACE` 0.9 — readback 흔들림 여유. 전체 1.0 rad 행정은 두 목표(한 번에 0.9 rad). SW 캐시 `2026-10-03-4`.
- 증거: `test_controls.py`·Pilot 시험 통과, `ROSY_RUN_BROWSER_TESTS=1 ... -k gripper` 4 passed (2026-10-03 Windows).
- gate 변화: 없음.
- 결정: D-411 구현 부록 14.

## 2026-10-03 · 09553e730 · feat(pilot): D-423 "모델" 패널(읽기 전용)

- 변경: `models.js`(5 s 폴링 `GET /api/v1/vision/models`, 작업·슬롯·판·마지막 오류), 주행 화면 HUD 에 접는 패널, 셸 캐시 키 `2026-10-03-1`, 설치 목록. promote/rollback 은 `rosy_ml` 에만.
- 증거: `src/hmi/pilot/test` 53 passed, 24 skipped(브라우저 시험은 이 PC 에서 건너뜀).
- gate 변화: 없음.


## 2026-10-03 · uncommitted · feat(link): D-432 주소 없는 장비 접속

- 변경: 태블릿 native shell은 같은 LAN 장비 목록→선택→개발 즉시 접속 또는 4자리 페어링 흐름이다. 설정 파일 UI는 사용자 보정으로 제거했다. 기존 Pilot PWA와 제어 owner를 재사용한다.
- 증거: 관련 Python 계약 시험·실제 loopback TLS HTTP/WS 시험을 실행했다. Pilot Android 설치·화면과 실제 로봇 연결·현장 트래픽 수용은 서로 다른 증거다.
- gate 변화: 실제 장비의 제어·FIELD 관문은 이동하지 않는다.
- 결정: D-432 2026-10-03 추가 결정.


## 2026-10-03 · uncommitted · fix(link): 현재 접속과 후속 코드 규약 구별

- 변경: 사용자 보정으로 4자리 코드 발급·Cam 표시 별칭은 이번 적용에서 제외했다. 현재 로봇 8자·Cam 6자리 규약을 유지하며 D-432에 추후 통합을 기록했다. 실제 Pinky 접속 수정은 진행한다.
- 증거: 영향받는 Python 2345 passed/84 skipped, quick tier 459 passed/2 skipped, Pilot PWA 87 passed/58 skipped. 코드 규약 보정 뒤 해당 인증·페어링 시험을 다시 실행한다. 공개 검증 기록은 docs/validation/discovery-link-2026-10-03/README.md.
- gate 변화: Android 설치·실제 CORE 인증 확인은 실제 주행·Cam 화면 off 연속 송출·현장 트래픽 수용과 별개다. DEVICE/FIELD 이동 없음.
- 결정: D-432 후속 결정: 접속은 지금, 짧은 코드 통합은 추후 적용.

## 2026-10-03 · uncommitted · feat(pilot): 공용 규칙으로 화면별 작업 흐름 정리

- 변경: 로봇 목록·연결·조회 전용 카메라·주행 도구·입력 설정·녹화본·OMX SIM을 같은 UI 규칙으로 정리했다. 전체 영상/채우기/잘림 드래그·읽기 쉬운 동작 이름·단일 열린 패널·닫기 초점 복귀를 적용했다. 설정 변경 후 게임패드 미리보기가 멈추는 결함과 실제 태블릿 카메라 높이 0 결함을 수정했다.
- 증거: 실제 태블릿 목록에서 Pinky 인증/저장 자격 재접속/GET 카메라 전체 영상 확인. 녹화 브라우저 9 passed, 입력/OMX 기록 3 passed, 비상 정지 중 GET 영상 1 passed, 공용 아이콘 키보드/비활성 사유 1 passed. 남은 브라우저 시나리오는 최종 검증 기록에 구별한다.
- gate 변화: 실제 양의 주행 명령·비상 정지 해제는 실행하지 않았다. DEVICE/FIELD 이동 없음.
- 결정: D-432 화면별 순차 개선/공용 디자인 소유권.

## 2026-10-03 · uncommitted · test(pilot): 재조작 시험의 새 목표 실행 상태 분리

- 변경: OMX 오류 후 재조작 시험의 완료 receipt를 해당 목표 ID에만 적용한다. 전역 SUCCEEDED가 이후 목표까지 즉시 완료하여 누적 목표 수 2를 지나치던 fixture 결함을 제거했다. 단순 전역 RUNNING 재설정은 이전 목표도 실행 중으로 되살려 거절을 만들므로 사용하지 않는다. 제품 제어 코드는 변경하지 않았다.
- 증거: 진단 브라우저에서 오류 뒤 조작 가능 복귀, 다음 목표 수락, 거절 없음 확인. 최종 재검증 결과는 docs/validation/discovery-link-2026-10-03/README.md에 기록한다.
- gate 변화: DEVICE/FIELD 이동 없음.
- 결정: D-432 공용 UI 최종 검증; 첫 실패와 재실행 결과를 구별한다.

## 2026-10-04 · uncommitted · feat(pilot): 운전 모드와 차선 인식 분리

- 변경: 수동·차선 자동·지도 목표 선택과 독립 인식 선택(학습 모델/반사 제거/기존 검출). 정지·설정은 명시적 조작이며 인식 선택은 주행 모드를 바꾸지 않는다. 관리자·신선한 정지 IDLE·차선 OFF에서만 적용하고 적용 중 진행을 막는다. 성공 응답과 설정 readback을 확인하며 실제 추론 출처가 없으면 확인 대기로 표시한다. Pilot 셸 캐시 갱신.
- 증거: Pilot host 87 passed, 59 skipped. 기존 자동·hold·수동 takeover 브라우저 4 passed. 인식 적용 실패·pending·readback·구 서버 브라우저 1 passed.
- gate 변화: 없음. 실기 주행 수용 증거는 아직 없다.

## 2026-10-04 · uncommitted · feat: 저조도 카메라 판정 불가 표시

- 변경: 기존 front/status quality를 읽어 저조도에서는 차선·물체를 판정할 수 없다고 표시한다. JPEG 표시를 유지하고 회복·누락·오래된 상태에서는 경고를 해제한다.
- 증거: Pilot·Dashboard 저조도 브라우저 회귀 각각 1 passed; shared controls + shell 30 passed.
- gate 변화: SOURCE/LOCAL. ARM64/device/field verification pending.

## 2026-10-04 · uncommitted · feat: 기기 기록과 브라우저 영상 옵션

- 변경: 기기 기록은 원본/표시본 선택을 분리하고 서버 지원·실제 readback을 따른다. 브라우저는 원본을 항상 보존하며 표시본을 별도 저장한다. 녹화 종료 시 원본부터 다운로드하고 다시 받기 동작을 제공한다.
- 증거: 기기 옵션·실제 readback 1 passed; 저조도 회귀 1 passed; 기존 로봇 기록·hold/takeover 4 passed.
- gate 변화: SOURCE/LOCAL. ARM64/device/field evidence remains separate.

## 2026-10-04 · uncommitted · docs: provide the recorded artifact gate command

- Change: Add the existing payload-boot-smoke workflow dispatch command to the ARTIFACT progress entry; preserve its state and evidence. No screen or runtime code changed.
- Evidence: GitHub run 37200780702 was independently read back as completed/success at commit af0b3211384c9a8f2e5abbc2863c2fbcb54b0ca3. This records the command missing from the existing GO entry; it does not repeat the observation or claim device acceptance.
- Gate: Metadata correction only; existing physical and field gates are unchanged.
## 2026-10-04 · uncommitted · fix: 과노출 판정 불가 안내

- 변경: 원본 영상 위에 덧씌우지 않고 기존 품질 경고에서 과노출 · 차선 정보 확인 불가를 표시한다. 저조도·과노출·회복·구형 응답을 각각 구분한다.
- 증거: Pilot/Dashboard bright-dark browser 2 passed; native quality/alarm 9 passed.
- gate 변화: SOURCE/LOCAL. No device writes or motion.
## 2026-10-04 · uncommitted · fix(pilot): 시작 대상 확인 실패와 재시도

- 변경: 대상 발견 실패·잘못된 응답은 빈 본문 대신 대상 미확인 안내와 같은 발견 재시도를 제공한다. 짧은 pending 잠금으로 중복 발견을 막고 실제 404만 기존 Pinky 연결로 간다. 성공·실패 응답은 시작 안내를 아직 소유할 때만 상단 문구를 바꿔 더 늦은 정지 안내를 보존한다. 연결 화면의 작은 상단 행을 감싸고 이미 전체 주행 폭에서 숨기는 세 중복 selector를 제거해 styles.css 800줄을 유지한다. SW CACHE를 올리고 실제 공용 import 두 자산을 셸·개발 fixture에 등록했다.
- 증거: 영향 Pilot 브라우저 7 passed/57 deselected (37.06s), 최종 시작 수명 1 passed (4.80s). SW·예산·비활성 닫힌 목록 8 passed (2.48s), API/예산 16 passed (8.21s). 최초 GREEN의 import fixture 실패와 호스트 SW/예산 실패는 수정 후 해당 대상으로 재검증했다. X 제공 pending 잠금·새 안내 소유권 변이가 실제 단언 RED이며 원본 제공 GREEN, 제품 소스 SHA256 불변을 확인했다.
- gate 변화: SOURCE/LOCAL·대역 발견 증거이다. 실제 이동·정지 해제·장치 수용을 실행하지 않았다.
- 결정: D-439 Task5. 기존 drive/arm/HUD/인증과 같은 출처 계약을 보존한다. 근거 X:\DevTemp\rosy-ui-unify\tools.

## 2026-10-04 · uncommitted · feat(pilot): 크래프트 회차 1 — G2 기준선과 44px 바닥 회복

- 변경: 첫 저장소용 G2 기준선 셀 9장(게이트·로비·주행 × 태블릿 가로·세로·전화, dev_server 합성)을 `docs/validation/pilot-g2-baseline-2026-10-04/`에 남기고 `surfaces.yaml` pilot의 `baseline_reason`을 baseline 경로로 바꿨다. 기계 계측으로 좁은 티어의 조작 면적 위반을 찾아 고쳤다 — `styles.css` 끝에 `width < 30rem` 블록에서 레이아웃 규칙(`data-drive-layout="side|below"`의 `min-width: 0`)이 프리셋(저속/보통/빠름)과 정밀 토글을 내용 폭으로 줄여 44px 바닥을 뚫는 것(390px에서 36px, 320px에서 42px)을 같은 특이도 되돌림(min-width 2.75rem + flex 0 1 auto)으로 회복. 넓은 화면의 flex 채움은 불변.
- 증거: 기계 계측 8셀(게이트 3·주행 3·전화 320 계측) 전부 e-stop 111×58 보임·44px 미만 0·4.5:1 미만 0·가로 넘침 0px(수정 전 390px 3개·320px 1개 위반 → 수정 후 0). 12px 텍스트는 DESIGN.md Micro 승인 바닥이라 무결. `python -m pytest src/hmi/pilot/test src/hmi/web_common/test src/runtime/api_web/test/test_pilot_route.py -q` 302 passed/92 skipped — `test_responsive_tiers` 1건은 main 선재 실패(console-detail.css 40rem, 이 브랜치 소유 아님). registry 시험은 PNG 추적 후 15 passed.
- gate 변화: 없음. LOCAL 합성 증거. 사람 G3 시트·실물 태블릿 관측은 다음 회차(사다리 P2와 묶음).
- 결정: DESIGN.md 조작 면적 바닥(44px, 모든 티어). D-280·D-405 계측 규율 준수.
- 교훈: flex 채움용 `min-width: 0`은 좁은 티어에서 터치 바닥을 무력화한다 — 되돌림은 같은 특이도 + 파일 끝 배치로만 이긴다.

## 2026-10-04 · uncommitted · Android 로봇 검색 고착의 독립 복구

- 변경: private bound discovery 자식 프로세스, Binder 종료 fence, STARTED 확인 전 watchdog, 쿼리별 12초 제한 및 최대 3회/5분 재시도를 적용했다. 이전 세션의 응답을 차단하되 복구 중 후보의 원래 60초 TTL과 제어 권한을 보존한다.
- 결정: D-432 추가 결정. 중단은 검색 tick만 취소하고 종료 완료 콜백을 보존한다. 주 프로세스나 제어 세션을 검색 복구 때문에 종료하지 않는다.
- 증거: JVM 46 PASS·APK 빌드 성공, 동일 서명 install-r 및 설치 APK SHA 일치. 실제 태블릿에서 전용 검색 자식 장애 후 부모 PID 유지·새 자식·새 IPv4 응답·목록 복구를 확인했다. 연속 다시 찾기, background 정리와 resume 재검색도 확인했다. 독립 SOURCE SPEC·Safety·QUALITY PASS.
- gate 변화: 이 Android 발견 복구의 실제 관측만 기록한다. 로봇 CORE 접속·정지 해제·주행·장치 릴리스 수락은 별개이며 실행하지 않았다.

## 2026-10-04 · uncommitted · feat(pilot): 로비 방 목록 — `GET /api/v1/site/rooms` 소비 (D-343 2.2-3)

- 변경: 접속 화면의 토큰 폼 위에 이웃 방 목록(`screens/connect.js` — `GET /api/v1/site/rooms` 공개 정보, 같은 기기는 제외, 최대 8개). 각 방 버튼은 그 기기의 origin 진입 URL을 `data-lobby-url`에 명시하고 클릭하면 `location.assign`으로 이동한다(CORS를 열지 않는다, D-323 same-origin 유지). 이웃 없으면 한 줄 안내. 탐색 불가(503·끊김)면 로비는 조용히 없고 토큰 게이트는 그대로 산다(접속 흐름을 막지 않는다).
- 증거: 브라우저 2 passed(이웃 표시+목적 URL 명시·불가 시 조용+게이트 생존). api_web 전체 77 passed/13 skipped(동일 코미트 범위의 site-rooms 시험 포함). node --check 통과.
- gate 변화: 없음. 호스트 UI. PWA 기억 방·관전 모드·운전석 임대·MJPEG은 뒤 작업(D-343 §2.1·2.4-5).
- 결정: D-343 계획 §4 순서 2의 프런트 부분.

## 2026-10-04 · uncommitted · fix(pilot): LAN 목록 재검색과 저장 연결 기록 보존

- 변경: 웹 LAN 목록은 loading/empty/failure를 구분하고 5초 singleflight 요청·다시 찾기를 제공한다. canonical LAN robot URL만 명시적으로 열며 발견을 승인으로 표시하지 않는다. Native Vault는 만료·충돌·검색 오류에서 암호화 기록을 보존하고 실제 HTTPS 신원 검증 후 hostname 슬롯으로 이전한다. HTTP 주소 변경은 자격 재사용하지 않는다. 로컬 기록 삭제는 zero/연결 종료 뒤 처리하며 기존 IP 재등장도 fence로 막는다.
- 증거: 독립 SPEC·Quality·Safety PASS, 작성자 JVM24 PASS·변이3 RED·복원24 PASS, root 실제 적용 소스 Gradle 컴파일/JVM24 PASS와 Chrome 목록4 PASS. 최초 root Gradle 실행은 PowerShell property 인자 분리로 태스크 조회 실패였고 실제 테스트 실행은 아니며 인자를 고쳐 재검증했다.
- gate 변화: SOURCE/LOCAL 한정. 일반 상대 승인/key proof/만료 뒤 무코드 로그인 갱신은 D-456 후속 소유 작업이고 실제 tablet/robot DEVICE 수락은 미완료다.

## 2026-10-04 · uncommitted · fix(ui): LAN 재검색 버튼의 공용 kind 선언 정합

- 변경: 동적 다시 찾기 버튼의 quiet 종류를 생성 직후 명시해 공용 helper 계약 검사에서 확인할 수 있게 했다. 기존 클릭/재검색/인증 행동과 종류 값은 동일하다.
- 증거: Pinky 학습 앱 main 동기화 중 공용 컴포넌트 검사가 이 위치를 지적했다. 해당 계약 및 Pilot 브라우저 소스 검사를 다시 수행한다.
- gate 변화: 없음. 장치 연결·주행·페어링 수용을 수행하지 않는다.

## 2026-10-04 · uncommitted · fix(pilot): 조종하지 않는 카메라의 frame Response 보존

- 변경: connect 화면의 frame fetch는 shared camera-pair 검증기에 Response를 넘겨 ok·metadata·blob 검사 소유권을 유지한다.
- 증거: 실제 EMERGENCY JPEG 표시와 mode 변경 요청 없음의 기존 browser 시험 PASS, 독립 source/host 리뷰 APPROVE. 전체 browser 727 입력의 유일한 실패는 Robot fullscreen 시험이며 원본은 별도 보존한다.
- gate 변화: SOURCE/LOCAL만. 실기 영상·주행·기록 또는 새 서명 payload 완료로 승격하지 않는다. D-427 개별 게이트 검증 기록 참조.

## 2026-10-05 · uncommitted · feat(pilot): DEVICE GO — 사용자 실기 확인 (D-444 §2 R2)

- 변경: pilot `progress.md` DEVICE 게이트 HOLD→GO. 사용자가 실기 Pinky에서 Pilot 원격 조종·페달 해제·e-stop이 실제 정지로 이어지는 것을 직접 확인했다. 정량 측정값(ms·cm)은 별도 회차에 보강한다. 증거: `docs/validation/pilot-device-user-confirmed-2026-10-05/README.md`.
- 증거: 사용자 확인 ("건했어. pilot 는 돼", 2026-10-05). 합격선 참조: `docs/plans/2026-10-04-pilot-device-stop-contract-measurement.md`.
- gate 변화: pilot DEVICE **GO** (사용자 확인 등급). FIELD는 별개(D-454 결정 3).
- 결정: D-444 §2 R2 충족. 사다리 P2 완료.
## 2026-10-05 · uncommitted · feat(pairing): LAN 승인 기록과 신원 확인 재연결

- 변경: 같은 LAN 목록에서 선택한 장비에 수신 승인을 요청하고 P256 키·TLS 신원 확인 뒤 기존 조종 세션으로 연결한다. 승인 기록은 일반 세션과 별도로 암호화해 보관한다. 승인 직후 연결 실패에도 기록을 남기고, 키 변경·폐기·발급자 만료 시 기록을 보존한 채 접속을 차단한다. 마지막 선택 장비의 연결 정보를 실패 화면에서도 열 수 있다.
- 증거: 최종 Kotlin 컴파일과 실제 JVM 검사 81 PASS·0 SKIP. 승인 뒤 challenge 실패의 저장 순서와 실패한 재연결에서 기존 암호화 바이트 보존을 회귀 검사했다. 실제 Android 대화상자 표시·APK 설치·상대 화면 승인·DHCP 재연결은 아직 확인하지 않았다.
- gate 변화: 새 페어링 변경의 SOURCE/LOCAL 증거다. 기존 D-444 사용자 실기 확인 DEVICE GO는 보존하며 이를 새 페어링 수용으로 대신하지 않는다. Bluetooth·주소 입력·개발 설정은 기본 연결 흐름에 추가하지 않는다.

## 2026-10-05 · uncommitted · refactor(pairing): 발급 세션 변수와 시험 이름 명확화

- 변경: 발급된 단기 세션 변수명을 accessToken으로 명확히 하고 세 시험 이름을 줄였다. wire 필드와 검증 단언은 유지한다.
- 증거: 세 파일의 독립 source 검토에서 이름 변경만 확인했다. 변경한 실제 snapshot의 Kotlin 컴파일과 JVM 검사 81 PASS·0 SKIP를 다시 확인했다.
- gate 변화: SOURCE/LOCAL만. 실제 설치·LAN 승인 수용은 별도다.

## 2026-10-05 · uncommitted · feat(drive): D-368 운전자 MJPEG 스트림 클라이언트

- 변경: `vision.js`에 `createDriverStream`(fetch 스트림 + multipart 증분 파서 + fps·age 통계, 헤더 인증만·URL 토큰 없음 D-193) 추가. `drive.js` 조종 화면에서 스트림 시도 — 붙으면 폴링 정지, 끊기면 폴링 복귀 후 3 s 재시도, HUD에 `영상 Nfps · Mms` fact(1 s 초과 경고색). 주석 쌍(annotated) 캡처는 원본 짝이 필요해 raw 모드에서만 스트림. `robot-recording.js`의 미리보기 수락 경로(acceptPreview)를 폴링·스트림 공용으로 추출. `sw.js` 캐시 키 갱신.
- 증거: `test/test_vision_stream_client.py` 3 PASS(분할 청크 재조립·몸통 분할 대기·프레임/통계/종료 폴백). pilot 전체 90 PASS. ADR이 명시한 createImageBitmap·캔버스 대신 기존 img+objectURL 파이프라인을 재사용했다 — 계약의 실질(헤더 인증·멀티파트·URL 토큰 금지)은 동일하고 녹화 캡처가 한 경로를 유지한다.
- gate 변화: SOURCE. 실기 태블릿에서의 fps ≥ 10·지연 실측은 DEVICE 별도 회차(D-368 Validation).

## 2026-10-05 · uncommitted · fix(pilot): 승인 화면 시험 서버 자산 정합

- 변경: 시험 서버의 peer-approval.js 제공을 CORE·OMX 목록과 일치시킨다. 실제 앱 번들·통신 권한은 바꾸지 않는다.
- 증거: 기존 shell 자산 불일치 실패를 수리한 뒤 관련 16 passed. 설치된 Pilot에서 같은 LAN 로봇 목록과 선택 뒤 기존 로그인 코드 창을 직접 확인했다.
- gate 변화: SOURCE/LOCAL 및 앱 설치 관찰. 새 수신 승인·장기 재연결의 DEVICE 수용은 배포 후 별도다.

## 2026-10-05 · uncommitted · fix(peer-assets): Pilot 승인 모듈 정적 경로 일치

- 변경: SIM·개발 서버 allowlist에 기존 peer-approval.js를 더해 CORE와 같은 정적 자산을 제공한다. API·제어 권한·UI 구성 변경 없음.
- 증거: test_shell_assets.py 4 passed, known_failures NEW 0.
- gate 변화: SOURCE/LOCAL. 실제 장치·FIELD 검증은 별도다.

## 2026-10-05 · uncommitted · feat(pilot): 연동 코드 보여주기(양방향)

- 변경: 기기에 화면이 없을 때 Pilot이 코드를 보여 주고 상대 기기에서 입력한다(D-193 §5 등록 코드, 기존 CORE `POST /api/v1/auth/enrollment-codes` 그대로 사용 — 새 API·모드·필드 없음). `client.js` `requestEnrollmentCode(role)`, 접속 화면의 관리자 전용 "연동 코드 보여주기"(코드 발급 → `scale="display"` 큰 표시 + 유효분 안내, 403은 권한 문구). 반대 방향(상대 화면 코드 → Pilot 입력)은 기존 폼 그대로. `sw.js` 캐시 키 갱신. 개발 서버에 canned 발급 + `devadmintoken`(administrator) 추가.
- 증거: `python -m pytest middleware/ui/pilot/test middleware/core/api_web/test/test_pilot_route.py -q` 92 passed 73 skipped; `ROSY_RUN_BROWSER_TESTS=1 -k "show_code or gate_panel or bad_token or lobby_lists"` 4 passed(신규: 운전자는 버튼 없음·관리자는 DEMO-C0DE 표시·가로 넘침 0); known_failures NEW 0.
- gate 변화: SOURCE 유지. ARTIFACT(새 APK 빌드·서명)·DEVICE(실 태블릿 표시·상대 기기 입력)·FIELD는 별도.

## 2026-10-05 · uncommitted · feat(pilot): 보여준 코드의 남은 유효 시간 표시

- 변경: 연동 코드 발급 뒤 남은 수명을 `유효 MM:SS` 카운트다운으로 같이 보여 주고, 만료 시 "다시 발급해 주세요" 안내만 바꾼다(자동 재발급 없음 — 코드 소모 없이 끝난다). 화면 재진입·재확인 때 카운트다운 타이머를 정리한다(`__enrollDispose`). 역할 문구는 조회용/운전자용으로 읽힌다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 -k show_code` 1 passed(카운트다운 진행·재발급 버튼 유지·재진입 정리); 전체 `middleware/ui/pilot/test` + `test_pilot_route` 92 passed 73 skipped, known_failures NEW 0.
- gate 변화: SOURCE 유지. 태블릿 재설치·실기 확인은 별도.
