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
    typography: "{typography.body}"
    rounded: "{rounded.radius-button}"
    padding: "0 24px"
    height: "48px"
  button-quiet:
    textColor: "{colors.ink-quiet}"
    typography: "{typography.label}"
    rounded: "{rounded.radius-button}"
    padding: "0 12px"
    height: "44px"
  button-irreversible:
    backgroundColor: "{colors.status-crit}"
    textColor: "{colors.ink-on-crit}"
    typography: "{typography.value}"
    rounded: "{rounded.radius-button}"
    padding: "8px 16px"
    height: "58px"
  button-segment-pressed:
    backgroundColor: "{colors.ground-card-2}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    height: "44px"
  button-toggle-active:
    backgroundColor: "{colors.series-primary}"
    textColor: "{colors.ground}"
    rounded: "{rounded.radius-button}"
    height: "44px"
  field:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.radius-control}"
    padding: "0 12px"
    height: "44px"
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
> 값의 원본은 [`tokens.css`](src/hmi/web_common/tokens.css), 부품은 [`components.css`](src/hmi/web_common/components.css)·[`ui.js`](src/hmi/web_common/ui.js), 표면 목록은 [`surfaces.yaml`](src/hmi/web_common/surfaces.yaml), 살아 있는 견본은 [`styleguide.html`](src/hmi/dashboard/styleguide.html)이다.
> 위 frontmatter의 색은 기본(어둡게) 테마 값이다. 밝게 값은 `tokens.css`의 `[data-theme="light"]` 블록에 있다.

## Overview

**Creative North Star: "차분한 지능에 은은한 따뜻함"** ([D-280](docs/adr/D-280-calm-intelligence-product-design-philosophy.md))

ROSY 화면은 사람이 로봇을 안전하게 감시·개입·설치·점검하게 돕는다. 화면은 조용하다. 바탕과 글자는 거의 무채색이고, 색은 뜻이 있을 때만 나온다. 따뜻함은 ROSY 이름의 장미색과 짧고 배려 있는 문장에만 둔다.

밀도는 관제 화면 수준이다. 노트북 1366×768, 관제 PC 1920×1080, 전화 390×844와 320×568에서 같은 화면이 읽혀야 한다. 장갑·조명·팔 길이 거리를 전제로 글자 바닥은 12px, 누름 면은 44px 이상이다.

D-280 다섯 원칙은 시각에서 이렇게 묶인다.

1. **아는 만큼 말한다.** 알 수 없는 값을 정상처럼 그리지 않는다. 증거 네 상태(`fresh`/`delayed`/`disconnected`/`unavailable`)를 따로 그린다. `unavailable`은 점선 테다.
2. **중요한 것이 먼저 보인다.** 비상 정지는 모든 폭에서 첫 화면에 있다. 되돌릴 수 없는 조작이 가장 크다(58px).
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

## Colors

색은 뜻의 예산이다. 한 화면에서 색이 적을수록 색이 뜻하는 바가 강하다. 의미 집합은 [D-82](docs/adr/D-82-oklch.md)가, 대비 바닥은 [D-202](docs/adr/D-202-danger-is-a-fill-alarm-text-contrast-contract.md)·[D-214](docs/adr/D-214-text-contrast-floor.md)가 정한다. 값은 OKLCH에서 생성했다.

### Primary
- **ROSY 장미(Rosy Rose)** (`brand-rose`): 워드마크와 현재 위치 표식 선택자에만 쓴다. 상태·포커스·데이터 계열에 쓰지 않는다. 옅은 바탕은 파생 `--brand-rose-wash`다.

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
- 다른 파일은 고치지 않는다. 고쳐야 한다면 어딘가 팔레트 이름을 역할 대신 쓰고 있다는 뜻이다.
- `python -m pytest src/hmi/web_common/test -q`를 돌린다. 팔레트 게이트(`test_palette_gates.py`)가 테마마다 돈다: 글자 대비 ≥ 4.5:1, 위험 채움 위 `ink-on-crit` 대비, 주의·위험 색약 대비, 장미 대 위험 거리, status 따뜻한 띠·series 차가운 띠, 래스터 단조, 로봇 사다리.
- 바꾸면 안 되는 것: D-82 의미 집합, D-277 장미색 범위, **주 명령 = ink 채움**, **위험 채움 위 글자 = `ink-on-crit`**(테마와 무관하게 밝다).

**The One Block Rule.** 테마 하나는 팔레트 블록 하나다. 표면 파일에 테마 분기가 생기면 구조가 틀린 것이다.

**The Normal Has No Colour Rule.** 계기의 안전 구간에는 아무것도 칠하지 않는다. 정상은 `--nominal`(= ink)이다.

### 테마 선택

- 기본은 어둡게다(관제실·현장 조명 계약). 밝게는 존재하지만 사람 G3·현장 조명 관측 전까지 운용 권장 테마가 아니다.
- [`theme.js`](src/hmi/web_common/theme.js)를 `<head>`에서 `tokens.css` 바로 뒤에 동기로 싣는다(CSP 준수 외부 스크립트). 첫 그림 전에 `<html data-theme>`과 `meta[name=theme-color]`(해당 테마 `--ground`)를 정한다.
- 선호는 `localStorage` `rosy.theme` = `dark|light|system`. 없거나 읽기 실패면 `dark`. `system`은 `prefers-color-scheme`을 따른다.
- API: `window.RosyTheme.get()`·`set(pref)`·`resolved()`. 바뀌면 `document`에 `rosy:theme` 이벤트(`{theme, preference}`)가 난다.
- 선택 UI는 `data-theme-choice` segment 버튼 세 개다. 로봇 `/device` 화면 설정 패널과 Fleet `설정` 안에 있다.
- 고정 표면: `surfaces.yaml`에 `themes: [dark]`인 표면(games 보드, `lane_live_view`, `diagnostic.html`)은 `<html data-theme-pin="dark">`다. 네이티브·LCD 사본도 어둡게 고정이다.
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

**The Latin Tracking Rule.** 자간 토큰은 라틴 대문자 라벨용이다. 자기 글자에 한글이 있는 요소(섞인 글 포함)는 자간 0이다: `ui.js`가 그런 요소에 `data-hangul`을 달고(글자가 바뀌면 따라간다) `components.css`가 그 요소의 `--track-*`를 0으로 둔다. 모든 페이지가 `lang="ko"`라 `:lang()`으로는 가를 수 없고, 한 요소 안에서 글자별 자간은 CSS로 줄 수 없어 섞인 글은 한글 쪽을 따른다.

**The Six Steps Rule.** 글자 크기는 여섯 단계로 닫혀 있다. 캔버스 글꼴도 `RosyPalette.canvasFont`로 토큰 가족·12px 이상이다.

**The Whole Word Rule.** 모든 표면 본문은 `word-break: keep-all; overflow-wrap: break-word`다. 한국어는 어절에서 끊고, 칸을 넘치는 긴 기계 값만 접는다. `anywhere`는 짧은 라벨을 음절 사이에서 꺾으므로 기본으로 쓰지 않는다.

## Layout

- **간격 척도**: 4의 배수 여섯 단계 `--space-1..6`(4/8/12/16/24/32px). 임의 값을 쓰지 않는다.
- **역할 간격**: 부품은 척도 대신 역할 이름을 읽는다 — `--inset-button`, `--inset-field`, `--inset-tag`, `--gap-actions`, `--gap-form`, `--gap-readout`, `--gap-topbar` 등([D-292](docs/adr/D-292-design-tokens-and-component-layout-contract.md)).
- **세 단**: **compact** `width < 30rem`, **medium** `30rem ≤ width < 64rem`, **wide** `width ≥ 64rem`. 범위 문법(`@media (width < 30rem)`)을 쓰고 `.01` 보정을 쓰지 않는다. 값은 rem이다.
- **허용 목록**: 세 단 밖의 값은 `surfaces.yaml`의 그 표면 `breakpoints`에 값과 이유를 적는다. 예: Fleet `90rem` — 머리의 토큰·역할·테마를 `설정` 뒤로 접는 폭. `test_responsive_tiers.py`가 대조한다.
- **칸 질의**: 공용 부품(`ui-form`, `ui-readout`, `ui-actions`)은 뷰포트가 아니라 자기 칸에 반응한다 — `@container (width < 22rem)`에서 한 열로 접힌다. 칸(`container-type: inline-size`)은 표면이 정한다. 22rem은 `surfaces.yaml` `container_breakpoints`에 있다. 표면이 공용 부품을 뷰포트 질의로 재정의하지 않는다.
- **표면이 배치를 소유한다.** 공용 부품은 얼굴만 준다. 어디 놓을지는 표면 시트가 정한다.

**The Header Budget Rule.** 390×844와 320×568에서 붙박이 상단바는 창 높이의 20% 이하다. 좁은 창에서는 두 줄로 모으거나 부가 항목(토큰 입력·역할·테마)을 접는다.

**The E-stop First Rule.** 비상 정지는 compact를 포함한 모든 폭에서 첫 화면에 보인다. 상단바 격자에서 늘 오른쪽 위에 두 줄을 차지한다.

**The Tall Enough Rule.** 고정 높이 프레임은 `(width >= 64rem) and (height >= 40rem)`에서만 쓴다. 그 밖은 흐르며 스크롤한다. 높이는 `vh`가 아니라 `dvh`다.

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

누름 면 크기가 위험도를 말한다 — 되돌릴 수 없는 것이 가장 크다.

- `--target-secondary` 44px: 모든 버튼·필드·체크 라벨의 최소 높이.
- `--target-primary` 48px: 주 명령.
- `--target-irreversible` 58px: 비상 정지·되돌릴 수 없는 조작.

**The Risk Ladder Rule.** 44 → 48 → 58은 위험 사다리다. 덜 위험한 조작을 더 크게 만들지 않는다.

## Components

모든 부품은 [`components.css`](src/hmi/web_common/components.css)가 그리고 [`ui.js`](src/hmi/web_common/ui.js)가 정의한다. 그림자 DOM을 쓰지 않는다. 견본은 [`styleguide.html`](src/hmi/dashboard/styleguide.html)이다.

### 버튼 — `<ui-button kind="…">`
- **종류**: `primary`(ink 채움, 48px), `quiet`(테두리만, 조용한 글자), `irreversible`(위험 채움 + `ink-on-crit`, 58px), `segment`(여러 중 하나), `toggle`(켜지면 계열 파랑 채움). `kind`가 없으면 계약 표지(`data-kind-missing`, 위험색 윤곽)가 그려진다.
- **상태**: `:hover`·`:active`·`:focus-visible`·비활성이 모두 `components.css`에 있다. 눌림은 `aria-pressed="true"`(또는 `aria-selected`, `.active`)의 공용 표현이다. 채움 종류는 누르는 동안 바탕색 안쪽 테를 얻는다.
- **비활성 사유**: `reason="운용자 권한이 필요합니다"`처럼 속성을 단다. `ui.js`가 버튼 안 `<small data-reason>`으로 그리고 `aria-describedby`로 잇는다. 사유가 있는 비활성은 흐리지 않고 점선 테와 조용한 글자로 말한다. `title`만으로는 사유가 아니다(터치에서 보이지 않는다).

### 필드 — `class="ui-field"`
- 네이티브 `input`/`select`/`textarea`에 `class="ui-field"`를 단다(폼 제출·`<label>` 연결·기존 핸들러 유지). 44px, `--radius-control`, `--field-bg`, `--field-line`, 등폭 숫자.
- `readonly`는 점선 테·조용한 글자, `:user-invalid`·`aria-invalid="true"`는 `--field-invalid` 테, 비활성은 `--disabled-opacity`.
- 체크·라디오는 상자를 따로 그리지 않는다. 감싸는 `<label class="ui-check">`가 44px 누름 면이다.
- `<ui-field>` 감싸개도 같은 얼굴이지만 제품 화면은 클래스 방식을 쓴다.

### 태그 — `<ui-tag status="…">`
- 깃발 모양, mono 라벨, `--track-state`. 상태 어휘: `neutral`(조용한 글자) · `active`(정상 진행 — ink 테, 색 아님) · `warn`(주의 글자·테) · `crit`(위험 채움 + `ink-on-crit`).

### 상태 글 — `<ui-status state="…">`
- 화면 알림 한 줄. `warning`/`error`/`unavailable`/`forbidden`은 주의색 글자. `state`가 없으면 계약 표지가 그려진다.

### 배치 묶음
- **`ui-actions`**: 버튼 줄. 줄바꿈하고, 좁은 칸에서 한 열로 늘어난다.
- **`.ui-form` / `.ui-field-label`**: 네이티브 폼의 필드 묶음. 좁은 칸에서 한 열.
- **`.ui-readout`**: `dl` 이름–값 두 열. 값은 등폭. 좁은 칸에서 한 열.
- **`.ui-readback`**: 쓰기 뒤 되읽기 결과 묶음.

### 상단바 — `<ui-topbar>`
- 붙박이, `ground-deep` 바탕, 88px 기준 높이. 왼쪽 `ui-brand`(장미색 워드마크 + 조용한 부제), 오른쪽 끝 비상 정지. 좁은 창의 접기는 표면이 정한다(로봇 셸: 두 줄 격자, Fleet: 90rem 아래 `설정` 뒤로 접기).

### 비상 정지
- `ui-button kind="irreversible"`. 로봇 셸 `#shell-estop`, Fleet `#estop`("전체 정지 / 등록된 모든 로봇"). 줄바꿈하지 않고, 모든 폭에서 첫 화면에 있다.

### 테마 선택
- `role="group"` 안에 `ui-button kind="segment" data-theme-choice="dark|light|system"` 세 개(어둡게·밝게·시스템). `theme.js`가 누름을 받아 `aria-pressed`를 맞춘다. 로봇은 `/device` 화면 설정 패널, Fleet은 `설정` 안이다.

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
- **Do** 새 테마 뒤에는 dark·light 두 테마로 390×844·320×568 캡처를 보고 넘침·머리 높이를 확인한다.

### Don't:
- **Don't** 표면 CSS·JS에 원시 색(hex·rgb·hsl·`oklch(`·`color(`)을 쓴다. `test_ui_token_contracts.py`가 막는다.
- **Don't** 장미색을 상태·포커스·데이터 계열에 쓴다([D-277](docs/adr/D-277-rosy-brand-colour-tokens.md)).
- **Don't** 주 명령을 초록이나 계열 파랑으로 칠한다. 주 명령은 ink 채움이다.
- **Don't** 공용 버튼에 `outline`이나 status 색을 덧칠해 눌림·선택을 표시한다. `aria-pressed`를 쓴다.
- **Don't** 공용 부품(`ui-actions`, `.ui-form`, `.ui-readout`)을 뷰포트 `@media`로 재정의한다.
- **Don't** 자간·글자 크기·간격에 토큰 밖 값을 쓴다. 12px 아래 글자를 만들지 않는다.
- **Don't** `title`만으로 비활성 사유를 대신한다.
- **Don't** 장식 전환·펄스·반짝임을 더한다([D-220](docs/adr/D-220-stillness-contract-zero-motion-budget.md)).
- **Don't** 고정 높이 프레임을 낮은 창에 쓴다. `100vh` 대신 `dvh`다.
- **Don't** 테마를 위해 표면 파일에 `[data-theme=…]` 분기를 둔다. 팔레트 블록 하나로 끝나야 한다.
