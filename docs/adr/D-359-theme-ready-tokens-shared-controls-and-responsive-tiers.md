## D-359 테마는 팔레트 한 블록만 바꾼다 — 토큰을 팔레트·파생·역할로 나누고, 공용 부품이 표면별 사본을 대체하며, 반응형은 세 단 어휘를 쓴다

**Status:** Accepted (2026-09-30, 웹 표면의 토큰 구조·공용 부품·반응형·계약 시험). D-280 다섯 원칙과 D-82 의미 집합(ground/status/series/brand), D-277 장미색 범위는 바꾸지 않는다. D-345의 "라이트 팔레트를 만들지 않는다"는 이 ADR §3으로 대체한다. 네이티브·LCD 사본은 어두운 팔레트에 고정한다(§3.4). 장치·현장 수용은 포함하지 않는다.

잇는 결정: [D-75](D-75-d-7-react.md) · [D-82](D-82-oklch.md) · [D-277](D-277-rosy-brand-colour-tokens.md) · [D-280](D-280-calm-intelligence-product-design-philosophy.md) · [D-292](D-292-design-tokens-and-component-layout-contract.md) · [D-294](D-294-shared-typography-and-interaction-tokens.md) · [D-329](D-329-surface-registry-and-visual-baseline.md) · [D-345](D-345-design-philosophy-reaches-every-surface.md).

### Context

2026-09-30 전 표면 UI/UX 감사(정적 읽기, 세 갈래: 토큰·테마 / 타이포·부품 / 반응형)의 결과다. 색 원본은 `tokens.css` 하나로 모였고 글꼴 가족·글자 크기·간격·모서리는 깨끗하다. 문제는 **값을 바꿀 때 따라오지 않는 곳**과 **시험이 보지 못하는 사본**이다.

**테마 준비도 — 약 절반.**
- `tokens.css`는 `:root` 한 층이다. 부품은 팔레트 이름을 직접 쓴다(`--paper` 79곳, `--muted` 83곳). `paper`는 밝은 테마에서 뜻이 뒤집히는 이름이다.
- 파생 토큰 약 30개가 어두운 값의 RGB로 굳어 있다: `--line-*`(paper RGB), `--scrim*`·`--panel-fill`(ground RGB), `--status-*-a*`, `--brand-rose-wash`·`--status-crit-ground`(어두운 바탕 위 미리 섞은 값).
- 캔버스: `dashboard/map.js` `readToken`과 Fleet `map-view.js` `hexToRgb`는 `#rrggbb`만 읽고 나머지는 검정이 된다. 둘 다 한 번 읽고 캐시한다. Fleet 지도는 지형에 `--paper`·`--ground-deep`을 써서 테마가 바뀌면 지도가 반전된다.
- `color-scheme: dark`가 네 파일에 흩어져 있다. Fleet `theme-color`는 `#111614`로 `--ground`가 아니다.
- 시험은 `--x: #hex;`를 파일 전체에서 정규식으로 읽는다. 두 번째 테마 블록이 생기면 뒤 값이 이기고 앞 테마는 검사되지 않는다.
- 쓰이지 않는 토큰 11개, 같은 값의 별칭(`--status-crit-2`, `--status-warn-2`, `--status-ok`/`--status-good`)이 있다.

**공용 부품 — 사본이 계약을 비켜 간다.**
- `<ui-field>`는 제품 화면에서 0회 쓰인다. 네이티브 입력 54개가 다섯 방식으로 따로 칠해진다. Fleet 입력·선택은 높이 하한이 없어 약 26–37px이다(D-292 §7의 44px 위반).
- 태그/깃발 사본이 세 이름으로 있다: Fleet `.tag`, dashboard `.status-badge/.machine-tag/.mode-chip`, games `.chips li`.
- 비활성 사유가 없다: 약 86곳 중 4곳만 이유를 준다. `authorization.js`는 운용자가 아니면 모든 조작을 말없이 막는다. `ui.js`에는 사유를 다는 API가 없다.
- teleop이 공용 버튼에 `outline: 2px solid var(--status-warn)`을 덧칠한다 — 포커스처럼 보이고, 임계가 아닌 상태에 status 색을 쓴다.
- `ui-button`에 `:hover`는 두 종류만, `:active`는 없다. Fleet·games에는 전역 `:focus-visible`이 없다.
- 자간 값 9개가 토큰 밖이다. 캔버스 글꼴이 `11px sans-serif` 등 토큰과 12px 바닥을 무시한다. `word-break: keep-all`이 없어 한국어가 음절 사이에서 끊긴다.
- 시험은 `ui-*` 선택자 이름과 토큰과 정확히 같은 값만 본다. 다른 클래스 이름의 사본, 근사 리터럴, `outline` 덧칠, 캔버스 글꼴, 빠진 `min-height`는 모두 통과한다.

**반응형 — 가로는 대체로 안전, 세로가 위험.**
- 중단점이 11개 값에 px·rem이 섞여 있다(30rem, 40/42rem, 62/64rem, 540/720/760/1000/1080px…).
- 실제 결함: Fleet `min-width: 62rem`과 `max-width: 62rem`이 992px에서 겹쳐 암시적 열이 생긴다. Fleet 24rem 블록은 두 열 격자에 `grid-column: 3`을 준다. shell의 `30.01rem`/`63.99rem`은 틈을 남긴다.
- 전화 세로에서 붙박이 상단바가 화면을 먹는다: Fleet 4–5줄(약 200–250px/844px), 로봇 `/console` 3줄(약 150–170px).
- 구 `/dashboard`의 `.console`은 721–1080px 폭에서 `height: calc(100vh - 88px); overflow: hidden`이라 가로 전화·낮은 태블릿에서 잘린다.
- `surface-panels.css`가 공용 `ui-actions`를 뷰포트 질의로 전역 재정의한다(D-292 §4 위반).
- 시험 공백: `/setup`·`/device` 뷰포트 시험 없음, 로봇 표면·games 320px 시험 없음, 상단바 높이 시험 없음.

사용자는 "나중에 테마처럼 색을 바꾸면 이것도 처리되게" 하라고 요구했다. 지금 구조에서는 테마 하나에 약 60개 값을 다시 써야 하고, 캔버스는 검게 칠해지며, 시험은 두 번째 테마를 보지 못한다.

### Decision

**1. 토큰은 세 층이다: 팔레트 → 파생 → 역할.**
1. **팔레트**는 테마마다 바뀌는 유일한 값이다. 목록은 닫혀 있다: `--ground`, `--ground-deep`, `--ground-raise`, `--ground-soft`, `--ground-card`, `--ground-card-2`, `--ink`, `--ink-quiet`, `--ink-on-crit`(위험 채움 위 글자 — 테마와 무관하게 밝다), `--status-crit`, `--status-warn`, `--status-good`, `--series-primary`, `--series-secondary`, `--series-goal`, `--robot-1..3`, `--raster-unknown/free/uncertain/occupied`, `--brand-rose`, `--shadow-base`.
2. **파생**은 팔레트만 참조한다. 알파·선·장막·세척은 `color-mix(in oklab, var(--팔레트) N%, transparent | var(--ground))`로 쓴다(oklch가 아닌 oklab: Chromium은 무채색의 hue를 `none`→0°로 풀어 회색을 붉게 섞는다. 2026-09-30 US-001 실측). 파생 블록에 원시 색(hex/rgb/hsl/oklch 리터럴)이 있으면 시험이 막는다.
3. **역할**(D-292 §1의 컴포넌트 층)은 파생·팔레트를 참조한다: `--surface-*`, `--button-*`, `--field-*`, `--flag-*`, `--focus-ring`, `--gauge-*`, `--nominal*`.
4. **이름 정리.** `--paper` → `--ink`, `--muted` → `--ink-quiet`로 바꾼다(밝은 테마에서 뜻이 뒤집히지 않는 이름). 쓰이지 않는 토큰과 같은 값 별칭(`-2`, `--status-ok`)은 지운다. 이름 변경은 한 커밋 안의 기계적 치환이고, 토큰 사본(`test_token_parity.py` 대상)의 주석 이름도 같이 바꾼다.
5. 표면 CSS·JS는 팔레트 이름 대신 역할·파생을 우선 쓴다. 팔레트 직접 참조는 허용하되 `--brand-*`는 D-277대로 워드마크·현재 위치 표식 선택자에만 쓴다.

**2. 테마는 선택자 한 블록이다.**
1. `:root, [data-theme="dark"]`가 기본 팔레트를, `[data-theme="light"]`가 같은 키 집합을 정의한다. 각 블록이 자기 `color-scheme`을 가진다. 표면 파일의 `color-scheme` 선언은 지운다.
2. 테마 블록은 **값만** 바꾼다. 이름·의미 집합은 그대로다: status는 따뜻한 띠, series는 차가운 띠, 정상은 색이 아니라 ink, 장미색은 이름에만, 주 명령은 테마와 무관하게 **ink 채움**(바탕과 가장 대비가 강한 중립)이다.
3. 새 테마 추가 = 팔레트 블록 하나 + 모든 게이트 통과. 다른 파일을 고치지 않는다. 이것이 이 ADR의 수용 기준이다.
4. **선택 경로.** `web_common/theme.js`(외부 스크립트, CSP 준수, `<head>`에서 동기 로드)가 저장된 선호(`localStorage` `rosy.theme` = `dark|light|system`, 없으면 `dark`)를 읽어 `<html data-theme>`와 `meta[name=theme-color]`(해당 테마 `--ground`)를 첫 그림 전에 정한다. `system`은 `prefers-color-scheme`을 따른다. 바뀌면 `rosy:theme` 이벤트를 낸다. 저장소 접근 실패는 기본값으로 떨어진다.
5. 선택 UI는 역할 표면의 `/device` 설정과 Fleet 설정에 둔다. 기본은 어둡게다(관제실·현장 조명 계약 유지).

**3. 밝은 팔레트를 둔다(D-345 해당 문장 대체).**
1. `light` 팔레트를 OKLCH에서 생성해 `tokens.css`에 추가한다. 두 번째 테마는 구조가 맞는지 증명하는 수용 시험이며, 제품 기본값을 바꾸지 않는다.
2. 모든 팔레트 게이트(D-82·D-202·D-214)는 테마마다 돈다: 글자 대비 ≥ 4.5:1, 위험 채움 위 `--ink-on-crit` 대비, 주의·위험 색약 대비, 장미 대 위험 거리, status 따뜻한 띠·series 차가운 띠, 지형 밝기 단조, 로봇 사다리.
3. 테마를 따르지 않는 표면은 `surfaces.yaml`에 `themes: [dark]`로 적고 `theme.js`가 그 표면에서 `data-theme="dark"`를 고정한다. 대상: games 보드(경기장 녹색이 바탕이다), `lane_live_view`(개발 도구, `contracts: []` 유지), `diagnostic.html`(PARKED).
4. 네이티브(`RosyTheme.kt`)와 LCD(`hmi/face`) 사본은 어두운 팔레트에 고정한다. 사본 형식에 테마 열이 생기기 전까지 `test_token_parity.py`는 dark 블록과 비교한다.

**4. 캔버스는 공용 팔레트 읽기를 쓴다.**
1. `web_common/ui.js`에 `readPalette(names)`를 둔다. 계산된 스타일로 어떤 CSS 색 형식이든 `[r,g,b,a]`로 풀고, `rosy:theme`에서 캐시를 비운다. `map.js` `readToken`/`paletteCache`, Fleet `hexToRgb`/`view.colors`, `camera-capture.js`, games `board.js`는 이것을 쓴다.
2. Fleet 지도 지형은 `--raster-*`를 쓴다.
3. 캔버스 글꼴은 `--body`/`--mono` 가족과 12px 이상이다.

**5. 공용 부품이 표면 사본을 대체한다(D-292 §4 이행).**
1. **필드.** 제품 화면의 텍스트 입력·선택·체크는 공용 필드 스타일(`ui-field` 또는 `components.css`가 소유하는 `input.ui-input`/`select.ui-input` 클래스 — 구현이 둘 중 하나로 정하고 styleguide에 싣는다)을 쓴다. 최소 높이 `--target-secondary`, 공용 모서리·바탕·포커스. dashboard `styles.css`와 Fleet `styles.css`의 입력 사본을 지운다. Fleet의 알약 모양 입력은 공용 모양이 된다.
2. **태그.** Fleet `.tag`와 dashboard `.status-badge/.machine-tag/.mode-chip`는 `<ui-tag>`로 바꾼다. games `.chips`는 경기장 어휘로 두되 토큰 글자 척도를 쓴다.
3. **비활성 사유.** `ui-button`에 `reason` 속성을 둔다. `ui.js`가 보이는 짧은 문구와 `aria-describedby`로 연결한다. `title`만으로는 사유로 치지 않는다(터치에서 보이지 않는다). 권한 잠금은 필요한 역할을 말한다(예: `운용자 권한이 필요합니다`).
4. **상태.** 모든 `ui-button` 종류가 `:hover`·`:active`·`:focus-visible`·비활성 상태를 `components.css`에서 가진다. 전역 `:focus-visible` 기본 규칙은 `components.css`에 있고 모든 표면이 받는다. 눌림 상태는 `aria-pressed`의 공용 표현이며 표면이 `outline`이나 status 색으로 덧칠하지 않는다.
5. **글자.** 자간은 토큰 값 또는 0만 쓴다. 표면 본문은 `word-break: keep-all; overflow-wrap: anywhere`를 공용 기본으로 받는다. 흐림은 `--disabled-opacity` 또는 `--ink-quiet`로 표현하고 임의 불투명도를 쓰지 않는다.

**6. 반응형은 세 단 어휘를 쓴다.**
1. 이름: **compact** `width < 30rem`, **medium** `30rem ≤ width < 64rem`, **wide** `width ≥ 64rem`. 범위 문법(`@media (width < 30rem)`)을 쓰고 `.01` 보정을 없앤다. 값은 rem이다.
2. 표면은 레이아웃을 계속 소유한다(D-292 §4). 세 단 밖의 값이 필요하면 `surfaces.yaml`의 그 표면 `breakpoints`에 값과 이유를 적는다. 시험이 `@media` 값을 이 허용 목록과 대조한다.
3. 공용 부품(`ui-form`, `ui-readout`, `ui-actions`)은 뷰포트가 아니라 자기 칸에 반응한다(`@container`). 표면이 공용 부품을 뷰포트 질의로 재정의하지 않는다.
4. 세로 예산: 390×844와 320×568에서 붙박이 머리(상단바)는 창 높이의 20% 이하다. compact에서는 붙박이를 풀거나 부가 항목(토큰 입력·역할 표시)을 접는다. 비상정지는 compact에서도 첫 화면에 보인다.
5. 고정 높이 프레임은 높이가 충분할 때만 쓴다(`(width >= 64rem) and (height >= 40rem)`), 그 밖은 흐르며 스크롤한다. 높이는 `dvh`를 쓴다.
6. 알려진 결함을 고친다: Fleet 62rem 겹침, Fleet 24rem `grid-column: 3`, shell 틈, 구 `.console` 고정 프레임, `surface-panels.css`의 `ui-actions` 재정의, games `.chips` 320px 넘침.

**7. 계약 시험은 구조를 본다.** 기존 시험을 넓히고 새 시험은 변이 증명(일부러 어겨 적신 확인)으로 믿는다.
1. `tokens.css`를 테마별 집합으로 파싱한다. 모든 테마가 같은 팔레트 키를 정의한다. 팔레트 게이트는 테마마다 돈다. 파생 블록에 원시 색이 없다. 파서는 `color-mix(in oklab, …)`를 풀어 대비를 계산한다.
2. 원시 색 금지 스캔을 모든 웹 표면(하위 폴더·Fleet·games JS 포함, `themes: [dark]` 고정 표면의 등록된 예외 블록 제외)으로 넓힌다. `oklch(`·`color(`도 원시 색으로 본다.
3. 표면의 `theme-color`는 `theme.js`가 정하거나, 정적 값이면 dark `--ground`와 같다.
4. 공용 부품 재정의 검사에 `outline`을 넣고, 이름이 다른 사본(입력·태그)을 구조로 찾는다: 제품 화면의 `input`/`select`는 공용 필드 클래스를 가진다.
5. 입력·선택은 `min-height`가 `--target-secondary` 이상이다(모든 표면).
6. 자간은 토큰 또는 0. 캔버스 `ctx.font`는 토큰 가족·12px 이상.
7. `@media` 값은 세 단 또는 그 표면의 허용 목록이다.
8. 브라우저: 역할 표면(`/console` `/setup` `/device`)과 Fleet·games를 390×844·320×568에서 가로 넘침 없음, 상단바 ≤ 20% 창 높이로 확인한다. 역할 표면·Fleet은 dark·light 두 테마로 캡처한다.

**8. 공유 문서.** 저장소 뿌리에 `DESIGN.md`를 둔다. D-280 성격과 원칙, 세 층 토큰과 테마 추가 절차, 공용 부품 목록과 쓰임, 세 단 반응형, 금지 목록을 한 문서로 요약하고 근거 ADR을 가리킨다. 계약은 ADR과 시험이 소유하고 `DESIGN.md`는 안내다(충돌하면 ADR이 이긴다).

### Alternatives

- **어두운 값만 유지하고 테마는 나중에.** 거부한다. 지금 구조에서 테마 하나는 약 60개 값 수정과 캔버스 수리를 뜻하고, 시험이 두 번째 테마를 보지 못해 조용히 깨진다.
- **팔레트 이름(`--paper`)을 그대로 두고 밝은 테마에서 값만 뒤집는다.** 거부한다. 이름과 값이 반대 뜻이 되어 다음 작업자가 틀린다.
- **토큰을 빌드 단계에서 생성한다(Style Dictionary 등).** 거부한다. D-75 무번들러 규칙을 깨고, `color-mix`로 같은 효과를 브라우저에서 얻는다.
- **`@custom-media`로 중단점 이름을 둔다.** 거부한다. PostCSS가 필요하다. 이름은 문서·시험 허용 목록으로 지킨다.
- **시험만 조이고 기존 사본은 손댈 때 고친다.** 거부한다. 44px 위반과 사유 없는 비활성은 D-292 §7 안전·접근성 계약이라 기다릴 수 없다.
- **games·lane_live_view까지 테마를 따르게 한다.** 거부한다. 경기장과 개발 도구는 바탕이 곧 내용이다. `themes: [dark]`로 명시해 고정한다.

### Consequences

- 새 테마 또는 색 조정은 `tokens.css` 팔레트 블록 하나의 변경이 되고, 게이트가 모든 테마에서 대비·의미를 확인한다.
- 캔버스·지도·`theme-color`가 테마 전환을 따른다.
- 표면별 입력·태그 사본이 사라져 44px·포커스·사유 계약이 한곳에서 지켜진다. Fleet 입력 모양이 바뀐다.
- `paper`/`muted` 이름이 사라지므로 진행 중인 가지(worktree)는 합칠 때 치환이 필요하다.
- 밝은 테마는 존재하지만 기본값이 아니며, 사람 G3 평가와 현장 조명 관측 전에는 운용 권장 테마가 아니다.

### Validation

- `python -m pytest src/hmi/web_common/test -q`와 확장된 계약 시험(§7), dashboard·Fleet·games 브라우저 시험.
- 변이 증명: 파생 블록에 hex 삽입, light 팔레트 키 하나 삭제, Fleet 입력 `min-height` 제거, `@media (max-width: 41rem)` 삽입, 자간 0.1em 삽입이 각각 적신을 낸다.
- Chromium 캡처: 역할 표면·Fleet × {dark, light} × {1366×768 또는 1920×1080, 390×844, 320×568}, games × {1280×800, 390×844, 320×568}.
- 이것은 SOURCE/LOCAL 증거다. 실물 태블릿·관제 모니터·현장 조명, 사람 G3 평가는 별도 회차다.
