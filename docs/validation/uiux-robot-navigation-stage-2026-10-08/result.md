# 로봇 운용 지도·경로 화면 검토 (2026-10-08)

## 판정

로컬 브라우저에서 모바일의 첫 관측 영역이 지도이고, 데스크톱에서는 기존 감지·관측·조작 3열을 유지한다. 로봇 위치와 계획 경로의 가독성을 높이고 CORE 상태, 위치 추정, SLAM 기능 제공 여부를 지도 위에 분리해 표시한다. 운용 콘솔 전체의 D-153 G2/G3 및 장치 수용은 **HOLD**다.

## 화면 평가와 변경

| 발견 | 조치 | 확인 |
|---|---|---|
| 모바일에서 지도는 긴 카메라 영역 뒤에 있어 첫 화면에서 경로를 찾기 어렵다 | 모바일 순서를 지도 → 조작 → 감지로 바꿈. 비상 정지는 상단에 유지 | 390×844 캡처에서 지도와 로봇·경로가 첫 프레임에 들어오고 가로 넘침 0 |
| 지도 안 로봇과 계획 경로가 작아 방향과 진행을 구별하기 어렵다 | 기존 의미색으로 경로 선과 방향 삼각형·위치 링을 확대 | 1366×768, 390×844 캡처를 육안 확인 |
| 지도·SLAM·위치 추정의 의미가 섞일 수 있다 | 주행 상태는 navigation 채널, 지도 좌표 확인은 최신 pose + LOCALIZED/map, SLAM은 capability 제공 여부만 표시 | fixture의 명시적 상태가 각각 별도 문구로 출력됨 |
| 준비 완료 문구와 조작 제한 안내가 지도보다 먼저 공간을 차지한다 | 중복된 준비 완료 문구는 숨기고 조작 제한 사유는 지도 아래에 배치 | 지도 시야가 늘고 비활성 조작의 사유는 남음 |

경로는 Nav2 계획 경로(`/api/v1/navigation/path`)다. 차선 추종의 센서 선이나 실제 주행 궤적이라고 부르지 않는다. 지도 패널은 최신 navigation 상태가 `PLANNING`/`NAVIGATING`이고 pose가 최신이며 경로의 지도 ID·좌표계가 표시 지도와 맞을 때만 경로를 그린다. HUD의 나이는 CORE가 그 경로 메시지를 마지막으로 수신한 뒤의 시간이다. 목표와 경로의 동일성은 API가 증명하지 않으므로 현재 목표의 확정 경로라고 부르지 않는다. SLAM 기능 제공은 현재 지도 생성 중이라는 뜻이 아니다. 실제 SLAM 실행 상태를 보여 주려면 별도 서버 계약이 필요하다.

## 증거

- 브라우저: 실제 FastAPI 정적 자산 + 합성 지도·CORE 상태 응답을 사용한 LOCAL 캡처. X: `projects/rosy-platform/2026-10-08--151842--robot-nav-stage--268890/evidence/navigation-stage/operator-console-navigation-1366x768.png`, `operator-console-navigation-390x844.png`, `navigation-stage-matrix.json`.
- 키보드 지도 선택, 레이아웃, 운용 콘솔 캡처: `11 passed`; `known_failures.py`: 0 NEW. 실행 기록: 같은 X 세션 `logs/focused-tests.txt`.
- G1/패키지/오류·뷰포트 회귀 첫 실행: 138 passed, 3 failed (`logs/ui-gates.txt`). 모바일 순서 단언 2개는 수정 뒤 390×844·320×568 뷰포트와 지도 캡처 3 passed, `known_failures.py` 0 NEW (`logs/final-browser.txt`). 남은 차선 추종 확인 시험은 변경 전 공유 `main`에서도 동일하게 비활성 버튼을 기다리다 실패했다 (`logs/main-line-follow.txt`); 이번 지도 변경의 회귀로 판정하지 않는다. 전체 묶음을 수정 후 다시 돌리지는 않았다.

## 남은 확인

- 현재 로봇 이미지 설치와 실제 지도·경로·위치 증거, SLAM 작업 상태는 확인하지 않았다.
- 기준 트리에서도 실패하는 차선 추종 시험의 fixture/구동 준비 상태는 별도 수정이 필요하다.
- D-153 전체 상태 매트릭스와 사용자 G3 평가는 별도 회차가 필요하다. 이 캡처만으로 GO를 선언하지 않는다.

## 후속: 보이는 순서와 키보드 순서 일치

모바일에서 지도→조작→감지 순서로 재배치한 뒤에도 실제 HTML 슬롯 순서는 감지→지도→조작이었다. 키보드와 화면 읽기 순서가 화면과 달라지는 결함이다. 셸에서 64rem 경계에 맞춰 슬롯 DOM 순서를 모바일 `지도→조작→감지`, 데스크톱 `감지→지도→조작`으로 동기화하고, 폭 전환 중 패널 안에 있던 초점을 복원했다. 패널을 새로 mount하거나 CORE 명령을 보내지 않는다.

- 2026-10-08 후속 LOCAL 캡처: 같은 X: 세션의 `evidence/focus-order/navigation-stage/operator-console-navigation-{1366x768,390x844}.png`와 `evidence/focus-order/viewport/robot-console-{390x844,320x568}.png`. 390px의 지도 무대와 1366px의 3열, 320px의 지도 오류·재시도 및 비상 정지를 원본 크기로 확인했다.
- 실제 FastAPI·Chromium에서 DOM/시각 순서와 1366→390→1366 폭 전환 후 지도 캔버스 초점 유지 등 3 passed, `known_failures.py` 0 NEW (`logs/responsive-focus-tests.txt`). 레이아웃 추가 묶음은 13 passed, 2 failed (`logs/focus-order-layout.txt`); 실패는 `/setup` 사실 격자 시험 2건이며 공유 `main`에서 같은 2건이 재현됐다 (`logs/main-procedure-baseline.txt`). 두 실행 모두 `known_failures.py`는 `NEW`로 분류하므로 전체 묶음 PASS는 주장하지 않는다.
- 390×844·320×568의 실제 CORE 셸 뷰포트 시험에서 문서 순서·정지 가시성·가로 넘침을 다시 확인했다: 2 passed, 0 NEW (`logs/focus-order-viewport.txt`).
- `impeccable detect --json` 변경 파일 검사 결과 `[]` (`logs/impeccable-focus-order.json`). 이 정적 검사와 합성 CORE 캡처는 실제 로봇·사용자 수용을 대체하지 않는다.

## 후속: 위치 추정 불확실 시 지도 목표 차단

CORE는 지도 좌표를 신뢰할 수 없는 로봇의 주행 목표를 거절한다. 콘솔도 최신 pose와 `LOCALIZED/map` 확인 전에는 목표 버튼을 막고 이유를 표시한다. 초기 위치 설정은 위치 추정을 회복하기 위한 조작이므로 권한·기능·하드웨어 조건을 만족하면 계속 사용할 수 있다. `SUSPECT` 등 불확실한 상태에서는 오래된 계획 경로와 로봇 좌표를 숨기고, 지도 HUD와 로봇 상태 요약에 위치 확인 필요를 표시한다. 위치 추정 블록이 없는 이전 CORE 응답은 기존 API 호환 범위로 처리한다.

- 같은 X: 세션의 `evidence/goal-gate/navigation-stage/`에 1366×768·390×844 정상 화면과 390×844 `SUSPECT` 화면, 매트릭스 JSON을 기록했다. 합성 API 응답으로 렌더링한 실제 FastAPI·Chromium 화면이며 로봇 readback은 아니다.
- `SUSPECT`에서 초기 위치 버튼 활성, 목표 버튼 비활성 및 사유, 파란 계획 경로와 좌표 숨김을 확인했다. `LOCALIZED/odom`에서도 목표 비활성, `LOCALIZED/map` 복귀 뒤 활성 상태를 확인했다. 브라우저·지도 관련 3 passed (`logs/goal-gate-tests.txt`), 추가 요약·지도 오류·패키지 회귀 21 passed (`logs/goal-gate-regression.txt`), 각 `known_failures.py` 0 NEW.
- 실제 장치의 pose 전환, 목표 전송 성공, 물리 주행, G3 운용자 판단과 전체 G2 상태 매트릭스는 여전히 HOLD다.

## 후속: 로봇과 표시 지도의 ID 정합성

지도 응답의 `map_id`와 로봇 상태의 `map_id`가 둘 다 있고 서로 다르면 지도 좌표 조작을 막는다. 경로·로봇 마커·기억한 목표 마커도 그 지도에 겹치지 않는다. 지도 HUD와 조작 사유에 불일치를 표시하고, ID가 다시 일치하면 표시와 조작을 복구한다. `/dashboard`의 기존 지도 호출도 같은 비교를 사용한다. CORE는 점유 지도를 수신할 때의 ID를 격자와 함께 저장한다. 이후 로봇 상태 ID가 바뀌어도 오래된 격자에 새 ID를 덧씌우지 않는다. 한쪽 ID가 없는 이전 응답에서는 비교를 확정할 수 없어 기존 동작을 유지한다.

- 같은 X: 세션 `evidence/map-identity/navigation-stage/`의 1366×768·390×844 정상 화면과 양쪽 폭의 `operator-console-navigation-map-mismatch-*.png`를 확인했다. 불일치 화면에서 양쪽 좌표 버튼 비활성, 이유 표시, 경로와 로봇 마커 숨김, 일치 복귀 뒤 목표 버튼 활성화가 브라우저 시험으로 확인됐다.
- 실제 FastAPI 정적 자산과 합성 CORE 응답의 관련 21 passed, `known_failures.py` 0 NEW (`logs/map-identity-tests.txt`). CORE 지도 스냅숏 API 11 passed (`logs/map-snapshot-tests.txt`): 로봇 상태 ID가 바뀐 뒤에도 이전 지도 응답 ID가 그대로인 시험을 포함한다. 추가 패널 브라우저 묶음은 21 passed/1 failed (`logs/map-identity-regression.txt`); 실패한 차선 추종 확인 시험은 기존 공유 `main`의 같은 시험에서도 재현돼 별도 결함으로 기록한다. 이 시점에는 경로 생성 시각이나 목표별 동일성을 증명할 수 없었고 실기 판정은 HOLD다.

## 후속: 계획 경로의 수신 근거와 좌표계

CORE는 마지막 `nav_msgs/Path`의 `frame_id`, 수신 때의 `map_id`, 서버 수신 나이 `age_s`를 경로 점과 함께 반환한다. [ROS 2 Jazzy `Path` 정의](https://github.com/ros2/common_interfaces/blob/jazzy/nav_msgs/msg/Path.msg)의 header가 좌표계를 담는다. 지도는 점이 둘 이상이고, 경로가 `map` 좌표계이며, 경로·지도 ID가 일치하고, 수신 나이가 유효한 경우에만 선을 그린다. HUD는 `계획 경로 · 마지막 수신 N초 전`이라고 말한다. 경로 데이터가 없거나 근거가 모자라면 그 이유를 표시한다. 전환 중 늦은 HTTP 응답이 새 경로를 덮어쓰지 않도록 요청 순서도 확인한다.

- 같은 X: 세션 `evidence/path-provenance/navigation-stage/`에 정상 1366×768·390×844, 경로 지도 ID 불일치 1366×768·390×844, `odom` 경로 390×844 캡처를 둔다. 파란 경로는 정상 근거에서만 보이며, 불일치에서도 로봇 위치 마커는 유지된다.
- CORE 지도·브리지 41 passed (`logs/path-provenance-core.txt`), 로봇 화면 브라우저·패키지 21 passed (`logs/path-provenance-browser.txt`). 둘 다 `known_failures.py`에서 NEW 여부를 확인한다.
- 수신 나이는 경로가 만들어진 시각이나 현재 목표에 속한다는 증거가 아니다. 작업 브랜치는 API Ref v1.141 기반이고 현재 공유 main은 v1.142여서 착지 전 API 버전·변경 이력의 재조정이 필요하다. 실제 Nav2 메시지 빈도, 현장 경로 추종·도착 및 G3 판정은 HOLD다.
