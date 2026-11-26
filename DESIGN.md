# Design System: ROSY

> 계약은 ADR과 계약 시험이 소유한다. 이 문서는 설계 요약이며, 충돌 시 ADR·게이트가 우선한다([D-359](docs/adr/D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) §8).
> 정본: [`tokens.css`](shared/web/tokens.css) · [`components.css`](shared/web/components.css) · [`ui.js`](shared/web/ui.js) · [`surfaces.yaml`](shared/web/surfaces.yaml) · 견본 [`styleguide.html`](middleware/robot_ui/robot/styleguide.html).
> 정적 부품 검증: `fleet_components.py --check`(Fleet 9문서, [D-906](docs/adr/D-906-fleet-static-components-layout-roles.md)·[D-909](docs/adr/D-909-fleet-procedure-document-components.md)), `review_shell.py --check`(Learning 12문서, [D-910](docs/adr/D-910-learning-static-shell-components.md)).

## 1. 철학·읽는 순서·말 ([D-280](docs/adr/D-280-calm-intelligence-product-design-philosophy.md) · [D-926](docs/adr/D-926-ui-reading-order-depth-and-wording.md))

**Creative North Star: "차분한 지능에 은은한 따뜻함"** — 무채색 캔버스 위에 뜻이 있을 때만 색을 쓰고, 따뜻함은 ROSY 브랜드 장미색과 짧고 정중한 문장에 둔다. 기준 해상도는 1366×768 · 1920×1080 · 390×844 · 320×568, 본문·레이블 최소 12px(`--text-micro`), 조작 터치 면적 44px 이상이다.

1. **아는 만큼 말한다.** 증거 네 상태(`fresh`/`delayed`/`disconnected`/`unavailable`)를 구분하고 미확인을 정상처럼 그리지 않는다(`unavailable`은 점선 테).
2. **안전과 핵심 상태 우선.** 비상 정지는 모든 폭 첫 화면에 보인다. 주 명령은 초록이 아닌 고대비 중립(`primary`)이며 화면당 하나다.
3. **복잡함 제어·정지 예산.** 막힌 단추는 `reason`을 글로 밝히고(다수면 구획 안내 한 줄), 장식 애니메이션을 두지 않는다([D-220](docs/adr/D-220-stillness-contract-zero-motion-budget.md)).

| 층 | 담는 것 | 표시 규칙 |
|---|---|---|
| 1 안전 | 비상 정지, 지금 막는 위험 | 앱 바 오른쪽 고정 · 위험 띠 맨 위 한 줄 |
| 2 지금 상태 | 이 화면·대상의 현재 | 제목 아래 한 줄 · 정상은 색 없음(`ink`) |
| 3 할 일 | 주 동작 하나와 입력 | `primary` 흰 채움 화면당 1개 · 보조 `quiet` |
| 4 근거 | 이유·출처·시각·신선도 | `--text-micro` 한 줄 · 접힘 또는 탭 |
| 5 진단 | 원시 값·내부 코드·리비전 | 접힌 개발 진단만 · `undefined`/`null` 노출 금지 |

- **깊이와 면**: 0 앱(`ground-deep` 바) → 1 영역(레일) → 2 화면(하위 탐색+`--surface-canvas`) → 3 대상(`--surface-raised`) → 4 확인·진단(대화상자·접힘). 카드 속 카드는 두지 않고, 경로 줄(`--pathbar-height`)이 위치를 알린다.
- **어휘와 부품**: 제목 `--text-title`, 구획 `--text-body`+`--weight-emphasis`, 본문·값 `--text-body`(숫자 `--mono` `tabular-nums`), 레이블·칩만 `--text-label`. 아이콘 단독은 앱 바 도구·알림·계정만 허용하며 본문·레일은 아이콘+이름을 함께 보인다. 파일 입력은 `.file-picker` 또는 `createFilePicker`를 쓴다.

### 업무 메뉴의 깊이

앱 안에서 주 메뉴는 독립적으로 시작하는 업무(1단), 서브메뉴는 그 업무의 화면(2단), 선택한 대상의 상세·편집기는 최대 3단이다. 목적지가 하나면 바로 연다. 기존 이름·주소가 담당 업무를 설명하면 유지한다.

새 업무를 고르는 버튼이나 팝업도 한 단계로 센다. 상태 필터·입력·저장·모바일 메뉴 펼치기는 같은 화면의 조작이다. 4단은 D-926의 확인·진단에 쓴다. 예를 들어 작업 → 새 작업 유형 선택 → 팔레트 적재 편집기는 3단이고, 편집기 안에서 수량을 입력하는 일은 폼 조작이다.

메뉴를 바꿀 때는 데스크톱과 모바일에서 기존 주소와 기본 메뉴로 같은 대상에 도착하는지 확인한다. 돌아오면 필터와 선택을 복원하고 다른 사람이 바꿀 수 있는 상태는 다시 조회한다.

### 조합 어휘
표면마다 다른 이름으로 다시 만들던 묶음을 한 이름으로 부른다. 새 부품이나 화면별 사본을 만들기 전에 이 표를 먼저 본다. 표에 없는 묶음이 두 표면에 필요해지면 구현을 옮긴 뒤 이 표에 한 줄을 더한다. 이름은 `test_content_vocabulary.py`가 지킨다. 화면 머리 두 줄(절차 단계·수치 띠)과 세 칸 틀 줄의 "지금 쓰는 곳"은 HTML 경로이고, 같은 시험이 실제로 그 부품을 쓰는 페이지와 대조한다. 값은 서버 응답만 보이고 노선·띠 모듈은 쓰기 요청을 보내지 않는다([D-978](docs/adr/D-978-screen-heads-show-server-answers-and-one-composition-table.md)).

| 개념 | 정본 이름 | 지금 쓰는 곳 |
| --- | --- | --- |
| 측정 행(이름–값) | `.ui-readout` · `.ui-readback` | 로봇 카드, Fleet 상세, 견본 |
| 작업 목록 행 | `.ui-task-row` · `taskRow()` | 로봇 작업, Fleet 작업 선택 |
| 절차 단계 | `.ui-stage-track` · `.ui-stage` | `applications/fleet/web/installation/install.html` · `applications/fleet/web/cell/cell.html` · `middleware/robot_ui/robot/styleguide.html` · `learning/curation/perception/review_app_web/learning.html` · `learning/curation/perception/review_app_web/index.html` · `learning/curation/perception/review_app_web/pixels.html` · `learning/curation/perception/review_app_web/omx.html` · `learning/curation/perception/review_app_web/vlm.html` |
| 화면 머리 수치 띠 | `.ui-readout[data-form="strip"]` | `applications/fleet/web/work/policy.html` · `applications/fleet/web/cell/cell.html` · `middleware/robot_ui/robot/styleguide.html` · `middleware/robot_ui/robot/panels/host/system.js` |
| 증거 블록 | `<ui-evidence>` · `<ui-empty>` | 로봇 카드, Fleet 큐 |
| 절차 작업 열 | `.ui-sidebar` | 설치·정비, Fleet 작업 선택 |
| 매체 칸 | `.ui-pane[data-pane]` | 로봇 셸, 감지·카메라 |
| 세 칸 틀 | `.ui-stage-grid` | `applications/calibration/web/index.html` · `applications/fleet/web/index.html` · `learning/curation/perception/review_app_web/evaluate.html` · `middleware/robot_ui/robot/styleguide.html` · `shared/web/template.html` |

### 절차 단계 상태 기본값
- `.ui-stage-track`의 단계 상태는 `done` · `now` · `blocked` · `todo` 넷이며, `data-state`가 없으면 `todo`다.

## 2. 색상·토큰 법칙 ([D-624](docs/adr/D-624-ui-role-token-closure.md) · [D-639](docs/adr/D-639-operational-ui-role-token-closure.md))

- 모든 웹 화면은 `/common/tokens.css`만 읽으며 원시 색(hex/rgb/oklch) 직접 선언과 공용 부품(`ui-*`) 덧칠은 정적 게이트가 차단한다([D-82](docs/adr/D-82-oklch.md) · [D-202](docs/adr/D-202-danger-is-a-fill-alarm-text-contrast-contract.md) · [D-214](docs/adr/D-214-text-contrast-floor.md) · [D-976](docs/adr/D-976-palette-from-product-scales-and-dense-tool-targets.md)).
- ROSY 장미(`--brand-rose*`)는 워드마크와 선택된 레일 위치 표식 두 곳만 쓴다([D-277](docs/adr/D-277-rosy-brand-colour-tokens.md)).
- 테마는 어둡게/밝게/시스템(`tokens.css` `[data-theme="light"]`, `theme.js`)을 제공하며 `test_token_parity.py` · `test_palette_gates.py` · `test_control_line_contrast.py`가 대비와 키 일치를 검증한다.

| 역할 | 토큰 | 용도 |
|---|---|---|
| 화면 바탕 / 들어간 면 | `--surface-canvas` / `--surface-recessed` | 기본 캔버스 / 지도·영상 프레임 |
| 보고 / 조작 면 | `--surface-flat` / `--surface-raised` | 읽기 정보 / 조작 패널·카드 |
| 본문 / 보조 / 위험 위 글 | `--text-primary` / `--text-secondary` / `--text-on-danger` | 위계·가독성(`--text-on-danger`는 위험 채움 전용) |
| 경계선 · 조작 경계 | `--border-subtle`/`default`/`strong` · `--control-line` | 구분선 · 3:1 이상 단추·입력 테두리 |
| 상태 색 | `--status-crit` / `--status-warn` / `--nominal*` | 확인된 위험·주의만 채움/글자(미확인은 중립·점선) |
| 정체성 · 선택 · 포커스 | `--series-*`, `--robot-*`, `--selection`, `--focus-ring` | 데이터·선택 표식(`--selection-edge`), 포커스 링 |

## 3. 앱 셸·관제 배치·안전 불변식 ([D-741](docs/adr/D-741-unified-app-shell-seats.md) · [D-658](docs/adr/D-658-fleet-app-bar-design.md) · [D-945](docs/adr/D-945-unified-app-shell-fleet-bar-layout.md))

- **공용 셸 (`app-shell.css`)**: 새 문서는 [`template.html`](shared/web/template.html)에서 시작한다. 문법은 `spatial`(위치 파악)·`exception`(예외 처리)·`focal`(한 대상)·`procedure`(단계 실행, `--sidebar-track`) 넷이며 `test_app_shell_seats.py`가 좌석·한 줄 헤더·`ui-subnav`·`ui-rail`을 고정한다.
- **Fleet 앱 바 & 위계 ([D-629](docs/adr/D-629-live-cockpit-map-dock-panel.md) · [D-540](docs/adr/D-540-fleet-console-structure-v2.md))**: 네 영역(`identity` · `status` · `actions` · `safety`) 한 줄 유지(320px까지 겹침·줄바꿈 없음, D-668 테마 순환 단추). `/console`은 `map-stage`(지도 · 캔버스 · PiP) + 우측 `robot-dock`(44px+ 빠른 선택, 정상은 맨 아이콘) + 좌측 비모달 밀기/모바일 시트 `robot-panel`(상태·3D·카메라·명령·설정·정지 바닥줄)로 구성한다.
- **독립 작업 선택 (`createTaskChooser()`)**: 하위 탐색(`ui-subnav`)에 현재 영역 작업을 올리고 선택 시 해당 패널만 연다([D-439](docs/adr/D-439-navigation-and-layout-principles.md) · [D-461](docs/adr/D-461-task-first-web-navigation.md)).
- **비상 정지와 취소 분리 ([D-421](docs/adr/D-421-fleet-cancel-all-driving-separate-from-latched-estop.md) · [D-1043](docs/adr/D-1043-viewer-may-press-the-fleet-site-estop.md))**: `#estop` · `#shell-estop`은 `ui-button kind="irreversible"` + `[data-always-live]`로 역할·잠금·부하와 무관하게 항상 활성화되며 관찰자도 누를 수 있다. 래치 없는 `#cancel-all` · 카드 `운행 취소` · 큐 `중단`은 `kind="quiet"`다.

## 4. 컴포넌트 경계·동적 값·게이트

- **3계층 모듈 경계**: ① **L1 파일 내부**(`export` 금지 -> `test_shared_dedupe.py` `exports`), ② **L2 앱 공용**(`applications/fleet/web/shared/` — Fleet 도메인 규칙·어댑터·독점 조종실 부품), ③ **L3 플랫폼 공용**(`shared/web/` `/common/*` — 두 표면 이상이 소비하는 토큰·부품·순수 도우미). 소비자가 0인 공개 이름과 미사용 CSS/HTML ID, 복제 본문은 `test_shared_dedupe.py`가 상한 래칫으로 막는다.
- **감독 우회 금지**: 로봇 도크·패널·워크스페이스(`robot-dock.js`, `robot-panel.js`, `roster-workspace.js`)는 `/api/fleet/pipeline/` 승인·게이트 우회 경로를 호출할 수 없으며 `operations/fleet/test/test_grammar_separation.py`가 정적으로 검증한다.
- **CSP 및 동적 스타일 (D1)**: 스크립트의 `el.style` · `style="..."` 속성은 금지(`CONSOLE_CSP style-src 'self'`, `test_no_element_style.py`)다. C5 이행 부채(`diagnostic-core.js`, `diagnostic-map.js`)만 닫힌 목록에 남아 있다.
- **사전 점검**: 웹 UI 변경 후 `python tools/ui_preflight.py` 또는 `rosy-ui` `ui_preflight.py`로 `fleet_components`, 정적 pytest 게이트, Node 단위 시험을 함께 실행한다.
