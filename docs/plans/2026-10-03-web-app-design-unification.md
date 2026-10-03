# ROSY 웹 앱 공용 디자인과 작업 흐름 개선 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 남은 웹 화면을 실제로 열어 점검하고 공용 디자인·작업 선택·진행/복귀가 분명하도록 화면별 개선, 검증, 커밋과 로컬 main 병합을 완료한다.

**Architecture:** D-359/D-432의 토큰과 공용 컨트롤을 유지하며 D-439의 작업 중심 구성을 적용한다. 웹 공용 라이브러리는 배치·입력 표현만 소유하고 서버 권한과 로봇 명령은 기존 표면/CORE가 소유한다. 같은 세션에서 subagent-driven-development의 구현→요구사항 검토→품질 검토 순서를 적용한다.

**Tech Stack:** Vanilla ES modules, HTML/CSS, FastAPI, pytest, Chromium/Playwright, Fleet 순수 JS의 node:test.

---

## 진행 규칙

- 작업 브랜치: `feat/hmi-task-layout`; worktree: 저장소 `.worktrees/ui-unify`.
- 임시 코드·로그·화면 캡처는 `X:\DevTemp\rosy-ui-unify`에 둔다.
- 실제 변경 전에 현재 route/패널/주 동작과 화면 증거를 확인한다.
- 장치의 양의 주행, 비상 정지 해제, PARKED 기능 활성화는 실행하지 않는다.
- 기능을 임의로 제거하지 않는다. 목적별 선택과 세부 정보 공개 단계로 정리한다.
- 같은 종류의 변경은 한 묶음으로 적용하고 화면 점검은 수정 전/후의 제한된 회차로 한다.
- 독립 작업을 동시에 수정하지 않는다. 요구사항 검토 통과 뒤 품질 검토를 진행한다.
- 각 완료 행에는 원인·수정·검증·커밋을 기록한다. 실패도 재실행과 구별한다.

## 화면 목록과 순서

| 순서 | 화면/구성 | 기준 파일 | 진행 |
|---|---|---|---|
| 1 | 현재 제품 웹 전체 기준선 | `src/hmi/web_common/surfaces.yaml`, `src/hmi/dashboard/panels.yaml` | 초기 기준선/전체 source 목록 확인; 기능별 추가 상태는 해당 작업에서 점검 |
| 2 | 공용 작업 선택·상태·초점 규칙 | `src/hmi/web_common/{task-chooser.js,task-chooser.css}` | 구현·독립 검토 완료 `15e8742b4`; 전체 회귀는 최종 통합에서 확인 |
| 3 | 로그인·역할 진입 | `src/hmi/dashboard/{index.html,surface.html,surface-navigation.js}` | 구현·독립 검토·집중 회귀 완료 `4e8cbe92d`; 전체 회귀는 최종 통합 |
| 4 | 로봇 운용 7패널 | `src/hmi/dashboard/panels/console/`, `shell/` | 카메라·운용 확인 `da3021b64`, 지도·상태 후속 `59b3803fe`, 호환 확인·자격/페이지 소유권 `b1dce38fe` 완료 |
| 5 | 작업 준비 5패널 | `src/hmi/dashboard/panels/setup/`, `shell/` | 교통 정책 `5b590cb37`, 나머지 수정·유지 판정 `59b3803fe` 완료 |
| 6 | 설치·정비 7패널 | `src/hmi/dashboard/panels/{host,system}/`, `shell/` | 목적·결과·미확인 구분 및 개별 유지 판정 `59b3803fe` 완료 |
| 7 | Fleet 관제 | `src/site/fleet/fleet/server/web/{index.html,console.js,styles.css}` | `21f5dd310`·`b42bcb12a`·`5cffc885d` 완료; D-201 높이·compact 실제 DOM/초점/입력 보존·공용 확인과 소유권 검증 |
| 8 | Fleet 기기 등록·카메라 설치 | `src/site/fleet/fleet/server/web/{install.html,install.js,enrollment.js,camera-pairing.js}` | `21f5dd310`·`b42bcb12a` 완료; 세 작업·재검색·보정 프리뷰와 주소 힌트/대화 owner, SPEC/QUALITY 통과 |
| 9 | 게임 보드 | `src/site/games/games/web/{index.html,board.js,styles.css}` | `e3f2bcd06` 완료; 관측 상태와 승인 구별·마커 상세, 독립 SPEC/QUALITY·직접 화면 확인 |
| 10 | 진단·시뮬 도구·작성 틀과 Pilot 웹 실패 화면 | `src/runtime/sensing/web/diagnostic.html`, `src/sim/gz_sim/scripts/lane_live_view.html`, `src/hmi/dashboard/styleguide.html`, `src/hmi/web_common/template.html`, `src/hmi/pilot/` | `e3f2bcd06` 완료; 모바일 배치·실제 공용 선택·미확인 거리·Pilot 재시도, PARKED 유지 |
| 11 | 전체 회귀·최신 main 통합·로컬 병합 | 영향받는 host/browser/node 계약과 quick tier | 진행; 교정 `b42bcb12a`와 공용 확인 `5cffc885d` 완료, 최신 main 기능 보존 통합·예산·최종 quick·로컬 병합 남음 |

### Task 1: 전체 화면 기준선과 구현 우선순위

**Files:**
- Read: 위 화면 목록의 source, `PRODUCT.md`, `DESIGN.md`, 각 모듈 `AGENTS.md`/progress/index.
- Create/Update: `docs/validation/web-app-design-2026-10-03/README.md`.
- Scratch: `X:\DevTemp\rosy-ui-unify\capture_baseline.py`, `baseline/`.

1. registry와 route·패널·확장 도구를 대조하여 누락된 화면을 목록에 추가한다.
2. 기존 브라우저 fixture로 데스크톱/모바일과 권한·빈 상태를 연다. 없는 API를 정상으로 꾸미지 않는다.
3. 직접 캡처를 보고 현재 목적, 반복/분산 UI, 가로 넘침과 작업 도달을 기록한다.
4. 화면별 개선과 그대로 둘 이유를 구체적으로 확정한다.
5. ADR/계획과 기준선 기록을 exact path로 커밋한다.

### Task 2: 공용 작업 선택과 절차 화면 구성

**Files:**
- Create: `src/hmi/web_common/task-chooser.js`, `task-chooser.css`; register in `shared-assets.json` and `CMakeLists.txt`.
- Reuse: `ui.js`, `components.css`, `tokens.css`. `ui.js`는 597/600줄 예산을 유지하고 별도 공용 구성 파일에 작업 선택만 둔다.
- Modify: `src/hmi/dashboard/shell/mount.js`, `shell.css`, 필요 시 `shell.js`.
- Test: `src/hmi/dashboard/test/test_surface_layout_browser.py`, `test_surface_entry_browser.py`, `test_action_groups_browser.py`, 공용 컨트롤 브라우저 시험.

1. 기준선에서 확인된 작업 선택 문제를 재현하는 행동 시험을 추가한다. 선택/키보드/복귀/권한/정지 접근을 검증한다.
2. `ROSY_RUN_BROWSER_TESTS=1 python -m pytest <추가한 시험> -q -p no:cacheprovider`로 수정 전 실패를 확인한다.
3. 공용 규칙을 기존 컨트롤로 구성한다. 같은 작업 화면의 입력 상태를 유지하고, 숨기기/해제 hook을 존중한다.
4. 표면 manifest에서 허용한 패널만 표시한다. URL 입력만으로 권한 없는 패널을 추가하지 않는다.
5. 해당 시험과 `python -m pytest src/hmi/web_common/test/ src/hmi/dashboard/test/ -q -p no:cacheprovider`를 실행한다. 브라우저는 영향받는 시나리오를 opt-in으로 별도 실행한다.
6. 요구사항 검토→품질 검토와 exact path 커밋을 완료한다.

### Task 3: 로봇 진입·운용·작업 준비·설치·정비를 패널별 개선

**Files:** 위 순서 3–6의 실제 패널, `panels/surface-panels.css`, `panels.yaml`(필요 시), dashboard tests.

세부 묶음은 순서대로 진입 → 교통 정책의 재저장/결과/정보 없음 결함 → 카메라 확대와
운용 7패널 → 준비·정비의 목적 구분과 나머지 패널이다.
기본 `/dashboard` 진입에서는 인증과 허용된 역할 목적지만 활성화하고, 명시적으로
선택한 `#compatibility` 경로에서 기존 종합 운용 화면을 유지한다. 인증과 토큰 보관은
기존 client가 계속 소유하며 기본 진입 화면 때문에 영상·상태 socket·운용 polling을
추가로 켜지 않는다. 등록된 자산과 CSP, 기존 호환 기능을 함께 검증한다.

카메라 확대에서는 셸이 소유한 정지와 피드백이 실제 fullscreen 표시 트리 안에서
접근 가능해야 한다. 영상 가장자리를 보존하고, 닫기·실패·unmount 때 셸과 초점이
복구되어야 한다. 녹화 중지는 보조 도구를 접어도 접근 가능하게 유지한다.
준비·정비에서는 위치 적용/맵 만들기, 접속 자격/안전 정책, 네트워크/릴리스/검수처럼
독립 목적을 기존 disclosure/section 어휘로 나누고 입력·결과를 계속 보존한다.
테마 아이콘 trio는 D-405를 유지하면서 시스템 테마 설명과 현재 선택을 정확하게 한다.

명시적 호환 화면의 `app.js`에도 모드·차선·정지 해제·DDS 재부팅·네트워크 변경의 native
확인 7곳이 남아 있다. 이 화면을 선택한 경우에도 같은 정지를 사용할 수 있게 공용 비차단
확인을 적용한다. 기존 화면 구성·기능·API를 유지하고, 확인 뒤 자격·대상·현 상태와 페이지
생존을 재판정한다. 페이지 종료는 확인을 취소하며 같은 요청을 중복하지 않는다.

1. 각 패널의 제목·주 동작·보류 사유·상태·세부 readback·완료 후 위치를 순서대로 점검한다.
2. 실제로 발견한 기능 문제에는 재현 시험을 먼저 둔다. 단순 문구/간격 변경은 구현을 복제하는 시험을 만들지 않는다.
3. 공용 helper와 토큰을 적용하고 독립된 목적에 따라 정보를 묶는다. 운용의 지도·영상·정지는 유지한다.
4. 비지원/권한 제한/오류/재시도와 키보드, 좁은 폭, 낮은 높이를 검증한다.
5. `src/runtime/api_web/test/test_ui_manifest.py`, dashboard host suites와 영향받는 browser 시나리오를 실행한다.
6. 패널별 판정·이유·확인 범위를 기록하고 독립 검토 뒤 커밋한다.

### Task 4: Fleet 관제와 설치 작업 분리·개선

**Files:** 위 순서 7–8, `src/site/fleet/test/web/`, `test/test_fleet_console_browser.py`, 설치 browser 계약.

1. 주의 로봇→대상 선택→현재 상태→개입/완료 흐름, 영상과 지도 읽힘을 확인한다.
2. 등록/보정은 설치 화면의 작업 흐름으로 정리한다. 접속·빈 목록·권한·비지원 안내를 점검한다.
   공용 작업 선택은 읽기·이동이므로 `operatorControls()`의 쓰기 권한 잠금 목록에 넣지 않는다.
   각 작업의 기존 서버 권한, 이름 있는 호출자 조건, 수신 소스·보정 입력 상태는 유지한다.
3. 같은 동작 아이콘/문구와 공용 부품을 적용한다. Fleet는 CORE 자격을 보유하거나 직접 요청하지 않는다.
4. `node --test src/site/fleet/test/web/`와 Fleet palette/disabled/server host suites, 영향 browser 시나리오를 실행한다.
5. 요구사항·품질 검토 후 변경과 증거를 기록하고 커밋한다.

### Task 5: 게임·도구·공용 부품 검토

**Files:** 위 순서 9–10, `test/test_games_board_browser.py`, `src/sim/gz_sim/test/test_lane_live_view_browser.py`, web_common tests.

직접 확인한 변경 대상은 게임의 구현 단계 문구와 마커 보조 정보, styleguide의 모바일
46px 넘침과 실제 공용 작업 선택 예제, template의 좁은 상단 배치다. 게임 마커 상세를
접으면 기존 칩 넘침 시험은 상세를 실제 열고 측정하여 검사 의미를 유지한다.
독립 레인 뷰어는 공용 자산 경로를 추가하지 않는다. 다만 첫 데이터 전의 ‘0개 완료’와
‘0.0 / 0.0 m’는 정보 없음으로 바꾸고, 경로 없음 응답은 이전 거리 표시를 남기지 않게 한다.
실제 측정된 0은 계속 0으로 표시한다. Pilot 웹의 대상 확인 실패에서는 빈 본문 대신 실패·재시도를 표시하고 접속 상단의 모바일 배치를 개선한다. 대상 미확인을 운전 허용으로 바꾸지 않고 기존 native/drive/arm·정지·자격·서비스 워커 계약을 유지한다. PARKED 진단은 활성화하지 않는다. 직접 관측한
모바일 지도 도구의 내부 잘림은 표시 배치만 줄바꿈하여 고친다. 세 영역·지도 계산·IIFE·
POST 처리·포트·런치와 배포 제외 계약은 그대로 유지하고 GET 전용 대역에서 확인한다.

1. 게임 단계·점수·중단·정보 지연과 경기 영상의 정보 순서를 확인한다.
2. 도구는 개발/진단 목적을 명확하게 표시하고 정보 묶음·터치·넘침을 개선한다. PARKED 진단은 활성화하지 않는다.
3. styleguide에 실제 새 공용 구성을 필요할 때 추가한다. 기존 의미 없는 variation은 늘리지 않는다.
4. 관련 host와 browser 시험, dark/light를 따르는 표면의 두 테마를 확인한다.
5. 수정하지 않은 표면도 이유와 검증 범위를 기록하고 독립 검토 뒤 커밋한다.

### Task 6: 최종 검증과 착지

최종 대조에서 Fleet D-201 높이 회귀와 남은 fixture의 소유권·준비 대기 결함이 발견되었다.
이 수정 묶음을 먼저 검증·커밋한다. 별도 후속 묶음으로 실제 연결된 compatibility
`settings.js`의 확인 8곳·`telemetry.js`의 교통 적용과 Fleet `console.js`의 확인 3곳·
`roster.js`의 IR 요청을 공용 확인으로 바꾼다. 기존 app 확인 hook과 factory hook을 재사용하고
서버 권한·대상 신선도·취소·정지 접근·페이지 종료를 검증한다. native 확인의 차단을 실제
재현한 행동 검사부터 시작하며 총 source 예산을 올리지 않는다. 각 묶음의 독립 SPEC→QUALITY와
주 담당자 화면 확인 후 최신 main을 통합한다.

후속 실제 클릭 검사에서는 호환 설정 탭의 정지가 숨겨진 운용 탭에 남는 결함도 재현되었다.
같은 정지 노드를 두 탭 위의 영구 안전 영역으로 옮기고 기존 처리기와 정지 해제 위치를
유지한다. inert 제외뿐 아니라 실제 가시성·클릭과 요청을 확인한다(D-439 §20).

1. 화면 목록의 모든 행에 결과/증거/커밋 또는 유지 이유가 있는지 대조한다.
2. 영향받는 host/browser/node 및 root AGENTS의 quick tier를 완료한다. 첫 실패와 재실행을 구별한다.
3. `python tools/harness/rosy_harness.py generate`와 lint, `git diff --check`를 확인한다.
4. 최신 main을 feature에 통합하고 변화에 맞는 검증을 다시 실행한다.
5. exact path 커밋 후 main에서 `git merge --ff-only feat/hmi-task-layout`를 실행한다. 다른 세션 WIP를 건드리지 않는다.
6. main/브랜치 커밋 일치와 실제 확인 범위를 보고한 뒤 goal을 완료한다. 완료되지 않은 화면이 있으면 goal은 active를 유지한다.
