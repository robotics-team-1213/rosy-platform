# ROSY UI/UX 품질 확인 — 2026-10-06

**판정: 제품 전체 HOLD.** 이 회차는 `PRODUCT.md`의 UI/UX 목표를 현재 화면에서 확인하기 시작한 LOCAL 점검이다. D-280의 성격과 `DESIGN.md`의 토큰·표면 문법을 유지하며, GO 기준은 D-153 G1/G2/G3 그대로다. 브랜치 `uiux/rosy-operate-quality`에서 작성했다.

## 이번 회차의 질문과 근거

| 표면·질문 | 현재 LOCAL 캡처 | 확인한 것 | 남은 것 |
|---|---|---|---|
| 로봇 운용: 지금 움직여도 되는가? | [1366×768](captures/robot-console-1366x768.png), [390×844](captures/robot-console-390x844.png), [G3 독회](#로봇-운용-g3-독회--local-진행-중) | 데스크톱 감지·관측·조작이 같은 폭이다. 390px에서 조작이 카메라·지도보다 먼저 오고 비상 정지가 첫 화면에 있다. 모드·수동 주행·차선 추종·도킹·지도 근거의 요청/접수/재확인을 두 폭에서 재생했다. | 선언된 역할·상태 전체 G2, 실제 CORE/장치 상태, G3 전체 근거 검토. |
| 장비·작업 준비: 다음 절차와 막힌 이유를 알 수 있는가? | [60셀 매트릭스](captures/roles-procedure/matrix.json), [첫 기동 6셀](captures/roles-first-boot/first-boot-matrix.json), [운용자 작업 준비 390×844](captures/roles-procedure/operator-setup-normal-390x844.png), [맵핑 시작 확인](captures/roles-procedure/operator-setup-confirm-dialog-390x844.png), [릴리스 복귀 확인](captures/roles-procedure/administrator-device-confirm-dialog-390x844.png), [관리자 장비 지연 390×844](captures/roles-procedure/administrator-device-delayed-host-operations-390x844.png), [권한 거부 390×844](captures/roles-procedure/operator-device-forbidden-390x844.png) | `/setup`·`/device`를 역할 2개·1366/390px·상태별 60셀과 첫 기동 6셀로 현재 FastAPI/Chromium에서 재생했다. 390px 패널 안의 입력·행동은 같은 가용 폭을 쓰며, 페이지 오류·가로 넘침 0, 쓰기 차단 fixture에서 확인 취소 POST 0이다. 첫 기동에는 상태 확인 대기가 표시되고 비상 정지가 두 폭에서 보인다. 확인창 6장에는 선택한 행동 이름이 실행 버튼에 보이고 비상 정지가 대화상자 위에 남는다. 관리자 호스트 지연·끊김·결측의 실제 작업 패널 6장을 별도로 저장했다. | 절차를 현장 사용자가 완료할 수 있는지 G3 작업 독회, 실제 Host Agent/장치 readback. |
| Fleet: 어느 로봇에 주의가 필요한가? | [1920×1080](captures/fleet-console-1920x1080.png), [320×844](captures/fleet-console-320x844.png), [상태 캡처](#fleet-g2-상태-확인--local-진행-중), [G3 독회](#fleet-g3-독회--local-진행-중) | 데스크톱 현장·개입 칸이 같은 폭이다. 전화의 **기본** 목록은 릴레이 오류가 있는 `rosy_03`부터 보여 주며 비상 정지가 첫 화면에 있다. 빈 목록·서버 실패에서도 320/390px 패널 폭과 다음 단계가 유지된다. | 선언된 상태 전체 G2, 연결된 카메라·실제 사이트 PC/로봇 readback, G3 전체 근거 검토. |
| 게임 보드: 경기장·공·로봇·골이 보이는가? | [진행 1280×800](captures/games-play-1280x800.png), [최초 1280×800](captures/games-initial-1280x800.png), [최초 390×800](captures/games-g3/games-initial-390x800.png), [지연 1280×800](captures/games-delayed-1280x800.png), [HOLD 1280×800](captures/games-hold-1280x800.png), [지연 390×800](captures/games-delayed-390x800.png), [G3 독회](#게임-보드-g3-독회--local-진행-중) | 최초·연결 오류 때 빈 피치에 이유를 표시한다. 데스크톱에서는 피치가 초점이라 관측보다 넓고, 전화에서는 점수·피치·관측이 같은 가용 폭으로 쌓인다. 지연 화면은 마지막 수신 정보임을 밝히고 정지가 첫 화면에 있다. | 현재 트리의 전체 상태 G2, 실물 카메라·경기 readback, G3 전체 근거 검토. |
| 로봇 얼굴: 의도·주의·위험이 즉시 구분되는가? | [첫 기동](captures/face-first-boot-320x240.png), [정상](captures/face-nominal-320x240.png), [E-STOP](captures/face-estop-320x240.png), [배터리 위험](captures/face-battery-critical-320x240.png) (모두 320×240) | 현재 `emotion.info_screen` PIL 렌더러의 정보 카드 네 장에서 정상·위험의 형태·문구가 구분된다. | D-433 `rosy-face` 실제 설치·LCD 경로, 1.5m/각도/조도 판독, 만료 후 의도 GIF 복귀, G3 전체 근거 검토. |
| 학습 검수: 원본과 편집 내용을 함께 볼 수 있는가? | [객체 1440px](captures/learning-width/learning-objects-1440.png), [객체 800px](captures/learning-width/learning-objects-800.png), [객체 390px](captures/learning-width/learning-objects-390.png), [픽셀 1440px](captures/learning-width/learning-pixels-1440.png), [픽셀 800px](captures/learning-width/learning-pixels-800.png), [픽셀 390px](captures/learning-width/learning-pixels-390.png) | 두 편집 화면의 캔버스·검수 창을 데스크톱에서 같은 폭으로 맞췄다. 좁은 화면에서는 두 창이 같은 가용 폭으로 쌓이고 가로 넘침이 없다. | 개발 도구의 다른 상태·실제 검수자 G3 독회. 로봇 현장 수용과 별도다. |
| Pilot: 운전·팔 조작 상태와 정지가 보이는가? | [팔 2000×1200](captures/pilot-arm/pilot-arm-gripper-2000x1200.png), [팔 1200×2000](captures/pilot-arm/pilot-arm-gripper-1200x2000.png), [팔 390×844](captures/pilot-arm/pilot-arm-gripper-390x844.png), [대상 확인 실패 390×844](captures/pilot-target-error-390x844.png), [기존 주행 기준선](../pilot-g2-baseline-2026-10-04/README.md) | 영상 없는 Gazebo 연습에서 빈 영상 칸 대신 조작부가 가용 폭을 쓰고 팔·그리퍼 창은 같은 폭이다. 전화에서는 같은 폭으로 쌓인다. 대상 확인 실패는 내부 영문 오류 없이 연결 확인과 재시도를 안내한다. E-stop은 세 폭 모두 첫 화면에 있다. | 주행·연결의 현재 트리 G2 전체 재확인, 실제 운전자 G3 독회. 기존 DEVICE 기능 확인을 UI/UX GO로 승격하지 않는다. |

로봇·Fleet 캡처는 FastAPI/Playwright fixture, 게임 캡처는 실제 PreviewServer와 fixture payload를 쓴 LOCAL 증거다. Fleet 전화의 `fleet_console_mobile_{width}.png`는 시험이 **전체 로봇 보기**를 누른 뒤 찍는 캡처여서 기본 예외 목록의 근거로 쓰지 않는다. 기본 목록은 위 `fleet-console-320x844.png`와 해당 브라우저 단언으로 확인했다.

작업 준비·장비 캡처는 같은 FastAPI fixture에서 생성했다. 첫 시도는 고급 네트워크 작업의 닫힌 disclosure 안에 있는 버튼을 바로 찾으려다 시험이 멈췄다. shipped UI대로 disclosure를 열어 비활성 버튼과 이유를 확인했다. 모바일 패널의 실제 내용 폭을 공용 폼의 container query가 읽도록 수정한 뒤 다시 실행해 **60셀 1 passed**, 반응형·셸 브라우저 **18 passed**, 별도 작업 패널 **6장**, `known_failures.py` **0 NEW**를 얻었다. 첫 실패를 제품 결함으로 분류하지 않는다.

첫 기동은 manifest와 CORE 첫 상태 응답을 보류한 별도 fixture다. **6셀 1 passed**, 60셀 재실행 **1 passed**, 각각 `known_failures.py` **0 NEW**였다. 비상 정지의 테스트 판정은 숨겨진 요소의 0폭 좌표가 통과하지 않도록 렌더된 폭을 확인한다. [관리자 장비 390×844](captures/roles-first-boot/administrator-device-first-boot-390x844.png)를 원본 크기로 확인했다.

불가역 확인은 이전 캡처가 대화상자를 닫은 뒤 화면만 남겼으므로 열린 상태를 1366/390px 각 3장씩 다시 찍었다. 맵핑 시작·중지·저장과 호스트 작업의 실행 버튼은 선택한 행동 이름을 말한다. 이 변경 뒤 절차 60셀 **1 passed**, 관련 작업 브라우저 **10 passed**, `known_failures.py` **0 NEW**였다. 6개 확인 셀은 취소 뒤 쓰기 요청이 0이다. 이는 확인창과 취소의 LOCAL 증거이지 실제 명령 완료 증거가 아니다.

운용자 작업 준비의 [웨이포인트 저장 390×844](captures/operator-setup-waypoint-saved-390x844.png)은 현재 FastAPI의 `POST /api/v1/waypoints`가 201을 돌려주고, 다음 목록 조회가 저장된 이름과 좌표를 화면에 표시한 LOCAL 작업 경로다. 브라우저 1 passed, `known_failures.py` 0 NEW였다. 이 테스트 인스턴스의 저장이며 실물 로봇의 위치 정확도는 검증하지 않는다.

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

| 상태 | 현재 캡처 | 확인 범위 |
|---|---|---|
| 빈 목록 | [1920px](captures/fleet-states/fleet_console_empty.png), [320px](captures/fleet-states/fleet_console_empty_320.png), [390px](captures/fleet-states/fleet_console_empty_390.png) | 등록할 로봇이 없다는 안내, 320/390px E-stop·패널 폭. |
| 서버 실패 | [1920px](captures/fleet-states/fleet_console_gather-error.png), [320px](captures/fleet-states/fleet_console_gather-error_320.png), [390px](captures/fleet-states/fleet_console_gather-error_390.png) | Fleet 상태 확인 불가 안내, 320/390px E-stop·패널 폭. |
| 느린 첫 응답과 회복 | [대기](captures/fleet-states/fleet_console_slow_loading.png), [회복](captures/fleet-states/fleet_console_slow_recovered.png) | 첫 응답을 기다리는 동안 중복 폴링 없이 회복된 목록을 표시한다. |
| 수신 후 끊김·지연·HOLD | [수신 후 끊김](captures/fleet-states/fleet_console_gather-lost-after-live.png), [팔로워 지연](captures/fleet-states/fleet_console_delayed.png), [대형 HOLD](captures/fleet-states/fleet_console_holding.png) | 상태 변화를 화면에 드러낸다. |
| 로봇 연결 끊김 | [1920px](captures/fleet-states/fleet_console_unreachable.png) | 실제 Fleet API의 `online: false, state: null` 계약으로 재촬영했다. 이전 fixture의 모순된 좌표·주행 상태를 제거했고, 해당 로봇 카드에 현재 좌표·NAVIGATING이 없음을 단언한다. |
| 안전 상태 결측·비상 정지 | [결측](captures/fleet-g3/fleet_safety_unknown.png), [비상 정지](captures/fleet-g3/fleet_safety_stopped.png) | CORE의 `NAVIGATING` 값이 남아도 주행 중이라는 문구 대신 목표가 남았음을 표시한다. 두 상태 모두 목표 전송은 막힌다. |

기존 상태 브라우저 **9 passed**, 320/390px 빈 목록·서버 실패 **4 passed**, 수정한 연결 끊김 **1 passed**였고 각 실행의 `known_failures.py`는 **0 NEW**였다. 이들은 fixture 기반 화면 검사다. Fleet의 선언 상태 전부와 카메라 연결, 실제 사이트 PC/로봇 readback, G3 사용자 독회는 남아 있어 G2/G3 GO로 판정하지 않는다.

### Fleet G3 독회 — LOCAL 진행 중

| D-153 항목 | 현재 근거 | 남은 판정 범위 |
|---|---|---|
| 1. 정직 | [안전 상태 결측](captures/fleet-g3/fleet_safety_unknown.png)·[비상 정지](captures/fleet-g3/fleet_safety_stopped.png)에서 목표 전송을 막고 `NAVIGATING`을 물리적 주행으로 표현하지 않는다. | 다른 조작의 상태 가용성과 실제 CORE readback. |
| 2. 증거 상태 | 느린 첫 응답, 수신 후 끊김, 로봇 연결 끊김, 안전 결측을 위 G2 캡처로 구분했다. | 각 값의 정상·지연·끊김·결측 전이 전체. |
| 3. 색 | 정상 카드는 중립이고 안전 정지는 빨강, 영상 연결 불가는 주의색이다. | 다른 경보·현장 조명. |
| 4. 위계 | [목표 확인창](captures/fleet-g3/fleet_goal_confirm_open.png)에서 보고 영역은 뒤로 물러나고 전송 선택이 올라온다. | 긴 목록과 현장 관제자의 시선 이동. |
| 5. 불가역 | [목표 선택](captures/fleet-g3/fleet_goal_preconfirm.png)→[로봇·좌표 확인](captures/fleet-g3/fleet_goal_confirm_open.png)→취소를 재생했고 취소 전송 0을 단언한다. 비상 정지는 Accepted D-414의 즉시 접근 예외로 확인창 위에 남는다. | 실제 목표·정지 readback, 취소·전체 취소의 현장 절차. |
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

학습 검수는 D-461의 병렬 원본·inspector 구조를 유지하면서 두 편집 창의 너비만 같게 했다. 현재 로컬 Chromium의 객체 작업 브라우저 **10 passed**, 픽셀 작업·반응형 계약 **14 passed**, 각 `known_failures.py` **0 NEW**였다. 1440/800/390px에서 두 창 너비와 가로 넘침을 검사했다. 이 캡처는 합성 검수 자료를 사용한 개발 도구 LOCAL 증거다.

Pilot 팔 화면은 카메라 없는 Gazebo fixture에서 빈 영상 자리 때문에 두 조작 창이 오른쪽 좁은 칸에 2:1로 압축됐다. 현재 CSS는 영상이 없을 때 조작부를 먼저 배치하고 동등한 팔·그리퍼 창을 같은 폭으로 쓴다. 영상이 있으면 영상·조작부 병렬 구조를 유지한다. 태블릿 2종·전화·영상 있는 경로의 브라우저 **5 passed**, `known_failures.py` **0 NEW**였다. 명령 경로는 가짜 CORE fixture이며 실기 조작 증거가 아니다.

Pilot 대상 발견 오류에서는 내부 `invalid simulation target`을 운용자에게 그대로 보여 주던 경로를 없앴다. [390px 캡처](captures/pilot-target-error-390x844.png)는 조종 대상 확인, 연결 점검, 다시 확인 버튼과 첫 화면 비상 정지를 보여 준다. 현재 트리의 브라우저 재시도 1 passed, 가로 넘침 0, `known_failures.py` 0 NEW다. 실제 Pilot Android 셸과 장치 연결의 품질 판정은 이 웹 fixture로 대신하지 않는다.

### 장비·작업 준비 G3 독회 — LOCAL 진행 중

| D-153 항목 | 현재 근거 | 남은 판정 범위 |
|---|---|---|
| 1. 정직 | [위치 정보 없음](captures/roles-procedure/operator-setup-unavailable-390x844.png)에서 저장을 막고, [관리자 호스트 지연](captures/roles-procedure/administrator-device-delayed-host-operations-390x844.png)에서 쓰기를 막는다. | 나머지 작업 패널의 결측값·실제 기능 가용성. |
| 2. 증거 상태 | [60셀 매트릭스](captures/roles-procedure/matrix.json)에 정상·지연·끊김·정보 없음의 화면을 분리했고 지연에는 22초 나이를 표시한다. | 모든 세부 값과 실장 Host Agent 전환. |
| 3. 색 | 해당 모바일 캡처에서 정상은 중립, 지연은 주의색, 비상 정지는 위험색이다. G1 팔레트 시험은 통과했다. | 선택되지 않은 작업 패널·현장 조명. |
| 4. 위계 | [웨이포인트 저장](captures/operator-setup-waypoint-saved-390x844.png)은 읽기 내용과 실행 버튼을 구분한다. | 다른 작업의 첫 화면과 긴 진단 내용. |
| 5. 불가역 | [맵핑](captures/roles-procedure/operator-setup-confirm-dialog-390x844.png)·[릴리스 복귀](captures/roles-procedure/administrator-device-confirm-dialog-390x844.png) 확인창에 대상 행동·취소·비상 정지가 보이고 취소 POST는 0이다. | 맵 리셋·언독 등 다른 종류와 실제 실행 readback. |
| 6. 어휘 | 운용자 작업은 한국어 평문이며 관리자 화면은 `CORE`·`Wi-Fi` 같은 장비 용어를 쓴다. | 나머지 절차의 현장 사용자 독해. |
| 7. 표면 질문 | 웨이포인트 이름 입력→201 저장→목록 readback을 재생했고, 막힌 위치·호스트 작업의 이유가 보인다. | 다른 작업의 완료·복구·재확인 경로. |
| 8. 표면 문법 | 1366px 작업 레일과 390px 작업 선택 후 한 절차가 펼쳐진다. | 모든 작업의 순서·스크롤 독회. |

여덟 항목 모두 현재는 **부분 근거**다. 각 항목의 남은 범위를 확인하기 전에는 장비·작업 준비 표면을 G3 GO로 쓰지 않는다.

현재 트리의 관련 G1 팔레트·토큰·반응형·Fleet 문법 시험은 **83 passed**다. Fleet 지도 적합·키보드 목표 확인 2 passed, 전화 기본 예외·넘침 검사 2 passed이고 세 실행 모두 `known_failures.py`가 0 NEW를 보고했다. 이는 이 회차에서 실행한 범위의 증거이며 D-153 G1 전체를 대체하지 않는다.

D-153이 이름 붙인 G1 시험 중 팔레트·토큰(스타일가이드 포함)·문법 **74 passed**, CORE 증거 **7 passed**를 현재 브랜치에서 다시 실행했고 `known_failures.py`는 0 NEW였다. `test_styleguide.py` 독립 파일은 현재 트리에 없고 스타일가이드 검사는 `shared/web/test/test_ui_token_contracts.py`에 있다. 이는 G1 코드 계약의 LOCAL 결과이며 G2/G3 판정은 별도다.

게임 보드 브라우저 전체는 현재 **19 passed**, 게임 모듈은 **113 passed**였다. 최초 1280/390px와 첫 연결 오류에서 피치 안의 명시적 대기·오류 문구를 확인했고, 정지 실패 뒤 재시도 시험의 관찰은 CSP에 걸리는 스크립트 대기 대신 DOM locator를 쓴다. 이 화면들은 관측 frame 없는 fixture이며 실제 카메라와 로봇 상태를 나타내지 않는다.

얼굴 PIL 렌더러는 **169 passed**, 정보 카드 캡처 1 passed(기존 Pillow 사용 중단 예고 5건), `rosy-face` 호스트 시험은 **153 passed / 1 skipped**다. 모두 `known_failures.py` 0 NEW였다. 이 네 이미지는 렌더러 직접 호출이며 `rosy-face`의 설치·입력·실물 LCD 출력을 통과한 사진이 아니다. D-433은 현재 **Proposed**이므로 실행 경로의 최종 결정·수용으로 읽지 않는다.

## 제품 범위와 판정 경계

현재 `shared/web/surfaces.yaml`의 표면을 제품 UI/UX 목표와 대조하면 다음과 같다. **부분 근거는 GO가 아니다.** 신규 표면의 선언 상태·뷰포트 카드는 D-153 재평가 트리거로 채워야 한다.

| 등록 표면 | 이번 회차의 범위 | 다음 판정 증거 |
|---|---|---|
| `robot` | `/dashboard`·`/console`·`/setup`·`/device` 중 운용·작업 준비 LOCAL 부분 근거 | 역할·상태 G2 잔여 셀, 작업 완료 G3, 실물 readback |
| `console` | Fleet LOCAL 부분 근거 | 선언 상태 G2 잔여 셀, 사이트 PC·카메라 readback, G3 |
| `game-board` | LOCAL 부분 근거 | 모든 상태 G2, 실제 경기 관측, G3 |
| `pilot` | 팔 LOCAL 부분 근거와 [2026-10-04 주행 기준선](../pilot-g2-baseline-2026-10-04/README.md) | 현재 트리의 접속·주행 G2, 운전자 G3; [DEVICE 기능 확인](../pilot-device-user-confirmed-2026-10-05/README.md)은 별도 |
| `robot-face` | 호스트 PIL 이미지 부분 근거 | 실제 설치 LCD 사진·거리/각도/조도 판독, G3 |
| `pinky-review` | 객체·픽셀 너비 LOCAL 부분 근거 | 개발 도구의 선언 상태·역할별 작업 G2/G3 |
| `pilot-shell` | 이 회차 UI 캡처 없음 | 네이티브 태블릿 접속 화면 캡처와 역할·상태 독회 |
| `cam` | 디버그 APK 로컬 빌드 성공. 이 회차 UI 캡처 없음: 격리된 Android 에뮬레이터가 ADB에 등록되지 않아 렌더링을 확인하지 못했다. | 네이티브 폰 설치·연결 상태 캡처와 설치자 작업 독회 |
| `control-diagnostic` | D-266 PARKED | 재개 결정 뒤 카드 작성 |
| `web-common`, `lane-live-view` | 라이브러리 / 제품 밖 시뮬 뷰어 | 제품 UI/UX G2 카드 대상 아님 |

D-153의 여섯 카드 중 운용자 콘솔·장비 런타임·Fleet·게임 보드·로봇 얼굴에 이 회차의 새 캡처가 있다. control 레거시 진단은 D-153에 따라 PARKED다. 이후 추가된 Pilot·Cam·학습 검수 등 활성 표면도 각자 질문·선언 뷰포트·상태 카드를 정해야 제품 전체 GO를 논할 수 있다. 이전 [2026-09-29 회차](../uiux-surfaces-2026-09-29/README.md)의 LOCAL 결과는 현재 트리 전체 G3나 DEVICE/FIELD 판정으로 승격하지 않는다.

**다음 판정 작업:** 각 활성 표면의 선언 상태·뷰포트 G2를 현재 트리에서 채우고, D-153의 여덟 G3 항목에 근거 셀을 적는다. 실제 장치·현장 수용은 LOCAL 캡처와 분리한다. 이 증거가 없으면 디자인이 마음에 들어 보이더라도 GO로 쓰지 않는다.
