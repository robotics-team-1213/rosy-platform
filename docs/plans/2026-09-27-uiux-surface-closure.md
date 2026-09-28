# Rosy OS UI/UX 화면별 개선 실행 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** D-306에 따라 모든 사용자 화면의 책임·조작·상태·반응형 증거를 표면별로 닫는다.

**Architecture:** 기존 정적 ES 모듈, `src/hmi/web` 토큰·공용 컴포넌트, 역할별 패널 레지스트리를 유지한다. Fleet·게임·CORE·LCD의 화면별 소유자는 각자의 표현과 상태를 고치고, 공통 부품은 실제로 같은 의미가 두 표면 이상에서 반복될 때만 확장한다. 진단은 D-266 채택 전까지 PARKED다.

**Tech Stack:** FastAPI 자산 경로, vanilla HTML/CSS/ES modules, PIL LCD, pytest, Playwright Chromium.

---

**디자인 읽기:** 산업용 로봇 운용자·설치자·사이트 관제자를 위한 안전 중심 제품 화면이다. Rosy의 차분한 어두운 표면, 의미가 고정된 상태색, 정지 시 무전이 규칙을 유지한다. 설치한 Taste Skill의 `redesign-existing-projects`는 기존 화면을 먼저 진단하고 의미 있는 약점만 고치는 절차에 적용한다. 기본 `design-taste-frontend`는 대시보드·다단계 제품 UI를 대상에서 제외하므로 미적 프리셋, 새 프레임워크, 동작 애니메이션을 이 제품에 적용하지 않는다. 화면별 글자 위계·밀도·포커스·빈/오류 상태 판단은 D-153·D-280·D-292와 대조한다.

## 협업과 증거 규칙

- 기준: `main`의 `ffb8f133`에서 만든 `.worktrees/uiux-surface-closure`와 D-306. 작업 전에 등록 worktree의 변경 파일과 최신 commit을 다시 확인한다. 본 계획의 문서와 Fleet 파일은 이 worktree가 소유한다. CORE 역할 화면, 게임, LCD, 진단은 담당 세션이 확정되기 전까지 파일을 선점하지 않는다.
- 다른 세션에 전달할 항목: D-306, 이 계획, 맡을 정확한 경로, 필요한 G2 셀, 검증 명령, 기준 commit, 현재 수정 파일. Orca CLI가 현재 PowerShell에서 인식되지 않으므로 기존 Orca 세션과의 직접 통신은 **미완료**다. 새 세션이 이 문서를 읽으면 맡은 범위를 기록하고 겹치는 파일을 수정하기 전에 조율한다.
- F:에는 소스/worktree만, 스크래치·캡처·로그는 `X:\DevTemp\`에 둔다. UI 회차 문서에는 캡처 메타데이터와 X: 경로만 적고, 일회성 캡처를 저장소에 복사하지 않는다. 보존형 G2가 불가능하면 D-153 GO를 주장하지 않는다.
- 모든 단계에서 SOURCE/LOCAL, ROS-SIM, ARTIFACT, DEVICE/BENCH, FIELD를 분리한다. 픽스처 캡처가 실제 이동·정지·LCD 판독을 증명하지 않는다.

## Task 1: Fleet 목표 지정의 키보드·확인 경로

**Files:** `src/site/fleet/fleet/server/web/index.html`, `console.js`, 필요 시 `styles.css`; `test/test_fleet_console_browser.py`, `test/test_web_dialog_contract.py`.

1. 브라우저 시험에 로봇 선택 → 지도 포커스 → 방향키로 좌표 이동 → Enter 확인 취소 시 목표 API 0회, 승인 시 대상·좌표 1회, Escape 선택 해제, 포커스·좌표 안내를 추가한다. 현재 코드에서 실패하는지 확인한다.
2. 캔버스의 포커스와 현재 대상·좌표를 읽을 수 있는 안내를 구현한다. 포인터와 키보드는 하나의 좌표 확정 함수로 들어가며 지도 바깥·맵 없음·선택 로봇 없음은 호출 0회다. `window.confirm`은 로봇 ID와 좌표·동작을 평문으로 묻는다.
3. D-218의 고정 확인 인벤토리를 함께 갱신한다. 기존 전체 정지 확인, 권한, idempotency key, 서버 readback 상태는 유지한다.
4. 실행: `$env:ROSY_RUN_BROWSER_TESTS='1'; python -X utf8 -m pytest test/test_fleet_console_browser.py test/test_web_dialog_contract.py -q`. 1920×1080, 390×844, 320×844에서 키보드 포커스·가로 넘침·버튼 접근을 캡처한다. 스크린샷 경로는 `X:\DevTemp\rosy-uiux-d304\`.
5. Fleet 파일과 관련 시험만 별도 커밋한다. 실패하면 이 커밋을 되돌려 기존 목표 클릭 경로로 복귀한다.

## Task 2: 역할별 절차 화면의 작업 순서

**Owner:** CORE 역할 화면 세션. **Files:** `src/hmi/dashboard/panels/setup/*`, `panels/host/*`, `panels/system/*`, `shell/shell.css`, 필요한 표면 시험.

1. `/setup`·`/device`에서 운영자/관리자의 기본·빈·지연·끊김·미지원·권한 거부 상태를 1366×768과 390×844로 기록한다. `docs/validation/uiux-surfaces-2026-09-27/README.md`의 이미 해결된 겹침·가로 넘침 문제는 중복 수정하지 않는다.
2. 각 절차를 현재 상태 → 필요한 조치 → 적용 결과로 재배열하고, 현재 조치와 무관한 상세값은 접을 수 있는 읽기 영역에 둔다. 저장 버튼과 결과는 같은 절차 안에 둔다. API·capability 판정·D-283 고정 3영역은 변경하지 않는다.
3. 역할별 브라우저 시험에 현재 단계 발견 가능성, 오류/거부 다음 행동, 포커스 순서, 저장 readback을 추가한다. 실행: `$env:ROSY_RUN_BROWSER_TESTS='1'; python -X utf8 -m pytest src/hmi/dashboard/test src/runtime/api_web/test/test_d283_console_browser.py -q`.

## Task 3: 게임 보드의 읽을 수 있는 경기 상태

**Owner:** 게임 세션. **Files:** `src/site/games/games/web/index.html`, `board.js`, `styles.css`, `test/test_games_board_browser.py`.

1. 점수·단계·유실·정지 요청과 결과가 시각적으로 서로 다른 상태인지 1280×800에서 확인한다. 의미 있는 상태 변화는 적절한 `role=status`/`aria-live`로 읽히게 하고 반복 폴링마다 같은 문장을 다시 알리지 않는다.
2. `/stop` 실패가 화면에 보이고 다시 시도할 수 있도록 한다. D-218·D-253의 게임 즉시 정지와 Space 단축키, 단일 보드 구조는 유지한다.
3. 경기 호스트 픽스처 브라우저 시험과 `python -X utf8 -m pytest src/site/games/test test/test_rosy_games_surface.py -q`를 실행한다. 실제 게임 진행/물리 정지는 별도 FIELD 증거다.

## Task 4: LCD와 진단의 별도 승격

- **LCD owner:** `src/hmi/face`. 코드 렌더 시험은 `python -X utf8 -m pytest src/hmi/face/test/test_info_screen.py -q`. 320×240 이미지의 코드·경고·긴 문자열·빈 네트워크 상태를 확인하고, 실물 사진에서 거리·각도·조명 판독성을 기록한다. 실물 증거 없이 DEVICE/BENCH GO를 쓰지 않는다.
- **진단 owner:** `src/runtime/sensing`. 먼저 D-266의 sensing 소유 판단, 인라인 스크립트의 D-218 계약 편입, G2 감지·관측·조작 셀을 해결한다. 그 전에는 `dashboard.html`을 대규모 컴포넌트화하거나 운영 화면으로 배포하지 않는다. PARKED를 유지하고 터치 취소·키보드·지도 입력 문제는 해제 작업의 명시적 목록으로 둔다.
- **Gazebo viewer owner:** `src/sim/gz_sim`. `scripts/lane_live_view.html`은 D-257의 1대·ROS 관측 전용 디버그 화면이다. `src/sim/gz_sim/test/test_lane_live_view_v2.py`와 데모에서 카메라·인지·진행·끊김을 확인하되, Fleet 또는 실물 운용 화면으로 간주하지 않는다. `src/hmi/dashboard/styleguide.html`·`src/hmi/web/template.html`은 운영 화면이 아닌 컴포넌트 계약 자료로 유지한다.

## Task 5: 표면별 회차와 통합

1. 각 owner가 G1 명령, G2 선언 셀·누락 셀, G3 D-153 8항을 `docs/validation/uiux-surfaces-<date>/README.md`에 기록한다. 실패나 미촬영은 HOLD로 남긴다.
2. `python -X utf8 -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`, `python tools/harness/rosy_harness.py lint`, `git diff --check`를 실행한다. 필요한 모듈 `progress.md`·`logs.md`를 증거 범위만큼 갱신한 뒤 `python tools/harness/rosy_harness.py generate`를 실행한다.
3. 병합 전 main·각 worktree의 HEAD/변경 경로/겹침을 다시 확인한다. 검증된 단위만 로컬 main에 통합한다. 원격 push, ARM64 이미지, 실제 로봇·현장 수용은 이 계획의 자동 완료 조건이 아니다.

## 완료 기준과 되돌리기

- 각 화면은 자기 질문·주요 조작·빈/오류/권한/증거 상태·키보드/터치·선언 뷰포트의 판정이 있다. 공통 컴포넌트 계약과 화면 소유 경계가 유지된다.
- Task 1~3은 서로 다른 파일 집합과 커밋으로 되돌린다. 공통 토큰을 바꾸면 모든 소비 표면 G1/G2를 다시 실행한다. D-266이 채택되지 않으면 진단은 PARKED로 남는다.

## G2/G3 후속 회차에서 확인한 미완료 작업

이 목록은 `docs/validation/uiux-surfaces-2026-09-27/`의 표면별 카드에서 확인한 차단 조건이다. 아래 항목은 후속 제안이며 현재 GO나 장치 수용 사실이 아니다.

1. **Fleet 증거 계약과 기본 로스터:** 팔로워별 마지막 수신 시각 또는 나이를 Fleet 응답 계약에 추가하고 `delayed`에 경과 시간을 표시한다. 정상 로봇은 기본 예외 목록에서 접고 전체 목록을 키보드로 열 수 있게 하는 흐름을 설계·검증한다. 식별색과 경보색의 적용 범위는 concept 16 §7.3 및 D-280과 대조해 결정한다. 확인창 G2 캡처, 실제 정지·목표 readback은 별도 게이트다.
2. **역할별 절차:** `/setup`과 `/device` 최초 기동, `/device` 지연·끊김·SAFE_STOP, 하위 API별 403/503과 저장 readback을 선언 뷰포트에서 채운다. SAFE_STOP은 해당 역할이 취할 다음 행동과 조작 가능성을 함께 정한다. 네이티브 확인창 이미지는 OS 캡처 수단이 확보되면 추가한다.
3. **게임 호스트:** `overlay_payload()`의 생성/수신 시각 계약을 정해 `delayed`와 마지막 정상 프레임을 구별한다. 공·원정팀 식별색을 D-153의 경보색 법칙에 어떻게 적용할지 문서 결정 후 G3를 재평가한다. `/stop` 접수와 실제 물리 정지를 분리해 장치 회차에서 확인한다.
4. **로봇 얼굴:** 대상 Pi 이미지의 폰트와 320×240 LCD에서 거리·각도·조도 판독, `hold_s` 뒤 의도 GIF 복귀, 네트워크 단절·E-STOP의 실제 입력/표시를 촬영한다. Windows PIL 캡처로 BENCH/DEVICE를 대체하지 않는다.
5. **통합 판정:** 각 표면의 G1 재실행, G2 전체 셀 보존, G3 8항 위반 0을 동일 회차에서 확인한 뒤 D-153 카드만 GO로 바꾼다. sensing 진단은 D-253/D-266 해제 전 PARKED, Gazebo 뷰어는 읽기 전용 SIM 도구로 분리한다. Orca 기존 세션 직접 메시징은 CLI/도구가 확보될 때까지 완료로 기록하지 않는다.

## 2026-09-28 통합 상태 재평가

아래는 이전 G2/G3 미완료 목록을 후속 회차 및 현재 확인 가능한 근거와 대조한 상태다. 과거 회차 기록은 당시 관찰로 보존하며, 현재 실행 순서는 이 표를 따른다. LOCAL 완료는 장치·현장 수용을 뜻하지 않는다.

| 표면 | LOCAL에서 닫힌 범위 | 계속 열려 있는 게이트 | 다음 조치 |
|---|---|---|---|
| Fleet | 지연 나이 표시와 예외 우선 목록은 후속 Fleet 회차에서 구현·검증됐고, G3 현황은 `fleet-g2-matrix.md`에 갱신됐다. | 실제 사이트 Fleet/로봇 연결, 화면 readback, 운영자 G3 평가 | 서버를 Docker로 띄운 통합 환경에서 실제 연결 전 상태·오류·권한별 readback을 재현하고 증거를 남긴다. |
| CORE `/console`, `/setup`, `/device` | 역할 G2의 60셀 재실행은 pageerror/가로 넘침 0, E-stop 가시 60/60, 취소 확인 POST 0으로 기록됐다. 이후 패널별 오류·요청 접수와 readback 분리, 폴링 중 draft/작업 피드백 유지 회귀도 각 후속 기록에서 통과했다. 이전 `confirm_cancel` 실패는 전용 수정 뒤 재실행으로 대체됐다. | 실제 Host Agent·CORE·로봇 readback, 물리 E-stop, 더 넓은 권한/저장 실패 조합, 키보드 전체 흐름 및 설치자·운영자 G3 평가 | 통합 main에서 역할 G2와 패널 브라우저 회귀를 다시 실행한 뒤, 장치가 연결될 때 readback 증거를 별도 수집한다. |
| Games | D-309가 생성 시각/연령 기반 `delayed`, 마지막 수신 데이터 표시, 원정팀 회청색과 공의 주황색 표식 예외를 확정했다. 최신 main 검증에서는 게임 서버·공용 표면 시험 111건, Chromium 15건이 통과했고 13셀을 재촬영했다. 상세는 `games-g2-matrix.md`의 최신 main 항목이다. | 실제 카메라·경기·로봇 반응, 양쪽 로봇의 물리 정지 readback, 사람 G3 및 DEVICE/FIELD | 실물 경기에서 카메라 증거와 정지 결과를 CORE readback과 대조한다. |
| LCD | PIL 렌더 계약과 코드 수준 확인은 가능하다. | 제품 Pi 이미지의 실제 LCD, 거리·각도·조도·표시 유지 시간, E-stop/전원/네트워크 전환 | 장치와 고정된 촬영 조건을 확보한 벤치 검증을 진행한다. |
| 통합 D-153 | 표면별 LOCAL 개선과 테스트는 각 기록에 분리됐다. | 운영자/설치자 사람 평가, 실제 장치·현장, 릴리스·배포 증거 | LOCAL 완료를 GO로 합산하지 말고 G3/DEVICE/FIELD 근거가 모인 뒤 통합 판정한다. |

**진행 우선순위:** (1) 현재 main의 화면 회귀 증거를 계속 최신화, (2) Docker Fleet 통합 서버에서 서비스 간 화면/readback 경로 확인, (3) 장치가 준비되면 CORE·Host Agent·LCD 실물 벤치, (4) 운영자/설치자 G3와 FIELD 수용. 현재 확인된 증거만으로 D-153 또는 DEVICE/FIELD를 GO로 바꾸지 않는다.
