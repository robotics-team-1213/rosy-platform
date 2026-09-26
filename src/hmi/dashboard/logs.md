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
