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
