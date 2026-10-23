---
name: ROSY
description: 로봇·플릿 관제 웹 표면의 시각 체계 — 차분한 지능에 은은한 따뜻함
colors:
  ground: "#101214"
  ground-deep: "#08090b"
  ground-raise: "#191b1d"
  ground-soft: "#1d1f21"
  ground-card: "#2b2d30"
  ground-card-2: "#35383c"
  ink: "#eeeeef"
  ink-quiet: "#9499a0"
  ink-on-crit: "#eeeeef"
  status-crit: "#c40921"
  status-warn: "#feb432"
  status-good: "#12bb81"
  series-primary: "#49affd"
  series-secondary: "#0777bb"
  series-goal: "#12bb81"
  robot-1: "#b6ddfe"
  robot-2: "#24a6fd"
  robot-3: "#0774b6"
  raster-unknown: "#111213"
  raster-free: "#1f2123"
  raster-uncertain: "#45484d"
  raster-occupied: "#d7d7d8"
  brand-rose: "#f697e7"
  shadow-base: "#000000"
typography:
  display:
    fontFamily: "ui-monospace, SF Mono, Cascadia Mono, Consolas, Roboto Mono, DejaVu Sans Mono, Noto Sans Mono, monospace"
    fontSize: "2rem"
    fontWeight: 650
    lineHeight: 1
    fontFeature: "tnum"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI Variable Text, Segoe UI, Roboto, Malgun Gothic, Apple SD Gothic Neo, Noto Sans KR, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.2
  value:
    fontFamily: "ui-monospace, SF Mono, Cascadia Mono, Consolas, Roboto Mono, DejaVu Sans Mono, Noto Sans Mono, monospace"
    fontSize: "1.125rem"
    fontWeight: 650
    lineHeight: 1.1
    fontFeature: "tnum"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI Variable Text, Segoe UI, Roboto, Malgun Gothic, Apple SD Gothic Neo, Noto Sans KR, sans-serif"
    fontSize: "1rem"
    fontWeight: 500
    lineHeight: 1.4
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI Variable Text, Segoe UI, Roboto, Malgun Gothic, Apple SD Gothic Neo, Noto Sans KR, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.12em"
  micro:
    fontFamily: "ui-monospace, SF Mono, Cascadia Mono, Consolas, Roboto Mono, DejaVu Sans Mono, Noto Sans Mono, monospace"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "0.12em"
rounded:
  radius-control: "6px"
  radius-button: "8px"
  radius-panel: "12px"
  radius-flag: "999px"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "12px"
  space-4: "16px"
  space-5: "24px"
  space-6: "32px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ground}"
    typography: "{typography.label}"
    rounded: "{rounded.radius-button}"
    padding: "0 12px"
    height: "48px"
  button-quiet:
    textColor: "{colors.ink-quiet}"
    typography: "{typography.label}"
    rounded: "{rounded.radius-button}"
    padding: "0 12px"
    height: "48px"
  button-irreversible:
    backgroundColor: "{colors.status-crit}"
    textColor: "{colors.ink-on-crit}"
    typography: "{typography.label}"
    rounded: "{rounded.radius-button}"
    padding: "0 12px"
    height: "48px"
  button-segment-pressed:
    backgroundColor: "{colors.ground-card-2}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    height: "48px"
  button-toggle-active:
    backgroundColor: "{colors.series-primary}"
    textColor: "{colors.ground}"
    rounded: "{rounded.radius-button}"
    height: "48px"
  field:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.radius-control}"
    padding: "0 12px"
    height: "48px"
  tag:
    textColor: "{colors.ink-quiet}"
    typography: "{typography.label}"
    rounded: "{rounded.radius-flag}"
    padding: "0 8px"
    height: "32px"
  tag-crit:
    backgroundColor: "{colors.status-crit}"
    textColor: "{colors.ink-on-crit}"
    rounded: "{rounded.radius-flag}"
    height: "32px"
  topbar:
    backgroundColor: "{colors.ground-deep}"
    textColor: "{colors.ink}"
    padding: "0 16px"
    height: "88px"
---

# Design System: ROSY

> 계약은 ADR과 계약 시험이 소유한다. 이 문서는 안내다. 이 문서와 ADR이 다르면 ADR이 이긴다.
> 근거: [D-359](docs/adr/D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) §8.
> 값의 원본은 [`tokens.css`](shared/web/tokens.css), 부품은 [`components.css`](shared/web/components.css)·[`ui.js`](shared/web/ui.js), 표면 목록은 [`surfaces.yaml`](shared/web/surfaces.yaml), 살아 있는 견본은 [`styleguide.html`](middleware/robot_ui/robot/styleguide.html)이다.
> 위 frontmatter의 색은 기본(어둡게) 테마 값이다. 밝게 값은 `tokens.css`의 `[data-theme="light"]` 블록에 있다.

## Overview

**Creative North Star: "차분한 지능에 은은한 따뜻함"** ([D-280](docs/adr/D-280-calm-intelligence-product-design-philosophy.md))

ROSY 화면은 사람이 로봇을 안전하게 감시·개입·설치·점검하게 돕는다. 화면은 조용하다. 바탕과 글자는 거의 무채색이고, 색은 뜻이 있을 때만 나온다. 따뜻함은 ROSY 이름의 장미색과 짧고 배려 있는 문장에만 둔다.

밀도는 관제 화면 수준이다. 노트북 1366×768, 관제 PC 1920×1080, 전화 390×844와 320×568에서 같은 화면이 읽혀야 한다. 장갑·조명·팔 길이 거리를 전제로 글자 바닥은 12px, 누름 면은 44px 이상이다.

D-280 다섯 원칙은 시각에서 이렇게 묶인다.

1. **아는 만큼 말한다.** 알 수 없는 값을 정상처럼 그리지 않는다. 증거 네 상태(`fresh`/`delayed`/`disconnected`/`unavailable`)를 따로 그린다. `unavailable`은 점선 테다.
2. **중요한 것이 먼저 보인다.** 비상 정지는 모든 폭에서 첫 화면에 있다. 모든 버튼은 48px이며 위험 조작은 색상과 보이는 동사로 구분한다.
3. **복잡함을 다룰 수 있게.** 막힌 버튼은 이유를 보이는 글로 말한다(`reason`). 부가 항목은 좁은 창에서 접힌다.
4. **따뜻함은 작은 곳에.** 장미색은 워드마크와 현재 위치 표식에만 쓴다([D-277](docs/adr/D-277-rosy-brand-colour-tokens.md)).
5. **현대성은 정교한 품질로.** 닫힌 척도(글자 6단, 간격 6단, 모서리 4종)만 쓴다. 장식 움직임은 없다([D-220](docs/adr/D-220-stillness-contract-zero-motion-budget.md)).

**Key Characteristics:**
- 무채색 바탕(H 258, C ≤ 0.012) 위 한 가족 글꼴, 숫자만 등폭
- 색은 네 의미 집합(ground·status·series·brand)에서만, 서로 섞지 않는다
- 정상에는 색이 없다 — 정상은 `ink`다
- 주 명령은 초록이 아니라 가장 대비가 큰 중립(ink 채움)이다
- 평평한 면은 보고하고, 솟은 면은 조작한다
- 움직임 없음. 상태 변화는 선과 면으로만 보인다
- 접점마다 같은 화면을 복제하지 않고 같은 성격을 매체에 맞게(D-280): 로봇 얼굴 LCD는 표정으로 조금 더 큰 표현 자유가 있고(D-280 P4·D-385), 비웹 표면은 등록부의 `token_copy` 사본이 이 체계를 따른다(D-345)

## Colors

### 반드시 지키는 색상 법칙 (D-624)

운영 표면의 토큰·규격·역할 폐쇄성은 [D-639](docs/adr/D-639-operational-ui-role-token-closure.md)를 따른다. 색뿐 아니라 글자 계단·조작 크기·내부 여백·포커스도 공용 원본에서 소비하며, 실제 화면이 공용 부품을 덧칠하지 않는다. 캔버스는 숫자 글자 크기 대신 글자 역할을 읽고 native는 같은 원본의 생성 export를 사용한다. 등록된 표면과 하위 자산 전체를 검사하며, 레지스트리 중복 키는 실패다. [전체 실행 계획](docs/plans/2026-10-11-platform-ui-role-tokens.md)의 역할 표와 소비자 시험으로 마감한다.

운용 화면의 배치와 정보 공개는 [D-641](docs/adr/D-641-operator-shell-icons-and-progressive-evidence.md)의 다섯 영역을 따른다. 헤더·전역 탐색·업무·현재 맥락·보조 운영정보의 소유권을 섞지 않는다. 반복 조작은 공용 의미 아이콘과 접근성 설명으로 정리하고, 현재 상태·위험·판단 결과의 필수 문구는 남긴다. 원시 JSON과 내부 코드는 개발 진단을 열었을 때 보여주며 요약·근거·실행 완료를 구분한다. 새 화면은 [확정 와이어프레임](docs/plans/2026-10-11-operator-shell-icons.md)과 실제 아이콘 견본을 기준으로 배치한다.

전역 탐색과 맥락 탭, 접속·알림·새로고침·확대·내보내기는 아이콘 단독을 기본으로 한다. 같은 의미의 글자를 옆에 반복하지 않으며 이름은 접근성 트리와 공용 툴팁으로 제공한다. 알림 숫자와 필수 상태·위험·실행 결과는 숨기지 않는다.

Fleet 앱 바의 오른쪽은 연결·알림·나·정지 순서다. 연결은 `실시간`·`지연`·`연결 끊김` 가운데 하나와 로컬 시각이고 브라우저와 Fleet 사이의 것이다. 알림 단추는 종과 읽지 않은 수다. 계정 단추는 역할 이름을 달고, 그 아래에 계정·화면 표시·토큰 접속이 있다. 개발 연결 표지는 닫힌 계정 단추에서도 보인다. 로봇 연결 수는 앱 바가 아니라 관제 화면의 지도 머리에 있다. 알림 열기·메시지 읽음·개입 해소는 별개다([D-741](docs/adr/D-741-unified-app-shell-seats.md) 3항, D-668의 테마 순환과 인라인 값 표현은 그대로 쓴다).

플랫폼 정체성은 [D-654](docs/adr/D-654-rosy-platform-route-mark.md)의 경로 R 심볼을 사용한다. `shared/web/brand/mark.svg`가 기하의 정본이며 공용 `ui-brand`가 기존 장미색과 글자 토큰으로 표시한다. 제품 이름·역할 아이콘·조작 아이콘의 목적은 서로 구분한다. 상태와 승인 여부를 플랫폼 색이나 심볼로 표현하지 않는다.

색은 값보다 역할을 먼저 정한다. `shared/web/tokens.css`가 원시 색의 유일한 출처이며, 모든 웹 화면은 `/common/tokens.css`를 읽는다. 파일 안에서 **팔레트 → 파생 → 역할 → 컴포넌트** 순서로 나눈다. `token.css` 사본이나 화면별 팔레트를 추가하지 않는다.

| 역할 | 토큰 | 사용 기준 |
|---|---|---|
| 화면 바탕 | `--surface-canvas` | 페이지와 작업 캔버스의 기본 바탕 |
| 들어간 면 | `--surface-recessed` | 영상·지도처럼 내용이 안으로 들어가는 면 |
| 보고 / 조작 면 | `--surface-flat` / `--surface-raised` | 기존 면 위계를 따른다 |
| 본문 / 보조 글 | `--text-primary` / `--text-secondary` | 중요도와 읽는 순서, 상태 의미를 대신하지 않는다 |
| 위험 채움 위 글 | `--text-on-danger` | 위험 색 위에서 읽히는 글; 일반 본문에 쓰지 않는다 |
| 경계선 | `--border-subtle` / `--border-default` / `--border-strong` | 행 구분 / 면 구분 / 강조 경계. 안전 신호를 대신하지 않는다 |
| 조작 경계 | `--control-line` | 단추·입력·펼침 행의 테두리. 잉크 50%이고 두 테마의 다섯 바탕 위에서 3:1 이상이다(D-741 10항, `test_control_line_contrast.py`). 면을 가르는 선에는 쓰지 않는다. 비율은 불투명한 다섯 바탕 위에서 계산한 값이고 화면에서 잰 값이 아니다. 영상 위나 반투명 면 위의 조작, 네이티브 앱의 외곽선은 이 관문 밖이다 |
| 명령 / 입력 / 포커스 | `--button-*` / `--field-*` / `--focus-ring` | 공용 컴포넌트가 소유한다 |
| 위험 / 주의 / 정상 | `--status-crit` / `--status-warn` / `--nominal*` | 확인된 임계만 색으로 강조; 미확인은 정상으로 칠하지 않는다 |
| 데이터 / 지도 / 브랜드 | `--series-*`, `--robot-*`, `--raster-*`, `--brand-rose*` | 데이터 정체성·지형·제품 식별을 상태 색과 섞지 않는다 |

새 화면은 먼저 목적·주 동작·현재 상태·복귀 동작을 정하고, 그 다음 위 역할을 선택한다. 색만으로 상태를 전하지 않고 글자·형태·출처·신선도를 함께 보여 준다. 같은 목적의 조작은 같은 공용 부품을 사용한다. 예외는 `surfaces.yaml`에 사유와 범위를 등록하고 해당 ADR을 연결한다.

변경자는 원시 색 금지, 역할 우선, 테마 키·대비·native parity 시험을 원격으로 실행한다. 새 역할은 ADR·사용처·시험을 같은 커밋에 넣는다. G1 시험 통과와 G2 화면 검증, G3 사용자 작업 검토를 구분해 기록한다. 모든 표면의 G2/G3가 없으면 제품 전체 디자인 완료로 선언하지 않는다.

색은 뜻의 예산이다. 한 화면에서 색이 적을수록 색이 뜻하는 바가 강하다. 의미 집합은 [D-82](docs/adr/D-82-oklch.md)가, 대비 바닥은 [D-202](docs/adr/D-202-danger-is-a-fill-alarm-text-contrast-contract.md)·[D-214](docs/adr/D-214-text-contrast-floor.md)가 정한다. 값은 OKLCH에서 생성했다.

### Primary
- **ROSY 장미(Rosy Rose)** (`brand-rose`): 워드마크와 현재 선택된 역할 메뉴(위치 표식)에만 쓴다 — D-277 원문의 두 자리다. 상태·포커스·데이터 계열·인터랙션에 쓰지 않고, 조작 상태는 `--focus-ring`이다. 옅은 바탕은 파생 `--brand-rose-wash`다.

### Secondary
- **계열 파랑(Series Blue)** (`series-primary`, `series-secondary`): 경로·계열 정체성. 차가운 띠에만 있다. 두 값은 색상이 아니라 밝기로 갈린다. 포커스 링(`--focus-ring`)과 켜진 토글도 이 색이다 — 포커스는 상태가 아니라 상호작용이기 때문이다.
- **목표 초록(Series Goal)** (`series-goal`): 목표 지점 계열. 상태의 "좋음"과 값이 같지만 뜻은 다르다.
- **로봇 사다리** (`robot-1..3`): 한 색상의 밝기 세 단. 식별은 라벨이 나르고 색은 보조다. N>3이면 순환한다.

### Tertiary (status — 임계에만)
- **위험(Critical)** (`status-crit`): 글자가 아니라 **채움**이다. 그 위 글자는 `ink-on-crit`이다.
- **주의(Warning)** (`status-warn`): 글자·테두리. 위험과 지각 밝기가 떨어져 있어 색약 시야에서도 갈린다.
- **좋음(Good)** (`status-good`): 임계 회복을 알릴 때만. 평소 정상 표시에는 쓰지 않는다.

### Neutral
- **바탕 사다리** (`ground-deep` → `ground` → `ground-raise` → `ground-soft` → `ground-card` → `ground-card-2`): `deep`에서 `card-2`로 갈수록 잉크 쪽이다. 상단바는 `ground-deep`, 페이지는 `ground`, 평평한 면은 `ground-soft`, 솟은 면은 `ground-card`, 눌림은 `ground-card-2`다.
- **잉크** (`ink`, `ink-quiet`): 글자. `ink`는 정상 값·주 명령 채움, `ink-quiet`는 라벨·단위·보조.
- **지도 래스터** (`raster-*`): 무채색, 밝기가 미지 → 비어 있음 → 불확실 → 점유 순으로 단조다.
- **그림자 바탕** (`shadow-base`): 음영 `--shade-14/28`의 원천.

### 세 층 토큰

1. **팔레트** — 테마마다 바뀌는 유일한 값. 키 목록은 닫혀 있다(위 frontmatter 24개). 원시 색은 이 블록에만 있다.
2. **파생** — 팔레트만 참조한다. 선(`--line-*`), 장막(`--scrim*`), 세척(`--status-crit-a07` 등)은 `color-mix(in oklab, var(--팔레트) N%, transparent | var(--ground…))`다. 원시 색 리터럴이 있으면 시험이 막는다.
3. **역할** — 부품이 읽는 이름: `--surface-*`, `--button-*`, `--field-*`, `--flag-*`, `--focus-ring`, `--gauge-*`, `--nominal*`. 표면 CSS는 팔레트보다 역할을 먼저 쓴다.

### 테마 추가·변경 절차

- 테마는 `tokens.css`의 `[data-theme="이름"]` 팔레트 블록 **하나**다. 기본(어둡게)은 `:root, [data-theme="dark"]`, 밝게는 `[data-theme="light"]`다.
- 새 블록은 dark와 **같은 키 집합**을 모두 정의하고 자기 `color-scheme`을 가진다. 값만 둔다.
- 선택지는 [`theme.js`](shared/web/theme.js)의 `CHOICES`에 `{ value, label }` **한 줄**을 `system` 앞에 더한다. 이것이 선택지의 단일 출처다(`RosyTheme.choices`): 로봇 `/device` 화면 패널은 여기서 버튼을 그리고, Fleet 헤더의 순환 버튼 하나도 같은 목록을 돈다(D-668, `test_theme_choices.py`).
- 그 밖의 파일은 고치지 않는다. 고쳐야 한다면 어딘가 팔레트 이름을 역할 대신 쓰고 있다는 뜻이다.
- `python -m pytest shared/web/test -q`를 돌린다. 팔레트 게이트(`test_palette_gates.py`)가 테마마다 돈다: 글자 대비 ≥ 4.5:1, 위험 채움 위 `ink-on-crit` 대비, 주의·위험 색약 대비, 장미 대 위험 거리, status 따뜻한 띠·series 차가운 띠, 래스터 단조, 로봇 사다리. 범위 게이트(`test_design_scope_gates.py`, D-398)가 정지(D-220)·장미색 범위(D-277)·역할 우선·`100vh` 금지를 지킨다.
- 바꾸면 안 되는 것: D-82 의미 집합, D-277 장미색 범위, **주 명령 = ink 채움**, **위험 채움 위 글자 = `ink-on-crit`**(테마와 무관하게 밝다).

**The One Block Rule.** 테마 하나는 팔레트 블록 하나다. 표면 파일에 테마 분기가 생기면 구조가 틀린 것이다.

**The Normal Has No Colour Rule.** 계기의 안전 구간에는 아무것도 칠하지 않는다. 정상은 `--nominal`(= ink)이다.

### 테마 선택

- 기본은 어둡게다(관제실·현장 조명 계약). 밝게는 존재하지만 사람 G3·현장 조명 관측 전까지 운용 권장 테마가 아니다.
- [`theme.js`](shared/web/theme.js)를 `<head>`에서 `tokens.css` 바로 뒤에 동기로 싣는다(CSP 준수 외부 스크립트). 첫 그림 전에 `<html data-theme>`과 `meta[name=theme-color]`(해당 테마 `--ground`)를 정한다.
- 선호는 `localStorage` `rosy.theme` = `dark|light|system`. 없거나 읽기 실패면 `dark`. `system`은 `prefers-color-scheme`을 따른다.
- API: `window.RosyTheme.get()`·`set(pref)`·`resolved()`. 바뀌면 `document`에 `rosy:theme` 이벤트(`{theme, preference}`)가 난다.
- 선택 UI는 `data-theme-choice` segment 버튼이다(`RosyTheme.choices` — 지금은 어둡게·밝게·시스템 셋). 로봇 `/device` 화면 설정 패널에 있다. Fleet은 헤더의 순환 버튼 하나(`data-theme-cycle`)가 같은 선택지를 돈다(D-668).
- 고정 표면: `surfaces.yaml`에 `themes: [dark]`인 웹 표면(games 보드, Pilot, `lane_live_view`, `diagnostic.html`)은 `<html data-theme-pin="dark">`이고, 왜 테마를 따르지 않는지 `theme_reason`에 적는다(없으면 레지스트리 시험이 막는다). 네이티브·LCD 사본도 어둡게 고정이다.
- 캔버스는 CSS 변수를 못 읽는다. `window.RosyPalette`(`readColour`·`readPalette`·`cssColor`·`canvasFont`)로 어떤 CSS 색이든 RGBA로 풀고, `rosy:theme`에서 캐시가 비워진다. 다시 그리는 일은 각 캔버스가 한다.

## Typography

**Body Font:** 플랫폼 UI 서체 → 플랫폼 한글 서체(`--body`: Segoe UI Variable Text, Malgun Gothic, Apple SD Gothic Neo, Noto Sans KR …)
**Mono Font:** `--mono`(Cascadia Mono, Consolas, SF Mono …). 웹폰트는 쓰지 않는다([D-75](docs/adr/D-75-d-7-react.md)).

**Character:** 한 가족, 숫자만 따로. 변하는 숫자는 전부 등폭(`tabular-nums`)이라 갱신될 때 자릿수가 흔들리지 않는다.

### Hierarchy
- **Display** (650, 2rem, 1): 점수처럼 일부러 키우는 숫자 하나. 문장에 쓰지 않는다.
- **Title** (700, 1.25rem, 1.2): 화면 하나의 이름, 워드마크.
- **Value** (650, 1.125rem, 1.1, mono): 계기 값.
- **Body** (500, 1rem, 1.4): 읽는 글. 긴 안내는 `--leading-copy` 1.5.
- **Label** (600, 0.875rem, 자간 0.12em — 한글은 0, 대문자): 이름·짧은 라벨.
- **Micro** (500, 0.75rem): 단위·각주·비활성 사유. **12px가 바닥이다.**

굵기는 `--weight-regular/medium/label/emphasis/strong`(400/500/600/650/700), 행간은 `--leading-flat … --leading-copy`(1–1.5), 자간은 `--track-label`(0.12em)·`--track-wide`(0.04em)·`--track-state`(0.06em) 또는 0만 쓴다([D-294](docs/adr/D-294-shared-typography-and-interaction-tokens.md)).

**The Latin Tracking Rule.** 자간 토큰은 라틴 대문자 라벨용이다. 자기 글자에 한글이 있는 요소(섞인 글 포함)는 자간 0이다: `ui.js`가 그런 요소에 `data-hangul`을 달고(글자가 바뀌면 따라간다) `components.css`가 그 요소의 `--track-*`를 0으로, `--mono`를 `--body`로 둔다(등폭 글꼴에는 한글이 없어 대체 글꼴로 그려지고 넓은 등폭 띄어쓰기만 남는다). 모든 페이지가 `lang="ko"`라 `:lang()`으로는 가를 수 없고, 한 요소 안에서 글자별 자간은 CSS로 줄 수 없어 섞인 글은 한글 쪽을 따른다.

**The Six Steps Rule.** 글자 크기는 여섯 단계로 닫혀 있다. 캔버스 글꼴도 `RosyPalette.canvasFont`로 토큰 가족·12px 이상이다.

**The Whole Word Rule.** 모든 표면 본문은 `word-break: keep-all; overflow-wrap: break-word`다. 한국어는 어절에서 끊고, 칸을 넘치는 긴 기계 값만 접는다. `anywhere`는 짧은 라벨을 음절 사이에서 꺾으므로 기본으로 쓰지 않는다.

## Layout

### 목적이 공간보다 먼저

화면의 크기와 연결은 [D-543](docs/adr/D-543-task-purpose-navigation-and-layout-review.md)의 작업 카드로 설명한다. 사용자가 누구인지, 첫눈에 답할 질문, 다음 안전한 행동, 완료 근거와 복귀 경로를 정한 뒤 지도·영상·목록의 면적을 배분한다. 전역 탭은 위치를 알려 주고, 맥락 링크는 작업 인계를 알려 준다. Fleet 네 문서의 같은 탭 줄(D-501)은 유지하되, 관제와 Cell 사이에서는 실제 인계의 목적과 결과를 화면에서 설명해야 한다. `설정`도 접속·역할·화면 표시·장치 설정의 소유와 효과를 구분해 평가한다. [작업별 평가표와 반복 절차](docs/plans/2026-10-09-uiux-purpose-and-layout-pipeline.md)가 첫 적용 기준이다.

- **간격 척도**: 4의 배수 여섯 단계 `--space-1..6`(4/8/12/16/24/32px). 임의 값을 쓰지 않는다.
- **역할 간격**: 부품은 척도 대신 역할 이름을 읽는다 — `--inset-button`, `--inset-field`, `--inset-tag`, `--gap-actions`, `--gap-form`, `--gap-readout`, `--gap-topbar` 등([D-292](docs/adr/D-292-design-tokens-and-component-layout-contract.md)).
- **세 단**: **compact** `width < 30rem`, **medium** `30rem ≤ width < 64rem`, **wide** `width ≥ 64rem`. 범위 문법(`@media (width < 30rem)`)을 쓰고 `.01` 보정을 쓰지 않는다. 값은 rem이다.
- **허용 목록**: 세 단 밖의 값은 `surfaces.yaml`의 그 표면 `breakpoints`에 값과 이유를 적는다. 예: Fleet `48rem` — 머리의 네 영역을 첫 줄·둘째 줄로 나누는 폭(D-658). `test_responsive_tiers.py`가 대조한다.
- **칸 질의**: 공용 부품(`ui-form`, `ui-readout`, `ui-actions`)은 뷰포트가 아니라 자기 칸에 반응한다 — `@container (width < 22rem)`에서 한 열로 접힌다. 칸(`container-type: inline-size`)은 표면이 정한다. 22rem은 `surfaces.yaml` `container_breakpoints`에 있다. 표면이 공용 부품을 뷰포트 질의로 재정의하지 않는다.
- **표면이 배치를 소유한다.** 공용 부품은 얼굴만 준다. 어디 놓을지는 표면 시트가 정한다.
- **동등한 창은 같은 폭**: 같은 행의 운용 영역과 나란한 지도·카메라 창은 같은 너비를 쓴다. 좁은 화면에서는 한 열로 쌓아 각 창이 가용 너비를 채운다. 탐색 사이드바처럼 역할이 다른 칸은 콘텐츠에 필요한 폭을 쓴다. Fleet `/console`의 현장 지도와 오른쪽 개입 열은 동등한 창이 아니며, [D-629](docs/adr/D-629-control-sizing-and-console-hierarchy.md)에 따라 넓은 화면에서 2:1로 배치한다.

**The Header Budget Rule.** 390×844와 320×568에서 붙박이 상단바는 창 높이의 20% 이하다. 좁은 창에서는 두 줄로 모으거나 부가 항목(토큰 입력·역할)을 접는다. 테마는 접지 않는다 — Fleet 헤더의 버튼 하나(D-668)이거나 로봇 대시보드의 시스템 화면 설정에 있다.

**The E-stop First Rule.** 비상 정지는 compact를 포함한 모든 폭에서 첫 화면에 보인다. 상단바 격자에서 늘 오른쪽 위에 있고, 머리가 두 줄인 표면에서는 두 줄을 차지한다.

**The Tall Enough Rule.** 고정 높이 프레임은 `(width >= 64rem) and (height >= 40rem)`에서만 쓴다. 그 밖은 흐르며 스크롤한다. 높이는 `vh`가 아니라 `dvh`다. 열 수는 폭만 따른다: 낮은 wide 창(1366×600)은 프레임만 풀고 열을 지킨다 — 프레임 규칙과 열 규칙을 한 미디어 조건에 묶지 않는다.

### 앱 셸의 자리 (D-741)

D-741(Accepted)이 정한, 모든 웹 표면이 같이 쓸 자리다. Rosy Fleet 콘솔이 탐색 레일(다섯 영역)과 하위 탐색을, Rosy Robot의 `/console`·`/setup`·`/device`가 탐색 레일(화면 전환)과 하위 탐색(작업 목록) 자리를, 학습 검수의 네 화면이 탐색 레일과 경로 줄을 쓴다. 치수는 `tokens.css`의 자리 토큰이고 배치는 [`app-shell.css`](shared/web/app-shell.css)가 갖는다. 표면 시트는 자리 안의 내용만 배치한다.

| 자리 | 토큰 | 담는 것 |
|---|---|---|
| 탐색 레일 | `--rail-track` 72px | 그 앱의 영역. 아이콘 아래에 이름 |
| 하위 탐색 | `--subnav-track` 232px | 영역 안의 화면이나 작업. 없으면 `data-seats="rail"` |
| 경로 줄 | `--pathbar-height` 56px | `영역 / 화면`과 만들기 단추 |
| 본문 | 남는 폭 | 지도, 영상, 목록, 미리보기, 폼 |
| 오른쪽 칸 | `--context-track` 360px | 위는 지금 상태, 아래는 입력·조작·근거 |

셸 폭 64rem 아래에서 레일과 하위 탐색이 가로 한 줄이 되고, 본문 폭 48rem 아래에서 지금 상태, 본문, 나머지 순서로 쌓인다. 둘 다 칸 질의다.

본문 격자의 배치는 `data-layout`으로 고른다. 배치마다 둘 수 있는 칸이 정해져 있고, 그 밖의 칸을 넣으면 격자가 깨진다.

| `data-layout` | 둘 수 있는 `data-pane` | 쓰는 곳 |
|---|---|---|
| 없음 | `stage`, `now`, `more` | 목록·미리보기와 오른쪽 칸 |
| `watch` | `stage`, `now`, `more` | 지도와 오른쪽 칸이 2:1 (D-629) |
| `solo` | `stage` | 폼과 결과만 |
| `sense` | `sense`, `stage`, `cam`, `now` | 한 로봇의 감지·관측·조작. 본문 폭 64rem 아래에서 두 칸이 된다 |

`data-order="stage-first"`는 좁은 폭에서 본문을 지금 상태보다 먼저 둔다. `data-seats="rail"`은 하위 탐색이 없는 화면, `data-seats="none"`은 레일도 없는 화면이다. `ui-shell`이 칸이 되므로 앱 바와 레일 안의 공용 부품(`ui-actions`, `.ui-form`)은 셸 폭에 답한다.

## Elevation & Depth

그림자로 깊이를 만들지 않는다. 깊이는 **면의 높낮이(바탕 사다리)**다. concept 16 Law 2: 보고하는 것은 평평하고, 세상을 바꾸는 것은 솟아 있다.

- **평평한 면** (`--surface-flat` = `ground-soft`): 읽기 전용 값, 격자 칸, 보고.
- **솟은 면** (`--surface-raised` = `ground-card`): 조작을 품은 면.
- **선** (`--surface-line` = ink 14%, `--surface-sheen` = ink 6%): 면 경계.
- **장막** (`--scrim`, `--scrim-raise`, `--scrim-top`, `--scrim-solid`, `--panel-fill`): 지도·영상 위에 얹는 글자의 바탕. 바탕 색의 알파다.
- **음영** (`--shade-14`, `--shade-28`): `shadow-base`의 알파. 떠 있는 대화상자에만 쓴다.

**The Stillness Rule.** 장식 움직임은 없다([D-220](docs/adr/D-220-stillness-contract-zero-motion-budget.md)). hover·active·눌림은 선과 면만 바꾼다. 전환 애니메이션을 더하지 않는다.

## Shapes

모서리는 네 종류다.

- **조작 모서리** (`--radius-control` 6px): 필드, 칩, `unavailable` 증거 테.
- **버튼 모서리** (`--radius-button` 8px): 모든 `ui-button`, skip link.
- **패널 모서리** (`--radius-panel` 12px): 패널.
- **깃발 모서리** (`--radius-flag` 999px): `ui-tag`, 점 표지.

비상 정지를 포함한 모든 조작의 크기를 통일한다([D-629](docs/adr/D-629-control-sizing-and-console-hierarchy.md)).

- `--target-secondary` 48px: 일반 버튼·필드·체크 라벨의 최소 높이.
- `--target-primary` 48px: 주 명령.
- `--target-irreversible` 48px: 비상 정지·되돌릴 수 없는 조작.

**공통 조작 법칙.** 비상 정지를 포함한 모든 버튼은 종류에 관계없이 48px·라벨 글자·좌우 여백을 공유한다. 폭은 라벨 길이로 정하고 아이콘 전용은 같은 누름 면의 정사각형이다. 크기는 최소값이므로 긴 문구·비활성 사유는 늘어날 수 있다. 버튼의 의미는 채움과 상태, 아이콘과 보이는 동사로 구분한다. 위험 조작의 크기 예외나 화면별 작은 버튼을 만들지 않는다.

### 관제의 정보 위계와 배치 이유

알림은 공통 머리의 조회 버튼에서 오른쪽 알림 창으로 들어간다. 현재 개입 요약과 최근 관제 메시지는 이 창구에 모으고, 상세 사건 증거는 `기록·근거`에 둔다. 읽음은 브라우저의 미확인 표시만 바꾸며 개입 해소·승인·정지 해제를 뜻하지 않는다. 반복 폴링은 새 알림이 아니다. 현재 개입과 비상 정지는 알림 창 밖에 유지한다([D-632](docs/adr/D-632-fleet-notification-inbox.md)).

| 영역 | 순서·강조 | 사용자에게 필요한 이유 |
|---|---|---|
| 비상 정지 | 머리에 고정, 위험 채움·48px·보이는 동사 | 어느 작업 중에도 즉시 정지할 수 있어야 한다. |
| 현재 개입 | 대응 레일 첫 항목, 실제 위험에만 상태색 | 지금 해결할 문제와 가능한 답을 먼저 찾는다. |
| 현장 지도 | 넓은 화면 왼쪽 2/3, 탭 전환과 무관하게 고정 | 로봇·경로·관측의 공간 관계를 계속 확인한다. |
| 등록 로봇 | 현재 개입 다음 | 개별 연결·상태·명령 대상을 찾는다. |
| 카메라·운영 도구 | 로봇 상태 다음 | 관측을 확인하거나 작업을 바꿀 때 펼친다. |
| 기록·근거 탭 | 오른쪽의 보조 탭, 기록은 중립 구분선 | 현재 경보와 과거 증거를 구분한다. 시작 시각은 제목과 분리한다. |

오른쪽 1/3의 현재 개입 큐는 탭 밖에서 항상 보인다. 그 아래 기본 `로봇 상태`, `기록·근거`, `운영 도구` 탭을 두어 확인·검토·설정 목적을 구분한다. 기록의 출처별 증거·검토 저장·내보내기를 없애지 않는다. 탭을 바꾸어도 지도의 크기와 표시가 유지되며, 넓은 화면의 지도/대응 레일과 좁은 화면의 단일 열은 같은 읽기 순서로 DOM과 시각 순서가 일치한다. 새 UI 배치에는 현재 작업, 다음 행동, 보조 증거의 구분과 그 이유를 먼저 기록한다.

## 표면 문법

모든 웹 표면은 `ui-shell`의 `grammar` 네 가지 중 하나로 시작한다(D-292 §5, [`template.html`](shared/web/template.html)). 문법은 화면의 읽는 순서와 첫 화면이 무엇인지를 정한다.

- **spatial** — 로봇 콘솔. 감각→관찰→조작 세 지역(`robot`, 견본 `web-common`)
- **exception** — 사이트 관제. 예외가 먼저, 지도·대형은 뒤(`console`)
- **focal** — 경기 보드·조종. 하나의 초점(공, 주행 무대)이 화면을 지배(`game-board`, `pilot`)
- **procedure** — 점검·진단. 단계가 순서대로(`control-diagnostic`)

등록부(`surfaces.yaml`)의 `grammar` 칸이 [`ui.js`](shared/web/ui.js)의 `GRAMMARS`와 같은지 계약 시험이 대조한다. 웹이 아닌 다섯째 문법 **intent**(로봇 얼굴, concept 16 §7.4)은 LCD 표면이 소유한다.

## Components

공용 구현은 [`shared/web/ui.js`](shared/web/ui.js)·[`components.css`](shared/web/components.css), 실행 가능한 견본은 로봇 `/styleguide`의 [`스타일 갤러리`](middleware/robot_ui/robot/styleguide.html)다. 새 컴포넌트 모음이나 화면별 버튼·입력 사본을 만들지 않는다. 갤러리에서 색상 역할, 다섯 버튼 종류, 입력, 상태, 증거, 읽기·되읽기, 작업 행·작업 선택을 함께 비교한다. 부품 변경은 사용 화면·갤러리·접근성/반응형 시험을 같은 변경에서 맞춘다.

모든 부품은 [`components.css`](shared/web/components.css)가 그리고 [`ui.js`](shared/web/ui.js)가 정의한다. 그림자 DOM을 쓰지 않는다. 견본은 [`styleguide.html`](middleware/robot_ui/robot/styleguide.html)이다.

### 독립 작업의 선택 — `createTaskChooser()`

[D-439](docs/adr/D-439-task-oriented-web-app-design.md): 서로 독립된 작업은 모두 펼치기보다
작업 이름을 먼저 선택하고 현재 작업 하나에 집중한다. 제목 → 현재 근거 → 입력과 주 행동
→ 결과/오류 → 다음 행동·복귀의 순서로 읽힌다. 지도·영상·정지를 함께 봐야 하는 운용 화면은
기존 공간 문법을 유지한다.

[`task-chooser.js`](shared/web/task-chooser.js)와
[`task-chooser.css`](shared/web/task-chooser.css)는 기존 segment/field/status를 조합한다.
큰 창은 세로 작업 목록, 64rem 미만은 네이티브 선택이다. 현재 작업과 선택은 중립 표현을 쓰며
현재 역할의 장미색 위치 표식(D-277)과 구별한다. 새 팔레트나 간격 척도를 추가하지 않는다.
모든 허용 작업은 mounted 상태로 입력·결과를 유지한다. 표면이 manifest, 권한, 요청과
`beforeHide`/polling을 소유하고 공용 선택기는 표현·초점·전환 잠금만 소유한다. 전환·종료
거절이나 시간 초과 뒤에는 현재 작업을 유지한다. 정지는 작업 선택 영역 밖에서 계속 접근한다.

### 버튼 — `<ui-button kind="…">`
- **종류**: `primary`(ink 채움, 48px), `quiet`(테두리만, 조용한 글자), `irreversible`(위험 채움 + `ink-on-crit`, 48px), `segment`(여러 중 하나), `toggle`(켜지면 계열 파랑 채움). `kind`가 없으면 계약 표지(`data-kind-missing`, 위험색 윤곽)가 그려진다.
- **상태**: `:hover`·`:active`·`:focus-visible`·비활성이 모두 `components.css`에 있다. 눌림은 `aria-pressed="true"`(또는 `aria-selected`, `.active`)의 공용 표현이다. 채움 종류는 누르는 동안 바탕색 안쪽 테를 얻는다.
- **비활성 사유**: `reason="운용자 권한이 필요합니다"`처럼 속성을 단다. `ui.js`가 버튼 안 `<small data-reason>`으로 그리고 `aria-describedby`로 잇는다. 사유가 있는 비활성은 흐리지 않고 점선 테와 조용한 글자로 말한다. `title`만으로는 사유가 아니다(터치에서 보이지 않는다).
- **목록 행 예외** ([D-371](docs/adr/D-371-list-row-irreversible-actions-confirm-before-danger-fill.md)): 같은 종류 항목이 반복되는 목록·표의 행(`li`·`tr`·`[role=row]`)에서 되돌릴 수 없는 조작은 `irreversible`이 아니라 `quiet` `삭제…`다(말줄임표 = 다음 단계가 있다). 누르면 `ui.js`의 `confirmIrreversible({message, action, opener})`가 확인 대화상자(아래)를 연다: 대상을 따옴표로 이름 부르며 묻고(`"operator-tablet" 토큰을 삭제할까요?`), `취소`는 `quiet`, 실행 버튼 하나(`토큰 삭제`)만 `irreversible`이다. Esc·취소는 요청 없이 닫히고 포커스는 행 버튼으로 돌아간다. 첫 화면의 위험 채움은 비상 정지 외에 하나를 넘지 않는다. 비상 정지와 단일 대상 명령은 그대로 위험 채움이다. `test_list_row_irreversible.py`·`test_list_row_confirm_browser.py`가 지킨다.

### 확인 대화상자 — `confirmIrreversible()` · `<dialog class="ui-confirm">`
- 대상 문장 하나, `취소`(`quiet`)와 실행 버튼 하나(`irreversible`). **비모달**(`dialog.show()`)로 열고 모달은 흉내 낸다: 대화상자와 `[data-always-live]` 밖은 `inert`, 뒤에는 `--scrim` 막이 깔린다. 정지 컨트롤 자리만 막에 구멍이 나서 **비상 정지는 대화상자 위에서도 보이고 눌린다**(`showModal()`은 문서 전체를 inert로 만들어 비상 정지까지 막았다 — 2026-09-30 US-010 측정, [D-371](docs/adr/D-371-list-row-irreversible-actions-confirm-before-danger-fill.md)).
- Esc·취소는 요청 없이 닫고 포커스를 행 버튼으로 돌린다. Tab은 취소 → 실행 → 보이는 정지 컨트롤을 돈다(정지 단축키는 없고, 새로 만들지 않는다). 정지를 누르면 정지가 실행되고 대화상자는 취소로 닫힌다.
- 정지 컨트롤을 가진 모든 ui.js 페이지는 그 버튼에 `data-always-live`를 단다(`test_stop_always_live.py`). 보기: `styleguide.html`의 `확인 대화상자` 칸.

### 필드 — `class="ui-field"`
- 네이티브 `input`/`select`/`textarea`에 `class="ui-field"`를 단다(폼 제출·`<label>` 연결·기존 핸들러 유지). 48px, `--radius-control`, `--field-bg`, `--field-line`, 등폭 숫자.
- `readonly`는 점선 테·조용한 글자, `:user-invalid`·`aria-invalid="true"`는 `--field-invalid` 테, 비활성은 `--disabled-opacity`.
- 체크·라디오는 필드 상자를 따로 그리지 않는다. 감싸는 `<label class="ui-check">`가 48px 누름 면이다. 체크 상자는 토큰으로 그린다(`appearance: none`): 테 `--ink-quiet`, 켜짐 `--focus-ring`, 비활성은 흐리지 않고 `--ink-quiet` **점선** 테 — 네이티브 비활성 체크는 accent를 버리고 1.2–1.8:1 회색이 되고, 실선이면 꺼진 빈 상자가 켜진 빈 상자와 같아 보인다. 테와 체크는 두 테마에서 3:1 이상이다.
- `<ui-field>` 감싸개는 견본·스캐폴드 전용이다. 같은 얼굴을 내지만 제품 화면은 클래스 방식을 쓰고, `test_content_vocabulary.py`가 등록 표면에서 `<ui-field>` 엘리먼트 사용을 막는다.

### 태그 — `<ui-tag status="…">`
- 깃발 모양, mono 라벨, `--track-state`. 상태 어휘: `neutral`(조용한 글자) · `active`(정상 진행 — ink 테, 색 아님) · `warn`(주의 글자·테) · `crit`(위험 채움 + `ink-on-crit`).

### 상태 글 — `<ui-status state="…">`
- 화면 알림 한 줄. `warning`/`error`/`unavailable`/`forbidden`은 주의색 글자. `state`가 없으면 계약 표지가 그려진다.

### 오버레이 칩 — `<ui-chip>` (폐기 예정)
- 지도·영상 위에 얹는 한 줄. 장막 바탕 + 표면선 테두리. 지도 조작은 무대의 높이를 훔치지 않는다.
- 남은 소비자는 스타일 갤러리 하나다. 새 화면은 쓰지 않는다. 지도·영상 위 한 줄이 필요하면 `.ui-pane` 안의 `ui-tag`·`ui-status`로 조합한다.

### 분류 머리 — `<ui-triage status="…">`
- 한 줄 머리. 색을 가진 것은 언제나 하나이고 맥락은 색 없이 따라간다. Fleet 예외 큐(주의·최우선)가 대표 소비자다.

### 증거 · 빈 상태 — `<ui-evidence state="…">` · `<ui-empty>`
- 증거 네 상태의 한국어와 나이는 공용 표(`core_ui_logic.js`)가 단일 출처다(운용자 말 참조). 빈 목록·읽기 실패는 목록 밖 한 줄 `ui-empty`다(목록은 숨긴다).

### 단계 스트립 — `<ol class="ui-stage-track">` · `.ui-stage`
- 절차(`procedure` 문법)가 몇 번째 단계인지 한 줄로 말한다. JS가 없다: `<ol class="ui-stage-track">` 안에 `<li class="ui-stage" data-state="done|now|blocked|todo">순번이 붙은 라벨</li>`을 두고, 지금 단계에 `aria-current="step"`을 단다.
- 표식은 `--size-stage-mark` 원이고 순번은 `--mono`다. 긴 절차는 줄바꿈해 흐르며 한 단계의 라벨만 `overflow-wrap: anywhere`로 접힌다.
- 상태는 `ui-tag`와 같은 어휘다. `done`은 지난 단계(조용한 글자, `--surface-raised` 채움 — 빈 테인 `todo`와 라이트에서도 구분된다), `now`는 지금(가장 밝은 중립 글자와 그 잉크로 채운 표식 — 정상은 색이 아니다, D-82), `blocked`는 주의 글자·테(`--status-warn`), `todo`는 남은 단계(빈 테). `data-state`가 없으면 `todo`다.
- 지금 단계의 뜻은 색 하나가 아니라 `aria-current`, 순번, 채움 셋이 함께 나른다.
- 규칙은 `/common/stage-strip.css`에 산다 — `components.css`는 D-766 한도(942줄)에서 동결됐으므로 쓰는 화면은 `components.css` 뒤에 이 시트를 링크한다.

### 아이콘 — `class="ui-icon"`
- 24 viewBox · 실선 2 · `currentColor`. 크기는 `--text-value` 박스 토큰이 정하고(D-405), 식별은 라벨이 나르며 아이콘은 보조다.

### 배치 묶음
- **`ui-actions`**: 버튼 줄. 줄바꿈하고, 좁은 칸에서 한 열로 늘어난다.
- **`.ui-form` / `.ui-field-label`**: 네이티브 폼의 필드 묶음. 좁은 칸에서 한 열.
- **`.ui-readout`**: `dl` 이름–값 두 열. 값은 등폭. 좁은 칸에서 한 열.
- **`.ui-readback`**: 쓰기 뒤 되읽기 결과 묶음.

### 조합 어휘
표면마다 다른 이름으로 다시 만들던 묶음을 한 이름으로 부른다. 새 부품이나 화면별 사본을 만들기 전에 이 표를 먼저 본다. 표에 없는 묶음이 두 표면에 필요해지면 구현을 옮긴 뒤 이 표에 한 줄을 더한다. 이름은 `test_content_vocabulary.py`가 지킨다.

| 개념 | 정본 이름 | 지금 쓰는 곳 |
| --- | --- | --- |
| 측정 행(이름–값) | `.ui-readout` · `.ui-readback` | 로봇 카드, Fleet 상세, 견본 |
| 작업 목록 행 | `.ui-task-row` · `taskRow()` | 로봇 작업, Fleet 작업 선택 |
| 절차 단계 | `.ui-stage-track` · `.ui-stage` | 견본 — 표면 채택 전 |
| 증거 블록 | `<ui-evidence>` · `<ui-empty>` | 로봇 카드, Fleet 큐 |
| 절차 작업 열 | `.ui-sidebar` | 설치·정비, Fleet 작업 선택 |
| 매체 칸 | `.ui-pane[data-pane]` | 로봇 셸, 감지·카메라 |

### 상단바 — `<ui-topbar>` (D-466)
- 자리는 셋이다. `brand`(장미색 워드마크 + 조용한 부제), `cluster`(화면 전환·상태·조용한 도구), `estop`(오른쪽 끝 비상 정지). cluster 안의 순서는 표면이 정하고, 바깥 자리는 더 만들지 않는다.
- 붙박이, `ground-deep` 바탕, `--topbar-height`. 64rem 미만은 두 줄이다. 첫째 줄은 이름·상태, 둘째 줄은 화면 전환, 비상 정지는 두 줄을 차지한다. 30rem 미만은 그 두 줄에서 여백과 부제만 줄인다.
- Fleet은 맥락 / 연결 / 알림·나 / 정지 네 영역의 한 줄 앱 바를 쓴다(D-741 3·5항). 높이는 `--appbar-height`에 아래 1px 선을 더한 값이고 320px까지 한 줄이다. 접힘은 셸 칸의 폭에 답한다: 64rem 아래에서 현장 이름과 래치 부제, 48rem 아래에서 시계와 평상 연결 글, 30rem 아래에서 워드마크 글과 계정 단추의 역할 글이 접힌다(역할은 단추의 접근 이름에 남는다). 48rem 아래에서 평상이 아닌 연결 글(`연결 대기`·`지연`·`연결 끊김`)은 앱 바 아래 자기 줄에 선다. 계정·화면 표시·토큰 접속은 계정 단추 아래에 접고, 접속이 필요할 때 저절로 펼친다. 문서 이동은 탐색 레일이 맡고 푸터는 없다.
- 워드마크는 한 줄이다. 칸이 모자라면 표면이 이름 칸에 `container-type: inline-size`를 주고 글자가 칸에 맞게 줄어든다(상한 title).

### 사이드바 — `.ui-sidebar` (D-466)
- 절차 작업을 고르는 열이다. 로봇 작업 준비·설치·정비의 작업 레일과 Fleet 설치 작업 선택이 그 열이다.
- 넓은 단(64rem 이상)의 폭은 `--sidebar-track` 하나다. 그 미만에서는 레일을 숨기고 선택 필드를 보여 준다.
- 화면 전환, 입구의 작업 화면 목록, 명렬, 지도, 감지·관측·조작 열은 사이드바가 아니다. 화면 전환은 머리의 cluster이거나, 공용 셸을 쓰는 표면에서는 탐색 레일이다(D-741 6항).

### 비상 정지
- `ui-button kind="irreversible"`. 로봇 셸 `#shell-estop`, Fleet `#estop`(팔각 아이콘과 보이는 동사 비상 정지. 넓은 머리의 래치 부제는 "래치 · 로봇별 관리자 해제". 명령은 [D-421](docs/adr/D-421-fleet-cancel-all-driving-separate-from-latched-estop.md)의 래치형 전체 비상 정지). 동사는 줄바꿈하지 않고, 모든 폭에서 첫 화면에 있다.
- 래치 없는 Fleet **전체 주행 취소**(`#cancel-all`)는 비상 정지가 아니다. 상단바가 아니라 발행 상태 줄에 `quiet`로 선다(위험 채움은 비상 정지 하나). 로봇 카드 `운행 취소`와 큐 펼침 `중단`도 `quiet`이고, 멈추는 동작이라 확인 없이 바로 나간다([D-540](docs/adr/D-540-fleet-console-structure-v2.md) 6항).

### 테마 선택
- `role="group"` 안에 `RosyTheme.choices` 하나마다 `ui-button kind="segment" data-theme-choice="값"`(지금은 어둡게·밝게·시스템). `theme.js`가 누름을 받아 `aria-pressed`를 맞춘다. 로봇은 `/device` 화면 설정 패널이다. Fleet은 이 묶음 대신 헤더의 순환 버튼 하나를 쓴다(D-668).

## 작업 화면의 기본 원칙 (D-461)

상태를 읽고 다음 일을 찾아 행동하는 순서를 공용 디자인의 기준으로 삼는다.
공용 작업 부품은 기존 `ui-*` 조작과 토큰을 합성하며 표면이 선택해 적용한다.
예제 소비자는 학습 작업 `/learning`과 사진 검수다. 기존 운용 화면이 이번 변경으로
전환·설치·현장 수용되었다고 계산하지 않는다.

- 상태와 이유를 같은 자리에서 읽는다. 실패·거절·미확인은 한국어 텍스트로 표시하며 색만으로 구분하지 않는다.
- 반복 작업을 첫 화면에 둔다. 등록 폼은 필요할 때 펼치고, 목록의 검색·종류·확인 필요 필터를 가까이 둔다.
- 다음 행동에는 대상을 붙인다. 검수 대기 사진 열기·연결 저장·이 작업 연결 해제처럼 실제 결과를 말한다.
- 사용자의 맥락을 보존한다. 선택한 사진과 검색/필터를 URL로 복원하며 수정 내용을 별도 승인 없이 확정하지 않는다.
- 증거 상세는 펼쳐 본다. 한국어 상태와 핵심 실패 이유를 먼저, 단계·SHA·경로·기술 JSON을 상세에 둔다.
- 마우스·키보드·터치에서 같은 작업을 마친다. 포커스·비활성 이유·빈 상태·실패 후 재시도를 기능과 함께 검증한다.

`/common/workspace.js`의 `taskRow()`는 작업 제목·종류·상태·다음 작업을 텍스트 DOM으로
합성한다. `.ui-task-row`는 선으로 나눈 목록이며 중첩 카드로 쓰지 않는다.
`.ui-workspace-bar`는 검색/필터/행동을 묶는다. 상태 판단은 소비자가 계약에 맞게
전달한다. 부품은 보고서 통과를 실행 권한·정책 승격으로 바꾸지 않는다.

## 운용자 말 (Copy)

- **운용자가 읽는 글은 한국어 평문이다.** 용어는 [`CONCEPTS.md`](CONCEPTS.md)를 따른다: 실행 모드(profile 아님), 기능·도킹 기능(capability 아님), 하드웨어 실행 모드, 내비게이션, 호스트 에이전트. `test_operator_copy.py`가 대시보드·Fleet·games의 한글 문자열에서 `profile|capability|hardware 모드|Navigation|프로필`과 맨 열거값(`IDLE`·`MANUAL`·`RUNNING`·`HOLDING`·`UNDOCKED`·`WAITING`·`STALE` 등)을 막는다.
- **열거값은 `title`에만 둔다.** 보이는 글은 공용 표의 한국어이고 원래 값은 `title`·`data-*`에 남는다. 공용 표는 [`core_ui_logic.js`](shared/web/core_ui_logic.js)의 `MODE_LABEL`(대기·수동·내비게이션·도킹·비상 정지), `NAVIGATION_LABEL`, `DOCK_STATE_LABEL`과 `enumLabel()`이다 — 로봇 대시보드와 Fleet이 `/common/`에서 같은 파일을 싣는다. 모르는 값은 받은 그대로 보인다.
- **증거 어휘도 공용 표다.** 네 상태의 한국어(최신·지연·연결 끊김·정보 없음)와 나이 뒤처리(` · N초 전`)는 [`core_ui_logic.js`](shared/web/core_ui_logic.js)의 `EVIDENCE_LABEL`·`evidenceAgeText()`가 단일 출처다(D-398). 주어를 앞에 붙인 문장(`릴레이 끊김`·`위치 지연`)은 이 표를 참조해 조립한다.
- **증거가 있는 값은 증거와 함께 말한다.** 지연은 `지연 · N초 전`, 끊김은 `연결 끊김`, 모름은 `정보 없음`이고 `data-evidence`를 단다. 카드에 홀로 붙는 알약은 무엇의 증거인지 말한다(`릴레이 끊김`).
- **한 원인은 한 번 말한다.** 같은 원인이 여러 버튼을 막으면 원인과 다음 할 일은 묶음 상태 한 줄에 두고, 버튼 사유는 짧은 `위 사유`로 `aria-describedby`가 그 줄을 가리킨다.
- **빈 목록·읽기 실패는 `ui-empty`다.** 목록 밖 한 줄로 두고(목록은 숨김), 지도 같은 무대에서는 무대 위에 얹고 다시 시도를 곁에 둔다.

## Do's and Don'ts

### Do:
- **Do** 색은 역할 토큰(`--surface-*`, `--button-*`, `--field-*`, `--nominal`)으로 쓴다. 팔레트 이름은 역할이 없을 때만.
- **Do** 위험 채움 위 글자는 `--ink-on-crit`을 쓴다(`test_text_on_a_danger_fill_uses_the_on_crit_ink`).
- **Do** 정상은 `--nominal`(ink)로 그린다. 색은 임계를 넘었을 때만 나온다([D-82](docs/adr/D-82-oklch.md)).
- **Do** 막힌 버튼에는 `reason`으로 이유와 필요한 권한을 적는다([D-359](docs/adr/D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) §5.3).
- **Do** 제품 화면의 입력·선택에는 `class="ui-field"`를 단다. 최소 높이는 `--target-secondary`다.
- **Do** 알파·혼합은 `color-mix(in oklab, …)`로 만든다. oklch는 무채색의 색상각을 0°로 풀어 회색을 붉게 섞는다.
- **Do** 캔버스 색과 글꼴은 `window.RosyPalette`로 읽고 `rosy:theme`에서 다시 그린다.
- **Do** 새 중단점이 필요하면 `surfaces.yaml`에 값과 이유를 적는다.
- **Do** 목록 행의 삭제는 `quiet` `삭제…` → `confirmIrreversible` 대화상자로 연다. 위험 채움은 대화상자의 실행 버튼에만 있다([D-371](docs/adr/D-371-list-row-irreversible-actions-confirm-before-danger-fill.md)).
- **Do** 정지는 대화상자 위에서도 살아 있다. 확인은 `confirmIrreversible`(비모달)로 열고, 새 정지 컨트롤에는 `data-always-live`를 단다. `showModal()`과 문서 전체를 덮는 막은 쓰지 않는다.
- **Do** 새 테마 뒤에는 dark·light 두 테마로 390×844·320×568 캡처를 보고 넘침·머리 높이를 확인한다.

### Don't:
- **Don't** 표면 CSS·JS에 원시 색(hex·rgb·hsl·`oklch(`·`color(`)을 쓴다. `test_ui_token_contracts.py`가 막는다.
- **Don't** 장미색을 상태·포커스·데이터 계열에 쓴다([D-277](docs/adr/D-277-rosy-brand-colour-tokens.md)).
- **Don't** 주 명령을 초록이나 계열 파랑으로 칠한다. 주 명령은 ink 채움이다.
- **Don't** 공용 버튼에 `outline`이나 status 색을 덧칠해 눌림·선택을 표시한다. `aria-pressed`를 쓴다.
- **Don't** 공용 부품(`ui-actions`, `.ui-form`, `.ui-readout`)을 뷰포트 `@media`로 재정의한다.
- **Don't** 자간·글자 크기·간격에 토큰 밖 값을 쓴다. 12px 아래 글자를 만들지 않는다.
- **Don't** `title`만으로 비활성 사유를 대신한다.
- **Don't** 목록의 행마다 `kind="irreversible"` 버튼을 그린다. 빨강이 반복되면 비상 정지의 위계가 흐려진다([D-371](docs/adr/D-371-list-row-irreversible-actions-confirm-before-danger-fill.md)).
- **Don't** 장식 전환·펄스·반짝임을 더한다([D-220](docs/adr/D-220-stillness-contract-zero-motion-budget.md)).
- **Don't** 고정 높이 프레임을 낮은 창에 쓴다. `100vh` 대신 `dvh`다.
- **Don't** 테마를 위해 표면 파일에 `[data-theme=…]` 분기를 둔다. 팔레트 블록 하나로 끝나야 한다.

### 공용 동작과 native 색 출처 (D-432)

동작 아이콘과 이름은 `shared/web/ui.js`의 `actionIcon(button, name)`으로 함께 구성한다.
아이콘 크기는 `.ui-icon`/`--text-value`, 색은 currentColor, 버튼 종류·터치 크기·비활성 사유는
기존 공용 컨트롤을 따른다. 화면은 배치와 동작을 소유하며 공용 컴포넌트는 장비 명령을 보내지 않는다.

Native Pilot의 Kotlin 색과 Android 색 리소스는 `tokens.css`의 dark 블록에서 build 시 생성한다.
표면 registry의 token_source/token_generator/token_verification으로 출처와 런타임 비교 시험을
연결한다. 수동 색 사본 대신 생성된 색을 시스템 바·버튼·목록·대화상자·vector·런처가 함께 쓴다.
다른 native/LCD의 기존 token_copy는 parity 계약을 유지하며 실제 전환 때 생성 경로를 등록한다.

화면 개선은 목적·주 동작·상태/오류·복귀·가로/세로 배치를 순차 확인한다. 보조 도구에서 설정이나
녹화본을 열면 이전 패널을 접고, 닫으면 보이는 여는 동작으로 초점을 복귀한다. 같은 규칙을 쓰는
화면을 이유 없이 다시 그리지 않으며, 실제 장비 확인과 브라우저 대역 확인은 구별해 기록한다.
# Fleet 공용 헤더 영역 (D-658)

계정 발견성·로그인 복귀·연결/권한 구분은 [플랫폼 사용 규칙 재정리](docs/plans/2026-10-12-platform-ux-conventions-design.md)와 [D-683](docs/adr/D-683-fleet-account-entry-and-login-return.md)를 따른다. D-683은 아래 D-658의 계정 상세 위치를 대체한다. 우측의 보이는 로그인 링크에서 전용 로그인 문서로 가며, 화면 표시와 토큰 접속은 계정 단추 아래에 있다(D-741이 D-683 2항을 바꿨다). Map/Cell은 초안 보존을 위해 새 탭에서 로그인하고 원래 작업 탭에서 세션을 다시 확인한다. 구현·G1/G2/G3·설치 증거는 별도다.

앱 바는 맥락(R 심볼, `Fleet`, 현장 이름), 연결(연결 글과 시각), 알림·나(알림 단추, 로그인 링크 또는 역할 이름이 붙은 계정 단추), 비상 정지 네 그룹이고 모든 폭에서 한 줄이다(D-741 3·5항). 연결 자리에는 조작이 없다. 계정·화면 표시·토큰 접속은 계정 단추 아래 펼침 칸이며 화면 폭 때문에 저절로 드러나지 않는다. 접속이 필요할 때의 자동 펼침은 유지한다. 탐색은 왼쪽 레일(아이콘 아래에 짧은 이름) 또는 머리 아래 한 줄, 작업·지도는 본문, 현재 영상·개입·알림은 오른쪽 문맥 패널이 맡는다. 푸터는 없다.

