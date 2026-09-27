# 역할 화면과 Fleet 배치 재평가 — 2026-09-27

## 범위와 판정

사용자가 지적한 겹침·과밀·시각 위계 문제를 현재 역할별 `/console`, `/setup`, `/device`와 Fleet `/console`에서 확인했다. 이 회차는 Windows Chromium과 가짜 CORE/Fleet 응답을 사용한 **LOCAL** 점검이다. 화면 수정은 완료했지만 D-153의 전체 상태 행렬, 8항 G3 수용과 D-255의 B2 벤치·B3 진단 편입이 남아 있으므로 **제품 전체 UI/UX 판정은 HOLD**다.

| 표면 | 수정 전 근거 | 수정과 현재 LOCAL 근거 |
|---|---|---|
| 역할 운용 1366×768 | 관측 열 아래의 카메라가 뷰포트 바닥에서 잘림 | 카메라를 상태 열에 놓고 지도에 관측 열을 모두 줬다. 문서 스크롤 0, 활성 조작 패널과 E-stop은 화면 안에 있다. 상태 열만 내부 스크롤한다. |
| 작업 준비·설치 390×844 | 입력창의 content-box 때문에 문서가 6px 가로로 넘침. 서로 다른 작업의 경계가 흐림 | 입력창 box sizing을 고치고 절차 패널을 공유 컴포넌트 바깥의 래퍼로 묶었다. 패널 교차와 가로 넘침 0. 절차 페이지의 세로 스크롤은 유지한다. |
| Fleet 1920×1080 | 지도 대부분은 비었고 24rem 오른쪽 열에 목록·발견·대형·신호가 몰림 | 지도 43%, 개입 57%로 배분하고 목록과 사이트 조작을 개입 영역의 별도 열에 놓았다. 로봇 목록은 자체 스크롤, 문서 스크롤 0. 반복 영문 소제목을 걷고 한국어 제목의 크기를 올렸다. |
| Fleet 390·320px | 상단 인증·상태·전체 정지가 화면 밖으로 밀리고 320px 로봇 상태 태그가 19px 넘침 | 상단을 폭에 맞춰 행으로 재배치하고 상태 태그가 접히게 했다. 두 폭에서 문서 가로 넘침 0, 상태와 정지 버튼은 화면 안에 있다. |
| 조작 그룹 키보드 | 비활성화 후 재활성화된 `ui-button` 탭 세 개가 모두 Tab 순서에 들어감 | 실제 공용 `ui-button`을 시험에 포함해 재현했고, 선택 탭 한 개만 Tab 순서에 남도록 복원했다. 방향키 뒤 포커스도 확인했다. |

## 배치 결정과 유지보수 경계

- D-280의 차분한 색과 공유 토큰을 유지한다. 색을 추가하지 않고 작업, 관측, 개입의 공간 비율을 조정했다.
- 카메라 위치는 `panels.yaml`의 slot 선언으로 옮겼다. API 계약이나 패널 동작은 바꾸지 않았다.
- 설치·정비 카드의 면과 테두리는 `.procedure-panel` 래퍼가 그린다. 공용 `ui-section`을 화면 CSS에서 다시 그리지 않으므로 공유 컴포넌트 계약을 지킨다. 래퍼는 패널 unmount와 함께 제거된다.
- Fleet의 관제 범위 설명은 지도 아래 기본 닫힌 disclosure로 옮겼다. 내용은 키보드로 다시 펼칠 수 있다. E-stop·연결 상태·대형 상태는 계속 바로 보인다.
- 되돌릴 때 이 회차의 manifest, shell CSS/JS, Fleet HTML/CSS를 한 단위로 되돌린다. API나 데이터 저장 형식의 마이그레이션은 없다.

## 검증과 캡처

| 게이트 | 명령·근거 | 판정 |
|---|---|---|
| G1 HMI | `ROSY_RUN_BROWSER_TESTS=1 python -m pytest src/hmi/web/test src/hmi/dashboard/test -q` | 최신 `main` 통합 후 105 passed |
| G1 역할 화면 API | `ROSY_RUN_BROWSER_TESTS=1 python -m pytest src/runtime/api_web/test/test_d283_console_browser.py -q` | 최신 `main` 통합 후 5 passed |
| G1 Fleet | `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py -q` | 최신 `main` 통합 후 17 passed |
| 문서 harness | `python tools/harness/rosy_harness.py lint`; `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q` | 0 errors/21 warnings; 75 passed/21 warnings |
| G2 로컬 뷰포트 | `/console` 1366×768·390×844, `/setup`·`/device` 1366×768·390×844, Fleet 1920×1080·390×844·320×844 | 이 범위의 겹침·가로 넘침 확인 |

캡처는 드라이브 규칙에 따라 저장소가 아닌 `X:\DevTemp\`에만 둔다: `d283-console-core-browser/`, `rosy-uiux-current-surfaces/`, `fleet_console_fit.png`, `fleet_console_mobile_320.png`, `fleet_console_mobile_390.png`. 위 명령으로 재생성할 수 있다. X:의 일회성 캡처가 유지되는 기간에만 직접 육안 대조할 수 있으므로 D-153의 보존형 G2 회차 완료로 세지 않는다.

## D-153 G3 8항 점검

| 항목 | 확인한 근거 | 남은 한계 |
|---|---|---|
| 정직 | CORE 미제공 Navigation/SLAM 조작은 비활성, Fleet 불가 조작은 기존 계약 시험에서 차단 | 실제 장치 기능 표본 없음 |
| 증거 상태 | CORE 최초 기동·Fleet 정상/빈 목록/큐 fixture를 구분 | 현재 역할 화면의 delayed·disconnected 등 전체 상태 캡처 미완료 |
| 색 | 기존 토큰을 재사용했고 새 장식색을 넣지 않음 | 실제 LCD·현장 조명 판정 없음 |
| 위계 | 운용 카메라가 지도에서 분리되고 Fleet 목록·사이트 조작에 서로 다른 공간을 부여 | 현장 거리에서 시인성 확인 필요 |
| 불가역 | E-stop은 상단에 있고 Fleet 확인 대화상자 회귀를 실행 | 물리 정지 readback 없음 |
| 어휘 | 반복 영문 eyebrow를 없애고 작업·현장 명칭을 유지 | 설치자 인터뷰 없음 |
| 표면 질문 | 운용 상태/관측/조작, Fleet 로봇/대형/신호를 캡처에서 대조 | 실시간 사이트 운용 판단 없음 |
| 표면 문법 | 운용·Fleet 데스크톱 무스크롤, 절차 화면 세로 스크롤, 모바일 줄바꿈 확인 | 전 상태·전 장치 크기 수용 아님 |

이 표는 에이전트 육안 검토 기록이다. D-153의 표면별 GO에는 보존된 전체 G2 상태 셀과 G3 위반 0의 별도 판정이 필요하다. D-255 B2/B3, 이미지 설치, 로봇·사이트 실측도 이 LOCAL 작업으로 승격하지 않는다.

## 후속 확인: 현재 역할 화면의 증거 상태

`/console`의 로봇 상태 패널에서 위치·배터리 `delayed`·`disconnected`·`unavailable`이 모두 “수신 대기”로 표시되는 결함을 확인했다. 서버의 증거 판정을 바꾸지 않고, 현재 역할 화면에서 각각 “지연 · 마지막 수신 후 경과 시간”, “연결 끊김”, “정보 없음”으로 구분했다. `fresh`인데 값이 비어 있는 경우도 0으로 대체하지 않는다.

실제 FastAPI 앱과 CORE 서비스 fixture를 통과하는 Chromium 시험은 세 상태 × 1366×768·390×844의 6셀에서 문구, `data-evidence`, 가로 넘침, 페이지 오류를 검사한다. 캡처는 드라이브 규칙에 따라 `X:\DevTemp\rosy-uiux-evidence-matrix\`에만 생성한다. 이 6셀은 **LOCAL 브라우저 증거**이며, 저장소에 보존된 전체 G2 행렬이나 BENCH/DEVICE 증거로 세지 않는다. D-153의 나머지 상태·표면 셀, G3 8항 최종 판정, D-255 B2/B3는 계속 별도 게이트다.

## D-306 후속 확인: Fleet 지도 목표 지정

Fleet 지도에서 `rosy_02` 목표를 선택하고 방향키로 한 칸 이동한 상태를 Windows Chromium의 1920×1080, 390×844, 320×844에서 캡처했다. 세 뷰포트 모두 가로 넘침과 페이지 오류가 없었고, 실제 포커스는 `map-canvas`였다. 대상과 현재 좌표 `(1.07, 1.03) m`, 방향키·Enter·Escape 안내가 보였다. 모바일 뷰포트에서 지도 포커스 링, 상단 전체 정지, 지도 아래 로봇 목록을 육안으로 확인했다.

| 셀 | LOCAL 결과 | 캡처 (일회성, X:) |
|---|---|---|
| Fleet 목표 선택 1920×1080 | 포커스·좌표 안내·가로 넘침 0·페이지 오류 0 | `X:\DevTemp\rosy-uiux-d306\fleet_goal_viewport_1920x1080.png` |
| Fleet 목표 선택 390×844 | 동일 | `X:\DevTemp\rosy-uiux-d306\fleet_goal_viewport_390x844.png` |
| Fleet 목표 선택 320×844 | 동일 | `X:\DevTemp\rosy-uiux-d306\fleet_goal_viewport_320x844.png` |

Fleet 브라우저 회귀는 18 passed, 포커스 복귀를 보완한 후 목표 지정·확인 계약 집중 회귀는 4 passed였다. 확인 취소 시 목표 API 0회, 승인 시 지정 로봇에 1회가 시험되었다. X: 캡처는 장기 보존 증거가 아니며 빈 지도·지연·연결 끊김·권한 거부 등 전체 G2 셀, G3 최종 판정, 실제 로봇 이동은 HOLD다.

## D-306 후속 확인: 다른 표면의 LOCAL 개선

| 표면 | 이번 변경과 LOCAL 증거 | 남은 판정 |
|---|---|---|
| `/device` Host Agent 절차 | 네트워크·릴리스 요청의 대기·거부·오류·접수 문구를 해당 조작 옆에 유지한다. Host Agent를 잃으면 과거 성공 문구를 가린다. 현재 teleop 자격을 빠뜨린 기존 시험 fixture를 정렬한 뒤 dashboard·역할 브라우저 46 passed. | `/setup`·`/device`의 지연·연결 끊김·권한 거부 등 전체 G2와 G3는 미완료. 장치 결과 readback은 별도. |
| 게임 보드 1280×800 | 최초 데이터 전 점수는 `—`이며 단계·점수·유실 변화만 보조기기에 알린다. `/stop`의 요청 중·접수·실패 및 재시도, 연결 오류의 마지막 수신값을 표시한다. 브라우저 9 passed, 게임 호스트 110 passed, 공유 UI 계약 58 passed. | 접수 문구는 물리 정지 증거가 아니다. 전체 G2·실제 경기/장치 정지는 HOLD. |
| LCD 320×240 | 긴 로봇 ID·상태·주소를 화면 여백 안에서 말줄임한다. PIL/QR 129 passed, 8개 LOCAL PNG를 육안으로 확인했다. | 거리·각도·조명에서 실물 LCD 판독성이 없어 DEVICE/BENCH HOLD. |
| Gazebo 읽기 전용 뷰어 1280×800 | 두 탭을 방향키·Home·End로 전환하고 포커스 및 탭·패널 관계를 표시한다. viewer 시험 59 passed, 라이브/지난 결과 캡처에서 가로 넘침·페이지 오류 0. | 데모/호스트 화면 증거로 실제 Gazebo 카메라·인지, 실물 운용을 증명하지 않는다. |
| 레거시 sensing 진단 | D-253의 PARKED와 D-266의 해제 조건을 유지했다. | 소유·보안·상태 행렬 승인 전 운영 화면 G2/GO에 포함하지 않는다. |

일회성 캡처는 저장소 밖 `X:\DevTemp\games_board_stop_retry.png`, `X:\DevTemp\games_board_host_disconnected.png`, `X:\DevTemp\rosy-uiux-lcd-2026-09-27\`, `X:\DevTemp\rosy-uiux-d306\gazebo_viewer_{live,results}_1280x800.png`에 있다. 이 회차는 상태별 전체 캡처와 독립 수용이 없어 D-153의 표면별 최종 GO를 선언하지 않는다.

## D-306 G2/G3 후속 회차 (현재 판정)

위 수치와 캡처는 최초 배치 회차의 기록이다. 후속 수정·평가의 최신 근거는 아래 표면별 카드가 소유한다. X: 캡처는 일회성 LOCAL 증거이며 실제 로봇·LCD·현장 수용으로 승격하지 않는다.

| 표면 | 후속 회차 근거 | 현재 차단 조건 |
|---|---|---|
| Fleet | [fleet-g2-matrix.md](fleet-g2-matrix.md): 1920×1080·390×844·320×844에서 상태 8종+최초 기동 27개 캡처, 가로 넘침 0, 브라우저·대화상자 24 passed. 안전 미확인 목표 차단과 빈 목록 안내 수정. | 팔로워 지연 나이 없음, 정상 로봇이 기본 목록에 모두 보이는 예외 문법 위반, 식별색 원칙 미정, 네이티브 확인 이미지·실물 개입 readback 없음. **HOLD** |
| 역할별 `/setup`·`/device` | [roles-g2-matrix.md](roles-g2-matrix.md): 운영자·관리자, 1366×768·390×844의 54셀 캡처에서 가로 넘침·페이지 오류 0. 위치 지연·끊김·정보 없음과 `/device` 권한 거부 복구 링크 수정. | 최초 기동·확인창 이미지, `/device` 지연/끊김, 절차의 SAFE_STOP 명시, 전체 권한/오류 조합과 장치 readback 없음. **각각 HOLD** |
| 게임 호스트 | [games-g2-matrix.md](games-g2-matrix.md): 1280×800 상태 10종, 넘침 0, 브라우저 11 passed. 점수의 마지막 수신 표시, 정지 실패·시간 초과와 포커스 복구 수정. | overlay 시각 정보가 없어 delayed 셀 미평가, 공·팀 식별색의 법칙 적용 범위 미정, 실제 정지·경기 확인 없음. **HOLD** |
| 로봇 얼굴 LCD | [lcd-g2-matrix.md](lcd-g2-matrix.md): 320×240 PIL 상태 9종, 관련 시험 148 passed. | Pi 폰트·실물 거리/각도/조도·카드 만료 후 GIF 복귀 미관찰. **HOLD** |

기존 `/console` 6셀은 위 "현재 역할 화면의 증거 상태"에 기록했다. 레거시 sensing 진단은 D-253/D-266에 따라 **PARKED**다. 제품 전체 D-153 UI/UX 판정은 **HOLD**다.

## D-309 실행 후 LOCAL 판정 (2026-09-27)

| 표면 | 현재 코드·브라우저 근거 | 남은 수용 |
|---|---|---|
| Fleet | 서버 532 passed/5 skipped, 브라우저 22 passed. 변경 후 `X:\DevTemp\fleet_console_exception_first.png`, `fleet_console_overlay.png`, `fleet_console_mobile_320.png`, `fleet_console_mobile_390.png`를 확인했다. 기본 목록은 개입 대상만 보이고 전체 보기로 정상 로봇에 접근한다. | 로봇 송신은 팔로워 수신·추종 readback이 아니다. 현장 목표 이동·정지와 전체 G3는 HOLD. |
| 역할 `/setup`·`/device` | 역할 매트릭스 단독 재실행 1 passed. `X:\DevTemp\rosy-uiux-d306-roles-g2\matrix.json`의 56셀 중 SAFE_STOP 6셀, 가로 넘침 0, pageerror 0을 확인했다. 동시 Chromium 실행은 브라우저 종료 오류가 있었고 단독 실행에서 재현되지 않았다. | 실제 CORE·장치의 정지 readback과 전체 역할별 G3는 HOLD. |
| 게임 보드 | 서버 102 passed, 브라우저 12 passed. 변경 후 `X:\DevTemp\games_board_play.png`, `games_board_delayed.png`에서 생성 시간과 지연을 확인했다. | 실제 카메라·로봇·물리 정지와 전체 G3는 HOLD. |
| LCD | 기존 PIL 148 passed와 320×240 캡처 9개. 이번 코드 변경 없음. | Pi 실물 가독성·만료·각도·조도는 HOLD. |

위 X: 파일은 일회성 로컬 캡처이며 저장소 증거 아카이브나 DEVICE/FIELD 수용을 대신하지 않는다. D-153의 화면별 G2/G3 GO는 선언하지 않는다.

## D-309 후속 회귀 (LOCAL)

- Fleet 상태 조회 상실 후 마지막 좌표를 가리고 목표·취소 조작을 막는다. 복구 시 새 조회값으로 돌아온다. 브라우저 23 passed, 상실·복구 단독 1 passed. 캡처: `X:\DevTemp\fleet_console_gather-lost-after-live.png`.
- `/setup` waypoint는 서버가 준 pose 증거가 fresh이고 좌표가 유효할 때만 저장을 연다. 전송 중 중복 요청과 끊김 뒤 재활성화를 막는다. 담당 세션 Chromium 4 passed, 신규 단독 1 passed.
- 게임 보드는 지연 상태 전환을 보조기기에 알리고 첫 연결 실패 때 경기 정보 없음으로 말한다. 브라우저 13 passed, 영향 시험 3 passed. 캡처: `X:\DevTemp\games_board_delayed.png`, `games_board_first_error.png`.
- LCD는 잘못된 카드 유지 시간을 기본 15초로 되돌린다. 호스트 시험 137 passed/4 skipped. 실제 LCD 카드 만료·GIF 복귀와 현장 가독성은 미검증이다.

이 회귀는 화면별 LOCAL 범위만 보강한다. 기존 표면별 HOLD와 DEVICE/FIELD 수용 대기는 유지한다.
