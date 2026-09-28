# dashboard logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-25 · uncommitted · refactor(hmi): operator screens leave the API package (D-243)

- 변경: `core_api_web/web`의 정적 파일을 이 패키지로 옮겼다. API는 설치 share 또는 이 소스 폴더를 읽는다
- 증거: 이 기록 직후 dashboard·gateway 대시보드 시험
- gate 변화: 신규. SOURCE GO, LOCAL GO, ARTIFACT HOLD, ROS-SIM/DEVICE/FIELD N/A
- 결정: D-243
- 교훈: 없음

## 2026-09-25 · 96654ed1 · feat(hmi): device card and motion reason (D-247)

- 변경: 점검 뷰 4번 카드 "장치" — 장치별 이름·버스·상태 칩(공용 [data-status] 어휘)·근거·`벤치 전용`·측정 시각, 관리자 "다시 점검". 운용 뷰 teleop 문구는 runtime mode로 막혔을 때 `motion_reason`을 보인다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 51 passed(Chromium)
- 미증명: 실기 대시보드
- gate 변화: 없음
- 결정: D-247
- 교훈: CORE-only viewer 상태는 1366×768에서 이전 문구로도 조작 열이 8 px 넘친다(feed2fc7부터). 문서 스크롤은 없다.

## 2026-09-26 · 88fbbe7f · feat(hmi): buzzer and lamp test buttons on the device card (D-247 6)

- 변경: 장치 카드의 부저·램프 행에 관리자 전용 "울려 보기"/"켜 보기"를 두었다. 드라이버가 없으면 꺼 둔다. 시험 결과 한 줄과 "들림·안 들림"/"보임·안 보임"도 보인다. 텍스트는 textContent만, 버튼은 공용 ui-button, CSS는 토큰만 쓴다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 55 passed(Chromium)
- 미증명: 실기 대시보드에서 버튼을 누른 뒤 소리·빛
- gate 변화: 없음
- 결정: D-247
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(hmi): add administrator hardware observation panel

- 변경: `/device`에 root probe의 장치별 상태·근거·측정 시각을 읽는 패널을 추가했다. 재점검은 기존 관리자 API만 호출하고, 이전 응답을 유지할 때는 stale로 표시한다.
- 증거: 화면 자산/매니페스트 계약 및 Chromium 패널 동작 시험. API 오류·쿨다운 상태는 서버 응답 문구를 표시한다.
- gate 변화: 없음. 테스트용 API 응답 브라우저 확인이며 Pi·실기 probe 결과는 확인하지 않았다.
- 결정: D-247의 관측/명령 경계를 그대로 쓴다. 이 패널은 hardware test나 사람 확인을 실행하지 않는다.
- 교훈: 마지막으로 받은 값은 접근 실패와 함께 stale로 표시해야 현재 관측으로 오해하지 않는다.

## 2026-09-26 · uncommitted · feat(hmi): extend role-based device and setup panels

- 변경: `/device`에 시스템 런타임·신원·CAP/inventory, Host Agent 네트워크·릴리스·커미셔닝 readback, 관리자 토큰 및 안전 한계 설정을 추가했다. `/setup`에는 Operator API 권한과 capability에 맞춰 초기 위치 입력 및 확인 대화상자를 둔 SLAM 시작·중지·저장 패널을 추가했다. 좁은 화면에서 상태 필드와 폼을 세로로 재배치한다.
- 근거: 패널/API 권한 계약과 manifest 시험, 대시보드/API 회귀, JavaScript 구문 검사, 선택 Chromium 회귀. `ROSY_RUN_BROWSER_TESTS=1` 대시보드/하드웨어 시험 57 passed.
- gate 변화: 없음. `/dashboard`의 기존 기능은 유지하며 이관 완료로 간주하지 않는다. 새 운전 콘솔, 도킹 준비 조작, ROS 그래프, 실제 네트워크/릴리스 조작, Pi/실기 검증은 남아 있다.
- 결정: 패널은 `panels.yaml`에서 추가하고 기존 API 계약의 최소 역할을 따른다. SLAM 조작은 Operator, 토큰/안전 정책은 Administrator다.
- 교훈: 새 페이지 readback은 Host Agent 릴레이 봉투(`available/data`)와 CORE 커미셔닝 직접 payload의 응답 모양 차이를 보존해야 한다.

## 2026-09-26 · uncommitted · feat(hmi): add operator docking preparation panel

- 변경: `/setup`에 도킹 상태와 저장된 도크 목록, capability 조건부 도킹/언도킹/취소, 확인 후 현재 위치 teach를 추가했다. 도킹 capability가 없거나 상태 조회가 실패하면 움직임 명령을 비활성화한다.
- 근거: DNC API 역할·경로를 고정한 패널 인벤토리 계약 및 정적 검사. 도킹 하드웨어/실기 동작은 확인하지 않았다.
- gate 변화: 없음. 도크 종류/등록 관리는 이 패널에 포함하지 않았고 `/dashboard` 설정은 유지했다.
- 결정: UI의 Operator 경로는 `docking.py` 권한 계약을 따른다. teach와 움직임 명령에는 확인 대화를 둔다.
- 교훈: `docking/status.supported`가 명시적으로 true가 아니면 UI에서 명령을 내보내지 않는다.

## 2026-09-26 · uncommitted · feat(hmi): add confirmed host recovery actions

- 변경: `/device` 네트워크 모드 전환·프로파일 적용·Wi-Fi 연결과 release rollback/recovery-hold 해제를 추가했다. 서버 Host Agent readback이 사용 가능할 때만 활성화하고 확인 대화, `confirmed`, idempotency key를 보내며 PSK 입력은 요청 후 지운다. 시스템 런타임 패널은 `/api/v1/system/runtime`가 실제 제공하는 ROS 그래프 snapshot도 표시한다.
- 근거: Host API 계약의 기존 경로 및 역할을 확인했고 Host Agent 부재 시 쓰기 API가 발생하지 않는 Chromium 테스트를 추가했다.
- gate 변화: 없음. Host Agent 장치, 실제 Wi-Fi 전환, 릴리스 rollback은 실행하지 않았다. ROS 그래프 개별 `/api/v1/ros/*`는 미구현 경로로 남겨 호출하지 않는다.
- 결정: 연결이 끊길 수 있는 작업은 확인한 뒤에만 요청한다. 비밀 PSK는 화면 보관이나 로그 출력 없이 1회 API 요청에만 넣는다.
- 교훈: CORE runtime ROS snapshot과 미구현 ROS 그래프 API를 구분한다.

## 2026-09-26 · uncommitted · feat(hmi): add role-gated console map panel

- 변경: `/console`에 occupancy/costmap/path 표시, 지도 레이어 선택, 클릭 및 키보드 십자선 기반 초기 위치/목표 선택을 등록했다. Viewer는 지도만 읽고 Operator 이상도 navigation capability가 `true`일 때만 명령을 보낸다. 지도 모듈의 패널 해제 API가 입력 리스너와 ResizeObserver를 정리한다.
- 근거: API/매니페스트 계약, 390px Chromium에서 키보드 포커스와 viewer POST 차단, 기존 dashboard 지도 브라우저 회귀로 확인한다.
- gate 변화: 없음. 실제 로봇 맵/위치 주행은 실행하지 않았다. 텔레옵/카메라/모드/도킹은 아직 새 console 패널로 옮기지 않았다.
- 결정: D-259 기존 map click·keyboard 경로와 동일한 confirmation/API 코드를 재사용하고, map refresh 실패는 독립 status로 보인다.
- 교훈: 재사용하는 지도 패널도 unmount 때 observer와 입력 리스너를 끊어야 한다.

## 2026-09-26 · uncommitted · feat(hmi): move live control panels into console

- 변경: `/console`에 capability·safety·freshness 확인 후 동작하는 operator hold-to-drive, 기존 프레임 sequence/인증 로직을 재사용하는 visibility-aware 카메라, capability-gated docking 운용을 추가했다. E-Stop은 공유 셸의 별도 고정 제어다. `/setup` 도킹은 이제 목록·pose fresh 확인·teach만 맡는다.
- 근거: static route/role 인벤토리, 390px Chromium에서 teleop 반복/terminal zero와 unmount, docking capability 차단, camera visibility/unmount 정리, 기존 `/dashboard` Chromium 회귀.
- gate 변화: 없음. 실제 주행·카메라 센서·도킹 하드웨어는 연결하지 않았다.
- 결정: 운전과 설정을 페이지 책임으로 분리했다. 버튼 hold 동안 100ms 명령을 보내고 손을 놓거나 연결/포커스를 잃으면 zero를 전송한다.
- 교훈: 이동 명령 버튼은 shell polling과 별개로 panel teardown/창 숨김 시에도 terminal zero를 보내야 한다.

## 2026-09-26 · uncommitted · feat(hmi): add shared role-based mode control

- 변경: `/console`에서 IDLE/MANUAL/NAVIGATION 전환을 분리된 Operator 패널로 제공한다. mode API 앞에서 공용 `rosy:stop-motion` 이벤트를 보내고, Navigation capability가 없거나 상태를 아직 모르면 모드 명령을 막는다. E-Stop 셸도 같은 stop 이벤트를 보낸다.
- 증거: API/manifest 역할 계약 및 Chromium에서 capability 차단과 stop event 후 mode 요청을 확인한다.
- gate 변화: 없음. 실제 모드 전환 및 움직임은 실행하지 않았다.
- 결정: 운전 모드와 hold-to-drive를 별도 패널로 두되 즉시 정지 이벤트만 공유한다.
- 교훈: 화면 간 제어 연결은 command ownership을 합치지 않고 명시적 stop 신호로 조율한다.

## 2026-09-26 · uncommitted · feat(hmi): add line-follow and traffic policy panels

- 변경: `/console`에 navigation capability-gated line-follow를 추가하고 `/setup`에 staged traffic policy 편집·정지 확인 후 적용을 추가했다. line-follow 정지는 capability 미제공 상태에서도 사용할 수 있고 simulation signal은 서버 지원이 readback된 경우에만 활성화된다.
- 증거: API/manifest 역할 계약, Chromium에서 capability 부재 시 line-follow OFF만 허용, traffic 정책 stage 이후 확인을 거쳐 apply가 전송되는 경로를 확인한다.
- gate 변화: 없음. 실제 차선 추종·교통 제어·로봇 움직임은 실행하지 않았다.
- 결정: 정책 설정은 준비 화면에, 즉시 운전 제어는 운용 화면에 둔다. 교통 정책 apply는 서버의 정지 상태 검증을 유지한다.
- 교훈: UI 확인은 서버 정지 인터록을 대체하지 않고, 런타임 capability readback으로 선택 가능한 동작만 노출한다.

## 2026-09-26 · uncommitted · feat(hmi): add administrator dock catalog and registration

- 변경: Viewer가 읽을 수 있는 dock type 목록 API와 Administrator 전용 `/setup` dock type 등록·도크 저장·삭제 패널을 추가했다. 새 도크는 fresh pose 및 type 목록을 확보한 뒤 현재 위치로 등록한다.
- 증거: GET dock type API 권한 시험과 Chromium에서 pose/type 미준비 시 등록 차단, 준비 뒤 기존 type의 dock POST를 확인한다.
- gate 변화: 없음. 실제 docking, tag observation, 장치 위치 측정은 수행하지 않았다.
- 결정: 설정 권한은 Administrator, 운행과 teach는 기존 Operator 계약으로 나눈다.
- 교훈: 현재 위치를 영구 기준점으로 저장하는 작업은 pose freshness와 명시적 확인을 요구한다.

## 2026-09-26 · uncommitted · feat(dashboard): D-260 operate-view summary line
- 변경: `status-summary.js` 신규(D-262 팩토리 모양), `app.js`가 느린 데이터 주기(5 s)에 `/host/status-summary`를 읽는다. 요약줄은 상태 레일의 한 칸 — 따로 한 줄을 쌓으면 1366×768 안전 정지 상태에서 조작 열이 34 px 넘쳤다(D-201). CMake 설치 목록과 app.py allowlist에 추가하고 셸이 import하는 모듈이 둘 다에 있는지 패키지 시험으로 지킨다
- 증거: 브라우저 시험 신규 6건(요약줄 내용·할 일 펼침·장치 카드 이동·실패/준비·긴 이유 적합 2 뷰포트) 포함 62 passed; 2026-09-26 Windows, `feat/d260-status-signals`: 호스트 묶음(foundation·gateway·api_web·hmi web/dashboard/face·lamp·boot display·hw-test·hw-probe·boot-status·native systemd·device surface·image customization·lamp image·harness) 2051 passed, 32 skipped, 2 failed — 둘 다 main의 `src/hmi/dashboard/logs.md` 두 항목(`- 근거:`)이 원인이고 깨끗한 main worktree에서도 같게 실패한다. `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 62 passed
- gate 변화: 없음
- 결정: D-260 Proposed
- 교훈: 셸 분해 모듈을 새로 만들면 `CMakeLists.txt` install과 `core_api_web/api/app.py` allowlist 둘 다에 넣어야 실기에서 404가 나지 않는다

## 2026-09-26 · uncommitted · feat(hmi): 실제 CORE 경로 연결과 화면 상태 보정

- 변경: `/console`, `/setup`, `/device`는 실제 CORE API/`CoreServices`로 검토한다(D-274). 화면 메뉴 포커스·반응형 영역을 보강하고 셸 body 기본 여백/배경을 지정해 흰 테두리를 없앴다. 빈 지도/숨긴 카메라의 공간을 줄이고 setup 입력을 어두운 공용 토큰에 맞췄다. 카메라 상태의 `null` age/captured 값을 0으로 표시하지 않는다.
- 증거: UI/API pytest 106 passed, 1 skipped; `test_dashboard_browser.py` 64 passed. Playwright에서 실제 FastAPI+`CoreServices.build()` CORE 경로를 사용해 manifest, whoami, system info, robot state HTTP 200, 세 표면 mount, 브라우저 오류 0을 확인했다. `test_dashboard_browser.py -k unavailable_camera_keeps_missing_timestamps`는 수정 전 `0 ms`로 실패하고 수정 후 통과. CORE 모드라 모터 미연결이며 이 증거는 ROS-SIM/DEVICE/FIELD 수용이 아니다.
- gate 변화: 없음(SOURCE/LOCAL 현재 수준 유지, ARTIFACT HOLD).
- 회귀: 별도 동료 WIP `deploy/release/test/test_secret_scan.py` 및 카메라 리포트 미수정·미스테이징.

## 2026-09-26 · uncommitted · fix(hmi): role-gate map selection and compact mobile controls (D-278)

- 변경: 지도 초기 위치·주행 목표 선택을 Operator 이상 및 Navigation capability가 확인될 때만 활성화한다. viewer와 미지원 프로필에는 비활성 상태와 이유를 함께 표시한다. 모바일 레이어 버튼을 가로 묶음으로 바꾸고 선택 상태는 중립 상승면으로 표현하며 E-stop 문구를 한 줄로 고정했다.
- 증거: 역할별 실제 CORE/Playwright 검토(viewer/operator/administrator, 1440px/390px), 직접 manifest 접근 viewer setup 403·operator device 403·administrator device 200. dashboard·palette/API manifest·UI route 시험 42 passed, docs generate 성공. harness lint는 이 파일 외 기존 문서 6 errors/21 warnings로 종료했다.
- gate 변화: 없음. ROS-SIM, Pi 장치, 현장 동작은 검증하지 않았다.
- 결정: D-278
- 교훈: 조작 화면의 capability 제한은 API 게이트만으로 충분하지 않다. 비활성 이유를 실제 조작 가까이에 표시하고 직접 클릭·키보드 경로도 같은 조건을 검사한다.

## 2026-09-26 · uncommitted · feat(hmi): show provisioned ROS identity in settings
- 변경: 현장 설정의 신원 카드와 장치 시스템 신원에 로봇 번호, ROS Domain ID, namespace 읽기 전용 표시를 추가했다. 표시 이름 수정은 기존 관리자 계약을 유지한다.
- 증거: 대시보드 관련 호스트 시험 78 passed; Chromium 현장 설정 시험 1 passed. 실제 Pi API는 19/59/rosy_19를 반환했으나 새 UI 산출물은 아직 장치에 설치되지 않았다.
- gate 변화: ARTIFACT HOLD 유지.
- 결정: 기존 IDN-003 응답 사용.
- 교훈: DDS 번호는 설치 신원에서 파생되므로 일반 설정 폼에서 임의 수정하면 안 된다.
## 2026-09-26 · uncommitted · feat(hmi): stabilize mobile /console topbar and capture current shell

- 변경: 390px topbar를 브랜드/E-stop, 화면 전환, 역할/안내의 분리된 행으로 정렬한다. D-280 기준선에 현재 `/console` LOCAL 캡처 측정과 desktop no-scroll/act 밀도 HOLD를 기록한다.
- 증거: Chromium 390×844에서 가로 overflow 0, 브랜드·탐색·역할·E-stop 겹침 0, E-stop viewport 내 표시; 실제 FastAPI+CoreServices CORE `/console`에서 브라우저 오류 0. 1366×768에서는 스크롤 823px, 조작 패널 경계 y=1017인 3열 후보는 하단 조작을 잘라 적용하지 않았다. 캡처는 X:\DevTemp에만 보관.
- gate 변화: 없음. ROS/장치/벤치/현장 검증은 하지 않았다.
- 결정: D-201 조작 영역을 스크롤 숨김으로 잘라내지 않는다. 역할과 실제 ROS 데이터별 패널 밀도를 확인한 뒤 desktop 배치를 다시 설계한다.

## 2026-09-26 · uncommitted · docs(hmi): compare operator console viewport by role

- 변경: D-280 기준선에 administrator/operator 두 역할의 현재 `/console` 캡처 결과와 데스크톱 초과의 원인을 기록한다.
- 증거: 실제 FastAPI+CoreServices CORE fixture, Playwright 1366×768/390×844, 두 역할 모두 console panel 7개(4 act), desktop scroll 823px, mobile scroll 3057px, 가로 overflow 0, 브라우저 오류 0. 역할에 따른 panel 수가 같고 CSS가 act를 다음 행에 둔다. 실제 ROS/장치 입력은 연결하지 않았다.
- gate 변화: 없음. D-201 layout 계약 위반을 확인했으나 새 배치는 승인/검증 전이다.
- 결정: act를 잘라내거나 스크롤하게 만드는 CSS는 보류한다. 조작 panel 밀도와 접이식/탭 우선순위를 설계한 뒤 desktop 변경을 평가한다.

## 2026-09-26 · uncommitted · docs(adr): D-283 운용 조작 그룹 결정

- 변경: D-283 Accepted와 docs/dashboard harness ADR 색인을 추가했다. 운전(모드+수동), 도킹, 차선 추종 그룹을 고정 act 영역에서 선택한다.
- 근거: 실제 CORE 경로 admin/operator 캡처에서 현재 823px desktop scroll을 확인했다. 펼친 3열 후보는 조작을 잘라 concept 16 §7.1 및 D-201을 위반했다.
- gate 변화: 없음. G1 정지 전환, G2 뷰포트 캡처, G3 운용자 평가와 ROS-SIM/DEVICE/FIELD 수용은 미실행이다.

## 2026-09-26 · uncommitted · feat(hmi): role-aware map absence and Host Agent recovery (D-279)

- 변경: preserve structured HTTP errors; only documented `404 / NOT_FOUND` becomes an empty map. Gate the `/setup` link by role and manifest. Render supplied Host Agent recovery as text and keep operations disabled while unavailable.
- Structure: role panels use shared `ui-status`, `ui-actions`, and named `ui-button` sizes.
- 증거: 241 passed, 2 skipped; visible CORE/Playwright review returned Viewer setup 403, Operator setup link only for an empty map, Administrator device 200; zero browser errors or 390px horizontal overflow.
- gate 변화: unchanged. CORE browser proof does not establish ROS-SIM, ARM64, device, or field acceptance.
- Decisions: D-279 behavior; D-284 shared components.
- Rule: do not infer freshness, causes, recovery steps, or role grants beyond API evidence.

## 2026-09-26 · uncommitted · test(hmi): verify role UI after current-main rebase

- 변경: re-run dashboard, shared UI, API, role browser, and device browser coverage after rebasing on current main.
- 증거: 241 passed, 3 skipped; visible CORE review remains on `/device` with Viewer setup 403, Operator setup link only for an empty map, Administrator device 200, and no browser errors or 390px overflow.
- gate 변화: unchanged. CORE browser proof does not establish ROS-SIM, ARM64 image, device, or field acceptance.
- Decision: D-279 behavior and D-284 shared components.

## 2026-09-26 · uncommitted · feat(dashboard): camera recording and screenshot controls

- 변경: 전방 카메라 화면에 JPEG 스크린샷, 2 FPS 브라우저 영상 녹화, 운전 조작 타임라인, PC/로봇 SD/둘 다 저장 선택, 로봇 저장 파일 목록·다운로드를 추가했다.
- 증거: `python -m pytest src/hmi/dashboard/test/ -q --basetemp X:/DevTemp/rosy-camera-capture`와 API 통합 시험. 실제 브라우저와 장치 저장 검증은 남아 있다.
- gate 변화: 없음. native ARM64 이미지와 물리 카메라 연결 검증은 별도다.

## 2026-09-26 · uncommitted · feat(hmi): implement D-283 console action groups

- 변경: `운전`·`도킹`·`차선 추종`을 capability-filtered accessible tabs로 묶었다. 탭을 벗어나기 전 terminal zero 응답을 기다리고 실패 시 현재 그룹을 유지한다. desktop은 sense/observe/act 3열 viewport에 맞추고 sense만 내부 scroll, mobile은 기존 vertical scroll을 유지한다.
- 근거: dashboard/API/gateway 관련 pytest 116 passed, 2 skipped; foundation 50 passed. 실제 FastAPI+`CoreServices` 브라우저에서 administrator/operator × 1366×768/390×844 4개 캡처, desktop page scroll 0, mobile horizontal overflow 0, E-stop visible. G1 active teleop zero → unmount, line-follow/docking 요청 대기·활성 중 그룹 이탈 차단, terminal zero 실패 시 전환과 unmountAll 차단, 재진입 후 자동 명령 없음 통과. 캡처 `X:\DevTemp\d283-console-core-browser`.
- gate 변화: SOURCE/LOCAL 구현·브라우저 gate GO. G3 8명 조작자 평가 전 D-201 desktop 제품 수용은 HOLD; ROS-SIM/ARTIFACT/DEVICE/FIELD 증거 아님.
- 결정: D-283 Accepted.
- 교훈: 선택형 조작 화면은 숨길 때 스트림/폴링을 내리고, 재진입은 새 사용자 입력부터 시작한다.

## 2026-09-26 · uncommitted · test(dashboard): real Chromium camera capture

- 변경: Chromium의 실제 `MediaRecorder`로 미리보기 JPEG 스크린샷, WebM 녹화, 조작 JSON의 파일 형식·내용을 검증하고 카메라 패널의 역할별 버튼 상태 시험을 수정했다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_camera_capture_browser.py test/test_role_menu_panels_browser.py::test_console_camera_preview_stops_on_hidden_document_and_unmount -q` 2 passed.
- gate 변화: 없음. 합성 프레임의 로컬 브라우저 증거이며 Pinky SD, 카메라 센서, ARM64 이미지 수용은 별도다.

## 2026-09-26 · uncommitted · feat(hmi): apply D-292 shared component roles

- 변경: 카메라 조작 버튼마다 실제 동작에 맞는 kind를 지정하고 라이브 안내를 ui-status로 통일했다. 액션 간격과 저장 필드 라벨은 공유 컴포넌트를 사용하며 캡처 오버레이 색상도 tokens.css에서 읽는다.
- 증거: HMI web + dashboard browser-enabled suites — 97 passed; API route/manifest tests — 27 passed. Visible CORE Chromium reviewed operator /console·/setup and administrator /console·/setup·/device at desktop/mobile sizes; 0 page errors and missing button kinds.
- gate 변화: SOURCE/LOCAL remain GO. ARM64 image, physical camera, DEVICE, and FIELD acceptance remain outside this UI review.
- 결정: D-292.

## 2026-09-26 · uncommitted · feat(hmi): document typography and interaction specimens (D-294)

- 변경: 스타일가이드에 공용 제목·라벨·값, 키보드 포커스, 비활성 버튼을 추가하고 닫힌 타이포그래피/상호작용 토큰을 연결했다.
- 증거: browser-enabled dashboard suite 포함 전체 HMI 100 passed; dashboard API route/manifest 29 passed. Visible Chromium에서 스타일가이드와 실제 operator/admin 화면을 desktop/mobile로 확인했다.
- gate 변화: 없음. ARTIFACT는 설치 이미지 증거가 없어 HOLD이며, 브라우저 검토는 DEVICE/FIELD 수용을 대신하지 않는다.
- 결정: D-294.

## 2026-09-27 · 6ce05ff1 · test(dashboard): verify D-294 browser and asset contracts

- 변경: D-294 스타일가이드와 화면 수용 결과를 기록했다.
- 증거: HMI browser-enabled suite 100 passed, dashboard API route/manifest 29 passed. Visible CORE Chromium reviewed styleguide, console/setup/device at desktop and mobile widths; 0 page errors and 0 positive horizontal overflow.
- gate 변화: SOURCE/LOCAL remain GO. Dashboard ARTIFACT remains HOLD pending image installation evidence.

## 2026-09-27 · uncommitted · name role surfaces
- Change: role surfaces have a focusable main landmark, skip link, H1 and panel H2 headings.
- Evidence: role surface keyboard browser regression passed; full UI/Fleet run had 661 passes, 5 skips and one Fleet keyboard focus failure resolved separately.
- Gate: SOURCE/LOCAL only; robot display acceptance remains unverified.
- Follow-up: the complete Fleet Chromium suite passed (15 tests); no further role-surface code changed.

## 2026-09-27 · uncommitted · D-300 surface typography and focus tokens
- 변경: dashboard의 반복 폰트 가중치, 행간, 자간 및 1px/2px 키보드 포커스 링을 공유 토큰에 연결했다. 1.35/1.45/1.55 고유 읽기 행간과 map canvas 3px 포커스 간격은 그대로 뒀다.
- 증거: browser-enabled HMI 전체 102 passed; 표면 계약 40 passed.
- gate 변화: SOURCE/LOCAL 유지. 이미지 설치·장치·필드 수용을 주장하지 않음.
- 결정: D-300.

## 2026-09-27 · 9049bd37 · test(dashboard): verify D-300 after latest-main integration
- 변경: 최신 main 통합 뒤 dashboard typography/focus 소비 계약을 재검증했다.
- 증거: browser-enabled HMI 전체 102 passed; D-300 표면 계약 40 passed.
- gate 변화: SOURCE/LOCAL 유지. 장치·필드 수용을 주장하지 않음.
- 결정: D-300.

## 2026-09-27 · f4f15776 · verify dashboard surface tokens after latest main integration
- 변경: latest main 통합을 확인했다. dashboard 코드는 변경되지 않았다.
- 증거: HMI web 77 passed; browser-enabled HMI의 이전 검증은 102 passed.
- Gate: SOURCE/LOCAL remain GO; device and field acceptance are separate.
- Decision: D-300.

## 2026-09-27 · 9ca7bc26 · inspect dashboard in visible Chromium
- 변경: latest main의 skip-link와 포커스 변경을 실제 브라우저에서 확인했다.
- 증거: 1366×900 visible Chromium에서 `/dashboard` 표시, 첫 Tab이 skip-link에 도달; page error 0, scroll width 1366. screenshot: X:\DevTemp\rosy-surface-d300-visible-dashboard.png.
- gate 변화: SOURCE/LOCAL 유지. API는 test fixture mock이며 실물 장치 확인은 아니다.
- 결정: D-300.
## 2026-09-27 · uncommitted · fix(ui): clarify role-screen spatial and procedure layouts

- 변경: 카메라를 상태 열로 옮기고 지도 관측 영역의 잘림을 없앴다. 절차 화면은 패널 래퍼로 그룹을 구분하고 모바일 입력의 6px 넘침을 수정했다. 조작 탭은 선택된 하나만 Tab 순서에 남긴다.
- 증거: HMI web/dashboard Chromium 포함 102 passed, 실제 CORE 절차 4셀 및 운용 역할/폭 1시험 통과. 캡처와 한계는 `docs/validation/uiux-surfaces-2026-09-27/README.md`.
- gate 변화: SOURCE/LOCAL 근거 보강. ARTIFACT·DEVICE·FIELD 승격 없음.

## 2026-09-27 · 804dda61 · fix(console): bound supervised web motion

- Change: limit forward/reverse to 0.03 m/s and one hold to 3 seconds. Require a confirmed motor or hardware runtime for teleop, and hardware runtime for map goals.
- Local evidence: browser panel suite 13 passed; dashboard package and mapping contracts 13 passed on main. The prior web-drive worktree recorded a Pinky motor-mode observation and no device deployment; that observation was not repeated during this integration.
- Gate: SOURCE/LOCAL only. Device motion and field acceptance remain unverified.

## 2026-09-27 · uncommitted · fix(device): keep Host Agent action results visible

- 변경: `/device`의 네트워크 프로파일 적용과 릴리스 복귀가 거부·성공 뒤에도 결과를 숨기던 상태 처리를 수정했다. 요청 중과 결과의 의미 상태를 조작 옆에 표시하고 Host Agent 연결이 사라지면 과거 성공 문구를 가린다. API·권한·네이티브 확인 경로는 유지했다.
- 근거: Playwright에서 거부 문구 숨김을 먼저 재현한 뒤 수정했다. 집중 브라우저 3 passed. 전체 dashboard/역할 회귀는 45 passed, 1 failed. 실패는 기존 `test_action_groups_browser.py::test_group_switch_sends_terminal_zero_before_unmount_and_never_resumes_motion`의 fixture가 현재 teleop 자격에 필요한 `/api/v1/host/commissioning` 응답을 누락한 것으로 단독 재현된다.
- gate 변화: SOURCE는 기존 회귀 실패 때문에 HOLD로 기록한다. LOCAL은 브라우저 fixture의 결과 표시만 확인했으며, `/setup`·`/device` 전체 G2/G3·실장치 수용은 아직 없다.

## 2026-09-27 · uncommitted · test(ui): align action-group fixture with teleop eligibility

- 변경: 기존 조작 그룹 브라우저 fixture의 `/api/v1/host/commissioning` 응답에 `motor` 실행 모드를 제공한다. 실제 teleop 자격·속도·정지 코드는 변경하지 않았다.
- 증거: 수정 전 단독 시험이 양의 `/api/v1/teleop` 호출을 기다리다 30초 timeout으로 실패했다. fixture 정렬 후 해당 파일 6 passed, dashboard + 역할 브라우저 확장 회귀 46 passed (Windows Chromium).
- gate 변화: 앞선 SOURCE HOLD의 유일한 재현 실패를 닫아 SOURCE GO를 복원했다. `/setup`·`/device` G2 전체 상태·G3·장치/현장 증거는 여전히 미완료다.

## 2026-09-27 · uncommitted · fix(device): keep Host Agent actions locked during request

- 변경: 네트워크·릴리스 작업 중 상태 조회가 도착해도 해당 절차의 모든 버튼을 비활성화하고 두 번째 POST를 막는다. 요청 완료 시 현재 Host Agent 상태로 버튼을 다시 판단한다.
- 근거: 지연된 POST 중 새 GET과 두 번째 클릭으로 2 POST를 재현했고 수정 후 브라우저 시험 2 passed. 역할 G2 FastAPI+Chromium 매트릭스 56셀은 오류·가로 넘침 0건이다.
- gate 변화: SOURCE/LOCAL 근거 보강. Host Agent 적용·롤백 readback과 G3 사람 판단, DEVICE/FIELD는 HOLD다.

## 2026-09-27 · uncommitted · test(roles): capture first boot before API responses

- 변경: 인증된 `/setup`·`/device`가 첫 CORE 상태 응답 전 `안전 상태 확인 중`을 표시한다. 인증 전에는 안전 문구와 역할 패널을 표시하지 않는다.
- 근거: 실제 FastAPI 정적 화면과 Chromium에서 매니페스트·상태 fetch를 보류한 첫 기동 6셀 및 기존 56셀 매트릭스 2 passed. 6셀은 패널 0개, 가로 넘침·pageerror 0건, E-stop 가시성을 확인했다.
- gate 변화: 역할 화면 첫 기동 LOCAL G2 근거를 추가했다. 실제 안전 상태와 물리 정지는 판정하지 않았다.

## 2026-09-27 · uncommitted · feat(device): display Host Agent source evidence

- 변경: `/device` 네트워크·릴리스 카드가 CORE의 원본 조회 증거와 나이를 표시하고 fresh 외에는 작업을 막는다. 브라우저는 자체 시각으로 상태를 판정하지 않는다.
- 근거: 서버 증거 4상태 브라우저 시험과 역할 G2 60셀(오류·가로 넘침 0건). Host Agent 실물은 이 화면 회차에서 사용하지 않았다.
- gate 변화: LOCAL 증거 상태 범위를 확대했다. 실제 장치 적용·재연결과 G3 사람 평가는 HOLD다.

## 2026-09-27 · uncommitted · fix(teleop): align grounded G4 controls

- 변경: 두 수동 운전 화면에서 바퀴 들기 확인 문구를 제거하고 현장 확인 문구를 표시한다. 버튼 속도는 선속도 0.03 m/s·각속도 0.10 rad/s, 홀드는 최대 2초로 맞췄다.
- 검증: Chromium에서 새 패널의 문구·버튼 값과 그룹 전환 정지 명령을 확인하고, 레거시 화면의 명령 값을 계약 시험으로 확인한다.
- gate 변화: 화면 SOURCE/LOCAL 구현 근거를 보완했다. 설치 로봇 화면과 물리 이동 결과는 별도다.

## 2026-09-27 · uncommitted · fix(setup): reuse dock type after detector selection

- 변경: `/setup`에서 기존 도크 유형을 선택하면 새 유형의 검출기·태그 필드를 실제로 숨기고 그 값으로 기존 유형의 등록을 막지 않는다. 새 유형으로 돌아오면 입력값은 유지한다.
- 근거: 실제 FastAPI 정적 화면 + Chromium에서 새 유형의 태그 관측 선택 → 기존 유형 선택 → 숨긴 필드 비우기 → 도크 등록 1건과 유형 생성 0건을 확인했다. 도크 흐름·첫 기동 집중 브라우저 2 passed, dashboard/shared controls 24 passed.
- gate 변화: LOCAL 작업 흐름 결함을 닫았다. 운영자/관리자 G3 사람 평가와 장치 등록 결과는 HOLD다.

## 2026-09-27 · uncommitted · fix(device): clear stale Host Agent readouts after read failure

- 변경: `/device` 네트워크·릴리스 상태가 뒤이은 권한 거부·읽기 오류·증거 없음으로 바뀌면 이전 SSID·릴리스 값과 세부/복구 문구를 비우고 확인 불가·다음 행동을 표시한다. 다음 정상 조회가 오면 새 값을 다시 표시한다.
- 근거: 실제 FastAPI+Chromium에서 정상→403→정상 전이를 재현하고, Host 카드 브라우저에서 503·403·원본 증거 없음의 값·조작 잠금 상태를 확인했다. 집중 브라우저 4 passed, dashboard/Host 계약 62 passed.
- gate 변화: LOCAL에서 이전 값을 현재 readback으로 오인하는 결함을 닫았다. Host Agent 실물 재연결과 G3 사람 평가, DEVICE/FIELD는 HOLD다.

## 2026-09-28 · uncommitted · fix(device): bring current state and next action into view

- 변경: `/device`의 호스트 신원·기능·런타임은 항상 보이는 짧은 요약과 접을 수 있는 세부 정보로 나눈다. 네트워크·릴리스·커미셔닝은 핵심 조회값과 증거를 먼저, 조작과 요청 결과를 다음에, 전체 readout을 펼침 영역에 둔다. 패널의 DOM·초점 순서, 매니페스트 순서, 권한/API 경계는 유지한다.
- 근거: 실제 FastAPI+Chromium 관리자 1366×768·390×844 전후 캡처 `X:\DevTemp\rosy-role-visual-flow\`에서 모바일 `/device` Host 작업 시작 y=2395→508px, 문서 높이 6661→3346px, 두 뷰포트 가로 넘침·pageerror 0. 핵심 요약·조작 위치·초점 표시와 운영자 `/device` 권한 제한을 브라우저에서 확인했다. Host/역할 집중 5건 각각 통과, dashboard/레이아웃/Host 계약 62 passed·6 skipped. Impeccable layout detect `[]`.
- gate 변화: LOCAL 시각 위계 결함을 보완했다. 실제 Host Agent readback·장치 결과와 D-153 G3 사람 평가는 HOLD다.

## 2026-09-28 · uncommitted · fix(teleop): remove repeated confirmation gate

- 변경: 기존 `/dashboard`와 새 `/console` 수동 운전에서 반복 확인 체크박스를 제거했다. 인증·MANUAL·E-Stop·최신 상태·runtime capability와 홀드/0 명령 전송은 유지한다.
- 검증: 새 패널의 그룹 전환 0 명령, 레거시 홀드/해제 0 명령 브라우저 시험을 실행한다.
- gate 변화: LOCAL 조작 단계만 줄였다. 장치 적용과 물리 이동은 별도다.

## 2026-09-28 · uncommitted · fix(setup): keep dock registration blockers next to the action

- 변경: `/setup` 도크 등록 버튼이 비활성인 동안 위치 freshness와 도크 유형 조회의 차단 이유를 버튼 가까이에 표시한다. 조회 오류와 등록/삭제 결과를 각각 분리해 주기 상태 갱신이 덮지 않게 한다. 도크 등록 후 입력 검증 실패는 해당 입력으로 초점을 돌리고, 필수 입력을 브라우저 의미 구조에도 표시한다. 입력을 미리 준비하는 동작과 서버 권한·위치 유효성 규칙은 바꾸지 않았다.
- 정적 확인: 기존 역할 매트릭스의 차단 문구·등록 성공 조회 경로와 대조, `git diff --check`, Impeccable detector `[]`. 이 변경 후 브라우저 회귀 및 새 뷰포트 캡처는 실행하지 않았다.
- gate 변화: 수정 후 SOURCE/LOCAL은 재검증 전 HOLD. 이전 실물 Host Agent·도크 위치 판정은 계속 DEVICE/FIELD HOLD다.

## 2026-09-28 · uncommitted · fix(setup): hide stale dock actions when inventory cannot be read

- 변경: `/setup` 운영·관리자 도크 목록 GET 실패 시 이전 목록 행과 현재 위치 기록·삭제 조작을 지운다. 응답을 다시 받기 전까지 빈 목록으로 오인하지 않도록 목록을 숨기고, 조회 오류를 별도 상태에 남긴다. 위치 기록·삭제 요청 중에는 1초/10초 목록 재렌더가 버튼을 다시 활성화하지 않도록 항목별 잠금을 유지한다.
- 정적 확인: 두 패널의 비동기 목록·조작 렌더 경로를 검토했고 `git diff --check`, Impeccable detector `[]`. 이 변경 후 브라우저 회귀 및 새 뷰포트 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 재검증 전 HOLD. 서버 쓰기 계약이나 실제 도크 위치 readback을 검증하지 않았다.

## 2026-09-28 · uncommitted · fix(setup): hide stale waypoints when inventory read fails

- 변경: `/setup` 웨이포인트 목록 조회가 실패하면 기존 좌표를 DOM에서 지우고 목록을 숨긴다. 조회 오류·현재 위치 준비 상태·저장 요청 결과를 각각 별도 상태 문구로 분리해 폴링이 다른 결과를 덮지 않게 했다. 목록은 다시 정상 응답을 받은 뒤에만 표시한다.
- 정적 확인: 성공/실패 렌더 전이를 코드에서 검토했고 `git diff --check`와 Impeccable detector(`[]`)를 통과했다. 이 변경에 대한 브라우저 회귀 및 새 뷰포트 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. API의 영속성·로봇의 실제 위치는 검증하지 않았다.

## 2026-09-28 · uncommitted · fix(setup): preserve localization action state during polling

- 변경: `/setup` localization 패널에서 capability readback과 초기 위치/SLAM 요청 결과를 별도 상태로 보여준다. 10초 기능 폴링이 진행 중인 위치·SLAM 요청 버튼을 다시 활성화하지 않도록 pending 잠금을 적용하고, 반복 요청을 막는다.
- 정적 확인: capability 성공/실패와 요청 진행/접수/오류 상태 경로를 검토했고 `git diff --check`, Impeccable detector(`[]`)를 통과했다. 브라우저 회귀 및 새 뷰포트 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. SLAM 서버 동작과 초기 위치의 로봇 readback은 검증하지 않았다.

## 2026-09-28 · uncommitted · fix(docs): validate dashboard source hold record

- 변경: package progress의 YAML 날짜 형식을 계약에 맞추고, dashboard SOURCE HOLD blocker를 최신 도크·웨이포인트·위치 설정 변경에 맞춰 구체화했다. 기존 작업 로그 본문은 보존한다.
- 증거: network/harness 계약 시험 77 passed; harness lint 0 errors, 기존 메타데이터 warning 19건. 도크·웨이포인트 브라우저 회귀와 새 화면 캡처는 이 변경에서 실행하지 않았다.
- gate 변화: SOURCE와 LOCAL은 계속 HOLD이며, browser 회귀와 관리자 화면 readback이 다음 출구다. ARTIFACT는 별도 이미지 검증 전 HOLD다.

## 2026-09-28 · uncommitted · fix(device): keep security and safety feedback distinct

- 변경: 관리자 `/device` 보안 패널에서 토큰 목록 오류, 토큰 생성/삭제 결과, 일회성 토큰 비밀값, 안전 정책 조회, 안전 정책 저장 결과를 별도 상태 영역으로 분리했다. 토큰 목록 조회가 실패하면 이전 행을 숨기고, 새 토큰 비밀값은 목록 재조회 오류나 안전 정책 폴링으로 사라지지 않게 한다. 안전 정책 폴링은 편집 중인 값을 보존하며 저장 요청 중에는 입력을 잠근다. 저장 응답의 현재값은 화면에 다시 반영한다.
- 정적 확인: 토큰 POST/GET/DELETE와 안전 정책 GET/PUT의 상태 경로를 코드 및 API 응답 계약에서 대조했다. `git diff --check`를 통과했고 Impeccable detector는 `[]`였다. 관리자 브라우저 회귀와 새 `/device` 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. 토큰 실사용·안전정책 런타임 readback 및 DEVICE/FIELD는 별도다.

## 2026-09-28 · uncommitted · test(dashboard): verify setup browser gates

- 변경: 도크·웨이포인트·위치 설정 회귀에서 여러 상태 안내가 함께 존재하는 구조에 맞춰 브라우저 검증 선택자를 상태 문구로 좁혔다. 저속 teleop 회귀도 제거된 확인 체크박스 대신 활성 조건을 만족한 실제 명령 버튼과 놓기/시간 제한 정지를 확인하도록 맞췄다.
- 증거: 지정 브라우저 회귀 54 passed (325.94초). 별도 FastAPI TestClient/Chromium 캡처에서 관리자 `/setup` 데스크톱 1366×768 및 모바일 390×844을 확인했다. `pageErrors=[]`, `overflowX=0`, 첫 페이지/API 응답 200; 캡처는 `X:\DevTemp\rosy-dashboard-browser-validation\administrator-setup-1366x768.png` 및 `administrator-setup-390x844.png`에 있다. Network/harness 계약 시험 77 passed; harness lint 0 errors, 기존 상태/변경 이력 warning 19건.
- gate 변화: 당시 변경 기준 SOURCE/LOCAL GO. 캡처와 API는 로컬 fixture evidence이며 실제 설치 이미지, 로봇 장치, 현장 수용을 대체하지 않는다. ARTIFACT HOLD 유지.

## 2026-09-28 · uncommitted · test(dashboard): verify latest security feedback

- 변경: main의 관리자 `/device` 보안·안전 피드백 보존 변경(6b0aaaa7)을 포함한 현재 화면/역할 회귀를 다시 실행했다.
- 증거: 지정 브라우저 회귀 54 passed (240.87초). 최신 checkout에서 관리자 `/setup` 캡처를 1366×768 및 390×844로 다시 생성했다. `pageErrors=[]`, 두 화면 `overflowX=0`, 첫 페이지/API 응답 200. 캡처는 `X:\DevTemp\rosy-dashboard-browser-validation\administrator-setup-1366x768.png` 및 `administrator-setup-390x844.png`에 있다.
- gate 변화: 최신 checkout 기준 SOURCE/LOCAL GO. 이는 fixture 기반 로컬 UI evidence다. ARTIFACT, 실제 장치 readback, 현장 수용은 별도 HOLD다.


## 2026-09-28 - uiux/mobile-acceptance - test: verify localization pending action state

- Change: Added panel regression for capability polling during pending initial-pose and SLAM-start actions, including lock and duplicate-POST checks. Refreshed administrator `/setup` full-shell captures at 1366x768 and 390x844.
- Evidence: Panel Chromium suite 14 passed. Role G2 5 passed; 60 cells, overflow 0, pageerror 0, E-stop visible 60/60, canceled confirmation POST 0. Screenshots and matrix JSON are in `X:\DevTemp\rosy-uiux-d306-roles-g2\`. `git diff --check` passed.
- Gate: SOURCE/LOCAL browser regression and captures checked for `b3d8e6cd`. Actual pose/SLAM readback, physical E-stop, G3, D-153, D-255, DEVICE/FIELD remain HOLD.


## 2026-09-28 - uiux/device-security-feedback-evidence - fix: clear stale token list after mutation refresh failure

- Change: Token list reload failures after successful token create/delete now use the shared unavailable handler, clearing and hiding the old inventory while keeping create/delete outcome and the one-time secret in separate status regions. Added regression for token polling, mutation refresh, safety polling, dirty form preservation, save locking, and CORE PUT response values.
- Evidence: Focused security regression 1 passed; full panel Chromium suite 15 passed. Current-main G2 5 passed, 60 cells, overflow/pageerror 0, E-stop visible 60/60, confirmation-cancel POST 0. Admin `/device` captures at 1366x768 and 390x844 are in `X:\DevTemp\rosy-uiux-d306-roles-g2\`. Impeccable `[]`; `git diff --check` passed.
- Gate: SOURCE/LOCAL follow-up verified. Actual Host Agent, physical safety readback/E-stop, G3 and broader D-153 DEVICE/FIELD remain HOLD.
## 2026-09-28 · uncommitted · fix(device): separate host capability and inventory readback

- 변경: 관리자 `/device` 시스템 패널에서 CORE capability 요약과 상세 인벤토리 조회 상태를 따로 표시한다. 한 조회의 성공/실패가 다른 조회 상태를 덮지 않게 하고, capability·인벤토리·호스트 런타임·로봇 신원 조회가 실패하면 해당 영역의 이전 값을 지워 현재값으로 오인하지 않게 한다.
- 정적 확인: 런타임·신원·capability·inventory GET 성공/실패 경로를 검토했고 `git diff --check`, Impeccable detector(`[]`)를 통과했다. 브라우저 회귀와 새 관리자 `/device` 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. 실제 Host Agent 및 장치 readback은 별도다.
## 2026-09-28 · uncommitted · fix(console): keep mode request feedback visible

- 변경: `/console` 운전 모드의 현재 readback, Navigation capability, 모드 변경 결과를 각각 표시한다. 1초 모드 폴링이 요청 접수/오류를 덮지 않으며 capability 조회 결과도 별도 영역에서 확인한다. 모드 요청 문구는 접수와 실제 현재 모드 readback을 구분한다.
- 정적 확인: 상태·capability 폴링과 모드 POST의 화면 갱신 경로를 검토했고 `git diff --check`, Impeccable detector(`[]`)를 통과했다. 브라우저 회귀 및 새 `/console` 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. 로봇의 실제 모드 전환은 별도다.
## 2026-09-28 · uncommitted · fix(console): separate teleop readiness and action feedback

- 변경: `/console` 수동 운전에서 readiness 설명과 주행/정지 결과를 분리했다. state·capability·safety·commissioning 조회 실패 원인을 readiness 영역에 유지하고, 성공 readback이 복구되면 갱신한다. 상태 폴링이 2초 제한 정지·연결 끊김 정지·명령 전송 결과를 덮지 않는다.
- 정적 확인: 홀드 시작/정지 및 네 상태 조회 성공·실패의 UI 갱신 경로를 검토했고 `git diff --check`, Impeccable detector(`[]`)를 통과했다. 브라우저 회귀와 새 `/console` 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. 실제 장치 이동과 안전 readback은 별도다.
## 2026-09-28 · uncommitted · fix(console): fail closed on stale lane-follow state

- 변경: `/console` 차선 추종에서 상태 조회 오류 시 이전 모드 정보를 지우고 시작·중지 조작을 잠근다. 현재 모드 readback, Navigation capability, 요청 결과를 나눠 폴링이 조작 결과를 덮지 않게 했다. 요청 접수는 실제 추종 시작/중지 readback과 구분한다.
- 정적 확인: 상태·capability 조회와 모드 변경의 오류·복구 경로를 검토하고 `git diff --check`, Impeccable detector를 실행한다. 브라우저 회귀 및 새 `/console` 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. 실제 라인 추종·센서 동작은 별도다.

## 2026-09-28 · uncommitted · fix(console): keep docking actions locked through readback polls

- 변경: `/console` 도킹 상태, 도크 목록, 명령 결과를 독립 표시한다. 도킹 상태 GET 실패 시 이전 상태를 지우고 명령을 잠근다. 요청 중에는 1초 readback 폴링이 버튼을 다시 활성화하지 않으며, 도크 목록 갱신은 사용자가 고른 위치를 유지한다.
- 정적 확인: docking status/list/command의 pending·실패·복구 UI 경로를 검토하고 `git diff --check`, Impeccable detector를 실행한다. 브라우저 회귀 및 새 `/console` 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. 실제 도킹 장치 readback은 별도다.
## 2026-09-28 · uncommitted · fix(console): separate map readback and action outcomes

- 변경: `/console` 지도에서 로봇 상태·Navigation·실행 모드 조회는 독립 readiness 상태로 표시하고, map-status는 지도 데이터 freshness만 담당한다. 상태 폴링 오류가 지도 조회 문구를 덮지 않는다. 초기 자세·주행 목표 요청의 접수/실패는 별도 action status에 남아 지도 주기 갱신에 의해 지워지지 않는다.
- 정적 확인: map helper의 지도 조회·action 경로와 세 상태 poll 성공/실패 UI를 검토했고 `git diff --check`, Impeccable detector(`[]`)를 통과했다. 브라우저 회귀 및 새 `/console` 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. 실제 위치·경로·주행 적용은 별도다.

## 2026-09-28 · uncommitted · fix(device): separate board refresh result from hardware readback

- 변경: 보드 장치 패널의 측정 상태 안내와 관리자 점검 요청 결과를 별도 live status로 분리했다. 주기적 GET 성공·실패가 POST의 pending·accepted·error 결과를 덮지 않는다. 접수 문구는 점검 완료를 주장하지 않고 마지막 측정 시각과 장치 상태에서 확인하도록 안내한다.
- 정적 확인: 변경 영역 코드 검토와 `git diff --check`를 실행했다. 브라우저 회귀, Impeccable detector, 새 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. 실제 Host Agent 점검 결과와 장치 readback은 별도다.
