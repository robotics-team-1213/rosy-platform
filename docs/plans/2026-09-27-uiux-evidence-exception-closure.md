# D-309 화면 증거·예외·안전 상태 완료 실행 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** D-153의 Fleet·게임·역할 절차 UI/UX HOLD 중 소스/LOCAL에서 해결 가능한 시간 증거, 예외 문법, SAFE_STOP, 색과 확인 증거를 순서대로 닫는다.

**Architecture:** 값별 신선도·capability·권한·안전·명령 결과의 판정은 CORE/Fleet/게임 호스트가 가진다. 프론트는 서버가 판정한 증거를 표면 문법으로 표시하고 목록 정렬·포커스·입력·확인·결과 읽기를 맡는다. LCD·실제 정지/이동과 현장 판독은 별도 BENCH/DEVICE/FIELD 수용이다.

**Tech Stack:** Python ROS-free pytest, FastAPI/TestClient, vanilla ES modules, Playwright Chromium, PIL LCD, Rosy 문서 harness.

**Basis:** [D-309](../adr/D-309-uiux-evidence-and-exception-closure.md), [D-153](../adr/D-153-ui-ux.md), [2026-09-27 표면 카드](../validation/uiux-surfaces-2026-09-27/README.md). 현재 기준 HEAD는 `751a54f7`; 실행 시마다 main·작업 worktree의 HEAD·변경 파일을 다시 확인한다. F:의 임시물은 만들지 않고 PNG/로그는 `X:\DevTemp\`에 둔다.

## Task 0 — 결정·계약·작업 경계

**Files:** `docs/adr/D-309-uiux-evidence-and-exception-closure.md`, 이 계획, `docs/reference/ROSY ADR Log.md`, `docs/progress.md`, `docs/logs.md`, `docs/index.md`(생성).

1. D-153/D-218/D-280/D-306 및 네 표면의 기존 G2 카드를 현재 코드와 대조한다. D-309를 Accepted로 기록하되 제품 표면 GO와 혼동하지 않는다.
2. ADR 로그에 D-309 한 행을 추가하고 `docs/progress.md`의 ADR 목록과 `docs/logs.md`에 SOURCE 문서 결정을 기록한다. `python tools/harness/rosy_harness.py generate`를 실행한다.
3. `python tools/harness/rosy_harness.py lint`와 `python -X utf8 -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q -p no:cacheprovider`를 통과시킨다. 문서만으로 G2/G3는 HOLD다. 문서 파일만 명시적으로 커밋한다.

## Task 1 — Fleet 팔로워 송신 나이

**Files:** `src/site/fleet/fleet/swarm/relay.py`, `src/site/fleet/fleet/server/console.py`, `src/site/fleet/fleet/server/web/map-view.js`, `src/site/fleet/fleet/server/web/roster.js`, `src/site/fleet/test/test_relay.py`, Fleet formation 응답 계약 시험, `test/test_fleet_console_browser.py`, `docs/spec/ROSY FLEET SRS.md` 또는 응답 계약의 현재 정본.

1. 가짜 monotonic clock에서 송신 전 `None`, 송신 직후 0초, 중단 후 실제 경과 시간이 `RelayStats.follower_last_tx_age_s[robot_id]`에 남는 시험을 먼저 적고 적색을 확인한다. 연결 실패·pause 후 오래된 송신을 새 송신으로 바꾸지 않는 사례를 포함한다.
2. `_Lane.rate.age_s()`를 읽기 전용 통계로 노출한다. Fleet 서버가 리더/팔로워별 `stream_evidence`의 판정·age·reason·threshold를 만들고 `/api/fleet/formation`에 보낸다. `leader_age_s`와 팔로워 마지막 송신 나이는 별개 출처다. CORE 로봇 수신·실행 증거로 재해석하지 않는다.
3. 브라우저 fixture는 서버가 준 `stream_evidence`로 `지연 · 마지막 송신 N초 전`, `끊김`, `송신 시각 없음`을 렌더한다. `map-view.js`의 `STREAM_HZ_FLOOR`·`LEADER_AGE_MAX_S`와 클라이언트 판정을 없앤다. 서버 판정이 빠진 구버전 응답은 `증거 판정 없음`으로 처리하고 정상으로 추정하지 않는다.
4. `python -X utf8 -m pytest src/site/fleet/test/test_relay.py -q -p no:cacheprovider`; `$env:ROSY_RUN_BROWSER_TESTS='1'; python -X utf8 -m pytest test/test_fleet_console_browser.py -q -p no:cacheprovider`. 이 범위와 Fleet G2 카드만 커밋한다.

## Task 2 — Fleet 예외 목록과 정상 접근

**Files:** `src/site/fleet/fleet/server/web/{index.html,console.js,roster.js,styles.css,map-view.js}`, `test/test_fleet_console_browser.py`, `docs/validation/uiux-surfaces-2026-09-27/fleet-g2-matrix.md`.

1. 예외 1대+정상 2대 fixture에서 초기 화면에는 예외만, 접힌 정상 수와 `전체 로봇 보기`가 보이는 실패 시험을 쓴다. 정상만 있을 때 `개입할 로봇 없음`, 빈 등록 목록일 때 별도 빈 안내를 요구한다.
2. 연결/안전/큐/양보/릴레이 근거에서 단일 `needsAttention(robot, formation)` 판정을 만들고 기본 목록을 정한다. 선택된 로봇은 목록을 다시 접어도 유지한다. 전체 보기 토글은 `aria-expanded`·연결 대상·포커스 복귀를 가진다. 지도와 formation 원본 `view.robots`는 필터링하지 않는다.
3. 정상 카드의 경보색 테두리를 중립으로 바꾸되 경보 행과 지도 데이터 식별색은 기존 토큰 의미를 유지한다. 키보드 ↑/↓/Enter/Escape, 목표 확인 취소/승인, 1920×1080 무스크롤과 390/320px 가로 넘침 0을 다시 시험·캡처한다.
4. Fleet 브라우저·대화상자·색 계약을 통과시키고 G3 #3/#8을 다시 판정한다. LOCAL 화면 계약만 커밋한다. 정상 로봇의 목표 지정 경로가 사라지면 병합하지 않는다.

## Task 3 — 게임 생성 시각과 색

**Files:** `src/site/games/games/host/{preview.py,loop.py}`, `src/site/games/games/web/{board.js,styles.css}`, `src/site/games/test/test_preview.py`, `test/test_games_board_browser.py`, `docs/validation/uiux-surfaces-2026-09-27/games-g2-matrix.md`.

1. 경기 틱의 UTC 생성 시각이 페이로드에 1회 기록되고, `PreviewBoard.snapshot()` 반복 읽기는 그 시각을 갱신하지 않는 시험을 먼저 적는다. 서버의 가짜 monotonic clock으로 신선/지연/아직 없음 판정과 나이를 시험한다.
2. `generated_at`을 페이로드에 추가하고 `/overlay.json` 요청 때 호스트가 `age_s`·`stale_after_s`·`evidence`를 계산한다. 보드는 서버 판정만 표시한다. `delayed`면 `지연 · 마지막 생성 N초 전`, 필드가 없으면 `시각 정보 없음`으로 말하며 클라이언트 시계로 `fresh`를 만들지 않는다. 서버 응답 실패와 경기 HOLD 문구는 별도 유지한다.
3. 공의 초점색만 D-280 데이터 예외로 남기고 홈/원정의 따뜻한 장식색을 중립화한다. 팀 이름·위치·텍스트가 색 없이 구분되는지 1280×800에서 캡처한다.
4. `python -X utf8 -m pytest src/site/games/test/test_preview.py -q -p no:cacheprovider`; `$env:ROSY_RUN_BROWSER_TESTS='1'; python -X utf8 -m pytest test/test_games_board_browser.py -q -p no:cacheprovider`. 시간 필드와 G2/G3 카드 변경을 묶어 커밋한다.

## Task 4 — 역할 절차 SAFE_STOP과 결과 읽기

**Files:** `src/hmi/dashboard/shell/{shell.js,shell.css}`, 필요한 `panels/setup`·`panels/host` 파일, `src/hmi/dashboard/test/test_role_g2_browser.py`, `src/runtime/api_web/test/test_d283_console_browser.py`, `docs/validation/uiux-surfaces-2026-09-27/roles-g2-matrix.md`.

1. 관리자/운영자 `/setup`, 관리자 `/device`에서 `mode=SAFE_STOP`이 들어오면 상단 절차 상태·다음 행동이 보이고 운동 개시 조작은 차단되며 E-stop과 읽기 패널은 남는 브라우저 실패 시험을 쓴다. `fresh`/단절에서 상태를 꾸미지 않는 시험도 포함한다.
2. 매니페스트 구조를 늘리지 않고 현재 `/api/v1/robot/state`를 절차 셸의 상태 리드백으로 사용한다. 안전 정지 표시는 조회 실패/권한 거부 시 `상태 확인 불가`로 바꾸고 과거 정상 문구를 남기지 않는다. 각 조작의 비활성 사유는 해당 패널에 붙인다. API 인가·D-283 운용 3영역은 유지한다.
3. 최초 기동→성공/거부/오류, `/device` Host Agent 끊김/복구, 네이티브 confirm 이벤트 증거를 1366×768·390×844로 보강한다. 확인 취소 API 0회, 승인 1회는 D-218 계약과 함께 검증한다. 단순 POST 접수는 적용 완료로 표시하지 않는다.
4. `$env:ROSY_RUN_BROWSER_TESTS='1'; python -X utf8 -m pytest src/hmi/dashboard/test src/runtime/api_web/test/test_d283_console_browser.py -q -p no:cacheprovider` 및 정적 자산 경로 시험 후 커밋한다. 실제 정지 readback은 DEVICE 회차다.

## Task 5 — 표면별 회차와 비로컬 수용

**Files:** `docs/validation/uiux-surfaces-2026-09-27/{README.md,fleet-g2-matrix.md,games-g2-matrix.md,roles-g2-matrix.md,lcd-g2-matrix.md}`, `docs/logs.md`, 필요할 때 각 모듈 `progress.md`·`logs.md`, 생성 index.

1. 네이티브 confirm은 페이지 호출 버튼 캡처 + dialog 문구 + 취소 0회/승인 1회 + 포커스 복귀로 기록한다. 브라우저/OS 크롬의 PNG는 D-309에 따라 비해당이며 캡처 부재만으로 G2를 막지 않는다.
2. 표면별 G1/G2/G3 8항을 현재 커밋과 캡처 경로에 다시 붙인다. `X:\DevTemp`의 일회성 캡처를 장기 보존 증거로 부르지 않는다. 남은 셀이 있으면 해당 표면 HOLD를 명시한다.
3. 실제 Pi LCD의 폰트/거리/각도/조도/GIF 만료, 로봇 목표 이동과 정지, 게임의 양쪽 정지, 현장 사이트 판독은 장치 식별·artifact digest·사진/영상·API/readback을 함께 받아 별도 BENCH/DEVICE/FIELD 카드로 기록한다. 장치 접근이 없으면 `NOT_RUN`/HOLD로 끝낸다.
4. `python tools/harness/rosy_harness.py generate`, `lint`, docs 계약 시험, `git diff --check`를 실행한다. main·worktree의 HEAD와 변경 경로를 확인하고 검증된 커밋만 로컬 main에 통합한다. push·CI·배포는 이 계획의 자동 완료가 아니다.

## 되돌리기

Task 1/2/3/4의 각 표면 변경은 별도 커밋으로 되돌린다. 시간 필드가 없는 이전 응답은 `시각 없음`으로 읽으므로 서버/화면을 함께 되돌릴 필요가 없도록 한다. 공용 토큰/부품을 바꾸면 모든 소비 표면 G1/G2를 다시 실행한다. D-309 기준 자체를 변경해야 하면 새 ADR로 대체한다.

## Task 0a — 서버 안전 경계 검증 (우선 실행)

- Fleet 작업 디스패처는 `safety.estop is False`가 명시된 로봇만 가용하다고 판단한다. 누락·null·true는 대기열에 남긴다.
- `test_task_api.py`에서 네 상태의 대기열 유지와 명시적 false의 배정을 검증한다.
- 프론트의 버튼 비활성화는 안내이며, Fleet 서버의 가용성 검사와 CORE의 최종 이동 허용 검사를 각각 유지한다.
- 명령 접수·CORE ACK·상태 readback·물리 이동은 다른 증거로 기록한다.

## 2026-09-27 실행 현황 (로컬 main 기준)

- Task 0/0a: D-309 결정·책임 경계와 Fleet 안전 상태 미확인 디스패치 차단을 `ca23fee7`로 통합했다.
- Task 1: Fleet 마지막 송신 나이와 서버 지연 판정을 `c2ae15b9`로 통합했다. 2 Hz 판정과 첫 표본 예외는 후속 보완했다.
- Task 2: Fleet 예외 우선 목록과 전체 로봇 접근을 `1a146b88`로 통합했다.
- Task 3: 게임 보드 생성 시각·지연 표시·팀 색 조정을 `67459ab0`로 통합했다.
- Task 4/5: 역할 화면 SAFE_STOP 표현·실제 명령 차단 검증, 변경 후 화면 캡처와 장치·현장 수용은 남아 있다. 현재 로컬 기준 화면 전체 G2/G3와 DEVICE/FIELD는 HOLD다.
- 상단 Basis의 `751a54f7`은 착수 시 기준선이다. 각 통합 이후의 HEAD는 위 커밋과 `git log`로 확인한다.

- Task 4 추가: 역할 화면 `SAFE_STOP`/상태 미확인 상단 문구와 정지 요청 후 CORE readback 안내를 로컬 매트릭스로 확인했다. 역할별 전체 G2/G3와 실제 물리 정지는 계속 HOLD다.

- Task 5 LOCAL: Fleet 기본/전체 목록과 320/390px, 게임 정상/지연, 역할 SAFE_STOP의 변경 후 X: 캡처를 확인하고 표면 카드에 보충했다. Fleet 532 passed/5 skipped, 게임 102 passed, Fleet 브라우저 22 passed, 게임 브라우저 12 passed, 역할 매트릭스 56셀(가로 넘침·pageerror 0). 장치·현장 근거가 없어 D-153의 표면별 전체 G2/G3는 HOLD다.

## 2026-09-27 후속 세션 통합

| 표면 | 결함과 반영 | LOCAL 재검증 | 남은 게이트 |
|---|---|---|---|
| Fleet | 상태 조회 실패 뒤 마지막 로봇 좌표·주행 상태가 현재값처럼 남던 경로를 `0bfc6656`에서 차단했다. 등록 이름은 남기고 카드·지도에서 위치를 숨긴다. | 브라우저 전체 23 passed, 병합 후 상태 상실·복구 1 passed. `X:\DevTemp\fleet_console_gather-lost-after-live.png` 시각 확인. | 실제 Fleet/CORE 단절·복구 및 목표 이동 readback은 DEVICE/FIELD HOLD. |
| 역할 `/setup` | 위치 증거가 최초·지연·끊김·좌표 없음일 때 waypoint 저장을 막고 전송 중 중복 POST를 차단했다(`05266ddc`). 서버 권한·좌표 검사는 유지한다. | 담당 세션 Chromium 4 passed, 최신 main 병합 전 신규 회귀 1 passed. | 실제 pose 신선도·저장 결과 readback은 DEVICE HOLD. |
| 게임 보드 | 지연 증거를 상태 알림에 한 번 전달하고 첫 연결 실패의 허위 '마지막 경기 정보' 문구를 고쳤다(`8a0b6569`, 패치 동등 원본 `2d30e461`). | 브라우저 전체 13 passed, 병합 후 영향 시험 3 passed. `X:\DevTemp\games_board_delayed.png`, `games_board_first_error.png`는 LOCAL 캡처다. | 실제 경기·카메라·물리 정지는 DEVICE/FIELD HOLD. |
| LCD | 잘못된 `hold_s`를 기본 15초로 정규화해 카드 만료 경로를 보호했다(`23bc45e2`). | LCD 호스트 시험 137 passed/4 skipped; 담당 세션 관련 묶음 157 passed. | 실제 LCD 만료·GIF 복귀와 거리·조도 판독은 DEVICE/BENCH HOLD. |

위 통합은 로컬 `main`의 코드·브라우저 근거다. D-153 화면별 G2/G3 전체 GO 또는 장치 수용으로 승격하지 않는다.

## 2026-09-27 남은 LOCAL 항목 처리

- Fleet: 느린 첫 조회의 중복 폴링과 빈 경보/토글 표시, 작은 지도 격자의 과대 주석을 수정했다(`b792a0b5`). 변경 후 27개 상태·뷰포트 캡처와 전체 브라우저 24 passed를 확인했다. Fleet 표면 카드에 D-309 네이티브 확인의 이벤트 증거를 연결했다.
- 역할 `/device`: Host Agent 작업 중 poll로 버튼이 재활성화되는 중복 POST를 수정했다(`29f44596`). 56셀 G2 기록을 현재 코드에 맞췄다.
- 게임: 13셀 현재 캡처와 시간 증거 없는 레거시 응답의 `unavailable` 회귀를 추가했다(`98f1cd6e`).
- LCD: 실제 노드의 카드 축소를 수정하고 콜백→만료→의도 GIF 복귀를 HOST에서 검증했다(`84364cad`).
- 남은 수용: 실제 Fleet/CORE 목표·정지 readback, Pi LCD 거리/각도/조도와 카드 만료, 천장 카메라·양쪽 로봇 정지, 현장 운영자의 G3 판단. 현재 장치 주소·이미지 digest가 확인되지 않아 물리 회차는 실행하지 않았다. D-153 전체 GO는 계속 HOLD다.

## D-309 역할 화면 첫 기동 보완 (LOCAL)

- 인증된 `/setup`·`/device`는 첫 CORE 상태 응답 전 `안전 상태 확인 중`을 공통 셸에 표시한다(`e9051960`). 첫 응답 뒤 SAFE_STOP 또는 상태 확인 불가 규칙으로 전환하며, 미인증 화면에는 상태 정보를 노출하지 않는다.
- 첫 기동 6셀(역할 3종 × 1366×768/390×844)을 전체 화면으로 캡처했다. `X:\DevTemp\rosy-uiux-d306-roles-g2\first-boot-matrix.json`과 PNG는 LOCAL 증거다. 역할 매트릭스 56셀 포함 브라우저 2 passed, 병합 후 첫 기동 단독 1 passed를 확인했다.
- Host Agent 원본 상태값의 생성 시각, 실물 네트워크·릴리스 결과 readback, 네이티브 확인창 이미지 및 G3 사람 평가는 아직 별도 게이트다.

## 2026-09-27 실물 로봇 읽기 전용 확인

- 대상 로봇의 현재 주소를 받아 SSH host key와 전용 operator key로 접속하고 Pi 5, `rosy-pinky-ufcz`, boot ID, 실행 릴리스 `2026.09.26-017`, 소스 `b093fe45` 및 manifest SHA-256을 확인했다. 원시 요약은 `X:\DevTemp\rosy-uiux-d309-device-readback.json`에 보관한다. 주소와 인증 값은 저장소에 기록하지 않는다.
- CORE·IO·부팅 표시 서비스는 active, navigation은 inactive였다. 인증된 CORE `/api/v1/robot/state`는 조회 시점에 `IDLE`, `estop=false`를 반환했다. 이는 명령 실행이나 물리 정지 확인이 아니다.
- 이 릴리스는 현재 `main`보다 270커밋 이전이고 Host Agent unit·socket이 없다. `/api/v1/host/network`와 `/release`는 둘 다 `HOST_AGENT_UNAVAILABLE`을 반환했다. 신규 UI·Host 증거 계약과 LCD 카드 수정은 이 장치에 설치되지 않았으므로 DEVICE 검증으로 승격하지 않는다. Fleet 서버 주소, 새 이미지 digest, 실물 화면·움직임·사람 평가는 계속 HOLD다.

## 2026-09-27 로컬 사이트 Docker 스택

- 사이트 Fleet·Vision·HTTPS proxy는 `deploy/site/compose.yaml`의 Docker Compose 서비스다. 이 PC에서 `a1e4f3bc` 소스를 `rosy-site-{fleet,vision,proxy}:local-uiux`로 빌드하고 별도 `rosy-uiux-local` 프로젝트로 시작했다. Docker 기본 주소 풀이 소진돼 X: 전용 override에 충돌 없는 3개 네트워크 대역을 지정했다. 다른 프로젝트의 네트워크는 건드리지 않았다.
- Fleet·Vision·proxy 모두 healthy, 루프백 `https://localhost:18445/healthz` 200, 인증된 `/api/fleet/session` 200(operator), `/api/fleet/state` 200을 확인했다. 실제 컨테이너의 `/console`을 1280×800으로 캡처해 페이지 오류·가로 넘침 0을 확인했다. 설정, throwaway 인증 값, 자가서명 인증서, PNG는 `X:\DevTemp\rosy-uiux-local-site\`에만 있다.
- 등록 `demo_01`은 의도적으로 연결되지 않는 가상 대상이며 실제 로봇 자격을 사용하지 않았다. 이 PC의 서비스는 루프백에만 노출된다. 사이트의 고정 주소·신뢰 CA·로봇 페어링·천장 카메라·현장 접근성·물리 readback은 미완료다. Docker healthy를 Fleet↔로봇 DEVICE 수용으로 승격하지 않는다.

## D-309 이번 실행의 최종 LOCAL 체크포인트

- Fleet 27장, 게임 13셀, 역할 매트릭스 60셀과 별도 첫 기동 6셀, LCD 노드 회귀와 사이트 Docker 화면을 현재 코드 기준으로 확인했다. 역할 매트릭스에는 Host Agent 증거 6셀이 포함된다. 역할 Host 원본 시각 계약은 `003a7c1f`에서 Host Agent→CORE→화면으로 구현됐고, CORE가 네 상태를 판정한다. 화면은 서버 판정만 표시한다.
- 관련 시험은 담당 회차에서 Host 서버·프로토콜 276 passed/13 skipped, 문서 82 passed, Chromium Host 집중 3 passed 및 역할 60셀 오류·가로 넘침 0이었다. 로컬 사이트 Compose 3서비스는 healthy이며 인증 GET 두 경로와 화면 캡처를 확인했다.
- 다음 DEVICE 게이트는 서명된 새 로봇 이미지의 버전·digest, Host Agent 설치, 실제 네트워크/릴리스 결과 readback, LCD 거리·각도·조도와 카드 만료, Fleet 고정 주소·TLS·페어링, 카메라와 양쪽 로봇 정지다. G3 사람 평가는 그 후 별도 기록한다. 현재 장치 릴리스와 로컬 Docker demo는 이 게이트를 대신하지 않는다.
