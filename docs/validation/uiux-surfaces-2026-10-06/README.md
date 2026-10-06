# ROSY UI/UX 품질 확인 — 2026-10-06

**판정: 제품 전체 HOLD.** 이 회차는 `PRODUCT.md`의 UI/UX 목표를 현재 화면에서 확인하기 시작한 LOCAL 점검이다. D-280의 성격과 `DESIGN.md`의 토큰·표면 문법을 유지하며, GO 기준은 D-153 G1/G2/G3 그대로다. 브랜치 `uiux/rosy-operate-quality`에서 작성했다.

제품 전체 수용 기준은 사용자 확인에 따라 **활성 표면 모두의 G1, 선언한 G2 상태·폭 전부, G3 실제 사용자 검토와 해당 실물 장치 readback**이다. 일부 화면의 너비 보정이나 LOCAL 시험 통과로 이 판정을 올리지 않는다.

## 이번 회차의 질문과 근거

| 표면·질문 | 현재 LOCAL 캡처 | 확인한 것 | 남은 것 |
|---|---|---|---|
| 로봇 운용: 지금 움직여도 되는가? | [1366×768](captures/robot-console-1366x768.png), [390×844](captures/robot-console-390x844.png), [G3 독회](#로봇-운용-g3-독회--local-진행-중) | 데스크톱 감지·관측·조작이 같은 폭이다. 390px에서 조작이 카메라·지도보다 먼저 오고 비상 정지가 첫 화면에 있다. 모드·수동 주행·차선 추종·도킹·지도 근거의 요청/접수/재확인을 두 폭에서 재생했다. | 선언된 역할·상태 전체 G2, 실제 CORE/장치 상태, G3 전체 근거 검토. |
| 장비·작업 준비: 다음 절차와 막힌 이유를 알 수 있는가? | [60셀 매트릭스](captures/roles-procedure/role-state-records.json), [첫 기동 6셀](captures/roles-first-boot/first-boot-matrix.json), [운용자 작업 준비 390×844](captures/roles-procedure/operator-setup-normal-390x844.png), [맵핑 시작 확인](captures/roles-procedure/operator-setup-confirm-dialog-390x844.png), [릴리스 복귀 확인](captures/roles-procedure/administrator-device-confirm-dialog-390x844.png), [관리자 장비 지연 390×844](captures/roles-procedure/administrator-device-delayed-host-operations-390x844.png), [권한 거부 390×844](captures/roles-procedure/operator-device-forbidden-390x844.png) | `/setup`·`/device`를 역할 2개·1366/390px·상태별 60셀과 첫 기동 6셀로 현재 FastAPI/Chromium에서 재생했다. 390px 패널 안의 입력·행동은 같은 가용 폭을 쓰며, 페이지 오류·가로 넘침 0, 쓰기 차단 fixture에서 확인 취소 POST 0이다. 첫 기동에는 상태 확인 대기가 표시되고 비상 정지가 두 폭에서 보인다. 확인창 6장에는 선택한 행동 이름이 실행 버튼에 보이고 비상 정지가 대화상자 위에 남는다. 관리자 호스트 지연·끊김·결측의 실제 작업 패널 6장을 별도로 저장했다. | 절차를 현장 사용자가 완료할 수 있는지 G3 작업 독회, 실제 Host Agent/장치 readback. |
| Fleet: 어느 로봇에 주의가 필요한가? | [1920×1080](captures/fleet-console-1920x1080.png), [320×844](captures/fleet-console-320x844.png), [상태 캡처](#fleet-g2-상태-확인--local-진행-중), [G3 독회](#fleet-g3-독회--local-진행-중) | 데스크톱 현장·개입 칸이 같은 폭이다. 전화의 **기본** 목록은 릴레이 오류가 있는 `rosy_03`부터 보여 주며 비상 정지가 첫 화면에 있다. 빈 목록·서버 실패에서도 320/390px 패널 폭과 다음 단계가 유지된다. | 선언된 상태 전체 G2, 연결된 카메라·실제 사이트 PC/로봇 readback, G3 전체 근거 검토. |
| Fleet Cell: 문서 준비부터 작업 제안·승인·중단까지 이해할 수 있는가? | [Cell 작업 카드](#fleet-cell-작업-g2g3--local-부분-근거) | `/console/cell`의 첫 화면 1440/390/320px에 비상 정지가 있고, 320px 부분 응답·결과 미확인을 구분한다. 레시피·셀 문서 창은 세 폭에서 같은 너비이며 compact에서는 작업 행동이 각 칸의 가용 폭을 채운다. | 선언 상태·폭 전체 G2, 실제 셀 장치 readback, 작업자 G3 8항 검토. |
| 게임 보드: 경기장·공·로봇·골이 보이는가? | [진행 1280×800](captures/games-play-1280x800.png), [최초 1280×800](captures/games-initial-1280x800.png), [최초 390×800](captures/games-g3/games-initial-390x800.png), [지연 1280×800](captures/games-delayed-1280x800.png), [HOLD 1280×800](captures/games-hold-1280x800.png), [지연 390×800](captures/games-delayed-390x800.png), [G3 독회](#게임-보드-g3-독회--local-진행-중) | 최초·연결 오류 때 빈 피치에 이유를 표시한다. 데스크톱에서는 피치가 초점이라 관측보다 넓고, 전화에서는 점수·피치·관측이 같은 가용 폭으로 쌓인다. 지연 화면은 마지막 수신 정보임을 밝히고 정지가 첫 화면에 있다. | 현재 트리의 전체 상태 G2, 실물 카메라·경기 readback, G3 전체 근거 검토. |
| 로봇 얼굴: 의도·주의·위험이 즉시 구분되는가? | 정보 카드 [첫 기동](captures/face-first-boot-320x240.png)·[정상](captures/face-nominal-320x240.png)·[E-STOP](captures/face-estop-320x240.png)·[배터리 위험](captures/face-battery-critical-320x240.png), 주행 카드 [수동](captures/robot-face_drive-manual-320x240.png)·[내비게이션/저배터리](captures/robot-face_drive-navigation-320x240.png)·[E-STOP](captures/robot-face_drive-estop-320x240.png) (모두 320×240) | PIL 렌더러의 두 카드 종류에서 정상·위험을 문구와 채움으로 구분한다. 주행 중 15% 배터리 문구도 위험색 바탕 위 밝은 글자로 읽힌다. | D-433 `rosy-face` 실제 설치·LCD 경로, 1.5m/각도/조도 판독, 만료 후 의도 GIF 복귀, G3 전체 근거 검토. |
| 학습 검수: 원본과 편집 내용을 함께 볼 수 있는가? | [객체 1440px](captures/learning-width/learning-objects-1440.png), [객체 800px](captures/learning-width/learning-objects-800.png), [객체 390px](captures/learning-width/learning-objects-390.png), [픽셀 1440px](captures/learning-width/learning-pixels-1440.png), [픽셀 800px](captures/learning-width/learning-pixels-800.png), [픽셀 390px](captures/learning-width/learning-pixels-390.png) | 두 편집 화면의 캔버스·검수 창을 데스크톱에서 같은 폭으로 맞췄다. 좁은 화면에서는 두 창이 같은 가용 폭으로 쌓이고 가로 넘침이 없다. | 개발 도구의 다른 상태·실제 검수자 G3 독회. 로봇 현장 수용과 별도다. |
| Pilot: 운전·팔 조작 상태와 정지가 보이는가? | [주행 2000×1200](captures/pilot-drive-current-2000x1200.png), [주행 1200×2000](captures/pilot-drive-current-1200x2000.png), [주행 390×844](captures/pilot-drive-current-390x844.png), [전화 회전 조작](captures/pilot-drive-turn-controls-390x844.png), [팔 390×844](captures/pilot-arm/pilot-arm-gripper-390x844.png), [대상 확인 실패 390×844](captures/pilot-target-error-390x844.png) | 현재 트리의 주행 화면에서 카메라 비율·조작부 분리·정지 첫 화면을 확인했다. 390px은 전진·후진과 스틱이 첫 화면에 있으며 회전 조작은 아래 조작 칸에서 스크롤해 닿는다. Gazebo 팔·그리퍼 창은 같은 폭이다. | 선언 상태 전체 G2, 전화에서 회전 조작 발견 가능성 G3, 실제 운전자 독회·장치 readback. 기존 DEVICE 기능 확인을 UI/UX GO로 승격하지 않는다. |

로봇·Fleet 캡처는 FastAPI/Playwright fixture, 게임 캡처는 실제 PreviewServer와 fixture payload를 쓴 LOCAL 증거다. Fleet 전화의 `fleet_console_mobile_{width}.png`는 시험이 **전체 로봇 보기**를 누른 뒤 찍는 캡처여서 기본 예외 목록의 근거로 쓰지 않는다. 기본 목록은 위 `fleet-console-320x844.png`와 해당 브라우저 단언으로 확인했다.

표의 학습 픽셀 390px 저장소 캡처는 편집기 입력 폭을 고치기 전 기록이다. 390/320px의 최신 원본과 검증 범위는 아래 픽셀 결정·자료 준비 단락의 X: 경로를 따른다.

로봇 역할 셸의 `/console`·`/setup`·`/device`를 320×568과 390×844에서 다시 띄웠다. `/console`에서는 조작→감지→관측이 한 열로 쌓이고 세 칸의 시작점·폭이 같으며, 두 폭 모두 첫 화면과 하단 스크롤에서 비상 정지가 보인다. 문서 가로 넘침과 페이지 오류는 0, 브라우저 **2 passed**, `known_failures.py` **0 NEW**다. 320px 첫 화면 원본은 X: `captures/robot-console-320-width/robot-console-320x568.png`에 있다. 이는 정상 fixture의 LOCAL 배치 근거이며 실제 CORE 상태와 작업 완료·G3는 미검증이다.

전방 카메라의 동등한 「영상 확대」·「녹화 중지」 행동도 390px에서 같은 폭으로 맞췄다. 320px에서는 두 행동이 각각 패널의 전폭을 쓰며 쌓인다. 실제 역할 셸의 두 폭에서 렌더된 행동 폭 차이 ≤1px, 가로 넘침 0, 비상 정지 가시성을 확인한 브라우저 **2 passed**, `known_failures.py` **0 NEW**다. 전체 화면 원본은 X: `captures/robot-camera-equal/robot-console-{320x568,390x844}.png`다. 카메라 수신과 녹화의 실제 완료·사용자 독회는 남아 있다.

기존 320px 카메라 폭 캡처의 「로봇 상태」 아래 빈 칸은 첫 상태 수신 전 화면이었다. 첫 상태 전 대기와 오류를 라벨·값 정의 목록 밖의 공용 `ui-status`에 표시하고, 수신 뒤에만 정의 목록을 보인다. 메시지는 390px 패널 전체 폭이며 `role=status`로 상태 변경을 알린다. 독립 패널 원본은 X: `captures/robot-overview-semantic/robot-overview-{pending,error}-390.png`이다. 대기→값→오류 브라우저 **1 passed**, 역할 셸 320/390px과 공용 반응형·조작 계약 **51 passed**, 각 `known_failures.py` **0 NEW**다. 기존 `captures/robot-camera-equal/robot-console-320x568.png`는 카메라 행동 폭 근거만으로 쓰고 상태 수신 근거로 쓰지 않는다. 이 결과는 LOCAL 가짜 상태 콜백이며 실제 CORE 스트림·장치 G3는 HOLD다.

작업 준비·장비 캡처는 같은 FastAPI fixture에서 생성했다. 첫 시도는 고급 네트워크 작업의 닫힌 disclosure 안에 있는 버튼을 바로 찾으려다 시험이 멈췄다. shipped UI대로 disclosure를 열어 비활성 버튼과 이유를 확인했다. 모바일 패널의 실제 내용 폭을 공용 폼의 container query가 읽도록 수정한 뒤 다시 실행해 **60셀 1 passed**, 반응형·셸 브라우저 **18 passed**, 별도 작업 패널 **6장**, `known_failures.py` **0 NEW**를 얻었다. 첫 실패를 제품 결함으로 분류하지 않는다.

첫 기동은 manifest와 CORE 첫 상태 응답을 보류한 별도 fixture다. **6셀 1 passed**, 60셀 재실행 **1 passed**, 각각 `known_failures.py` **0 NEW**였다. 비상 정지의 테스트 판정은 숨겨진 요소의 0폭 좌표가 통과하지 않도록 렌더된 폭을 확인한다. [관리자 장비 390×844](captures/roles-first-boot/administrator-device-first-boot-390x844.png)를 원본 크기로 확인했다.

불가역 확인은 이전 캡처가 대화상자를 닫은 뒤 화면만 남겼으므로 열린 상태를 1366/390px 각 3장씩 다시 찍었다. 맵핑 시작·중지·저장과 호스트 작업의 실행 버튼은 선택한 행동 이름을 말한다. 이 변경 뒤 절차 60셀 **1 passed**, 관련 작업 브라우저 **10 passed**, `known_failures.py` **0 NEW**였다. 6개 확인 셀은 취소 뒤 쓰기 요청이 0이다. 이는 확인창과 취소의 LOCAL 증거이지 실제 명령 완료 증거가 아니다.

운용자 작업 준비의 [웨이포인트 저장 390×844](captures/operator-setup-waypoint-saved-390x844.png)은 현재 FastAPI의 `POST /api/v1/waypoints`가 201을 돌려주고, 다음 목록 조회가 저장된 이름과 좌표를 화면에 표시한 LOCAL 작업 경로다. 브라우저 1 passed, `known_failures.py` 0 NEW였다. 이 테스트 인스턴스의 저장이며 실물 로봇의 위치 정확도는 검증하지 않는다.

Pilot 주행의 선언된 320×568 폭도 현재 트리에서 다시 렌더했다. 첫 화면의 비상 정지·카메라·전진/후진·스틱, 조작 칸을 내린 뒤의 좌/우 제자리 회전을 X: `captures/pilot-current-320/pilot-drive-{current,turn-controls}-320x568.png`에 남겼다. 390×844에서도 회전 버튼 두 개의 렌더 폭 차이 ≤1px이며, 320×568에서도 같은 조건을 직접 검사했다. 카메라 비율·조작 겹침·전화 회전 안내 브라우저 **7 passed**, 추가 동등 폭 검사 **2 passed**, 각 `known_failures.py` **0 NEW**다. 이는 fixture 기반 LOCAL 배치 근거다. 회전 조작의 실제 발견 가능성, 선언 상태 전체, 운전자 G3와 장치 readback은 HOLD다.

### 로봇 운용 G3 독회 — LOCAL 진행 중

| D-153 항목 | 현재 근거 | 남은 판정 범위 |
|---|---|---|
| 1. 정직 | [모드 요청](captures/robot-g3/operator-console-mode-feedback-390x844.png)은 CORE 접수와 현재 모드를 분리한다. [지도 근거 결측](captures/robot-g3/operator-console-map-data-action-390x844.png)은 위치·목표 전송 0이다. | 실제 주행 가능성·물리 정지·지도/자세 readback. |
| 2. 증거 상태 | [수동 운전 상태 읽기 실패](captures/robot-g3/operator-console-teleop-feedback-390x844.png), [차선 추종 읽기 실패](captures/robot-g3/operator-console-line-follow-390x844.png), [도킹 읽기 실패](captures/robot-g3/operator-console-docking-390x844.png)를 요청 접수와 분리했다. | 선언 상태 전체의 값별 fresh/delayed/disconnected/unavailable 전이. |
| 3. 색 | 상태 결측·읽기 실패는 주의색 문구, 비상 정지는 위험색이며 정상 숫자는 중립이다. | 장치 조명·나머지 상태와 대비 독회. |
| 4. 위계 | 데스크톱 [운전 모드](captures/robot-g3/operator-console-mode-feedback-1366x768.png)의 감지·관측·조작은 같은 폭이다. 390px은 조작을 먼저 보이고 세 칸이 가용 폭을 채운다. | 지도보다 긴 카메라 영역이 모바일 작업 발견에 미치는 영향. |
| 5. 불가역 | 모드·차선 추종·도킹의 확인 뒤 요청을 보내며, [지도 근거 결측](captures/robot-g3/console-map-data-action-matrix.json)에서 POST 0이다. 비상 정지는 두 폭 첫 화면에 있다. | 실제 명령·정지 readback, 현장 확인/취소 작업. |
| 6. 어휘 | 영문 서버 오류 설명은 HTTP 상태와 다음 확인을 말하는 한국어로 보이며, 한국어 서버 사유는 유지한다. 테스트 manifest의 도킹·차선 추종 이름도 실제 등록 값과 같다. | 다른 오류·네트워크 실패 문구와 운용자 독해. |
| 7. 표면 질문 | 모드·수동·차선·도킹·지도 결측의 [재생 기록](captures/robot-g3/console-line-follow-docking-matrix.json)은 요청, 읽기 실패, 막힌 조작을 분리한다. | 실물 로봇에서 지금 움직여도 되는지 한눈에 답할 수 있는지. |
| 8. 표면 문법 | 공간형 데스크톱 3열과 모바일 조작→감지→관측 순서를 유지하며 가로 넘침은 0이다. | 모바일 긴 화면의 작업 순서·스크롤 독회. |

모든 항목은 **부분 근거**다. 현재 FastAPI/Chromium의 모드·수동·차선/도킹·지도 시험 **4 passed**, `known_failures.py` **0 NEW**였다. 첫 차선/도킹 시도는 fixture가 실제 버튼 준비 계약인 `teleop: true`·`runtime.drive: ready`를 빼서 막혔다. fixture를 계약에 맞춘 뒤 재실행했다. 이는 LOCAL 요청·화면 증거이고 장치가 움직이거나 멈췄다는 증거가 아니다.

### Fleet G2 상태 확인 — LOCAL 진행 중

대형 진행 중에 상태 조회가 끊긴 뒤 복구되는 흐름을 1920×1080, 390×844, 320×568에서 재생했다. 끊긴 동안 마지막 리더·전송률·지도 대형 표시를 지우고 시작·재구성·재개를 막는다. 원시 `FORMATION_UNAVAILABLE` 코드 대신 Fleet 연결을 확인하라는 안내를 표시한다. 복구 뒤에는 진행 상태와 대형 표시가 돌아온다. 전화 폭에서는 지도·목록·작업 블록의 시작점과 폭 차이가 ≤1px이고, 비상 정지는 첫 화면에 있으며 가로 넘침은 없다. 대형 끊김·복구와 HOLD 브라우저 **4 passed**, `known_failures.py` **0 NEW**. 320px에서 목록을 4px 줄인 변이에는 폭 검사가 실패했고 복원 뒤 통과했다. 원본은 X: `captures/fleet-formation-mobile/fleet_formation_read_{lost,recovered}_{1920,390,320}.png`, 실행 기록은 `logs/fleet-formation-{code-red,width-mutation,final}.txt`다. 이는 fixture 기반 LOCAL G2 일부 근거이며 실제 사이트·운영자 G3는 HOLD다.

| 상태 | 현재 캡처 | 확인 범위 |
|---|---|---|
| 빈 목록 | [1920px](captures/fleet-states/fleet_console_empty.png), [320px](captures/fleet-states/fleet_console_empty_320.png), [390px](captures/fleet-states/fleet_console_empty_390.png) | 등록할 로봇이 없다는 안내, 320/390px E-stop·패널 폭. |
| 서버 실패 | [1920px](captures/fleet-states/fleet_console_gather-error.png), [320px](captures/fleet-states/fleet_console_gather-error_320.png), [390px](captures/fleet-states/fleet_console_gather-error_390.png) | Fleet 상태 확인 불가 안내, 320/390px E-stop·패널 폭. |
| 느린 첫 응답과 회복 | [대기](captures/fleet-states/fleet_console_slow_loading.png), [회복](captures/fleet-states/fleet_console_slow_recovered.png); 1920/390/320px 최신 원본은 아래 X: 경로 | 첫 응답을 기다리는 동안 중복 폴링 없이 회복된 목록을 표시한다. 세 폭에서 지도·로봇 목록 패널 폭이 같고 E-stop이 첫 화면에 남는다. |
| 수신 후 끊김·지연·HOLD | [수신 후 끊김](captures/fleet-states/fleet_console_gather-lost-after-live.png), [팔로워 지연](captures/fleet-states/fleet_console_delayed.png), [대형 HOLD](captures/fleet-states/fleet_console_holding.png); 끊김·지연 320/390px 원본은 아래 X: 경로 | 상태 변화를 화면에 드러낸다. 수신 후 끊김에서는 마지막 좌표·목표 조작을 내리고 320px 머리의 「Fleet 서버 없음」을 끝까지 읽을 수 있다. 320/390px에서 지도·목록 폭과 비상 정지 첫 화면을 유지한다. |
| 로봇 연결 끊김 | [1920px](captures/fleet-states/fleet_console_unreachable.png); 320/390px 원본은 아래 X: 경로 | 실제 Fleet API의 `online: false, state: null` 계약으로 재촬영했다. 이전 fixture의 모순된 좌표·주행 상태를 제거했고, 해당 로봇 카드에 현재 좌표·NAVIGATING이 없음을 단언한다. 320/390px에서는 연결 끊긴 로봇이 목록 첫 카드이며 비상 정지가 화면 안에 남고 가로 넘침이 없다. |
| 안전 상태 결측·비상 정지 | [결측](captures/fleet-g3/fleet_safety_unknown.png), [비상 정지](captures/fleet-g3/fleet_safety_stopped.png) | CORE의 `NAVIGATING` 값이 남아도 주행 중이라는 문구 대신 목표가 남았음을 표시한다. 두 상태 모두 목표 전송은 막힌다. |
| 전체 주행 취소 | 1920/390/320px 확인·부분 응답과 320px 실패 원본은 아래 X: 경로 | 확인 중 비상 정지가 화면 안에 남는다. 취소는 POST 0이고, 전송 뒤 부분 응답 `1/3`·물리 정지 미확인과 로봇별 기록 링크가 행동 옆에 보인다. 503은 취소 결과 미확인과 상태 재확인을 알린다. |
| 전체 비상 정지 | 운용·설치 1920/390/320px 응답과 320px 부분·미확인 원본은 아래 X: 경로 | 한 번 누르면 확인창 없이 POST한다. 응답 `3/3`·`1/3`과 물리 정지 미확인, 503의 결과 미확인·즉시 상태 확인을 머리 바로 아래에서 읽는다. 설치 화면도 비상 정지는 남기고 전체 주행 취소만 운용 화면에 둔다. |

기존 상태 브라우저 **9 passed**, 320/390px 빈 목록·서버 실패 **4 passed**, 연결 끊김 1920/390/320px **3 passed**였고 각 실행의 `known_failures.py`는 **0 NEW**였다. 모바일 연결 끊김 원본은 `X:\DevTemp\projects\rosy-platform\2026-10-06--032913--uiux-quality--199bc9\captures\fleet-unreachable-mobile\`의 `fleet_console_unreachable_320.png`와 `fleet_console_unreachable_390.png`다. 이들은 fixture 기반 화면 검사다. Fleet의 선언 상태 전부와 카메라 연결, 실제 사이트 PC/로봇 readback, G3 사용자 독회는 남아 있어 G2/G3 GO로 판정하지 않는다.

느린 첫 Fleet 상태 응답도 1920×1080·390×844·320×568에서 대기→회복을 재생했다. 대기 1.4초 동안 상태 GET은 1회이고 비어 있는 예외 큐는 숨긴다. 세 폭에서 지도·로봇 목록 칸의 렌더 폭 차이 ≤1px, 가로 넘침 0, 비상 정지 첫 화면을 확인했다. 세 폭 브라우저 **3 passed**, `known_failures.py` **0 NEW**다. 로봇 목록을 4px 좁힌 실제 스타일 변이를 적용한 320px 실행은 폭 단언에서 실패했고, 원복 후 같은 셀 **1 passed**였다. 실행 기록은 X: `logs/fleet-slow-{three-widths,width-mutation,width-restored}.txt`, 원본은 `captures/fleet-slow-mobile/fleet_console_slow_{loading,recovered}_{1920,390,320}.png`다. 이는 fixture 기반 LOCAL G2 부분 근거이며 사이트 PC·로봇 수신 증거가 아니다.

실제 상태를 받은 뒤 다음 Fleet 조회가 실패하는 전환도 1920×1080·390×844·320×568에서 끊김→회복으로 재생했다. 마지막 좌표 `1.00`과 목표 행동을 내리고, 지도와 로봇 목록에 확인 불가를 표시한다. 세 폭에서 지도·목록 폭 차이 ≤1px, 가로 넘침 0, 첫 화면 비상 정지를 확인했다. 320px의 빨간 머리 표지 「Fleet 서버 없음」은 이전에 잘렸고, compact 시계를 보조 글자 단계로 줄여 끝까지 읽히게 했다. 끊김·회복/compact 머리 브라우저 **5 passed**, 공유 시트를 쓰는 설치 화면의 세 폭 정지 회귀 **3 passed**, 반응형·팔레트·토큰 계약 **97 passed**, 각 성공 실행 `known_failures.py` **0 NEW**다. 상태 표지 잘림을 단언한 첫 320px 실행은 실패했고 수정 뒤 통과했다. 목록을 4px 좁힌 스타일 변이도 폭 단언에서 실패했으며 원복 후 같은 셀 **1 passed**였다. 원본은 X: `captures/fleet-loss-mobile/fleet_console_gather_{lost,recovered}_{1920,390,320}.png`, 실행 기록은 `logs/fleet-{gather-loss-three-widths,loss-pill-red,loss-pill-font,loss-current,loss-style-contracts,loss-width-mutation,loss-width-restored,loss-install-estop}.txt`다. 이는 fixture 기반 LOCAL G2 부분 근거이며 실제 사이트 장애·로봇 수신 증거가 아니다.

팔로워 지연도 1920/390/320px **3 passed**, `known_failures.py` **0 NEW**로 다시 확인했다. 모바일 원본은 같은 X: 회차의 `captures\fleet-delayed-mobile\fleet_console_delayed_320.png`와 `fleet_console_delayed_390.png`다. 연결 끊김과 마찬가지로 fixture 기반 LOCAL 근거이며 G2/G3 판정은 HOLD다.

전체 주행 취소의 1920/390/320px 확인→취소/전송→부분 응답과 320px 503 실패, 확인창 중 정지 가용성 회귀는 브라우저 **5 passed**, `known_failures.py` **0 NEW**다. 전후 원본은 같은 X: 회차 `captures\fleet-cancel-all-mobile\fleet_cancel_all_{confirm,result}_{320,390}.png`와 `fleet_cancel_all_failure_320.png`다. 이전에는 로봇별 결과가 긴 기록 아래에만 있어 320px 첫 화면에서 응답을 볼 수 없었다. 현재는 주행 취소 버튼 옆에 응답 요약과 기록 링크가 표시된다. 이는 API fixture의 LOCAL 요청·응답 근거이며 실제 로봇 취소·물리 정지는 미확인이다.

전체 비상 정지도 운용·설치 두 문서의 1920/390/320px 한 번 누름과 320px 부분 응답·503 미확인을 재생했다. 집중 브라우저 **10 passed**, 설치 작업 브라우저 회귀 **7 passed**, Fleet 팔레트·공용 토큰 계약 **52 passed**, 각 `known_failures.py` **0 NEW**이며 원본은 같은 X: 회차 `captures\fleet-estop-feedback\`의 `fleet_estop_result_{index,install}_{1920,390,320}.png`와 `fleet_estop_{partial,unknown}_{index,install}_320.png`다. 이전에는 응답이 긴 기록 칸에만 있었다. 지금은 머리 바로 아래에 요청 중·응답 수·물리 정지 미확인 또는 결과 미확인·즉시 확인 행동을 표시한다. 이 응답은 fixture의 API 결과일 뿐 실제 정지 readback이 아니다.

비상 정지 응답과 관제 준비 순서의 좌우 끝을 본문 패널의 가용 폭에 맞췄다. 이전 320px 응답은 본문보다 양쪽 4px씩 좁았다. 운용·설치 1920/390/320px의 렌더된 좌우 끝과 가로 넘침을 확인한 브라우저 **6 passed**, 팔레트·토큰 계약 **52 passed**, 각 `known_failures.py` **0 NEW**다. 같은 X: 회차 `captures\fleet-width\fleet_estop_result_{index,install}_{1920,390,320}.png`가 최종 원본이다. 접속 안내도 같은 여백 규칙을 쓴다.

로봇 카드의 동등한 「목표 지정」·「취소」 버튼이 글자 길이와 관계없이 같은 폭을 쓰도록 했다. 320/390px에서 두 버튼의 렌더된 폭 차이 ≤1px, 가로 넘침 0을 단언했다. 1920px 전체 높이 검사에서 남아 있던 5px 세로 넘침은 본문 하단 여백을 줄여 해소했다. Fleet 브라우저 **6 passed**, `known_failures.py` **0 NEW**다. 전화 원본은 같은 X: 회차의 `fleet_console_mobile_default_{320,390}.png`다. 공유 `main`의 동일 높이 검사는 15px 넘침으로 실패했으므로, 이 결과는 브랜치의 LOCAL 개선이며 현장 판정은 아니다.

설치 화면의 카메라 연결 승인 제목 아래에 건너뛴 `h5` 수준도 `h3`/`h4`로 정리했다. 글자 크기와 간격은 기존 토큰 값을 유지한다. 이는 문서 구조 수정이며 화면 사용성·현장 수용 판정은 위 상태 근거와 별개다.

### Fleet Cell 작업 G2/G3 — LOCAL 부분 근거

`shared/web/surfaces.yaml`의 활성 `console`은 사이트 관제·설치와 함께 `/console/cell`의 문서 준비·작업 제안도 소유한다. 이 회차의 Cell 질문은 **운영자가 레시피·셀 문서를 준비하고 미리보기·제안·승인·HOLD·취소의 상태와 사이트 정지 경계를 구분할 수 있는가**다. 선언 뷰포트는 1440×1000, 390×844, 320×568이다. 이전 점검에서는 이 경로가 카드에서 빠져 있었다.

현재 트리의 첫 화면은 X: `captures/fleet-cell/fleet-cell-initial-{1440x1000,390x844,320x568}.png`에 있다. 처음에는 세 폭 모두 비상 정지가 없었고 집중 브라우저 3건이 실패했다(X: `logs/fleet-cell-estop-red.txt`). 지금은 세 폭 모두 첫 화면에 즉시 요청 버튼이 있고, 320px에서 부분 응답 `1/3`과 물리 정지 미확인·503 결과 미확인을 서로 다른 상태로 보인다(X: `captures/fleet-cell/fleet-cell-estop-{partial,unknown}-320x568.png`). 기존 Console 세션 토큰을 이어 받아 요청하며, 결과 상태 칸은 본문 패널과 같은 폭이다. Cell 브라우저 전체 **13 passed**, 상태 칸 폭 집중 **1 passed**, 각 성공 실행의 `known_failures.py` **0 NEW**다. Chromium이 임시 포트 6566을 차단한 첫 상호작용 실행은 앱 진입 전 오류였고, 새 포트에서 같은 검사가 통과했다.

작업 취소는 기존에 첫 클릭으로 요청을 보냈다. 지금은 작업 ID와 「실행 중인 장치를 정지하지 않습니다」 경고를 확인창에 표시한다. 1440×1000·390×844·320×568에서 취소 버튼을 누르고 확인창을 캡처했다(X: `captures/fleet-cell/fleet-cell-cancel-confirm-{1440x1000,390x844,320x568}.png`). 확인창의 취소는 POST 0, 비상 정지는 확인창을 닫고 즉시 누를 수 있으며, 「작업 취소」 확인 뒤에는 취소 POST 1이다. 320px에서는 로그인 뒤 긴 세션 이름이 비상 정지와 제품 이름·접속 버튼을 밀어 겹치던 문제도 머리의 좁은 폭 격자로 고쳤다. 세 폭 브라우저 **3 passed**, Cell 브라우저 전체 **15 passed**, Fleet 계약 **21 passed**, 현재 트리 G1 **90 passed**, 각 성공 실행의 `known_failures.py` **0 NEW**다. Cell의 새 공용 확인 모듈을 수입 허용 목록에 반영하기 전에는 계약 1건이 실패했고, 반영 뒤 재실행에서 통과했다. 원본은 X: `logs/fleet-cell-cancel-{3widths-final,full-final,contracts-final}.txt`, `logs/g1-after-cell-cancel.txt`다. 이 경로는 로컬 Cell API와 합성 Fleet 응답의 UI 근거이며 실제 장치 정지는 검증하지 않았다.

저장된 문서 목록의 접속 전·조회 중·빈 목록·조회 실패·다시 접속·문서 존재 상태를 로컬 브라우저에서 재생했다. 1440×1000·390×844·320×568의 빈 목록은 다음 작성 단계를 표시하고 가로 넘침이 없었다. 320px에서 목록 API 503은 실패와 재시도를 알리며, 복구 후 문서 두 개가 보인다. 자격 증명을 바꾸면 이전 접속의 목록을 즉시 숨긴다. 해당 브라우저 **5 passed**, Cell 전체 **19 passed**, Cell API **8 passed**, 공용 UI 계약 **231 passed, 25 skipped**, 각 성공 실행의 `known_failures.py` **0 NEW**다. 원본은 X: `captures/fleet-cell/fleet-cell-empty-{1440x1000,390x844,320x568}.png`, `fleet-cell-list-error-320x568.png`, 실행 기록은 `logs/fleet-cell-list-{focus,full,api,shared}.txt`다. 합성 서버 응답에 대한 LOCAL G2 부분 근거다.

이미 접속한 Cell에서 세션 재확인이 401·403으로 거부될 때, 이전 계정·저장 문서 목록·저장 버전·미리보기 요약·작업 상태를 내려 현재 근거로 오인하지 않게 했다. 운영자 작성 초안은 남기되 저장·제안은 막고, 320px 첫 화면에 권한 확인과 재접속 안내를 표시한다. 거부 전 상태를 가진 로컬 브라우저 2셀을 재생했고 가로 넘침 0이다. Cell 브라우저 전체 **21 passed**, Cell API **8 passed**, 공용 UI 계약 **231 passed, 25 skipped**, 마지막 접속 안내 변경의 집중 재검사 **3 passed**, JS 구문 검사 통과, 각 성공 실행의 `known_failures.py` **0 NEW**다. 원본은 X: `captures/fleet-cell/fleet-cell-auth-{401,403}-320x568.png`, 실행 기록은 `logs/fleet-cell-auth-{focus-final,full,api,shared,final-focus}.txt`다. 이는 권한 거부 전환의 LOCAL G2 부분 근거이며 실제 계정 만료·권한 변경 검증은 남는다.

동등한 레시피·셀 문서 창은 1440×1000에서 같은 폭으로 나란히 놓이고 390×844·320×568에서 같은 가용 폭으로 쌓인다. compact의 문서·미리보기·제안·승인·복귀 행동도 각 행동 칸의 전폭을 쓴다. 기존에는 390/320px의 「불러오기」가 82px에 머물러 272px 칸을 채우지 못했고, 「미리보기」도 제목 옆의 좁은 버튼이었다. 먼저 Cell 전체 **24 passed**, 공용 UI 계약 **231 passed, 25 skipped**를 확인했다. 미리보기 폭을 마지막으로 맞춘 뒤 세 폭 기하 검사 **3 passed**, 미리보기·취소 상호작용 **4 passed**, 각 성공 실행의 `known_failures.py` **0 NEW**다. 전체 페이지 원본은 X: `captures/fleet-cell/fleet-cell-widths-{1440x1000,390x844,320x568}.png`, 실행 기록은 `logs/fleet-cell-{uniform-full,uniform-shared,uniform-widths-final,uniform-interaction}.txt`다. 긴 전화 화면에서 실제 작업 흐름을 찾는 G3 검토는 남는다.

저장한 레시피를 수정하면 이전 「저장된 버전」 대신 저장 전 초안임을 표시한다. 저장 409 충돌은 작성 내용 복사→최신 문서 불러오기→내용 재적용→저장 순서를 알리고, 컴파일 503은 이전 미리보기 결과를 내리고 결과 미확인·재확인을 표시한다. 두 상태를 1440×1000·390×844·320×568에서 재생하고 로컬 상태 칸이 각 패널 폭을 채우며 제안이 막히는지 확인했다. 320px 저장 503도 결과 미확인으로 구분했다. Cell 전체 **31 passed**, Cell API **8 passed**, 공용 UI 계약 **231 passed, 25 skipped**를 확인한 뒤, 문서가 아직 저장되지 않아 미리보기를 시작할 수 없는 세 폭을 별도 문구로 **3 passed** 재검사했다. JS 구문 검사 통과, 각 성공 실행의 `known_failures.py` **0 NEW**다. 원본은 X: `captures/fleet-cell/fleet-cell-{save-conflict,preview-unavailable}-{1440x1000,390x844,320x568}.png`, `fleet-cell-save-unavailable-320x568.png`; 실행 기록은 `logs/fleet-cell-{write-final-focus,save-unavailable,write-full,write-api,write-shared,preview-precondition}.txt`다. 합성 응답의 LOCAL G2 부분 근거이며 실제 충돌·장치 실행을 검증하지 않는다.

G2는 실제 첫 기동, 증거 `fresh/delayed/disconnected/unavailable`의 나머지 경로, 권한 거부와 저장/컴파일 실패의 나머지 경로, SAFE_STOP/HOLD의 나머지 선언 폭별 캡처가 남았다. G3 여덟 항목의 실제 운영자 작업 독회와 셀 장치·물리 정지 readback도 없다. 이 Cell 카드와 Fleet 전체는 **HOLD**다. Cell 화면의 정지 API 응답은 물리 정지 증거가 아니다.

### Fleet G3 독회 — LOCAL 진행 중

| D-153 항목 | 현재 근거 | 남은 판정 범위 |
|---|---|---|
| 1. 정직 | [안전 상태 결측](captures/fleet-g3/fleet_safety_unknown.png)·[비상 정지](captures/fleet-g3/fleet_safety_stopped.png)에서 목표 전송을 막고 `NAVIGATING`을 물리적 주행으로 표현하지 않는다. 전체 주행 취소 부분 응답도 물리 정지 미확인으로 표시한다. | 다른 조작의 상태 가용성과 실제 CORE readback. |
| 2. 증거 상태 | 느린 첫 응답, 수신 후 끊김, 로봇 연결 끊김, 안전 결측을 위 G2 캡처로 구분했다. | 각 값의 정상·지연·끊김·결측 전이 전체. |
| 3. 색 | 정상 카드는 중립이고 안전 정지는 빨강, 영상 연결 불가는 주의색이다. | 다른 경보·현장 조명. |
| 4. 위계 | [목표 확인창](captures/fleet-g3/fleet_goal_confirm_open.png)에서 보고 영역은 뒤로 물러나고 전송 선택이 올라온다. | 긴 목록과 현장 관제자의 시선 이동. |
| 5. 불가역 | [목표 선택](captures/fleet-g3/fleet_goal_preconfirm.png)→[로봇·좌표 확인](captures/fleet-g3/fleet_goal_confirm_open.png)→취소를 재생했고 취소 전송 0을 단언한다. 전체 주행 취소도 3폭에서 취소 POST 0과 결과 가시성을 확인했다. 비상 정지는 Accepted D-414의 즉시 접근 예외로 확인창 위에 남고, 운용·설치 모두 한 번 누름 뒤 응답을 첫 화면에서 읽는다. | 실제 목표·정지·전체 취소 readback과 현장 절차. |
| 6. 어휘 | 탐색 상태를 원시 `NAVIGATING` 대신 `목표 활성`/`목표 남음`으로 구분한다. | 나머지 메시지의 운용자 독해. |
| 7. 표면 질문 | 320px 기본 예외 목록에서 오류 로봇이 먼저 나오고 결측·정지 카드에서 개입 불가 이유가 보인다. | 현장 관제자가 여러 로봇의 다음 행동을 고르는 작업. |
| 8. 표면 문법 | 기본 목록은 주의가 필요한 로봇부터 보여 주며 전체 목록은 별도 선택이다. | 모든 선언 상태에서 정상 숨김과 예외 우선순위. |

여덟 항목 모두 **부분 근거**다. 이번 변경의 Fleet 브라우저 **3 passed**, Fleet 서버·팔레트 **60 passed**, Fleet 웹 Node **134 passed**, 각 Python 실행의 `known_failures.py` **0 NEW**였다. 실제 사이트 PC·카메라·로봇 readback과 현장 사용자 독회가 없어 G3는 HOLD다.

### 게임 보드 G3 독회 — LOCAL 진행 중

| D-153 항목 | 현재 근거 | 남은 판정 범위 |
|---|---|---|
| 1. 정직 | [최초](captures/games-initial-1280x800.png)는 점수를 `—`로 두고 피치에 대기를 말한다. [첫 연결 오류](captures/games-g3/games_board_first_error.png)는 이전 경기 정보가 있는 척하지 않는다. | 실제 카메라·로봇값의 결측과 정지 readback. |
| 2. 증거 상태 | 최초 대기, [지연](captures/games-delayed-1280x800.png), [수신 후 연결 오류](captures/games-g3/games_board_host_disconnected.png)를 구분한다. 지연은 마지막 생성 나이를, 끊김은 현재 위치가 아님을 말한다. | 선언 상태와 각 값의 전이 전체. |
| 3. 색 | 최초 대기는 중립 테두리, 연결 오류·정지는 위험색, 지연은 주의색이다. 경기장·공 팔레트는 고정 시각화 색이다. | 실제 조명에서 경고와 공 색의 구분, 나머지 상태. |
| 4. 위계 | 1280px 피치가 관측 카드보다 넓고, 390px에서는 같은 가용 폭으로 쌓인다. 정지는 첫 화면에 있다. | 노트북 현장 관찰과 정보량 많은 관측. |
| 5. 불가역 | [정지 실패·재시도](captures/games-g3/games_board_stop_retry.png)는 요청 실패를 알리고 재시도를 허용한다. 성공 문구도 요청 접수와 실제 정지 확인을 구분한다. D-306의 게임 정지 즉시 실행 예외를 유지한다. | 실제 두 로봇 정지 readback과 현장 조작. |
| 6. 어휘 | 대기·지연·연결 오류·정지 결과를 한국어 평문으로 말한다. | 게임 호스트 운용자의 독해. |
| 7. 표면 질문 | [진행](captures/games-play-1280x800.png)은 점수·피치·로봇·공을 보이고, 결측에는 답을 아는 척하지 않는다. | 실물 경기 관측과 모든 선언 상태. |
| 8. 표면 문법 | `game-board`의 focal 문법에 따라 피치를 초점으로 두고, 정지 행은 1280/390px 첫 화면에 남는다. | 실제 노트북 사용 환경의 시선·거리. |

여덟 항목 모두 **부분 근거**다. 현재 트리의 게임 보드 브라우저 **19 passed**, 게임 모듈 **113 passed**, `known_failures.py` **0 NEW**다. 캡처는 PreviewServer와 fixture payload의 LOCAL 증거이며 G3 GO나 실제 정지 증거가 아니다.

추가로 320×568에서 최초 대기와 지연 상태를 확인했다. 점수·피치·관측 패널의 시작점과 폭이 각각 같고, 가로 넘침 없이 정지가 첫 화면에 남는다. 두 브라우저 시험의 4개 셀은 통과했고 `known_failures.py`는 0 NEW다. 원본 캡처는 `X:\DevTemp\projects\rosy-platform\2026-10-06--032913--uiux-quality--199bc9\captures\game-320\games_board_initial_320x568.png`와 같은 폴더의 `games_board_delayed_320x568.png`에 있다. 이 fixture 검사는 실제 경기·정지 readback이나 전체 G2/G3 판정이 아니다.

진행 중인 320×568/390×844 보드에서도 세 패널의 시작점·폭, 마커 칩 넘침, 첫 화면 정지를 검사했다. 320px 캔버스에서는 기존 공 반지름 7 내부 픽셀이 화면상 약 2.6px에 불과했다. 현재는 공 반지름을 화면상 최소 5px로, 로봇 표식·이름을 캔버스 표시 배율에 맞춰 그린다. 노트북 720px에서는 기존 크기다. 전후 원본은 X: `captures/games-live-width/`와 `captures/games-live-markers-final/`에 있으며, 진행·좁은 폭 브라우저 **3 passed**, `known_failures.py` **0 NEW**다. D-101의 운영 대상은 노트북이므로 전화 캡처는 추가 LOCAL 가독성 근거이며 실물 경기·운영자 G3는 HOLD다.

첫 연결 실패와 경기 수신 후 연결 끊김도 320×568/390×844에서 재생했다. 두 상태·두 폭 모두 점수·피치·관측 패널의 시작점과 폭 차이 ≤1px, 문서 가로 넘침 0, 연결 문구의 가로 잘림 0, 첫 화면의 정지를 확인했다. 첫 실패는 점수를 `—`로, 수신 후 끊김은 마지막 점수와 「현재 위치 아님」을 표시한다. 패널 폭을 일부러 줄이면 320px 검사가 실패했고 되돌린 뒤 브라우저 **2 passed**, `known_failures.py` **0 NEW**였다. 원본은 X: `captures/game-recovery-mobile/games_board_{first_error,lost_after_live}_{320x568,390x844}.png`다. 이는 PreviewServer와 fixture payload의 LOCAL 복구 화면 근거로, 실제 경기·카메라·정지 readback 또는 G3 판정은 아니다.

학습 검수는 D-461의 병렬 원본·inspector 구조를 유지하면서 두 편집 창의 너비만 같게 했다. 현재 로컬 Chromium의 객체 작업 브라우저 **10 passed**, 픽셀 작업·반응형 계약 **14 passed**, 각 `known_failures.py` **0 NEW**였다. 1440/800/390px에서 두 창 너비와 가로 넘침을 검사했다. 이 캡처는 합성 검수 자료를 사용한 개발 도구 LOCAL 증거다.

390px 검수 화면에서는 두 창의 폭은 같아도 작업 버튼이 내용 길이만큼만 차지했다. 객체·픽셀 편집 칸을 컨테이너로 선언하고, 24rem 미만에서는 기존 공용 `ui-actions` 동작처럼 버튼을 각 칸의 전폭으로 쌓았다. 현재 Chromium 측정에서 두 칸의 폭은 각각 358px, 첫 작업 버튼도 각각 358px이고 가로 넘침은 0이다. 객체·픽셀 1440/800/390px 브라우저 6건과 반응형 계약 9건 **15 passed**, `known_failures.py` **0 NEW**다. 전후 캡처는 X: `captures/learning-width-container{,-final}/learning-{objects,pixels}-390.png`에 둔다. 실제 검수자 G3 독회는 남는다.

24rem 이상 편집 칸의 작업 버튼도 기존 24rem 컨테이너 경계에서 두 개의 동등 폭 열로 정렬했다. 800px 픽셀 화면에서 내용 길이에 따라 제각각 감기던 버튼 폭이 같아졌고, 1440/800/390/320px의 두 편집 경로 **8 passed**, 800px 연결 끊김·권한 거부·응답 보류·저장 충돌 등 **16 passed**, 각 `known_failures.py` **0 NEW**다. 원본은 X: `captures/learning-actions-equal/`에 둔다. 캡처의 픽셀 영상은 합성 fixture이며 실제 검수 결과·G3 수용은 남는다.

픽셀 검수의 사진 이동은 390px에서 이전 249px·다음 86px로 달라져 긴 비활성 이유가 이동 칸을 밀었다. 현재는 사진·상태 선택을 각 전폭으로 놓고 이전·다음을 173px씩, 최신 내용 불러오기를 358px로 놓는다. 320px도 같은 구조이며 가로 넘침이 없다. 객체·픽셀 1440/800/390/320px와 반응형 계약 **17 passed**, `known_failures.py` **0 NEW**다. 최종 캡처 `learning-nav-final/learning-pixels-{390,320}.png`는 같은 X: `captures/`에 둔다. 실제 검수자 작업 독회는 남는다.

객체 검수의 빈 필터 상태를 1440·800·390px에서 추가 재생했다. 처음에는 `.workspace`의 자동 여백 때문에 데스크톱 내용이 좁은 열에 모이고 작은 화면의 작업 목록이 머리 아래로 밀렸다. 현재는 작업 영역이 가용 폭을 채우고 머리 바로 아래에서 시작한다. 세 폭 모두 가로 넘침 없이 「전체 사진 보기」로 검수 화면에 복귀한다. 현재 트리의 객체 브라우저 **13 passed**, `known_failures.py` **0 NEW**이며 캡처 원본 `learning-objects-empty-{1440,800,390}.png`는 X: `2026-10-06--032913--uiux-quality--199bc9/captures/`에 둔다. 이는 빈 상태의 LOCAL G2 부분 근거다.

작업 목록(`/learning`)과 자료 등록(`/catalog`)도 같은 자동 세로 여백으로 짧은 내용이 머리 아래에서 밀렸다. `.learning-main`을 가로 방향으로만 가운데 정렬해 두 경로가 머리 바로 아래에서 시작하게 했다. 두 경로 × 1440·800·390px **6 passed**, 가로 넘침 0, `known_failures.py` **0 NEW**다. 전후 측정은 `X:\DevTemp\projects\rosy-platform\2026-10-06--032913--uiux-quality--199bc9\logs\learning-pages-{baseline,three-widths}.txt`, 최종 캡처는 같은 X:의 `captures/learning-{learning,catalog}-{1440,800,390}.png`다. 실제 자료 등록·작업 연결의 G3는 남는다.

두 경로의 작업영역 응답 보류·403 거부·다시 확인을 1440/800/390px에서 재생했다. 응답 전에는 연결·등록 입력과 행동을 막고 현재 확인 중임을 표시한다. 거부되면 오래된 작업 수·목록을 내려 권한 확인과 재시도를 보이며, 390px의 등록 시도 403은 누른 자리의 화면 안에 이유를 표시한다. 권한을 다시 읽으면 입력·행동이 열린다. API 응답을 지연·거부로 대체한 LOCAL 브라우저 **8 passed**, 기존 두 경로 배치 회귀 **6 passed**, 각 `known_failures.py` **0 NEW**다. 원본은 같은 X: `captures/learning-pages-load/learning-{learning,catalog}-{waiting,denied}-{1440,800,390}.png`와 `learning-{learning,catalog}-submit-denied-390.png`다. 실제 권한 부여·파일 등록 완료와 검수자 G3는 남는다.

네 경로의 작업영역 API가 HTML 본문의 503을 돌려주는 경우를 1440/800/390px에서 재생했다. 응답 상태를 JSON 파싱 전에 확인해 연결 끊김·권한 거부와 다른 「서비스를 사용할 수 없습니다」 및 복구 후 재시도를 표시하고, 편집·등록 입력은 막는다. 390px 객체 검수와 자료 등록의 다시 확인 버튼은 가용 폭을 채운다. 학습 작업은 같은 실패 문구를 두 번 표시하지 않는다. 503 12셀과 기존 연결 끊김·권한 경로를 묶은 브라우저 **24 passed**, 마지막 390px 503·빈 필터 **5 passed**, 각 `known_failures.py` **0 NEW**다. 원본은 X: `captures/learning-unavailable/learning-{objects,pixels,learning,catalog}-unavailable-{1440,800,390}.png`에 있다. 이는 LOCAL 가짜 응답 근거이며 실제 서버 장애와 검수자 G3는 남는다.

픽셀 검수의 결과 없는 필터에서도 이전 사진 제목·상태와 빈 사진 선택기가 남아 있던 것을 발견했다. 현재는 「픽셀 승인 0장 · 필터 결과가 없습니다」를 표시하고 사진 선택·이전/다음 이동을 숨긴다. 「전체 보기」로 원래 검수 화면에 복귀한다. 1440·800·390px 빈 상태 **3 passed**, 관련 픽셀 브라우저 **11 passed**(이동 버튼 숨김 전), 최종 빈 상태 재검사 **3 passed**, 각 실행의 `known_failures.py` **0 NEW**다. 최종 캡처 `learning-pixels-empty-{1440,800,390}.png`는 같은 X: `captures/`에 둔다. 이는 합성 자료의 LOCAL G2 일부와 G3 정직 항목의 부분 근거이며 실제 검수자 작업 수용은 남는다.

등록된 사진이 0장인 최초 사용 상태는 필터 결과 없음과 분리했다. 객체 검수는 로딩 화면 대신 「등록된 사진이 없습니다」와 「자료 등록 열기」를 보이며, 픽셀 검수도 빈 필터와 이전/다음 이동을 숨기고 같은 다음 단계로 간다. 390px에서 두 경로를 재생하고 자료 등록으로 실제 이동했다. 현재 트리의 객체·픽셀 회귀 브라우저 **24 passed**, `known_failures.py` **0 NEW**다. 최종 캡처 `learning-{objects,pixels}-first-use-390.png`는 같은 X: `captures/`에 둔다. 이는 합성 저장소를 비운 LOCAL 최초 사용 근거이며 실제 자료 등록·승인 작업의 G3는 남는다.

작업 목록 API 연결을 끊은 객체·픽셀 검수 화면에서는 로딩 표시와 오래된 편집 내용을 내리고 실패 이유·재시도를 보여 준다. 1440·390px 두 경로의 초기 실패·복구 4셀과 390px에서 정상 표시 후 새로고침 실패·복구 2셀, 브라우저 **6 passed**, `known_failures.py` **0 NEW**다. `learning-{objects,pixels}-disconnect-{1440,390}.png` 원본은 같은 X: `captures/`에 둔다. 이는 LOCAL 연결 끊김 G2 일부와 D-153 정직·증거 상태의 부분 근거다. 지연 시간은 아직 별도 셀이 필요하다.

다른 탭의 저장과 충돌한 객체·픽셀 검수도 1440·390px에서 재생했다. 현재 편집의 되돌리기·승인을 막고 충돌 이유와 「최신 내용 불러오기」를 표시하며, 390px에서 복구 버튼은 화면 폭의 80% 이상이고 가로 넘침이 없다. 다시 불러온 뒤 서버의 새 revision을 읽는다. 브라우저 **4 passed**, `known_failures.py` **0 NEW**다. 원본은 같은 X: `captures/learning-conflict-mobile/learning-{objects,pixels}-conflict-{1440,390}.png`에 둔다. 합성 저장소의 LOCAL 충돌·복구 근거이며 실제 검수자 G3는 남는다.

객체·픽셀 검수에서 API의 403 권한 거부를 1440/390px에서 별도로 재생했다. 작업영역을 다시 읽을 때는 오래된 편집 내용을 내리고 권한 확인·재시도를 표시한다. 자료 준비가 거부되면 해당 버튼 옆에 이유를 표시하고 화면 안으로 가져오며, 편집·자료 준비를 막는다. 권한이 복구된 뒤 최신 작업영역을 다시 읽으면 조작이 돌아온다. 두 경로 × 두 폭의 권한 브라우저 **4 passed**(결과의 실제 화면 내 가시성 포함), 관련 객체·픽셀 브라우저 전체 **43 passed**, 각 `known_failures.py` **0 NEW**다. 브라우저 라우트가 실제 서버의 403 응답 모양을 주입한 LOCAL 근거이고, 원본은 같은 X: `captures/learning-permission/learning-{objects,pixels}-{workspace,prepare}-denied-{1440,390}.png`다. 실제 검수자 권한·작업 완료의 G3는 남는다.

작업영역 응답을 보류한 객체·픽셀 1440/390px의 첫 기동과 다시 읽기도 확인했다. 보류 중에는 이전 편집을 내리고 「검수 내용을 확인하는 중」과 현재 작업 불가를 표시한다. 응답을 받으면 같은 화면에서 편집·자료 준비를 다시 열며, 브라우저 **4 passed**, `known_failures.py` **0 NEW**다. 원본은 같은 X: `captures/learning-waiting/learning-{objects,pixels}-waiting-{1440,390}.png`다. 관련 객체·픽셀 전체 실행은 **46 passed, 1 setup ERROR**였다. 오류는 브라우저가 fixture의 임의 포트 6697을 `ERR_UNSAFE_PORT`로 거부해 페이지 로드 전 발생했고, 해당 단일 셀 재실행은 **1 passed**, `known_failures.py` **0 NEW**였다. 따라서 이 전체 실행을 무오류 통과로 쓰지 않는다. 현재 트리에서 800px을 포함한 객체·픽셀 × 1440/800/390px 보류 **6 passed**, 가로 넘침 0, **0 NEW**를 확인했다. 원본은 같은 X: `captures/learning-waiting-current/learning-{objects,pixels}-waiting-{1440,800,390}.png`, 실행 기록은 `logs/learning-waiting-3widths.txt`다. 이 상태는 보류된 LOCAL 응답 근거이며 실제 검수자 G3는 남는다.

800px 픽셀 보류 화면에서 같은 「검수 내용을 확인하는 중」이 상태 줄과 빈 상태 제목에 중복됐다. 응답 대기 중에는 빈 결과 칸을 숨기고 상태 줄만 남겼다. 503 오류 때는 다시 빈 결과 칸의 제목과 재시도 버튼이 나타난다. 객체·픽셀 보류와 네 경로의 503 복구를 800px에서 브라우저 **6 passed**, `known_failures.py` **0 NEW**로 확인했다. 변경 뒤 화면은 X: `captures/learning-load-clean-final/learning-pixels-waiting-800.png`, 실행 기록은 `logs/learning-load-clean-800-final.txt`다. 이는 LOCAL 문구·상태 개선이며 검수자 G3는 남는다.

객체·픽셀 검수의 결정 결과를 합성 원본으로 끝까지 재생했다. 객체는 제외→재검수→전체 확인→승인→자료 준비, 픽셀은 제외→재검수→전체 채우기→전체·배경 확인→승인→자료 준비 순서다. UI 상태와 저장소 상태를 각 전이에서 대조하고 제외·승인·준비 결과를 따로 캡처했다. 객체 1440/800/390/320px과 픽셀 1440/800/390px **7 passed**, `known_failures.py` **0 NEW**다. 390/320px 객체 화면에서는 짧은 한 행에 눌리던 세 사진 이동 버튼을 각각 같은 가용 폭으로 쌓았다. 원본은 X: `captures/learning-decision-result/learning-{objects,pixels}-{excluded,approved,decision-result}-{1440,800,390,320}.png`(픽셀 320px 셀 없음)에 있다. 이 결과는 LOCAL 합성 자료이며 실제 검수자의 원본 판단·자료 등록/학습 수용을 증명하지 않는다.

픽셀 결정·자료 준비의 320px 셀도 추가했다. 사진 이동 칸의 같은 폭을 유지하면서, 편집기의 픽셀 클래스·브러시 반지름·허용치 방식·허용치·겹쳐 보기 입력을 390/320px에서 각각 가용 칸의 전폭으로 맞췄다. 기존 compact CSS 선택자는 사진 이동 칸에만 닿고 편집기 안의 입력 묶음에는 닿지 않았다. 수정 후 두 폭의 집중 브라우저 시험 **2 passed**, 픽셀 브라우저 전체 **11 passed**, 각 `known_failures.py` **0 NEW**이며 320px 이전·다음 이동 칸도 같은 폭으로 재확인했다. 원본은 같은 X: 회차의 `captures/learning-pixels-width-final/learning-pixels-decision-result-{390,320}.png`다. 합성 원본의 LOCAL 화면·작업 근거이며 실제 검수자 수용은 남아 있다.

자료 등록은 합성 검증 폴더를 실제 로컬 서버에 제출한 뒤 새 사진 1장·중복 표현 1개·픽셀 검수 대기 1장의 결과와 저장소 상태를 대조하고, 「객체 검수 대기」를 눌러 새 대기 사진까지 이동했다. 390px에서 입력·등록 행동은 같은 폭의 나란한 칸이고, 320px에서는 둘 다 가용 폭으로 쌓이며 버튼 높이는 정상 조작 크기다. 새 대기 사진 카드도 320px에서 목록의 전폭을 쓰고 상태 문구가 한 줄에 남는다. 집중 브라우저 **2 passed**, `known_failures.py` **0 NEW**; 결과·다음 화면 원본은 같은 X: 회차 `captures/learning-import-final3/learning-import-{result,pending}-{390,320}.png`다. 합성 자료의 LOCAL 작업 근거이며 실제 입력 자료와 검수자 G3는 남아 있다.

Pilot 팔 화면은 카메라 없는 Gazebo fixture에서 빈 영상 자리 때문에 두 조작 창이 오른쪽 좁은 칸에 2:1로 압축됐다. 현재 CSS는 영상이 없을 때 조작부를 먼저 배치하고 동등한 팔·그리퍼 창을 같은 폭으로 쓴다. 영상이 있으면 영상·조작부 병렬 구조를 유지한다. 태블릿 2종·전화·영상 있는 경로의 브라우저 **5 passed**, `known_failures.py` **0 NEW**였다. 명령 경로는 가짜 CORE fixture이며 실기 조작 증거가 아니다.

영상이 있는 Pilot 팔 화면의 병렬 작업 공간과 조작 칸도 같은 폭으로 맞췄다. 2000×1200 브라우저에서 두 칸의 실제 너비 차이는 1px 이하이고, 2000×1200·1200×2000·390×844 조작 배치와 영상 경로의 집중 시험은 **4 passed**, `known_failures.py` **0 NEW**다. 영상 fixture의 이미지는 비어 있어 영상 내용의 가독성 근거가 아니며, 원본은 X: `captures/pilot-arm-equal/`에 있다. 실제 태블릿·로봇과 사용자 G3는 HOLD다.

Pilot 대상 발견 오류에서는 내부 `invalid simulation target`을 운용자에게 그대로 보여 주던 경로를 없앴다. [390px 캡처](captures/pilot-target-error-390x844.png)는 조종 대상 확인, 연결 점검, 다시 확인 버튼과 첫 화면 비상 정지를 보여 준다. 현재 트리의 브라우저 재시도 1 passed, 가로 넘침 0, `known_failures.py` 0 NEW다. 실제 Pilot Android 셸과 장치 연결의 품질 판정은 이 웹 fixture로 대신하지 않는다.

현재 트리의 Pilot 주행 화면을 2000×1200·1333×760·1200×2000·390×844에서 다시 재생했다. 390px 원본은 회전 버튼이 고정 높이 조작 칸 아래에 잘려 있었다. 지금은 영상 면적을 유지하면서 전진·후진을 첫 화면에 두고 회전 버튼을 조작 칸 안에서 스크롤해 접근한다. [첫 화면](captures/pilot-drive-current-390x844.png)과 [회전 버튼](captures/pilot-drive-turn-controls-390x844.png)을 나눠 보관했다. 영상·조작 배치 4 passed, 스틱·페달 접촉 2 passed, `known_failures.py` 0 NEW다. 이 재실행에서 발견된 스트림 재시도 타이머의 런타임 오류도 수정해 페이지 오류 0으로 확인했다. 좁은 화면에서 회전 버튼 발견이 쉬운지와 실제 운전자의 손 위치는 G3에서 남는다.

Pilot 390×844에서 회전 조작을 첫 화면에 올리려고 아래 조작 칸 높이를 `38dvh`에서 `45dvh`로 키운 **임시 실험은 채택하지 않았다**. 회전 버튼은 일부 드러났지만 카메라 실제 표시 면적이 화면의 `0.126`으로 줄어 `>0.2` 영상 계약 시험이 실패했다(4셀 중 전화 1 failed). 원래 `38dvh`로 되돌린 같은 4셀 시험은 **4 passed**, `known_failures.py` 0 NEW다. 실패 화면은 X: `captures/pilot-height/pilot-drive-current-390x844.png`, 시험 로그는 X: `logs/pilot-height-{pytest,reverted-pytest}.txt`에 둔다. 회전 조작 발견 가능성을 개선하려면 영상 높이를 빼는 방식 대신 고정된 조작 칸 안의 모드·페달·회전 배치를 검토해야 한다. 이 항목은 G3 HOLD다.

고정된 조작 칸의 스틱 아래 빈 곳에 전화 폭에서만 「↓ 회전 조작」 안내를 넣었다. 피벗 기능이 없는 프로필에는 표시하지 않는다. 390×844 첫 화면에서 안내는 스틱 아래와 화면 안에 있고, 스크롤하면 좌·우회전 버튼에 닿는다. 카메라 면적·분리 4폭, 기능 없는 프로필, 스틱 인접 터치 2폭의 브라우저 **7 passed**, `known_failures.py` **0 NEW**다. 원본은 X: `captures/pilot-turn-cue/pilot-drive-{current,turn-controls}-390x844.png`에 둔다. 실제 운전자가 안내를 발견하고 이해하는지는 G3 HOLD다.

차선 자동 모드에서는 수동 회전 버튼이 숨겨지므로 안내도 숨긴다. 390×844에서 자동 진입→안내 없음→수동 복귀→안내 표시를 브라우저 **1 passed**, `known_failures.py` **0 NEW**로 확인했다. X: `captures/pilot-turn-cue-mode/pilot-turn-cue-{auto,manual}-390x844.png`에 두 상태를 보관했다. 실제 운전자 G3는 그대로 HOLD다.

320×568 추가 확인에서 주행 머리의 `Rosy Pilot` 이름이 「Rosy Robot」 이동 버튼과 겹쳤다. 22rem 미만 주행 화면에서는 중복 이름을 숨겨 이동·비상 정지 버튼을 분리했다. 320/390px의 자동·수동 화면 브라우저 **2 passed**, `known_failures.py` **0 NEW**다. 겹침 전후 원본은 X: `captures/pilot-320/`와 `captures/pilot-320-fixed/`에 있다. 실제 전화와 운전자 G3는 여전히 HOLD다.

같은 320px 수동 화면의 제자리 회전 버튼은 각각 57px 칸에 66px 내용이 넘쳤다. 22rem 미만에서는 좌·우회전을 각각 조작 열의 전폭으로 쌓아 글자 잘림을 없앴다. 첫 화면의 「↓ 회전 조작」 안내에서 스크롤해 두 버튼 모두 화면 안으로 가져올 수 있다. 320/390px 브라우저 **2 passed**, `known_failures.py` **0 NEW**이며 전후 원본은 X: `captures/pilot-320-fixed/`와 `captures/pilot-320-pivots/`에 있다. 실제 운전자 발견·조작은 G3 HOLD다.

320×568에서는 기존 HUD와 최소 18rem 조작부가 카메라 높이를 0으로 만들었다. 첫 보정은 영상 면적 계약을 통과했지만 HUD와 조작부에 두 스크롤 영역이 생겼다. 현재 짧은 전화 화면은 조작부를 10rem으로 두고, 기존 「도구」 판에 모델·차선 인식·영상 맞춤/채우기 설정을 옮긴다. HUD 자체는 스크롤하지 않으며 속도·현재 동작·「정지 · 설정」·연결 사실·「도구」·조종 종료를 바로 보여 준다. 전진·후진·스틱과 자동 모드 진행은 첫 화면, 좌·우회전과 속도 설정은 조작부 스크롤로 닿는다. 영상 비율·비겹침·표시 면적 `>0.2`와 320/390px 재배치·기존 녹화 도구를 포함한 브라우저 **9 passed**, `known_failures.py` **0 NEW**다. 원본은 X: `captures/pilot-camera-320/`, `captures/pilot-short-tools-final/`, `captures/pilot-short-tools/pilot-tools-320x568.png`에 있다. 실제 전화 운전자가 이 순서와 도구 판을 이해하는지는 G3 HOLD다.

도구 판을 열고 모델 세부 내용을 펼친 채 320×568→390×844→320×568로 화면을 바꾸면, 전환 때 열린 도구 판과 세부 내용이 닫히고 각 설정은 해당 폭의 자리로 이동한다. 반응형 브라우저 **1 passed**, `known_failures.py` **0 NEW**다. 이는 회전·창 크기 변경의 LOCAL 상태 정합성 근거이며 실제 전화 회전 중 운전자 판독은 G3 HOLD다.

이 320px 전용 배치가 쓰는 22rem 경계는 `shared/web/surfaces.yaml`의 Pilot breakpoint에 사유와 함께 선언했다. 반응형 계약 **9 passed**, `known_failures.py` **0 NEW**다. 화면 동작을 추가로 바꾼 것은 아니다.

객체·픽셀 검수의 작업영역 응답을 390px에서 3초 넘게 보류하면 대기 시간이 초 단위로 보이고 편집은 계속 막힌다. 응답 후에는 최신 검수 화면으로 돌아온다. 브라우저 **2 passed**, `known_failures.py` **0 NEW**이며 원본은 X: `captures/learning-delayed/learning-{objects,pixels}-delayed-390.png`다. 이는 **서버 응답 대기 시간**의 LOCAL 근거다. D-153의 값별 `delayed` 근거와 나이, 다른 선언 폭·경로, 실제 검수자 작업은 별도로 남는다.

### 장비·작업 준비 G3 독회 — LOCAL 진행 중

| D-153 항목 | 현재 근거 | 남은 판정 범위 |
|---|---|---|
| 1. 정직 | [위치 정보 없음](captures/roles-procedure/operator-setup-unavailable-390x844.png)에서 저장을 막고, [관리자 호스트 지연](captures/roles-procedure/administrator-device-delayed-host-operations-390x844.png)에서 쓰기를 막는다. | 나머지 작업 패널의 결측값·실제 기능 가용성. |
| 2. 증거 상태 | [60셀 매트릭스](captures/roles-procedure/role-state-records.json)에 정상·지연·끊김·정보 없음의 화면을 분리했고 지연에는 22초 나이를 표시한다. | 모든 세부 값과 실장 Host Agent 전환. |
| 3. 색 | 해당 모바일 캡처에서 정상은 중립, 지연은 주의색, 비상 정지는 위험색이다. G1 팔레트 시험은 통과했다. | 선택되지 않은 작업 패널·현장 조명. |
| 4. 위계 | [웨이포인트 저장](captures/operator-setup-waypoint-saved-390x844.png)은 읽기 내용과 실행 버튼을 구분한다. | 다른 작업의 첫 화면과 긴 진단 내용. |
| 5. 불가역 | [맵핑](captures/roles-procedure/operator-setup-confirm-dialog-390x844.png)·[릴리스 복귀](captures/roles-procedure/administrator-device-confirm-dialog-390x844.png) 확인창에 대상 행동·취소·비상 정지가 보이고 취소 POST는 0이다. | 맵 리셋·언독 등 다른 종류와 실제 실행 readback. |
| 6. 어휘 | 운용자 작업은 한국어 평문이며 관리자 화면은 `CORE`·`Wi-Fi` 같은 장비 용어를 쓴다. | 나머지 절차의 현장 사용자 독해. |
| 7. 표면 질문 | 웨이포인트 이름 입력→201 저장→목록 readback을 재생했고, 막힌 위치·호스트 작업의 이유가 보인다. | 다른 작업의 완료·복구·재확인 경로. |
| 8. 표면 문법 | 1366px 작업 레일과 390px 작업 선택 후 한 절차가 펼쳐진다. | 모든 작업의 순서·스크롤 독회. |

여덟 항목 모두 현재는 **부분 근거**다. 각 항목의 남은 범위를 확인하기 전에는 장비·작업 준비 표면을 G3 GO로 쓰지 않는다.

현재 트리의 관련 G1 팔레트·토큰·반응형·Fleet 문법 시험은 **83 passed**다. Fleet 지도 적합·키보드 목표 확인 2 passed, 전화 기본 예외·넘침 검사 2 passed이고 세 실행 모두 `known_failures.py`가 0 NEW를 보고했다. 이는 이 회차에서 실행한 범위의 증거이며 D-153 G1 전체를 대체하지 않는다.

D-153이 이름 붙인 G1 시험 중 팔레트·토큰(스타일가이드 포함)·문법 **74 passed**, CORE 증거 **7 passed**를 UI/UX 브랜치 `d04f764c4`의 제품 코드에서 다시 실행했고 두 실행의 `known_failures.py`는 모두 0 NEW였다. 원본 실행 기록은 X: `logs/g1-current-{visual,evidence}.txt`다. `test_styleguide.py` 독립 파일은 현재 트리에 없고 스타일가이드 검사는 `shared/web/test/test_ui_token_contracts.py`에 있다. 이는 G1 코드 계약의 LOCAL 결과이며 G2/G3 판정은 별도다.

현재 변경 트리에서 D-153의 팔레트·토큰/스타일가이드·문법·CORE 증거 계약과 반응형 선언 검사를 다시 실행해 **90 passed**, `known_failures.py` **0 NEW**를 확인했다. 원본은 X: `logs/catalog-width-current-contracts.txt`다. Pilot Shell 너비 변경 커밋 `f4fb54347` 뒤 같은 명명 계약을 재실행한 결과도 **90 passed**, **0 NEW**이며 원본은 X: `logs/g1-current-after-native.txt`다. Pilot 전화 폭 검사까지 반영된 HEAD `42d22b12e`에서도 동일한 G1 명명 계약이 **90 passed**, **0 NEW**였다(원본 X: `logs/g1-current-after-pilot.txt`). Fleet Cell 머리·상태 칸을 추가한 현재 작업 트리에서도 **90 passed**, **0 NEW**였다(X: `logs/g1-after-fleet-cell.txt`). 이 LOCAL 코드 계약 결과는 모든 표면의 G2/G3를 대신하지 않는다.

이번 브랜치의 전체 `shared/web/test` 재실행은 처음에 세 계약 실패를 드러냈다. 역할 화면의 단순 기록을 D-329 형식의 `matrix.json`과 구분해 `role-state-records.json`으로 이름 붙이고, Fleet compact 머리의 현재 격자 계약을 갱신했으며, 명시적인 활성화 호출을 비활성 사유 누락으로 읽던 검사기를 고쳤다. 개발 연결 버튼은 요청 중·재시도 대기의 비활성 이유를 제공한다. 수정 후 공유 UI 계약 **231 passed, 25 skipped**, 개발 연결의 기본·호환 경로 브라우저 **2 passed**, 각 `known_failures.py` **0 NEW**다. 이유 속성을 제거하면 호환 경로 시험이 실패하고 복원 후 통과했다. 원본 실행 기록은 X: `logs/g1-current-fixed.txt`와 `logs/dev-entry-post-mutation.txt`다. 25건의 skip과 표면별 G2/G3 미완료를 UI/UX GO로 해석하지 않는다.

게임 보드 브라우저 전체는 현재 **19 passed**, 게임 모듈은 **113 passed**였다. 최초 1280/390px와 첫 연결 오류에서 피치 안의 명시적 대기·오류 문구를 확인했고, 정지 실패 뒤 재시도 시험의 관찰은 CSP에 걸리는 스크립트 대기 대신 DOM locator를 쓴다. 이 화면들은 관측 frame 없는 fixture이며 실제 카메라와 로봇 상태를 나타내지 않는다.

정지 요청 실패·재시도 흐름은 1280×800, 390×844, 320×568에서 다시 확인했다. 세 뷰포트 모두 실패 이유와 재시도 안내, 정지 버튼이 화면 폭 안에 있고 가로 넘침 없이 표시되며 키보드 재시도 후에도 버튼에 초점이 남는다. 집중 브라우저 시험 **3 passed**, `known_failures.py` **0 NEW**; 캡처 `X:\DevTemp\games_board_stop_retry_{1280x800,390x844,320x568}.png`, 로그 `X:\DevTemp\projects\rosy-platform\2026-10-06--032913--uiux-quality--199bc9\logs\games-stop-width-rerun.txt`. 첫 실행의 데스크톱 Chromium 시작 제한 시간 초과는 재실행에서 재현되지 않았다. 이 증거는 PreviewServer fixture의 LOCAL 범위다.

얼굴 PIL 렌더러는 이전 실행에서 **169 passed**, 기존 정보 카드 캡처 1 passed, `rosy-face` 호스트 시험 **153 passed / 1 skipped**였다. 모두 `known_failures.py` 0 NEW였다. 기존 네 정보 카드 이미지는 렌더러 직접 호출이며 `rosy-face`의 설치·입력·실물 LCD 출력을 통과한 사진이 아니다. D-433은 현재 **Proposed**이므로 실행 경로의 최종 결정·수용으로 읽지 않는다.

### 로봇 얼굴 G3 독회 — LOCAL 진행 중

| D-153 항목 | 현재 근거 | 남은 판정 범위 |
|---|---|---|
| 1. 정직 | 첫 기동의 결측 배터리는 `--`이고, 주행 카드의 결측 속도는 0으로 꾸미지 않는다. | 실제 CORE 입력과 카드 만료 후 얼굴 복귀. |
| 2. 증거 상태 | 정보 카드의 첫 기동·정상·정지·저배터리와 주행 카드의 수동·내비게이션·정지를 별도 렌더했다. | 실제 수신 지연·연결 끊김·결측 전이와 카드 교체 시점. |
| 3. 색 | 정상은 무채색, 정지·배터리 위험은 위험색 채움과 밝은 글자다. [15% 주행 카드](captures/robot-face_drive-navigation-320x240.png)도 같은 규칙으로 수정했다. | 실물 LCD 밝기·각도·주변 조도에서 대비 판독. |
| 4. 위계 | 주행 카드는 모드를 크게, 속도와 내비게이션을 아래에, 배터리를 게이지 옆에 둔다. 정지 때는 [E-STOP](captures/robot-face_drive-estop-320x240.png)이 첫 시선이다. | 1m 이동 중과 1.5m 정지 관찰의 시선·시간 측정. |
| 5. 불가역 | 얼굴은 입력·명령이 없는 표시 표면이고 정지 명령을 보내지 않는다. | 실제 정지 상태가 LCD까지 도달하는 지연. |
| 6. 어휘 | 고정 320×240 카드에서 `MANUAL`·`NAVIGATION`·`E-STOP`을 구분한다. | 행인·운용자가 영문 모드와 `HEALTH` 진단을 이해하는지. |
| 7. 표면 질문 | [수동](captures/robot-face_drive-manual-320x240.png)과 저배터리 내비게이션에서 현재 의도·주의 신호를 분리한다. | 실물에서 반초 안에 상태를 말할 수 있는지. |
| 8. 표면 문법 | D-394의 웨이크/주행 카드 둘 다 320×240 고정 가로 프로파일을 쓴다. | 실물 LCD 회전·리사이즈·GIF 복귀와 다른 프로파일. |

여덟 항목은 모두 **부분 근거**다. 현재 트리의 정보 카드·주행 카드·팔레트 관련 **71 passed**, `known_failures.py` 0 NEW였다. 세 새 이미지는 PIL 직접 렌더이며 20초마다 5초 표시되는 D-394 기기 동작이나 D-433 설치 경로를 검증하지 않는다.

### Cam 네이티브 G2 — 에뮬레이터 부분 근거

Windows의 TCP 예약 범위 `5541–5640`이 에뮬레이터 기본 콘솔·ADB 포트를 포함했다. 격리된 Android 35 AVD를 예약 범위 밖 `-ports 5662,5663`으로 부팅하자 `adb devices`에서 `emulator-5662 device`를 확인했다. 현재 브랜치의 `:app:assembleDebug` 성공 APK를 설치하고 Cam 앱을 실행했다. 캡처와 UI 계층은 `X:\DevTemp\projects\rosy-platform\2026-10-06--032913--uiux-quality--199bc9\captures\`에만 둔다.

| 상태·폭 | 관찰 | 남은 확인 |
|---|---|---|
| LAN 목록, 320×640 및 390×844·글자 130% | Wi-Fi 없음 안내와 다시 찾기·수동 설정 조작이 화면 안에 있고, 다시 찾기는 본문 너비를 채운다. | 실제 수신 기기 목록·기억한 연결과 승인 진입. |
| 설정 첫 화면·하단, 320×640·글자 200% 및 390×844·글자 130% | 탐색 버튼·입력칸은 본문 너비다. 기존 320px/글자 200%에서는 반폭 「돌아가기」가 두 줄로 깨졌다. 현재는 하단까지 스크롤할 수 있고 뒤로·저장이 각각 한 줄의 전폭 버튼이다. UI 계층의 두 버튼 bounds는 320px에서 각각 `[16,480][304,534]`·`[16,546][304,600]`(288px), 390px에서 `[16,697][374,745]`·`[16,757][374,805]`(358px)다. | 실제 입력 오류·저장 결과, 실물 폰 터치. |
| 저장된 연결의 송출 대기 화면, 320×640·글자 200% 및 390×844·글자 130% | 격리 AVD에서 문서용 IP `192.0.2.1`과 가짜 토큰을 저장해 대기 화면에 진입했다. 기존 320px/200% 반폭 「연결 설정」·「카메라 켜기」 글자가 잘렸다. 수정 후 두 버튼이 같은 전폭(320px에서 288px, 390px에서 358px)으로 표시되고 한 줄로 읽힌다. 미리보기 높이를 조정해 320px에서도 연결·송출 정보 보기가 보인다. | 실제 카메라 시작·중지·오류, 실물 폰 터치와 수신기 연결. |

이는 네이티브 **에뮬레이터 G2 부분 근거**다. 수신 기기 없는 환경이라 Pairing·Peer 승인·실제 송출 화면은 표시하지 못했고, 설치자 G3 작업 독회와 실제 폰·현장 수용도 없다.

확대 글자 보정 후 현재 브랜치 `:app:testDebugUnitTest` **366 passed**, `:app:assembleDebug` 성공이다. 전후 화면·UI 계층 원본 `cam-settings-bottom-{320x640-font200,320x640-font200-fixed,390x844-font130-fullwidth}.*`은 위 X: `captures/`에 둔다. AVD의 화면·글자 설정을 초기화하고 종료했다.

송출 대기 화면 보정도 같은 JVM **366 passed**와 APK 빌드 성공으로 확인했다. 전후 화면·UI 계층 원본 `cam-stream-{320x640-font200,390x844-font130}*.{png,xml}`은 위 X: `captures/`에 둔다. 이 가짜 연결에서는 카메라를 켜거나 프레임을 전송하지 않았다.

Pairing의 인증서 확인·실패 복구 조작은 각 상태의 두 반폭 버튼을 본문 전폭으로 쌓았다. 첫 단계에서는 `:app:compileDebugKotlin`으로 소스만 확인했고, 아래의 격리 AVD에서 이어서 렌더했다. 실제 설치자 터치와 수신기 연결은 G2/G3 HOLD다.

이후 debug 전용 합성 상태 화면을 격리 AVD에서 열어 Pairing 요청·인증서 확인·거부와 Peer 승인 대기·인증서 확인·연결 실패를 **320×640/글자 200%와 390×844/글자 130%**에 표시했다. 원본은 X: `captures/cam-pairing-preview/{pair-requested,pair-fingerprint,pair-rejected,peer-pending,peer-certificate,peer-failed}-{320x640-font20,390x844-font13}-final.png`이고, 320px은 같은 폴더의 `*-actions-final.png`에서 스크롤 뒤 행동을 확인한다. 첫 390px 자동 캡처 일부는 Android 시작 화면이어서 버리고, UI가 안정된 뒤 `-final`을 다시 찍었다. Pairing 확인·실패의 두 버튼은 같은 전폭이며, Peer 인증서 확인·중단도 같은 전폭이다. Peer 화면의 스크롤 내용이 320px에서 상태 표시줄 아래로 들어가던 문제는 LAN·Peer 화면의 안전 영역 적용 후 재캡처했다(`peer-certificate-320x640-font20-safearea.png`). Debug APK 빌드와 release manifest 처리가 성공했고 합성 화면 Activity는 release manifest에 없다. 이는 **LOCAL 합성 상태 렌더**다. 실제 수신기 발견·승인·거부·스트림, 실물 폰 설치자 작업, 나머지 선언 상태는 여전히 G2/G3 HOLD다.

320px/글자 200% 인증서 확인에서 4자리 지문 묶음 `3456`이 중간에서 갈라져 콘솔 값과 대조하기 어려웠다. 표시할 때 하이픈 뒤에만 줄바꿈 기회를 주고 원본 지문·접근성 읽기 값은 유지했다. 현재 APK를 격리 AVD에 설치해 320×640에서는 `ABCD-EF12-` / `3456-7890`, 390×844/글자 130%에서는 한 줄임을 화면으로 확인했다. 최종 원본은 X: `captures/cam-fingerprint-wrap/fingerprint-320x640-font200-groups.png`와 `fingerprint-390x844-font130-final.png`; 처음 390px 캡처는 시작 화면이라 근거에서 제외한다. Cam JVM **366 passed**와 debug APK 빌드 성공은 X: `logs/cam-fingerprint-wrap-gradle.txt`에 있다. 실제 사이트 콘솔 값 대조와 설치자 G3는 여전히 HOLD다.

기존 `pair-fingerprint-320x640-font20-final.png`은 화면이 어둡게 캡처되어 지문 판독 근거에서 제외한다. 320px 지문 판독에는 위의 새 `fingerprint-320x640-font200-groups.png`를 쓴다.

### Pilot Shell 네이티브 G2 — 태블릿 너비 부분 근거

현재 브랜치의 Pilot Android debug APK를 격리된 Android 35 에뮬레이터에 설치했다. 밀도 320dpi에서 2000×1200(1000dp), 1200×800(600dp), 800×600(400dp) 가로 화면을 확인했다. 원본 캡처는 위 Cam 회차와 같은 X: `captures` 폴더의 `pilot-shell-*density320*.png`에 둔다.

| 상태·폭 | 관찰 | 남은 확인 |
|---|---|---|
| 빈 로봇 목록, 2000×1200·1200×800 | 앱 정보 칸과 로봇 목록 칸이 나뉘고 다시 찾기·태블릿 상태·기기 연결이 보인다. 1200×800에서 글자 130%일 때 제목 `[568,80][834,180]`과 다시 찾기 `[834,82][1120,178]`가 겹치지 않는다. | 실제 후보 목록·선택·연결 상태. |
| 빈 로봇 목록, 800×600 | 변경 전 고정 260dp 정보 칸 때문에 다시 찾기 글자가 세로로 쌓이고 목록 제목이 밀렸다. 변경 후 목록이 가용 너비를 채우고 다시 찾기·상태·기기 연결이 모두 보인다. 글자 130%에서도 각 항목의 UI bounds는 `[32,32]`부터 `[768,568]` 사이에 있고 기기 연결 버튼까지 보인다. | 실제 소형 가로 기기와 사용자 판독. |
| 합성 후보·연결 보류, 2000×1200·1200×800·800×600 | 실제 `PilotViews.robot` 두 행을 debug 전용 화면에 표시했다. 600dp에서 기존 260dp 정보 칸 때문에 이름이 세 줄로 몰렸다. 목록을 720dp 미만에서 한 열로 두고 Android의 균형 줄바꿈을 적용한 뒤 600dp의 두 행은 각각 `[32,207][1168,427]`·`[32,427][1168,704]`로 같은 1136px 폭이다. 400dp도 두 행이 각각 736px 폭이고, 첫 화면의 연결 행과 스크롤 후 보류 이유를 읽는다. | 실제 발견·후보 선택·승인·재접속과 Lenovo 태블릿 터치. |
| 기기·연결 대화상자, 1200×800·800×600 | 배터리·발열 문구가 보이고, 800×600에서는 긴 설명을 스크롤해 끝까지 읽으며 닫기를 누를 수 있다. | 실제 페어링·승인·오류 대화상자와 사용자 독회. |

기존 빈 목록 JVM `testDebugUnitTest` **89 passed**와 이번 현재 트리 `assembleDebug` 성공을 구분한다. 변경된 실제 빈 로비도 1200×800/글자 130%에서 다시 표시해 다시 찾기·상태·기기 연결이 한 화면 안에 있음을 확인했다. 합성 후보 전후·최종 캡처와 UI 계층은 X: `captures/pilot-candidate-preview/pilot-candidates-{800x600-font13,1200x800-font13,2000x1200-font10}{,-final}.{png,xml}`과 `pilot-candidates-800x600-font13-held-bottom.png`, 실제 빈 로비는 `pilot-empty-1200x800-font13-final.png`다. Debug 전용 화면은 release manifest에 없고 `android.permission.DUMP`를 요구한다. 이는 **LOCAL G2 부분 근거**이며 실제 Lenovo 태블릿, 로봇 연결, 운전자 G3는 미검증이다.

800×600/밀도 320dpi/글자 130% 합성 후보 목록은 두 행이 같은 736px 폭이지만, 기존 첫 행의 장식 아이콘이 이름을 두 줄로 밀어 첫 화면에서 두 번째 후보를 가렸다. 480dp 미만에서는 그 아이콘만 생략했다. 현재 APK의 첫 행 UI bounds는 `[32,207][768,427]`로 기존 `[32,207][768,491]`보다 64px 낮고, 두 후보 이름이 첫 화면에 보인다. 스크롤 뒤 보류 이유·조작은 그대로 읽히며, 1200×800에는 기존 아이콘이 남는다. 안정된 화면·UI 계층은 X: `captures/pilot-candidate-compact/candidates-800x600-font130.{png,xml}`, `candidates-800x600-font130-held.png`, `candidates-1200x800-font130-final.png`이다. 첫 1200px 자동 캡처는 검은 전환 화면이라 제외한다. Pilot JVM **89 passed**와 debug APK 빌드 성공은 X: `logs/pilot-candidate-compact-gradle.txt`에 있다. 합성 후보 LOCAL G2이며 실제 발견·선택과 운전자 G3는 HOLD다.

### 추가 활성 표면 평가 카드 — G2/G3 HOLD

이 세 카드는 D-153의 새 표면 재평가 기준을 적용한다. 각 폭에서 표시되는 **동등한 창·조작은 같은 가용 폭**을 쓰고, 작은 화면에서는 잘림 없이 한 열로 읽고 실행할 수 있어야 한다. 아래 캡처는 일부 상태의 LOCAL 근거이며 선언 상태 전체의 G2 통과를 뜻하지 않는다.

| 표면과 먼저 답할 질문 | 선언 뷰포트 | G2에서 채울 상태와 현재 근거 |
|---|---|---|
| `pinky-review`: 검수자는 원본과 라벨을 대조하고 승인·제외·내보내기를 정확히 끝낼 수 있는가? | 웹 1440·800·390px, 객체·픽셀 검수·작업 목록·자료 등록 | 두 편집 창의 폭은 [객체 캡처](captures/learning-width/learning-objects-1440.png)·[픽셀 캡처](captures/learning-width/learning-pixels-1440.png) 등에서 부분 확인. 390px에서는 각 편집 칸의 작업 버튼이 전폭이고 800px에서는 동등 폭 열이다(X: 캡처). 네 경로의 503 사용 불가를 세 폭에서, 작업 목록·자료 등록의 응답 보류·권한 거부·재시도와 객체·픽셀 편집의 응답 보류·연결 끊김·저장 충돌·권한 거부 및 합성 승인·제외·자료 준비 결과를 1440·800·390px에서 부분 확인했다. 각 경로의 실제 지연, 자료 등록 완료와 실제 검수·학습 수용을 채운다. 로봇 SAFE_STOP은 이 개발 도구의 조작 상태가 아니다. |
| `pilot-shell`: 운전자는 올바른 로봇을 찾아 연결 상태를 확인할 수 있는가? | 네이티브 가로 1000·600·400dp, 400·600dp 글자 130% | 빈 발견·기기 상태와 합성 후보·보류 행을 위 에뮬레이터 캡처로 부분 확인. 각 폭의 실제 최초 기동·발견 중·지연·연결 끊김·사용 불가, 실제 후보·선택·승인·거부·연결 실패·재접속을 채운다. SAFE_STOP·주행 명령은 연결 로비가 아닌 Pilot PWA에서 평가한다. |
| `cam`: 설치자는 카메라를 올바른 수신기에 연결하고 송출 상태를 확인할 수 있는가? | 네이티브 세로 320×640·390×844, 글자 130%·200% | LAN 빈 목록·설정·가짜 연결의 송출 대기와 Pairing/Peer 합성 상태 6종을 에뮬레이터에서 부분 확인. 실제 최초 기동·탐색 중·지연·연결 끊김·사용 불가, 실제 Pairing·Peer 승인/거부, 권한/입력 오류, 송출 시작·중지·실패를 채운다. SAFE_STOP·로봇 명령은 Cam의 소유 범위 밖이다. |

G3 여덟 항목은 세 표면 모두 **미완료**다. 아래는 이번 회차의 부분 근거와 판정에 필요한 검토 장면이다. 각 장면에서 사용자 또는 평가자가 실제 작업을 수행하고 근거 셀을 남겨야 한다.

| D-153 항목 | `pinky-review` | `pilot-shell` | `cam` |
|---|---|---|---|
| 1. 정직 | 원본·라벨과 승인 결과 일치 확인 | 실제 발견·연결 여부와 버튼 가용성 확인 | 실제 수신기·송출 여부와 버튼 가용성 확인 |
| 2. 증거 상태 | 로딩·오래된 자료·연결 끊김·결측을 구분 | 발견·연결의 대기·지연·실패를 구분 | 탐색·페어링·송출의 대기·지연·실패를 구분 |
| 3. 색 | 승인·제외·오류의 의미와 대비 확인 | 연결·오류·주의의 의미와 대비 확인 | 승인·송출·오류의 의미와 대비 확인 |
| 4. 위계 | 원본·편집·검수 결정의 순서와 동등 창 너비 확인 | 후보·연결 행동·기기 상태의 순서와 좁은 폭 확인 | 수신기·송출 행동·설정의 순서와 동등 조작 너비 확인 |
| 5. 불가역 | 라벨 삭제·제외·자료 준비의 영향과 복구 경로 확인 | 로비의 연결 변경·기기 정보 접근을 확인; 정지는 Pilot PWA 카드에서 검토 | 연결 해제·송출 중지·설정 저장의 영향과 확인 경로 검토 |
| 6. 어휘 | 검수자에게 객체·픽셀·승인 용어가 명확한지 확인 | 운전자에게 후보·연결·승인 문구가 명확한지 확인 | 설치자에게 LAN·Peer·송출 문구가 명확한지 확인 |
| 7. 표면 질문 | 3폭에서 원본 대조부터 결과 확인까지 수행 | 3폭에서 발견부터 연결 확인까지 수행 | 2폭에서 수신기 선택부터 송출 확인까지 수행 |
| 8. 표면 문법 | 검수 작업은 원본·편집·결정 순으로 읽히는지 확인 | 로비는 후보 선택·연결 상태가 먼저 읽히는지 확인 | 설치 절차는 발견·승인·송출·확인 순으로 읽히는지 확인 |

## 제품 범위와 판정 경계

현재 `shared/web/surfaces.yaml`의 표면을 제품 UI/UX 목표와 대조하면 다음과 같다. **부분 근거는 GO가 아니다.** 신규 표면의 선언 상태·뷰포트 카드는 D-153 재평가 트리거로 채워야 한다.

| 등록 표면 | 이번 회차의 범위 | 다음 판정 증거 |
|---|---|---|
| `robot` | `/dashboard`·`/console`·`/setup`·`/device` 중 운용·작업 준비 LOCAL 부분 근거 | 역할·상태 G2 잔여 셀, 작업 완료 G3, 실물 readback |
| `console` | Fleet LOCAL 부분 근거 | 선언 상태 G2 잔여 셀, 사이트 PC·카메라 readback, G3 |
| `game-board` | LOCAL 부분 근거 | 모든 상태 G2, 실제 경기 관측, G3 |
| `pilot` | 현재 트리의 주행 4폭·팔·대상 오류 LOCAL 부분 근거 | 선언 상태 전체 G2, 전화 회전 조작 발견 가능성·운전자 G3; [DEVICE 기능 확인](../pilot-device-user-confirmed-2026-10-05/README.md)은 별도 |
| `robot-face` | 웨이크·주행 카드 호스트 PIL 이미지와 [G3 부분 독회](#로봇-얼굴-g3-독회--local-진행-중) | 실제 설치 LCD 사진·거리/각도/조도 판독, 카드 전이·G3 |
| `pinky-review` | 객체·픽셀 편집 창과 전화 작업·사진 이동 너비 LOCAL 부분 근거 | 개발 도구의 선언 상태·역할별 작업 G2/G3 |
| `pilot-shell` | [에뮬레이터 가로 3폭의 빈 발견·기기 상태·합성 후보 G2 부분 근거](#pilot-shell-네이티브-g2--태블릿-너비-부분-근거) | 실제 후보·페어링·승인·오류 화면, Lenovo 태블릿과 사용자 독회 |
| `cam` | Pairing·송출·LAN 연결·설정의 조작 너비, Android APK 빌드, [LAN·설정·송출 대기와 합성 Pairing/Peer 6상태 에뮬레이터 G2 부분 근거](#cam-네이티브-g2--에뮬레이터-부분-근거) | 실제 Pairing·Peer·송출 상태 캡처, 실제 폰과 설치자 작업 독회 |
| `control-diagnostic` | D-266 PARKED | 재개 결정 뒤 카드 작성 |
| `web-common`, `lane-live-view` | 라이브러리 / 제품 밖 시뮬 뷰어 | 제품 UI/UX G2 카드 대상 아님 |

D-153의 여섯 카드 중 운용자 콘솔·장비 런타임·Fleet·게임 보드·로봇 얼굴에 이 회차의 새 캡처가 있다. control 레거시 진단은 D-153에 따라 PARKED다. 이후 추가된 Pilot·Cam·학습 검수의 질문·뷰포트·상태는 위 카드에 선언했으며, 아직 채우지 못한 셀이 있어 제품 전체 GO를 논할 수 없다. 이전 [2026-09-29 회차](../uiux-surfaces-2026-09-29/README.md)의 LOCAL 결과는 현재 트리 전체 G3나 DEVICE/FIELD 판정으로 승격하지 않는다.

**다음 판정 작업:** 각 활성 표면의 선언 상태·뷰포트 G2를 현재 트리에서 채우고, D-153의 여덟 G3 항목에 근거 셀을 적는다. 실제 장치·현장 수용은 LOCAL 캡처와 분리한다. 이 증거가 없으면 디자인이 마음에 들어 보이더라도 GO로 쓰지 않는다.
