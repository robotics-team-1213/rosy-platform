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

## 2026-10-01 · 5db3391d · feat(pilot): 보정 중 판과 비소유자 주행 잠금
- 변경: `calibration.js`(순수 판정) 추가. 상태의 `activity` 가 CALIBRATING 이면 영상 위 "보정 중 — <label>" 판과 HUD 칩. whoami id 가 owner 가 아니면 조작부 전체 disabled + 사유, 명령 루프는 아무것도 보내지 않는다. 상단 E-Stop 은 그대로. SW 셸 키 `2026-10-01-1`.
- 증거: test_calibration_view.py 5 passed; ROSY_RUN_BROWSER_TESTS=1 test_pilot_browser 전체 18 passed(새 `test_calibration_banner_locks_drive_for_other_tokens_and_keeps_estop` 포함, 배치 시험 유지). 스크린샷 X:\DevTemp\calibration-mode\pilot-calibration-locked.png·pilot-calibration-owner.png.
- gate 변화: 없음.
