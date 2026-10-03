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

## 2026-09-28 · uncommitted · fix(device): prevent duplicate identity editors on polling

- 변경: 관리자 로봇 표시 이름 폼을 초기 구성 때 한 번만 만든다. 기존 폴링은 `<dl>`을 갱신했지만 그 `<dl>`에서 폼 존재를 찾았기 때문에 30초마다 중복 폼을 추가했다. 이제 편집 초안이 유지되고 저장 중 입력·버튼을 잠그며, 요청 접수는 다음 신원 조회의 실제 반영과 구분한다.
- 정적 확인: 변경 영역 코드 검토와 `git diff --check`를 실행한다. 브라우저 회귀, Impeccable detector, 새 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. 실제 기기 신원 readback은 별도다.

## 2026-09-28 · uncommitted · fix(device): explain hardware refresh role restriction

- 변경: 관리자 전용 보드 점검 버튼을 비관리자 화면에서 비활성화할 때 권한 사유를 함께 보여주고, 버튼의 `aria-describedby` 설명으로 연결한다. 관리자에게는 조작 결과 status가 있을 때만 해당 영역을 표시한다.
- 정적 확인: 변경 영역 코드 검토와 `git diff --check`를 실행한다. 브라우저 회귀, Impeccable detector, 새 캡처는 실행하지 않았다.
- gate 변화: SOURCE/LOCAL은 회귀·화면 재확인 전 HOLD. 실물 Host Agent 점검은 별도다.

## 2026-09-28 - uiux/host-console-readback-evidence - verify independent readbacks and mode feedback

- Change verified: `/device` runtime, robot identity, CORE capability, and detailed inventory readbacks fail independently and clear only their own stale values. `/console` current-mode readback, Navigation capability, and mode POST outcome remain separate while polling continues; CORE acceptance is not presented as proof that the robot already changed mode.
- Evidence: Focused host and mode panel browser regressions passed; the full panel Chromium suite passed 17 tests. Role G2 passed 6 tests and refreshed 60 cells with overflow 0, pageerror 0, and E-stop visible 60/60. Full-shell `/console` mode feedback captures at 1366x768 and 390x844 each recorded one MANUAL POST, an IDLE current-mode readback at acceptance, overflow 0, no page errors, and visible E-stop. Admin `/device` normal and console captures were visually inspected. Artifacts: `X:\DevTemp\rosy-uiux-d306-roles-g2\`.
- Gate: SOURCE/LOCAL browser regression and captures verified for `a81dbcb2` and `3b89deeb`. These fixtures do not prove actual Host Agent or robot readback, physical E-stop, G3, DEVICE/FIELD, D-153, or D-255 B2/B3; those remain HOLD.

## 2026-09-28 · uncommitted · fix(device): remove unreachable hardware role hint

- 변경: G2 역할 매트릭스를 확인해 `host.hardware`가 `min_role: administrator`인 것을 대조했다. 비관리자 화면에서 버튼이 비활성이라는 조건은 실제 surface에서 도달할 수 없어 조건부 안내를 제거했다. 권한 제한은 `/device` surface entry가 담당한다.
- 정적 확인: 현재 main의 역할 G2 Chromium 매트릭스 60셀 실행에서 페이지 오류 0, 가로 넘침 0, E-stop 60/60을 확인했다. Impeccable detector(`[]`)를 실행했다.
- gate 변화: 실제 Host Agent readback·DEVICE/FIELD와 전체 D-153/G3 판정은 HOLD.

## 2026-09-28 · uncommitted · test(device): verify identity draft and hardware action feedback at two widths

- 검증: current main의 실제 FastAPI `create_app` + Chromium에 local API fixture를 붙여 1366×768·390×844에서 편집 중 identity poll을 가속했다. 각 폭에서 폼 수 1개, 2회 이상 poll 뒤 초안 유지, 이름 저장 POST, 측정 poll 이후에도 하드웨어 점검 접수 상태 유지, pageerror 0, 가로 넘침 0을 확인했다. 전체 역할 G2도 60셀 Chromium 1 passed, overflow 0, pageerror 0, E-stop 60/60이다.
- 시각 확인: desktop/mobile 전체 페이지를 직접 확인했다. PNG는 `X:\DevTemp\rosy-uiux-d306-roles-g2\admin-device-feedback-{1366x768,390x844}.png`에 일회성으로 둔다.
- 한계: API는 fixture이므로 실제 Host Agent, CORE 저장 readback, 물리 E-stop, 사람 G3 수용은 증명하지 않는다. 해당 게이트는 HOLD.

## 2026-09-28 - uiux/console-teleop-feedback-evidence - verify readiness and action feedback

- Evidence: Focused Playwright panel regressions passed 2 tests, covering four independent read failure/recovery reasons and feedback retention for hold, release, shared forced stop, two-second timeout, and failed terminal zero delivery. Full dashboard panel suite passed 19 tests. Role G2 passed 7 tests and refreshed 60 cells: overflow 0, pageerror 0, E-stop 60/60, canceled-confirmation POST 0. Full-shell `/console` screenshots at 1366x768 and 390x844 show state-read failure and preserved release/stop result simultaneously; both record a terminal zero POST and no page errors or horizontal overflow. PNG/JSON artifacts: `X:\DevTemp\rosy-uiux-d306-roles-g2\`. The full-shell fixture explicitly inserts `console.teleop` into its manifest and uses controlled API responses.
- Gate: SOURCE/LOCAL browser regression and captures verified for `1af1fa41`. Real motion/stop readback, physical E-stop, G3, and D-153 DEVICE/FIELD acceptance remain HOLD.

## 2026-09-28 - uiux/host-console-readback-evidence - verify line-follow and docking feedback

- Evidence: Focused Playwright panel regressions verified line-follow status failure clears stale facts and blocks commands until recovery, Navigation capability feedback remains independent, pending requests stay locked during polling, and CORE acceptance is distinct from mode readback. Docking regressions verified status/list failure clearing, selected-dock retention, all-action pending locks across poll refreshes, and independent action feedback. Full dashboard panel suite: 21 passed. Role G2: 8 passed, 60 cells, overflow 0, pageerror 0, E-stop visible 60/60, canceled-confirmation POST 0.
- Captures: Full-shell `/console` line-follow and docking captures at 1366x768 and 390x844. Each showed an unavailable readback beside the preserved CORE request receipt, one expected action POST, no page errors or horizontal overflow, and visible E-stop. Fixture explicitly adds these action groups to the local console manifest and controls API responses. PNGs and `console-line-follow-docking-matrix.json`: `X:\DevTemp\rosy-uiux-d306-roles-g2\line-follow-docking\`. Visually inspected.
- Gate: SOURCE/LOCAL browser verification complete for `02600b2a`. Actual line-follow/docking robot readback and motion, physical E-stop, G3, DEVICE/FIELD, D-153, and D-255 B2/B3 remain HOLD.

## 2026-09-28 - uiux/host-console-readback-evidence - verify console map feedback

- Evidence: Focused Chromium regression verified robot-state, Navigation capability, and commissioning failures stay in readiness status while map freshness is independent. Clicking a target without map data reports that nothing was sent, with no confirm and no POST. After map recovery, accepted and failed target outcomes remained visible through explicit map refresh callbacks. Full panel suite: 22 passed. Full-shell captures at 1366x768 and 390x844 showed no map, robot-state read failure, and separate no-request action result; overflow 0, pageerror 0, E-stop visible, no POST. Artifacts: `X:\DevTemp\rosy-uiux-d306-roles-g2\map-data-action\`.
- G2: Full command reported 8 passed, 1 failed in administrator `/device` `confirm_cancel` (`test_role_procedure_g2_local_matrix`, rollback button disabled). This is outside the map panel; the run did not produce a fresh complete 60-cell matrix. Dedicated map capture test passed.
- Gate: LOCAL map-panel browser regression and captures complete for `5c414c2c`. Actual map/robot readback and target application, physical E-stop, G3, DEVICE/FIELD, D-153, and D-255 B2/B3 remain HOLD.

## 2026-09-28 - uiux/host-console-readback-evidence - verify device hardware refresh feedback

- Evidence: Focused Playwright panel regression passed 1 test. A measurement poll during a pending hardware refresh POST did not replace pending feedback; later measurements did not erase the accepted request receipt; a POST error survived a measurement-read failure. Dedicated full-shell capture test passed at 1366x768 and 390x844 with overflow 0, pageerror 0, and visible E-stop. Screenshots and `admin-hardware-refresh-matrix.json`: `X:\DevTemp\rosy-uiux-d306-roles-g2\host-hardware-refresh\`; visually inspected.
- Scope: The local fixture accelerates only the relevant hardware poll and returns controlled measurement/API responses. Full G2 matrix and Impeccable detector were not rerun.
- Gate: SOURCE/LOCAL browser verification complete for `17f30137`. Actual Host Agent measurement, physical device completion, G3, DEVICE/FIELD, and D-153 acceptance remain HOLD.

## 2026-09-28 - uiux/host-console-readback-evidence - verify identity editor polling

- Evidence: Focused Playwright panel regression passed 1 test. Repeated identity readbacks kept one editor and preserved the draft. While PUT was pending, input and save control were disabled; accepted request feedback remained visible through stale readback and stayed separate from identity status. Dedicated full-shell capture test passed at 1366x768 and 390x844 with overflow 0, pageerror 0, and visible E-stop. PNG/JSON: `X:\DevTemp\rosy-uiux-d306-roles-g2\admin-device-identity-feedback\`; visually inspected.
- Scope: The fixture accelerates only the 30-second identity poll and returns controlled stale GET and accepted PUT responses. Full G2 matrix and Impeccable detector were not rerun.
- Gate: SOURCE/LOCAL browser verification complete for `df260822`. Actual Host Agent and physical identity readback, G3, DEVICE/FIELD, and broader D-153 acceptance remain HOLD.

## 2026-09-28 - uiux/device-refresh-access - check hardware permission hint reachability

- Evidence: Focused panel Chromium regression passed 1 test: admin action status was initially hidden, referenced by the refresh button `aria-describedby`, then shown after interaction. Admin full-shell capture regression passed at 1366x768 and 390x844 with accepted request result visible. Current-main operator device-entry capture regression passed at both widths: access denied, `/console` return link shown, no hardware/host-operations panel, overflow 0, no page errors. Screenshots and matrix are under `X:\DevTemp\rosy-uiux-d306-roles-g2\operator-device-entry-denied\` and `X:\DevTemp\rosy-uiux-d306-roles-g2\host-hardware-refresh\`; visually inspected.
- Finding: `b61fb526` exists in history, but later `fb2b220c` removed the conditional operator hint. Both the `/device` surface and `host.hardware` panel require administrator role, so a non-admin cannot reach that disabled button. The claimed non-admin button description is not verified and is unreachable under the current policy.
- Scope: Full G2 and Impeccable detector were not rerun.
- Gate: Admin browser interaction and actual operator access-denial path verified locally. The requested non-admin hardware-button hint remains HOLD pending a role/surface access decision. Actual Host Agent readback, G3, DEVICE/FIELD, and broader D-153 acceptance remain HOLD.

## 2026-09-28 · uncommitted · fix(dashboard): restore module harness validation

- 변경: dashboard `progress.md`의 검증 날짜를 YAML date로 기록했다. 기존 append-only `logs.md`의 병렬 세션 헤더 10개는 본문을 다시 쓰지 않고 harness의 정확한 legacy allowlist로 보존했다. 생성 index와 STATUS를 다시 만들었다.
- 증거: `python tools/harness/rosy_harness.py lint` 0 errors, 18 warnings; network topology 및 harness 계약 시험 77 passed. 별도 latest-main 역할 브라우저 행렬은 60셀 모두 overflow/pageerror 0, E-stop visible, 취소 POST 0이었다.
- gate 변화: dashboard SOURCE/LOCAL은 전체 화면·제품 수용 HOLD를 유지한다. 이 문서/기록 형식 수정은 Host Agent, 실제 장치, G3 사람 수용, DEVICE/FIELD를 승격하지 않는다.

## 2026-09-28 - uiux/device-refresh-access - rerun latest-main role G2

- First attempt on `757fb38f` stopped at administrator `/device` `confirm_cancel`: the test checked rollback enabled after panel mount, before the release readback poll completed. The fixture returns a fresh release record with previous version `r1`; rollback becomes enabled after that readback. Updated the test to wait for the actual release readiness instead of panel count.
- Rerun: `ROSY_RUN_BROWSER_TESTS=1 python -X utf8 -m pytest src/hmi/dashboard/test/test_role_g2_browser.py::test_role_procedure_g2_local_matrix -q` passed **1 test, 60 cells** in 274.59s. Matrix: overflow 0, pageerrors 0, E-stop visible 60/60. Artifact: `X:\DevTemp\rosy-uiux-d306-roles-g2\matrix.json`.
- Gate: only test synchronization changed. Local FastAPI/Chromium does not prove physical stop or Host Agent result. G3, DEVICE/FIELD, D-153 remain HOLD.

## 2026-09-29 · uncommitted · fix(dashboard): restore shared-control contracts and P1 craft round

- 변경: main에 커밋된 공유 계약 위반 3건을 복원했다 — host identity 버튼의 kind 선언 패턴(system.js), `/setup`·`/device` 패널 모듈 import 중 `ui-empty` 로딩 문구(mount.js), `/setup`·`/device` 데스크톱 main 슬롯을 row-pairing grid에서 multicol로(shell.css), action-group 탭의 균등 전폭 스트레치를 콘텐츠 폭 flex로, 접근 토큰 행의 58px 삭제 버튼이 텍스트·인접 행을 침범하지 않게 flex 배치(surface-panels.css). G2 harness가 첫 패널이 아니라 조립 완료(`#surface-status` hidden)를 기다리고 캡처한다.
- 증거: `src/hmi/dashboard/test` 43 passed, `src/hmi/web/test` 22 passed, D-283·surface 레이아웃 23 passed, `test/test_role_menu_panels_browser.py test/test_role_surface_states_browser.py` 29 passed. 역할 G2 60셀 재생성(overflow 0, pageerror 0). Impeccable detect `[]`. 회차 기록은 `docs/validation/uiux-surfaces-2026-09-29/README.md`.
- gate 변화: dashboard SOURCE/LOCAL HOLD -> GO(브라우저 회귀 + 신흘 캡처 블로커 해소). ARTIFACT은 이미지 설치 증가 없이 HOLD. D-153 표면 G3 사람 평가·DEVICE/FIELD는 별도다.

## 2026-09-29 · uncommitted · fix(dashboard): 역할 화면 브랜드를 대시보드 홈 링크로

- 변경: `surface.html` 상단 바 `ui-brand`가 일반 텍스트여서 `/console`·`/setup`·`/device`에서 ROSY 브랜드를 클릭해도 홈으로 갈 수 없었다. 대시보드 `index.html`의 홈 링크와 같은 `<a href="/dashboard" aria-label="Rosy OS 대시보드 홈">`로 감쌌고, `shell.css`에 `ui-brand a:focus-visible` 포커스 링을 더했다. 같은 텍스트와 토큰이라 화면 픽셀 변화는 없고 링크 동작만 추가된다. `/dashboard` 자신의 브랜드 링크와 Fleet·경기 보드(별도 호스트, D-275)는 대상이 아니다.
- 근거: 정적 계약 `src/hmi/dashboard/test/test_surface_home_link.py` 신설(링크·포커스 링 고정, 브라우저 클릭 1건은 게이트 변수). `python -X utf8 -m pytest src/hmi/dashboard/test/test_surface_home_link.py src/hmi/dashboard/test/test_dashboard_package.py src/hmi/dashboard/test/test_web_budgets.py src/hmi/web/test/test_palette_gates.py -q` 23 passed 1 skipped. `ROSY_RUN_BROWSER_TESTS=1`에서 `test_surface_home_link.py test_surface_entry_browser.py test_surface_layout_browser.py` 11 passed, `test/test_role_menu_panels_browser.py test/test_role_surface_states_browser.py test/test_web_dialog_contract.py src/runtime/api_web/test/test_d283_console_browser.py` 43 passed.
- gate 변화: 없음. dashboard SOURCE/LOCAL GO 유지, ARTIFACT HOLD 유지.

## 2026-09-29 · uncommitted · fix(dashboard): 예산 후보는 추적 파일만 훑는다

- 변경: `test_web_budgets.py`의 두 시험이 파일시스템 `SRC.rglob("*.js")` + `SRC.rglob("*.html")`로 후보를 모아 `.gitignore`된 `site/overhead/android/build/reports/problems/problems-report.html`(600행 초과)을 예산 초과 후보로 잡았다. `_web_files()`로 바꿔 `git ls-files -c -o --exclude-standard -- src`로 후보를 얻는다 — 추적 파일과 아직 add하지 않은 새 파일은 잡고, ignore된 빌드 산출물은 잡지 않는다. git이 없으면 skip하고 파일시스템 훑기로 대체하지 않는다. `.js`까지 보는 것이 이 스캔만의 일이므로(레지스트리 발견 스캔은 `.html` 한정) 여기에 둔다. 예산값 600/150과 `VERDICTS`는 그대로다.
- 근거: 변경 직전 `test_web_files_over_budget_have_a_recorded_verdict` 1 failed — 원인은 그 무시된 Android 빌드 산출물. 변경 후 `python -m pytest src/hmi/dashboard/test -q` 14 passed, 32 skipped. 변이 확인: add 안 된 700행 `src/hmi/dashboard/zz_mut_proof.html`을 놓으면 `needs a verdict: ['hmi/dashboard/zz_mut_proof.html']`로 빨갛고, 지우면 다시 14 passed로 복구한다.
- gate 변화: 없음. dashboard SOURCE/LOCAL GO 유지, ARTIFACT HOLD 유지.
- 결정: D-329 Decision 3 "tracked files only"를 이 예산 시험에도 적용했다. 판정 기준과 `VERDICTS`는 바꾸지 않는다.

## 2026-09-29 · uncommitted · D-335 역할 화면 브랜드 홈 링크를 공용 선언으로

- 변경: feat/surface-home-link에서 앵커를 직접 적던 `surface.html`을 `<ui-brand href="/dashboard" aria-label="Rosy OS 대시보드 홈">` 선언으로 되돌려 공용 동작(D-335)을 쓰게 했다. `shell.css`의 `ui-brand a:focus-visible`은 공용 `components.css`로 옮겨 표면 복제를 지웠다. `test_surface_home_link.py`는 표면 선언·공용 스타일 소유·Chromium 클릭(공용 ui.js 로드)을 고정한다. `/dashboard` 홈에서 역할 화면으로 가는 가시 경로(비평 P1)는 이번 회차 대상이 아니며 D-204 브리지 회차가 판다.
- 증거: 정적 97 passed 1 skipped(`src/hmi/web/test` + dashboard 계약 3종). `ROSY_RUN_BROWSER_TESTS=1`에서 `src/hmi/dashboard/test` + `test_role_menu_panels_browser.py` + `test_role_surface_states_browser.py` + `test_web_dialog_contract.py` + `test_d283_console_browser.py` 89 passed(역할 G2 60셀 재생성 포함, overflow 0·pageerror 0). harness lint 0 errors, `test_harness_contracts.py` 54 passed.
- gate 변화: 없음. dashboard SOURCE/LOCAL GO 유지, ARTIFACT HOLD 유지.

## 2026-09-29 · uncommitted · feat(dashboard): 홈 브리지가 목적지 역할 화면을 매니페스트로 말한다

- 변경: 비평 P1(2026-09-26) 회차. `/dashboard` 상단 바에 `#surface-bridge`를 두고, 인증된 호출자의 목적지를 console 매니페스트의 `surfaces` 메타데이터로 그린다 — 역할 화면 스위치와 같은 단일 출처고 서버가 역할으로 걸러 준다(viewer는 /console 1개). `surface-navigation.js`의 `dashboardSurfaceBridge(nav, surfaces)`가 등록된 역할 표면만 남겨 그리고, 목록이 비면 숨긴다. `app.js`는 whoami 뒤에 목록을 채우고 신원이 없으면(로그아웃·만료) 비운다. 모바일(≤720px, console height:auto 구간)에서만 상단 바 묶음 줄바꿈을 허용해 데스크톱 뷰 계약(D-201, .console 토큰 높이)은 그대로다. 새 토큰·ui-* 부품·문법 없음 — D-335의 다음 회차로서 ADR 없이 진행했다.
- 증거: 정적 `src/hmi/dashboard/test/test_surface_bridge.py` 신설(선언·빌더·배선·스타일 고정, 뮤테이션 3종 붉게 확인 후 복원) + `src/hmi/web/test` 99 passed 2 skipped. `ROSY_RUN_BROWSER_TESTS=1`로 `src/hmi/dashboard/test` + `test_dashboard_browser.py`(통합 신설 2건: 관리자 3링크/뷰어 1링크 + 클릭 이동) + 역할 메뉴/표면 + 다이얼로그 + D-283 165 passed. UI/UX 실측(X:\DevTemp\bridge-destination\uiux\, probe.json): 1366×768·390×844 가로 overflow 0, 링크 높이 44px = 터치 바닥, 상단 바 위 대비 6.95:1, Tab 5번에 브리지 도달 + 2px 포커스 링, hover 색·배경 변화, E-stop 양 폭 보임.
- gate 변화: 없음. dashboard SOURCE/LOCAL GO 유지, ARTIFACT HOLD 유지. 역할 화면으로의 가시 경로는 이제 홈에서 열렸고, /dashboard 조작 중복의 퇴역 기준은 D-204 이행 회차가 판다.

## 2026-09-29 · uncommitted · feat(dashboard): 교통 정책 팩트에 신호 원 행

- 변경: `/setup` 교통 정책 패어널과 `/console` 교통 팩트에 "신호 원" 행을 추가했다 — `TrafficPolicyStatus.signal_source_kind`(v1.56, D-337)를 그대로 보여 주고 관측 프레임 동결(`signal_head_frozen`) 시 `frozen`으로 표기한다. 운영자가 관측 소스 바인딩을 켠 사이트에서 fused 강등·동결이 화면에 드러난다. 새 토큰·ui-* 부품·문법 없음.
- 증거: `src/hmi/dashboard/test` + `src/runtime/api_web/test` + `test_dashboard.py` 116 passed 47 skipped(2026-09-29 Windows). D-283 배치 시험(facts 2열·폼 위치) 행 추가 후에도 통과.
- gate 변화: 없음. 실화면 확인은 T5 벤치 회차가 함께 한다.

## 2026-09-29 · uncommitted · feat(dashboard): 교통 정책 패어널에 정지선 규칙 편집·표시

- 변경: `/setup` 교통 정책 패어널에 `junction_rule` select(신호 제어 / 무신호: 정지 후 진입)를 스테이징 폼에 추가하고 상태 facts에 "정지선 규칙" 행을, `/console` 교통 facts에 "규칙" 행을 각각 추가했다. 새 토큰·ui-* 부품 없음 — 기존 `select`·facts 문법 재사용. 기본값 `signal_controlled` 표기로 규칙 미선언 상태가 지금과 같음을 화면에서 읽을 수 있다.
- 증거: 정적 스캔 `src/hmi/dashboard/test` + `src/hmi/web/test` + api_web 105 passed 47 skipped(2026-09-29 Windows, 브라우저 게이트 시험은 스킵 — ROSY_RUN_BROWSER_TESTS 미설정). 패어널 배치 시험(D-283 facts 2열·폼 위치)은 행 추가 후에도 그대로 통과했다.
- gate 변화: 없음. 무신호 `stop_and_go`의 실화면 확인은 브라우저 회차가 남아 있다.

## 2026-09-30 · ff6938e4 · D-359 US-002 /device 화면 테마 패널과 테마 로드

- 변경: `index.html`·`surface.html`·`styleguide.html`이 tokens.css 바로 뒤에 `/common/theme.js`를 싣는다. `/device`에 `system.display` 패널(화면 테마: 어둡게/밝게/시스템, 공용 segment 버튼, 이 브라우저에만 저장)을 order 110(맨 뒤)으로 더했다 — 좁은 화면에서 상태·조치가 먼저 보이게. `styles.css`·`surface-panels.css`의 `color-scheme` 선언을 지웠다(테마 블록의 몫). 위험 채움 위 글자 `--ink` 세 곳을 `--ink-on-crit`로 바꿨다(밝게에서 짙은 글자가 짙은 적색 위에 사라짐).
- 증거: `python -m pytest src/hmi/dashboard/test src/site/fleet/test src/site/games/test -q` 876 passed 39 skipped. 1366×768 밝게 캡처(`X:/DevTemp/rosy-d359/shots`)에서 /console·/device 글자 가독 확인.
- gate 변화: 없음.

## 2026-09-30 · 089bdb69 · D-359 US-003 로봇 지도·카메라 오버레이가 RosyPalette로 색을 읽는다

- 변경: `map.js`의 hex 전용 `readToken`·`paletteCache`를 지우고 `window.RosyPalette.readPalette`를 쓴다(래스터 한 장에 표 한 번). `rosy:theme`이면 새로 고침 없이 `rebuildRaster()`·`paint()`. `camera-capture.js` 오버레이는 `cssColor`와 `canvasFont(…, "body")`(sans-serif·직접 getPropertyValue 제거) — 녹화 중 프레임마다 다시 그리므로 따로 듣지 않는다. 시험 하네스(`test_map_readout_browser.py`, `test/test_camera_capture_browser.py`, Node 스텁 `test_camera_capture.py`)가 실제 셸처럼 ui.js/RosyPalette를 먼저 싣는다.
- 증거: `python -m pytest src/hmi/web_common/test src/hmi/dashboard/test src/site/fleet/test src/site/games/test src/runtime/sensing/test -q` 2674 passed 129 skipped 1 failed — 실패는 Node 스텁이 RosyPalette를 몰라서였고 스텁을 고친 뒤(2aaae787) `test_camera_capture.py` 5 passed. 브라우저(`ROSY_RUN_BROWSER_TESTS=1`) `src/hmi/dashboard/test` 51 passed + 같은 Node 1건, `test/test_camera_capture_browser.py`·`test_role_menu_panels_browser.py` 통과.
- gate 변화: 없음.

## 2026-09-30 · 1cea0fe5 · D-359 US-004 로봇 표면 필드·태그·사유·눌림이 공용 부품을 쓴다

- 변경: `/dashboard`와 역할 패널의 입력·선택 전부 `class="ui-field"`(패널은 `el("input", "ui-field")`), 로그인 유지 체크는 `label.ui-check`. `styles.css` 필드 사본(auth/settings/host/traffic-policy)과 `surface-panels.css`의 `.surface-slot` 필드 사본을 지웠다. `.status-badge/.machine-tag/.mode-chip`과 `[data-status]`·`.mode-chip[data-mode]` 색 규칙을 지우고 `<ui-tag>`로 바꿨다 — `dom.js` `tagStatus`/`setTagState`가 OK·SITE_STA 등 → active, WARNING·AP 계열 → warn, ERROR·UNAVAILABLE·HOLD 계열 → crit(채움)로 옮긴다. 모드 버튼은 `title` 대신 `reason`(app.js, panels/console/mode.js), `[data-mode]` 선택자를 `ui-button[data-mode]`로 좁혀 태그가 모드 버튼 클릭 처리를 받지 않게 했다. teleop·모드·라인 모드 눌림은 `aria-pressed`, `surface-panels.css`의 teleop `outline` 덧칠 삭제. 자간 리터럴 10곳 → 토큰/0, 불투명도 0.9/0.42/0.72 → 삭제·`--ink-quiet`. styleguide에 필드·체크·readonly·사유·눌림·active 태그 예를 실었다(cda6c382).
- 증거: 브라우저 `src/hmi/dashboard/test` 52 passed, `test/test_role_surface_states_browser.py` 5 passed. 캡처 `X:/DevTemp/rosy-d359/shots/us004-robot-{console,setup}-{dark,light}-{1366x768,390x844}.png` — 필드 44px, 내비게이션 비활성 사유 보임.
- gate 변화: 없음.

## 2026-09-30 · 06650820 · D-359 US-004 알 수 있는 비활성 사유를 모두 reason으로

- 변경: `dom.js`에 `setOff(control, off, reason)`, `setEnabled(id, enabled, reason)`. 패널은 한 줄 지역 `setOff`. 라인 추종·교통 신호·SLAM·관리자 전용·네트워크/릴리스·구 `/dashboard` teleop(`teleopBlockReason`은 `teleopEligible`과 같은 순서)·도킹·카메라 녹화·초기 위치·웨이포인트·토큰 삭제·도크 목록 버튼이 같은 조건에서 짧은 사유를 달고 켜지면 지운다. `map.js`는 `goalReason` 선택지. 역할 화면 teleop 네 버튼은 보이는 준비 문장(readinessStatus)에 `aria-describedby`로 잇는다. 요청 중 잠금·첫 readback 전 초기값·네이티브 select/option·공용 안내가 있는 곳은 `test_shared_controls.py` `DISABLED_WITHOUT_REASON` 닫힌 목록(이유 포함)에 있다. role G2 시험은 버튼을 접근 이름으로 찾는다(보이는 사유가 textContent에 들어가므로).
- 증거: 단위 2709 passed 132 skipped. 브라우저 `src/hmi/dashboard/test` 50 passed 2 failed → G2 로케이터를 `get_by_role`로 고친 뒤 `test_role_g2_browser.py` 12 passed. `test/test_role_surface_states_browser.py` 5 passed. 변이 5건 빨강 후 복구(X:/DevTemp/rosy-d359/us004b-mutations.log).
- gate 변화: 없음.

## 2026-09-30 · aeb31356 · D-359 US-005 셸 세 단·세로 예산·구 콘솔 프레임

- 변경: `shell/shell.css` — `.surface-main`·`.surface-slot`이 inline-size 칸(`.surface-main`은 flex 열 안에서 0폭이 되지 않게 `width: 100%`). 운용 고정 프레임은 `(width >= 64rem) and (height >= 40rem)`만, 3열·설정 2단 등은 `(width >= 64rem)`. 30.01/63.99 틈을 없앴다. wide 아래 머리는 두 줄 격자(이름·역할 / 화면 전환, 비상 정지가 두 줄 오른쪽), 알림은 글이 있을 때만 셋째 줄; compact는 링크·정지 안쪽 여백만 줄인다 — 320×568에서 머리 105px(18.5%). `surface-panels.css`의 ui-actions 재정의 삭제. 구 `/dashboard` `styles.css`: `.console` 고정 프레임은 `(width >= 64rem) and (height >= 40rem)`에서 `100dvh`, 그 밖(`(width < 64rem), (height < 40rem)`)은 영역을 쌓아 흐른다. 1080/720px → 64rem. `panels/system/events.css` 1080/720px → 64rem/30rem. 시험: 새 `test/test_surface_viewport_budget_browser.py`(FastAPI 원본으로 /console·/setup·/device × 390×844·320×568: 넘침 0, 머리 ≤ 20%, 비상 정지 첫 화면·끝 스크롤 뒤에도 화면 안), 레이아웃 시험은 두 줄 머리 순서·칸 반응(1440의 좁은 칸은 쌓이고 넓은 칸은 행, 320은 쌓임, 390은 두 열)으로 고침, `test_surface_bridge.py` 분할 키를 `@media (width < 64rem) {`로.
- 증거: 브라우저 `src/hmi/dashboard/test` 55 passed, `test/test_role_surface_states_browser.py` 5 passed. 변이: components.css `ui-topbar` `min-height: 300px` → 예산 시험 두 칸 빨강. 캡처 `X:/DevTemp/rosy-d359/shots/us005-robot-*.png`(console dark·light, setup·device dark; 1366×768·390×844·320×568).
- gate 변화: 없음.
- 결정: D-359 §6.

## 2026-09-30 · 0308c67c · D-359 US-007 웨이포인트 폼이 공용 ui-form을 쓴다

- 변경: `panels/setup/waypoints.js` 폼에 `ui-form`. 390·320에서 이름 칸과 저장 버튼이 틈 없이 두 줄로 붙었다(평범한 인라인 폼). 이제 `--gap-form`을 지키고 좁은 칸에서 한 열로 접힌다. 시험: `test_waypoint_readiness_browser.py`에 폼 클래스·행 간격 8px 단언.
- 증거: 수정 전 빨강, 수정 후 초록. 캡처 `X:/DevTemp/rosy-d359-captures/robot-setup-*`.
- gate 변화: 없음.
- 결정: D-359 §5.

## 2026-09-30 · 570e3a29 · D-359 US-008 낮은 wide 콘솔이 열을 지킨다

- 변경: `shell/shell.css` 운용 열(64rem 이상)과 고정 프레임(64rem 이상 + 40rem 이상 높이)을 두 미디어 조건으로 나눴다. 1366×600은 세 열을 지키고 페이지가 스크롤한다. 옛 `/dashboard`(`styles.css`)도 같이 나눴다. `DESIGN.md` Tall Enough Rule에 한 줄. 시험: `test_surface_layout_browser.py::test_wide_but_short_console_keeps_its_columns_and_scrolls_the_page`, `test/test_dashboard_browser.py::test_wide_but_short_operate_view_keeps_three_columns`.
- 증거: 두 시험 모두 수정 전 빨강.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §5·§6 (US-008).

## 2026-09-30 · uncommitted · fix(dashboard): D-359 restore legacy /dashboard (missing dom.js imports, teleop pad overflow)

- 변경: `app.js`·`ros-network.js`·`settings.js`가 부르던 `setTagState`를 `./dom.js`에서 가져온다(없어서 렌더 사슬 전체가 ReferenceError로 끊겼다). `.teleop-pad ui-button`은 세로 쌓기·간격 0이라 1366×600에서 "→우회전"(keep-all로 안 끊김)이 8 px 넘치지 않는다. 시험 두 곳은 뜻을 지켜 새 마크업(ui-tag 벤치 태그, 사유 small 제외한 부저 라벨)을 본다. 새 호스트 시험 `test_module_imports.py`가 dom.js·core_ui_logic.js·ui.js에서 내보낸 이름을 부르는 모든 대시보드 스크립트가 그 이름을 가져오는지(또는 지역 바인딩인지) 본다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py -q` 70 passed, 1 failed(`test_operate_view_fits_and_does_not_crush[viewport0-]`, 동시 Fleet 브라우저 부하 중) → 단독 재실행 4 passed. `test_module_imports.py` 39 passed, 옛 app.js·ros-network.js·settings.js에 대해 `setTagState (from dom.js)`를 짚고 import 하나를 지우는 변이도 잡는다.
- 미증명: 실기 대시보드
- gate 변화: 없음
- 결정: D-359
- 교훈: 호스트 시험은 브라우저 모듈의 ReferenceError를 못 본다 — 공용 도우미 import는 정적 스캔으로 지킨다.

## 2026-09-30 · 6d296cd6 · D-359 US-009 로봇 상태 개요의 모드·내비게이션 증거

- 변경: 내비게이션은 자기 채널로 `readout()`을 거쳐 `지연 · N초 전`/`연결 끊김`과 `data-evidence`를 얻는다. 모드는 CORE 자신의 값이라 응답이 부모 증거다. 둘 다 한국어 표, 열거값은 title. 시험 `test_panel_copy_evidence_browser.py::test_overview_…`.
- 증거: 수정 전 `NAVIGATING` 날값·증거 없음(빨강).
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 (US-009).

## 2026-09-30 · 5518f9bc · D-359 US-009 운용자 말을 CONCEPTS 용어로

- 변경: mode·line-follow·map·docking·teleop·setup(docking·localization)·host/system·app.js·settings.js·index.html의 profile/capability/Navigation/hardware 모드/프로필/MANUAL·NAVIGATION 모드 문장을 내비게이션·실행 모드·하드웨어 실행 모드·기능·수동 모드로. 모드 패널 상태·버튼·확인 문장은 MODE_LABEL(6cadb183).
- 증거: web_common `test_operator_copy.py` 0건. role-menu 시험 문구 기대값 갱신.
- gate 변화: 없음.
- 결정: D-359 (US-009).

## 2026-09-30 · 937bd659 · D-359 US-009 호스트 에이전트 원인은 한 번

- 변경: 네트워크·릴리스 작업이 같은 에이전트 상태로 막히면 패널 머리 아래 상태 한 줄(원인+다음 할 일), 버튼 사유는 `위 사유` + aria-describedby. 한쪽만 막히면 그 묶음 상태가 말한다. 403은 권한 문장. 묶음 상태는 쓸 때만 문서에 있다(698e6192). CONCEPTS.md에 호스트 에이전트.
- 증거: `test_host_agent_outage_is_said_once_and_buttons_point_at_it` — 원인 글을 가진 보이는 요소 정확히 1개. 수정 전 네트워크 버튼 4개 + 상태 줄들이 같은 원인을 되풀이.
- gate 변화: 없음.
- 결정: D-359 (US-009).

## 2026-09-30 · 26226596 · D-359 US-009 호스트 런타임 빠진 원천을 한국어로

- 변경: `system.js` `runtimeGap()` — os_release→운영체제 … network_counters→네트워크 통계, 전부 없으면 `호스트 런타임 정보를 받지 못했습니다`, 키는 title. node 단위 시험이 CORE runtime.py 키 목록과 대조.
- 증거: `test_host_system_copy.py` 5 passed.
- gate 변화: 없음.
- 결정: D-359 (US-009).

## 2026-09-30 · 029188c4 · D-359 US-009 카메라 상태 태그

- 변경: vision.js 상태 태그가 `실시간`/`수신 대기`/`지연 · N초` + data-evidence, 옛 LIVE/WAITING/STALE은 title. 콘솔 카메라 패널은 프레임이 없으면 동작 아래 대기 줄을 숨긴다(대기 문장 1회). 레거시 대시보드 시험 기대값 갱신.
- 증거: `test_camera_status_speaks_korean_with_evidence_and_waits_on_one_line`, 레거시 카메라 시험 초록.
- gate 변화: 없음.
- 결정: D-359 (US-009).

## 2026-09-30 · 709651d1 · D-359 US-009 로봇 지도 읽기 실패는 무대 위에

- 변경: 지도 읽기 실패(또는 권한 없음)면 무대의 ui-empty가 원인을 말하고 곁에 `다시 시도`(권한 없음은 없음), 같은 원인의 지도 상태 줄과 `선택 좌표` 줄은 숨긴다. createFieldMap은 `mapState`를 내보인다. role-surface-states 시험은 빈 무대 대신 실패 장을 기대한다.
- 증거: `test_robot_map_read_failure_is_an_overlay_with_retry_and_no_target_row`(모의 500 → 다시 시도 → 복구).
- gate 변화: 없음.
- 결정: D-359 (US-009).

## 2026-09-30 · bd2bd093 · D-359 US-009 도크 상태 한국어, 빈 목록 모양 통일

- 변경: /setup·/console 도크 상태가 DOCK_STATE_LABEL(모든 DockState). 도크·도크 관리·웨이포인트 빈 목록은 목록을 숨기고 목록 밖 ui-empty 한 줄.
- 증거: `test_setup_empty_lists_are_one_ui_empty_outside_the_list[3]`, `test_dock_state_reads_korean_with_the_enum_in_title[2]`; 웨이포인트 간격 시험은 빈 줄을 잰다.
- gate 변화: 없음.
- 결정: D-359 (US-009).

## 2026-09-30 · 5bcd9617 · D-371 US-010 목록 행 삭제는 조용한 `삭제…` + 확인 대화상자

- 변경: `/device` 토큰 목록(`panels/system/security.js`)과 도크 관리(`panels/setup/dock-admin.js`)의 행 `삭제`가 위험 채움 → quiet `삭제…`, 누르면 `confirmIrreversible`(대상 이름, `토큰 삭제`/`도크 삭제`). "지금 쓰는 토큰" 사유 유지. 옛 `/dashboard` `settings.js` 토큰·도크·웨이포인트 삭제도 같은 대화상자(이미 quiet였음, `삭제…`로), D-218 핀 settings.js 11→8. 새 브라우저 시험 `src/hmi/dashboard/test/test_list_row_confirm_browser.py`(e20078de): 실제 /device 첫 화면 위험 채움 ≤1(비상정지 제외, dark/light × 1366/390), 삭제 흐름(Esc·취소 → 요청 0·포커스 복귀, 실행 → DELETE 1회). 패널 시험은 대화상자 실행 버튼을 누른다.
- 증거: 브라우저 변이(행 kind=irreversible) → 빨강 2개 채움; 캡처 `X:\DevTemp\rosy-d359-captures\us010-*` 채움 0·넘침 0·오류 0.
- gate 변화: 없음.
- 결정: D-371.

## 2026-09-30 · 79787e7a · D-371 US-010 정지 컨트롤에 data-always-live, 대화상자 위 정지 시험

- 변경: `surface.html` `#shell-estop`, `index.html` `#emergency-stop`, `styleguide.html` 표본 정지에 `data-always-live`. 스타일가이드에 `확인 대화상자` 고정 그림(94ba6de2, 인라인 스크립트 없음). 브라우저 시험 `test_device_estop_stays_live_over_the_delete_dialog`(/device: 정지 비inert, elementFromPoint가 정지, 밖 컨트롤 전부 inert, 폴링·늦게 붙은 노드도 막힘, Tab 고리, 정지 클릭 → POST /safety/stop + 대화상자 닫힘 + DELETE 0, Esc 취소)와 옛 /dashboard `test_waypoint_delete_dialog_keeps_the_estop_out_of_the_inert_region`(2bd9c0bb).
- 증거: ROSY_RUN_BROWSER_TESTS=1: `test_list_row_confirm_browser.py` 6 passed, `test_role_menu_panels_browser.py`+`test_web_dialog_contract.py` 27 passed, `test_dashboard_browser.py -k "setting or token or dock or waypoint"` 7 passed, 2 skipped (`X:\DevTemp\rosy-d359\us010b\browser.txt`)
- gate 변화: 없음.
- 결정: D-371 Refinement(2026-09-30).
- 교훈: 옛 /dashboard는 정지가 운용 뷰에만 있어 점검 뷰의 설정 목록에서 대화상자를 열면 정지가 화면에 없다(이번 변경 전부터). 대화상자는 정지를 inert로 만들지 않지만, 뷰 전환 탭은 열린 동안 막힌다 — Esc로 닫고 운용 뷰로 간다.
## 2026-09-30 · uncommitted · feat(icons): D-358 S3 대시보드 파비콘

- 변경: `index.html`·`surface.html`에 `<link rel="icon" type="image/svg+xml" href="/common/icons/robot-dashboard.svg">`를 더했다. 제목(`Rosy 로봇 — 대시보드`)은 이미 이름표와 같아 바꾸지 않았다.
- 증거: `test_surface_icons.py`, `src/runtime/api_web/test/test_ui_route.py` 녹색.
- gate 변화: 없음.
- 결정: D-358 2·3항.
- 교훈: 없음.


## 2026-09-30 · uncommitted · docs(adr): D-358 앱 역할 ADR을 D-370으로 재번호

- 변경: 이 모듈의 D-358 앱 역할·이름·아이콘 주석과 시험 문서 문자열을 D-370으로 바꿨다. 동작 변경 없음.
- 증거: 번호만 바꾼 diff. 시험은 병합 뒤 회차에서 다시 돌린다.
- gate 변화: 없음.
- 결정: 이 항목 앞의 "D-358 S1/S2/S3"·"D-358 N항"은 D-370을 가리킨다(main의 D-358 ER2 피드백 outbox와 다름). 옛 항목은 고치지 않는다.
- 교훈: 없음.

## 2026-09-30 · uncommitted · refactor(dashboard): D-377 Rosy Robot title and favicon
- 변경: `index.html` `<title>` `Rosy Robot`, `surface.html` `Rosy Robot — {{title}}`, 파비콘 `/common/icons/robot.svg`.
- 증거: `python -m pytest src/hmi/dashboard/test -q` 17 passed, 34 skipped (브라우저 시험 opt-in); `src/hmi/web_common/test` 111 passed (2026-09-30 Windows).
- gate 변화: 없음. 폴더·패키지 이동(`src/hmi/robot`, `rosy_robot`)은 D-374 단계 3 게이트 그대로.

## 2026-10-01 · uncommitted · fix(dashboard): D-359 리뷰 P2-2 — 모드·도크·네트워크·차선 추종 열거값을 한국어로

- 변경: `app.js` 모드 확인·결과 글은 `enumLabel(MODE_LABEL, requestedMode)`, 네트워크 적용 글은 `NETWORK_MODE_LABEL`. `settings.js` 도크 상태 글은 `DOCK_STATE_LABEL`. `panels/console/line-follow.js`는 `LINE_MODE_LABEL`(꺼짐·적외선 센서·카메라)로 상태·요청 글과 모드 값을 쓴다. `panels/host/operations.js` 네트워크 모드도 `NETWORK_MODE_LABEL`. `test_host_operations_browser.py` 서버가 `/common/`을 web_common으로 옮긴다.
- 증거: `test_host_operations_browser.py` 3 passed, `test/test_role_menu_panels_browser.py -k line_follow` 2 passed, `test/test_role_surface_states_browser.py -k host_agent` 1 passed (ROSY_RUN_BROWSER_TESTS=1, 2026-10-01 Windows).
- gate 변화: web_common `enum_text_problems` 린트가 이 파일들을 본다.
- 결정: D-359 US-009.
- 교훈: 없음.

## 2026-10-01 · uncommitted · fix(dashboard): D-359 리뷰 P2-5 — 화면 테마 패널은 RosyTheme.choices로 그린다

- 변경: `panels/system/display.js`의 따로 적은 선택지 표를 지우고 `window.RosyTheme?.choices`로 버튼을 그린다.
- 증거: `src/hmi/web_common/test/test_theme_browser.py -k device_display` 통과, `test_theme_choices.py` 4 passed.
- gate 변화: web_common `test_theme_choices.py`가 이 파일에 이름 사본이 없는지 본다.
- 결정: D-359 §2.5.
- 교훈: 없음.

## 2026-10-01 · uncommitted · test(dashboard): D-359 리뷰 P2-2 — 모드 확인 문구 시험을 한국어로

- 변경: `test/test_dashboard_browser.py`의 모드 변경 확인 시험이 `IDLE 모드로` 대신 `대기 모드로`를 보고, 확인 문구에 열거값이 없는지 본다(bcee2ebb에서 문구가 `enumLabel(MODE_LABEL, …)`로 바뀜).
- 증거: `test/test_dashboard_browser.py -k test_irreversible_mode_change_needs_confirm` 1 passed. 마무리 회차 `-k "mode or setting or token"`에서 이 시험만 옛 문구로 실패했었다.
- gate 변화: 없음.
- 결정: D-359 US-009.
- 교훈: 문구를 바꾸면 루트 `test/`의 브라우저 시험도 grep한다.

## 2026-10-01 · uncommitted · revert(dashboard): D-359 정리의 setOff 통합을 되돌림

- 변경: 034fa28f(패널 10개가 `/assets/dom.js`의 `setOff`를 import)를 되돌렸다. 패널은 각자 한 줄 `setOff`를 다시 든다.
- 증거: 7.6 회귀에서 `test/test_role_menu_panels_browser.py` 12건·`src/hmi/dashboard/test` 6건·`test_role_surface_states_browser.py` 1건이 실패했다. 패널 시험 하네스는 패널 파일만 라우팅하고 `/assets/dom.js`를 제공하지 않는다.
- gate 변화: 없음.
- 결정: D-359 §5.3. 정리 패스는 동작·시험 하네스를 바꾸지 않는다.
- 교훈: 패널 모듈의 import 그래프는 운영 서버뿐 아니라 패널 단위 하네스가 제공하는 경로 안에 있어야 한다.

## 2026-10-01 · uncommitted · fix(dashboard): D-359 차선 추종 모드 값은 title에 원래 열거값을 둔다

- 변경: `panels/console/line-follow.js`의 모드 `dd`가 한국어 라벨과 함께 `title`에 원래 열거값(`IR_LINE`·`OFF` 등)을 둔다(DESIGN.md 운용자 말: 열거값은 title에만). `test_action_groups_browser.py`는 `title`로 상태 도착을 기다린다.
- 증거: 7.6 회귀에서 `test_real_operation_panels_block_switch_during_start_and_while_active`가 단독 재실행에서도 `textContent === "IR_LINE"` 대기로 실패. 수정 후 해당 파일 + `test/test_role_menu_panels_browser.py` 30 passed, 호스트 340 passed.
- gate 변화: 없음.
- 결정: D-359 §5, US-009 P2-2 후속.
- 교훈: 화면 글자를 한국어로 바꿀 때 열거값을 title로 옮기지 않으면 상태를 읽는 시험·도구가 기댈 곳이 사라진다.

## 2026-10-01 · uncommitted · feat(console): D-383 편대 역할 칸과 버전 계보

- 변경: 계기 셋에 FORMATION ROLE 칸(leader/follower 한국어, 대형 이름, 기본 hidden), 식별줄에 software_version 추가. telemetry.js renderFormationHero + app.js 배선, console-detail.css 계기 문법. 새 파일·새 엔드포인트 없음.
- 증거: dashboard 패키지 시험 9 passed·suite 21 passed 34 skipped, 게이트웨이 dashboard/웹공통 139 passed. 변이 증명 2종(배선·hidden 규칙 제거 시 빨강).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(console): 계보줄 단일 작성자 — 10Hz 덮어쓰기 제거

- 변경: renderRobotState 가 robot-id 를 더 이상 쓰지 않는다. 실기(013)에서 D-383 계보(모델·버전·모드)가 매 틱 state.robot_id 하나로 지워지는 것을 확인했다. 식별 렌더(renderRobotInfo)가 유일한 작성자다.
- 증거: dashboard 패키지 시험 (app.js 에 setText("robot-id" 부재). 변이: 재추가 시 빨강.
- gate 변화: 없음.

## 2026-10-01 · c302529d · feat(dashboard): 보정 중 칩
- 변경: 콘솔 로봇 카드(`panels/console/overview.js`) 맨 위와 /dashboard 모드 옆(`#calibration-chip`)에 `ui-tag status=warn` "보정 중 — <label>".
- 증거: ROSY_RUN_BROWSER_TESTS=1 test_calibration_chip_browser.py 1 passed(실제 CoreServices 로 lease 를 열고 닫는다). 스크린샷 X:\DevTemp\calibration-mode\dashboard-*-calibration-chip.png.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(console): 모드 버튼·히어로가 한국어로 말한다

- 변경: 모드 버튼 IDLE→대기·MANUAL→수동·NAV→자율주행. 히어로 모드 표시가 원본 enum 대신 enumLabel(MODE_LABEL, …)을 쓴다. MODE_LABEL 은 core_ui_logic.js 에 이미 있었다 — 버튼만 영어 enum 을 그대로 보여주고 있었다.
- 증거: test_dashboard_package.py test_the_mode_control_speaks_korean (변이: 영어 되돌리면 빨강).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(console): Escape 키 즉시 비상정지

- 변경: keydown Escape → POST /safety/stop — 확인창 없음(위급 순간의 장벽은 위험). 입력 필드(INPUT·TEXTAREA·SELECT·contentEditable)에서는 발동 안 함. 이미 정지면 재발동 안 함. event.repeat 무시. 토큰 없으면 무시.
- 증거: test_dashboard_package.py test_escape_key_stops_the_robot_immediately.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(console): 지도 목표 마커 + 스켈레톤 펄스

- 변경: ① map.js paint() 에 목표 다이아몬드(경로 색) — rosy:goal 설정, rosy:goal-clear 해제. ② 텔레메트리 '--' 값에 data-pending 스켈레톤 펄스(1.6s 호흡).
- 증거: test_dashboard_package.py 2신규 (마커·스켈레톤).
- gate 변화: 없음.


## 2026-10-01 · uncommitted · D-398 죽은 토큰 참조·펄스·페이드 정리

- 변경: console-detail.css의 var(--muted/--paper/--radius-1) → --ink-quiet/--ink-on-crit/--radius-control(존재하지 않는 토큰 참조였음). skeleton 펄스·액션 페이드 제거로 D-220 회복 — 기다림은 조용한 뮤트 대시, 숨김은 점프 컷(레거시 시험 핀 2건 갱신, 깨져 있던 디밍 계약 시험도 초록). overview·pose-evidence·operations·triage·telemetry·vision이 EVIDENCE_LABEL/evidenceAgeText로 말을 만든다. styleguide.css의 죽은 .demo-* 부품 재구현 삭제(견본은 실제 ui-* 요소).
- 근거: D-398. dashboard·web_common 시험 통과.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · D-398 후속 — 원시 줄 간격 토큰화

- 변경: styles.css 2곳(1.55→--leading-copy, 1.35→--leading-label), console-detail.css 2곳(1.45→--leading-body, font 단축형 /1.45→--leading-copy). 표면 줄 간격은 이제 토큰만.
- 근거: D-398 후속. web_common 타이포 계약 시험이 폐쇄 화이트리스트로 잔존을 적발(변이 증명).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · feat(console): camera fullscreen and lane/object legend
- 변경: 카메라 영상 확대/닫기, 종료 시 키보드 초점 복귀, 수신 전 확대 비활성 사유, 차선·객체 표시 읽는 법 범례를 추가.
- 증거: 실제 브라우저 확대/초점·수신 대기·범례·모바일 overflow 3 passed; viewport/layout 브라우저 10 passed. 기존 camera capture 5 passed.
- 한계: 저장된 테스트 영상/브라우저 검증과 로봇 실시간 배포는 별도. 전원이 꺼진 로봇에는 아직 반영하지 않음.
- gate 변화: 없음. LOCAL 브라우저 증거 추가; DEVICE/FIELD 미승격.


## 2026-10-02 · uncommitted · fix(console): fullscreen uses dynamic viewport height
- 변경: 확대 카메라 높이를 100dvh로 수정해 모바일 주소창 변경과 D-359 높이 규칙을 반영.
- 증거: 원격 CI 36895230123이 새 100vh를 적발. design scope gate 5 passed로 수정 확인. 기존 테스트만 통과한 상태를 전체 CI 성공으로 취급하지 않음.
- gate 변화: 없음. 전체 CI 및 실기 관문은 별도.

## 2026-10-02 · uncommitted · D-405 /device 테마 버튼 아이콘 렌더 + fullscreen 100dvh 게이트 수리
- 변경: panels/system/display.js가 RosyTheme.choices의 icon을 그리고 이름을 sr-only·title로 둔다. panels/surface-panels.css의 #vision-stage:fullscreen height 100vh를 100dvh로(6818ba40에서 들어온 위반을 test_full_viewport_heights_use_dvh가 지적).
- 근거: D-405; D-359 높이 계약(dvh).
- gate 변화: 없음.
- 최종 증거: web_common 209 passed(dvh 게이트 포함); dashboard 회귀 포함 1291 passed 65 skipped.

## 2026-10-02 · uncommitted · D-409 잔존 높이 함수 dvh 교정
- 변경: console-detail.css clamp(190px, 31vh→31dvh, 290px)·.region-observe min-height 60vh→60dvh, shell/shell.css clamp(9rem, 24vh→24dvh, 14rem)·max-height 24vh→24dvh — D-405 잔존 목록 소진.
- 근거: D-359 높이 계약, D-409 결정 3.
- gate 변화: 없음.
- 최종 증거: web_common+dashboard 287 passed 82 skipped(dvh 게이트 포함).

## 2026-10-02 · uncommitted · 스타일 가이드 어휘 패리티 — status·empty·actions·readout·icon + "아직 없는 넷" 현행화
- 변경: styleguide.html에 ui-status(다섯 상태)·ui-empty·ui-actions(버튼 줄)·.ui-readout(이름–값 읽기)·.ui-icon(D-405, currentColor 인라인 SVG) 항목을 추가하고, 글자 위계 조작 행에 toggle tone="good"(자동 복구)을 더했다. "아직 없는 넷" 문단은 실제 구현 상태(확인 대화상자 D-371, Fleet 예외 행 — Fleet 콘솔 주의·최우선 큐, 좁은 화면 D-359; face intent는 LCD 소유 D-385)에 맞춰 "어휘를 늘리는 규칙"으로 고쳤다. 규칙 본문(D-92 제5항·D-130.2)은 유지.
- 근거: D-92(어휘 표와 견본은 같은 커밋), D-286·D-287(readout·readback), D-359, D-371, D-385, D-405, D-130.2.
- gate 변화: 없음.
- 최종 증거: web_common+dashboard 286 passed 82 skipped. fleet styles.css opacity: 0.4 사전 실패 1건은 본 변경 없이도 재현(stash 확인)되어 무관.

## 2026-10-02 · uncommitted · D-423 카메라 범례에 거리 출처
- 변경: `panels/console/camera.js` 범례 OBJ 줄에 "0.42m L은 카메라 앞 거리(L LiDAR, G 바닥 평면 추정)" 추가.
- 근거: D-423 §1.6.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · fix(console): 점유 격자를 가리지 않고 즉시 정지는 버튼이 확인이다
- 변경: 지도 도구는 점유 지도 제목의 한 줄, 범례는 캔버스 아래 한 줄. 즉시 정지 클릭의 window.confirm을 뺐다(Esc 표시, 해제는 그대로 묻는다). Escape는 session.token이 있을 때만 같은 정지를 보낸다. 신선하지 않은 계기는 지연·연결 끊김·정보 없음이 크고 숫자는 작다. 소켓이 살아 있어도 위치·속도가 신선하지 않으면 배지는 "통로만 연결", 그 외에는 "값 수신 중". 64rem 미만에서는 즉시 정지를 뷰포트 바닥에 고정하고 연결 문장을 숨기지 않는다. 모드 히어로·기능 이름·차선 꺼짐은 한국어. API 문서는 점검의 호스트 상태로 옮겼다. SAFE_STOP은 RobotMode에 넣지 않고 operatorModeLabel로 "안전 정지".
- 근거: D-201, D-218, D-77. 운용 화면 비평의 P1·P2.
- 증거: 2026-10-03 Windows. 대화 계약, 콘솔 배치, enum, 운용 카피, dashboard 패키지, host copy, shared controls, token, ui route, dashboard browser, drive를 ROSY_RUN_BROWSER_TESTS=1로 한 번에 실행해 240 passed, 2 failed. 실패 둘은 Page.goto 5000ms 초과였고 같은 둘만 다시 실행하면 2 passed(4.04s). Escape의 session.token과 화면 모드 수동을 고친 뒤 키보드 목표 확인과 상태 읽기 시험은 2 passed(6.07s). 1366에서 도구와 범례는 캔버스를 가리지 않고 문서 스크롤은 0이다. 캔버스 높이는 112px이다(비전 스테이지 238px, 도구 줄 72px). 390에서 즉시 정지는 뷰포트 바닥에 고정된다.
- gate 변화: 없음.
- 미증명: 실기 텔레옵. 비전 신선도 판정은 바꾸지 않았다.

## 2026-10-04 · uncommitted · feat(dashboard): 차선 인식 선택

- 변경: 차선 추종 패널에 인식 방식 선택과 설정/실제 추론 출처 표시. 관리자·신선한 정지 IDLE·추종 OFF에서만 적용. 적용 중 추종 시작 잠금, 실패는 실패로 표시하고 PUT 뒤 GET readback을 확인한다.
- 증거: 인식 적용 실패·pending·readback 브라우저 2 passed, 기존 패널 브라우저 13 passed. 실제 입력의 최신 출처와 모델 판을 별도로 표시하며 지연·누락은 확인 대기로 둔다.
- gate 변화: 없음. 실제 추론 출처 없는 응답은 확인 대기로 표시한다.

## 2026-10-04 · uncommitted · feat: 저조도 카메라 판정 불가 표시

- 변경: 기존 카메라 패널에 저조도 경고를 추가했다. 실시간 JPEG 수신과 차선·물체 판정 가능 여부를 별도로 표시한다.
- 증거: Pilot·Dashboard 저조도 브라우저 회귀 각각 1 passed; shared controls + shell 30 passed.
- gate 변화: SOURCE/LOCAL. ARM64/device/field verification pending.

## 2026-10-04 · uncommitted · feat: 브라우저 원본·표시본 확인 영상

- 변경: 카메라 패널에서 원본 또는 원본+표시본을 선택한다. 같은 촬영 시점의 두 프레임을 확인하고 원본부터 저장한다. 원본 누락·구형 서버 응답·촬영 시점 불일치는 녹화를 막는다.
- 증거: 브라우저 표시본+원본 저장/원본 누락/저조도/확대 3 passed.
- gate 변화: SOURCE/LOCAL. ARM64/device/field evidence remains separate.

## 2026-10-04 · uncommitted · fix: 과노출 판정 불가 안내

- 변경: 기존 카메라 품질 경고에 과노출 안내를 추가했다. JPEG 수신 상태와 차선 판정 가능 여부는 별도로 표시하며 원본 픽셀은 바꾸지 않는다.
- 증거: Pilot/Dashboard bright-dark browser 2 passed; native quality/alarm 9 passed.
- gate 변화: SOURCE/LOCAL. No device writes or motion.
