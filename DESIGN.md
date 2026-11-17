---
name: ROSY
description: 로봇·플릿 관제 웹 표면의 시각 체계 — 차분한 지능에 은은한 따뜻함
colors:
  ground: "#111113"
  ground-deep: "#0c0d0f"
  ground-raise: "#18191b"
  ground-soft: "#212225"
  ground-card: "#272a2d"
  ground-card-2: "#2e3135"
  ink: "#eeeeef"
  ink-quiet: "#b0b4ba"
  ink-on-crit: "#eeeeef"
  status-crit: "#b54548"
  status-warn: "#ffc53d"
  status-good: "#3dd68c"
  series-primary: "#58a6ff"
  series-secondary: "#2870bd"
  series-goal: "#3dd68c"
  robot-1: "#bddafe"
  robot-2: "#63abfe"
  robot-3: "#2f76c4"
  app-line-learning: "#0eb39e"
  app-line-fleet: "#9eb1ff"
  app-line-robot: "#b1a9ff"
  raster-unknown: "#0c0d0f"
  raster-free: "#18191b"
  raster-uncertain: "#43484e"
  raster-occupied: "#b0b4ba"
  brand-rose: "#e796f3"
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
> Fleet 헤더·탐색의 정적 컴포넌트와 작업 본문·접속 폭의 역할 토큰은 [D-906](docs/adr/D-906-fleet-static-components-layout-roles.md)을 따른다. 원본은 Fleet의 `shared/fleet-header.html.inc`·`fleet-nav.html.inc`이며 생성된 네 문서 사본은 직접 편집하지 않는다. [D-909](docs/adr/D-909-fleet-procedure-document-components.md)의 나머지 다섯 절차 문서는 `fleet-document-header.html.inc`·`fleet-document.css`를 소비한다. `fleet_components.py --check`가 아홉 문서의 드리프트를 거절하고 공용 갤러리에서 계산된 역할 값을 확인한다.

> Learning의 12개 정적 문서는 [D-910](docs/adr/D-910-learning-static-shell-components.md)의 `review_app_web/components/`에서 헤더·전역 메뉴를 합성한다. `review_shell.py --check`가 원본과 문서 사본의 일치를 확인한다. 기존 셸 자리·시각 토큰을 소비하며, 화면별 폼과 하위 탐색은 각 문서에 둔다.
> 위 frontmatter의 색은 기본(어둡게) 테마 값이다. 밝게 값은 `tokens.css`의 `[data-theme="light"]` 블록에 있다.

## 먼저 지킬 것: 읽는 순서·깊이·말 ([D-926](docs/adr/D-926-ui-reading-order-depth-and-wording.md))

토큰은 값을 닫는다. 이 절은 그 값을 **어떤 순서로, 몇 개를, 어느 깊이에** 놓는지를 닫는다. 새 화면을 만들거나 고칠 때 이 절을 먼저 맞추고, 아래 절의 값은 그다음에 고른다.

### 읽는 순서

| 층 | 담는 것 | 모양 |
|---|---|---|
| 1 안전 | 비상 정지, 지금 막고 있는 위험 하나 | 앱 바 오른쪽 고정. 위험 띠는 본문 맨 위 한 줄에 원인과 할 일 |
| 2 지금 상태 | 이 화면 대상의 현재 | 화면 제목 아래 한 줄 |
| 3 할 일 | 주 동작 하나와 그 입력 | 흰 채움(`primary`)은 화면당 하나 |
| 4 근거 | 이유·출처·기록 | 보조 글자, 접힘 또는 다른 탭 |
| 5 진단 | 원시 값·리비전·해시·내부 코드 | 개발 진단을 열 때만. `undefined`·`null`은 화면 글자가 될 수 없다 |

### 깊이

| 깊이 | 무엇 | 자리 | 면 | 나가는 법 |
|---|---|---|---|---|
| 0 앱 | 제품 | 앱 바 한 줄 | `ground-deep` 띠 | 늘 보임 |
| 1 영역 | 관제·작업·기록·지도·설치 | 탐색 레일 | 레일 선택 막대 | 다른 영역 |
| 2 화면 | 영역 안의 일 하나 | 하위 탐색 + 본문 | `--surface-canvas` | 다른 하위 화면 |
| 3 대상 | 고른 로봇·작업·지도 판 | 오른쪽 칸, 좁으면 상세 화면 | `--surface-raised` | `← 목록` |
| 4 확인·진단 | 되돌릴 수 없는 확인, 원시 값 | 대화상자·진단 접힘 | 장막·음영 | 취소·Esc·접기 |

- 깊이 2 이상은 경로 줄(`--pathbar-height`)에 `영역 / 화면 / 대상`을 쓴다. 깊이 수는 폭과 무관하다.
- 한 단계 깊어지면 면이 한 단계 솟는다. 카드 속 카드는 없다.
- 하위 탐색은 이동이다. 누르면 본문에 그 화면 하나만 보인다. 다른 층을 한 목록에 섞지 않는다.
- 접힘은 한 겹이고 깊이 4에만 쓴다. 접힘이 셋 이상 필요하면 하위 화면으로 나눈다.
- 앱 바 아래에 소속 없는 줄을 두지 않는다. 모든 Fleet 문서는 같은 앱 바와 레일을 쓴다.

### 말

| 쓰임 | 토큰 | 규칙 |
|---|---|---|
| 화면 제목 | `--text-title` | 화면당 하나 |
| 구획 제목 | `--text-body`, `--weight-emphasis` | 구획당 하나 |
| 본문·값 | `--text-body` | 사용자 문장의 기본 |
| 보조 | `--text-micro` | 시각·출처·사유 한 줄 |

- `--text-label`은 입력 이름과 칩에만 쓴다. 문장·안내·목록 항목에 쓰지 않는다.
- 안내 문장은 구획당 한 문장이다. 같은 말은 화면에 한 번만 쓴다.
- 운용자 말을 쓴다. 바꿀 말이 없는 내부 용어(`owner HOLD`, `revision`, `lease`, ADR 번호)는 진단 층으로 보낸다.

### 부품 모양

- 목록은 공용 목록 행(이름·상태 칩·보조 한 줄·동작)이다. 브라우저 기본 점 목록을 쓰지 않는다.
- 상태 칩은 한 모양이고 색만 다르다. 칩 옆에 맨 글자 상태를 섞지 않는다.
- 막힌 버튼의 사유는 점선 테 안, 버튼 이름 아래 한 줄이다(아래 비활성 사유). 같은 구획에 막힌 버튼이 셋 이상이면 구획 위에 한 번만 쓴다.
- 본문 탭은 아이콘과 이름을 함께 보인다. 앱 바의 알림·계정 단추만 아이콘 단독이다.
- 빈 상태는 한 줄과 다음 동작이다. 파일 입력은 한국어 단추의 `.file-picker`(Fleet `file-picker.css`·`file-picker.js`, 정적 HTML)이고, 스크립트로 만드는 폼은 `createFilePicker`다. 칸을 넘는 행은 버그다.

### 고친 뒤 확인

1366×768과 390×844 캡처로 본다. 목적과 상태가 3초 안에 읽히는가 · 흰 채움이 하나인가 · 빨강 옆에 할 일이 있는가 · 내부 용어나 `undefined`가 보이는가 · 하위 탐색이 본문을 바꾸는가 · 390에서 본문이 첫 화면 안에서 시작하는가 · 칸을 넘는 것이 있는가.

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
- 차가운 무채색 바탕(Radix slate, C ≤ 0.010) 위 한 가족 글꼴, 숫자만 등폭
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

앱 바의 알림·계정과 접속·새로고침·확대·내보내기 같은 반복 도구 단추는 아이콘 단독을 기본으로 하고 이름은 접근성 트리와 공용 툴팁으로 제공한다. 탐색 레일과 본문의 맥락 탭은 아이콘과 이름을 함께 보인다(D-741, [D-926](docs/adr/D-926-ui-reading-order-depth-and-wording.md)). 알림 숫자와 필수 상태·위험·실행 결과는 숨기지 않는다.

Fleet 앱 바의 오른쪽은 연결·알림·나·정지 순서다. 연결은 `실시간`·`지연`·`연결 끊김` 가운데 하나와 로컬 시각이고 브라우저와 Fleet 사이의 것이다. 알림 단추는 종과 열린 개입 수(큐의 긴급·주의 행)다. 누르면 어느 Fleet 화면에서든 관제 큐 패널로 간다(2026-11-18). 계정 단추는 역할 이름을 달고, 그 아래에 계정·화면 표시·토큰 접속이 있다. 개발 연결 표지는 닫힌 계정 단추에서도 보인다. 로봇 연결 수는 앱 바가 아니라 관제 화면의 지도 머리에 있다. 알림 열기·메시지 읽음·개입 해소는 별개다([D-741](docs/adr/D-741-unified-app-shell-seats.md) 3항, D-668의 테마 순환과 인라인 값 표현은 그대로 쓴다).

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

색은 뜻의 예산이다. 한 화면에서 색이 적을수록 색이 뜻하는 바가 강하다. 의미 집합은 [D-82](docs/adr/D-82-oklch.md)가, 대비 바닥은 [D-202](docs/adr/D-202-danger-is-a-fill-alarm-text-contrast-contract.md)·[D-214](docs/adr/D-214-text-contrast-floor.md)가 정한다. 값은 실제 제품 색 체계(Radix Colors·GitHub Primer)의 단계에서 골라 팔레트 게이트로 걸렀다([D-976](docs/adr/D-976-palette-from-product-scales-and-dense-tool-targets.md)). 같은 색이 넓은 면을 칠하지 않는다 — 끝난 진행·정상 칸은 중립이고 색은 지금 도는 것과 주의가 필요한 것에만 간다.

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
- 그림자 토큰은 없다(`shadow-base`는 쓰는 곳이 없어 2026-11-18에 지웠다). 그림자가 필요해지면 그때 팔레트 키로 다시 정한다.

### 세 층 토큰

1. **팔레트** — 테마마다 바뀌는 유일한 값. 키 목록은 닫혀 있다(위 frontmatter 27개). 원시 색은 이 블록에만 있다.
2. **파생** — 팔레트만 참조한다. 선(`--line-*`), 장막(`--scrim*`), 세척(`--status-crit-a07` 등)은 `color-mix(in oklab, var(--팔레트) N%, transparent | var(--ground…))`다. 원시 색 리터럴이 있으면 시험이 막는다.
3. **역할** — 부품이 읽는 이름: `--surface-*`, `--button-*`, `--field-*`, `--flag-*`, `--focus-ring`, `--gauge-*`, `--nominal*`. 표면 CSS는 팔레트보다 역할을 먼저 쓴다.

### 테마 추가·변경 절차

상세는 [ui-design-details.md](docs/reference/ui-design-details.md)의 「테마 추가·변경 절차」로 옮겼다.

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
- **하위 메뉴 링크가 많을 때**: 64rem 미만에서 `.ui-subnav-item`이 7개 이상이면 `ui-wiring.js`가 `data-many`를 달고 줄바꿈 대신 한 줄 가로 스크롤이 된다(링크는 그대로 눌린다). 6개 이하는 줄바꿈한다. 접힘이나 `select`는 쓰지 않는다 — 닫힌 접힘 안 링크는 시험과 키보드가 누를 수 없다.
- **Robot 운용 콘솔 좁은 화면 순서**: 머리·띠 → 운전 모드 → 카메라 → 지도, DOM 순서와 같다([D-1028](docs/adr/D-1028-robot-console-narrow-order-head-mode-camera-map.md)). 정지는 머리에서 늘 첫 자리다.
- **기록 아이콘**: 기록·로그 이동은 `log`(장부)다. `list`는 목록, `history`는 지연 상태 전용이다.
- **동등한 창은 같은 폭**: 같은 행의 운용 영역과 나란한 지도·카메라 창은 같은 너비를 쓴다. 좁은 화면에서는 한 열로 쌓아 각 창이 가용 너비를 채운다. 탐색 사이드바처럼 역할이 다른 칸은 콘텐츠에 필요한 폭을 쓴다. Fleet `/console`의 현장 지도와 오른쪽 개입 열은 동등한 창이 아니며, [D-629](docs/adr/D-629-control-sizing-and-console-hierarchy.md)에 따라 넓은 화면에서 2:1로 배치한다.

**The Header Budget Rule.** 390×844와 320×568에서 붙박이 상단바는 창 높이의 20% 이하다. 좁은 창에서는 두 줄로 모으거나 부가 항목(토큰 입력·역할)을 접는다. 테마는 접지 않는다 — Fleet 헤더의 버튼 하나(D-668)이거나 로봇 대시보드의 시스템 화면 설정에 있다.

**The E-stop First Rule.** 비상 정지는 compact를 포함한 모든 폭에서 첫 화면에 보인다. 상단바 격자에서 늘 오른쪽 위에 있고, 머리가 두 줄인 표면에서는 두 줄을 차지한다.

**The Tall Enough Rule.** 고정 높이 프레임은 `(width >= 64rem) and (height >= 40rem)`에서만 쓴다. 그 밖은 흐르며 스크롤한다. 높이는 `vh`가 아니라 `dvh`다. 열 수는 폭만 따른다: 낮은 wide 창(1366×600)은 프레임만 풀고 열을 지킨다 — 프레임 규칙과 열 규칙을 한 미디어 조건에 묶지 않는다.

### 앱 셸의 자리 (D-741)

상세는 [ui-design-details.md](docs/reference/ui-design-details.md)의 「앱 셸의 자리 (D-741)」로 옮겼다.

## Elevation & Depth

그림자로 깊이를 만들지 않는다. 깊이는 **면의 높낮이(바탕 사다리)**다. concept 16 Law 2: 보고하는 것은 평평하고, 세상을 바꾸는 것은 솟아 있다.

- **평평한 면** (`--surface-flat` = `ground-soft`): 읽기 전용 값, 격자 칸, 보고.
- **솟은 면** (`--surface-raised` = `ground-card`): 조작을 품은 면.
- **선** (`--surface-line` = ink 14%, `--surface-sheen` = ink 6%): 면 경계.
- **장막** (`--scrim`, `--scrim-raise`, `--scrim-top`, `--scrim-solid`, `--panel-fill`): 지도·영상 위에 얹는 글자의 바탕. 바탕 색의 알파다.

**The Stillness Rule.** 장식 움직임은 없다([D-220](docs/adr/D-220-stillness-contract-zero-motion-budget.md)). hover·active·눌림은 선과 면만 바꾼다. 전환 애니메이션을 더하지 않는다.

## Shapes

모서리는 네 종류다.

- **조작 모서리** (`--radius-control` 6px): 필드, 칩, `unavailable` 증거 테.
- **버튼 모서리** (`--radius-button` 8px): 모든 `ui-button`, skip link.
- **패널 모서리** (`--radius-panel` 12px): 패널.
- **깃발 모서리** (`--radius-flag` 999px): `ui-tag`, 점 표지.

비상 정지를 포함한 모든 조작의 크기를 통일한다([D-629](docs/adr/D-629-control-sizing-and-console-hierarchy.md)). 좁은 Fleet 관제의 배치·읽기 순서는 [D-892](docs/adr/D-892-fleet-mobile-operator-priority.md)를 따르되, 현재 개입 → 지도 → 로봇 상세 순서는 [D-1027](docs/adr/D-1027-fleet-narrow-order-exceptions-map-context.md)이 대체한다.

- `--target-secondary` 48px: 일반 버튼·필드·체크 라벨의 최소 높이.
- `--target-primary` 48px: 주 명령.
- `--target-irreversible` 48px: 비상 정지·되돌릴 수 없는 조작.

**공통 조작 법칙.** 비상 정지를 포함한 모든 버튼은 종류에 관계없이 48px·라벨 글자·좌우 여백을 공유한다. 폭은 라벨 길이로 정하고 아이콘 전용은 같은 누름 면의 정사각형이다. 크기는 최소값이므로 긴 문구·비활성 사유는 늘어날 수 있다. 버튼의 의미는 채움과 상태, 아이콘과 보이는 동사로 구분한다. 위험 조작의 크기 예외나 화면별 작은 버튼을 만들지 않는다.

**도구 단계(D-976, D-629 개정).** 넓은 화면(64rem 이상)의 마우스 작업 면에서만 도구 막대·표 행 동작의 아이콘 단추는 `--target-tool` 36px, 표·목록 행은 `--row-dense` 34px를 쓸 수 있다. 아이콘 단독 도구에는 `aria-label`이 있다. 주 동작·비상 정지·되돌릴 수 없는 조작·폼 입력은 48px 그대로이고, 64rem 미만에서는 소비 시트가 `--target-secondary`로 되돌린다.

### 관제의 정보 위계와 배치 이유

상세는 [ui-design-details.md](docs/reference/ui-design-details.md)의 「관제의 정보 위계와 배치 이유」로 옮겼다.

## 표면 문법

모든 웹 표면은 `ui-shell`의 `grammar` 네 가지 중 하나로 시작한다(D-292 §5, [`template.html`](shared/web/template.html)). 문법은 화면의 읽는 순서와 첫 화면이 무엇인지를 정한다.

- **spatial** — 로봇 콘솔. 감각→관찰→조작 세 지역(`robot`, 견본 `web-common`)
- **exception** — 사이트 관제. 예외가 먼저, 지도·대형은 뒤(`console`)
- **focal** — 경기 보드·조종. 하나의 초점(공, 주행 무대)이 화면을 지배(`game-board`, `pilot`)
- **procedure** — 점검·진단. 단계가 순서대로(`control-diagnostic`)

등록부(`surfaces.yaml`)의 `grammar` 칸이 [`ui.js`](shared/web/ui.js)의 `GRAMMARS`와 같은지 계약 시험이 대조한다. 웹이 아닌 다섯째 문법 **intent**(로봇 얼굴, concept 16 §7.4)은 LCD 표면이 소유한다.

## Components

공용 구현은 [`shared/web/ui.js`](shared/web/ui.js)·[`components.css`](shared/web/components.css), 실행 가능한 견본은 로봇 `/styleguide`의 [`스타일 갤러리`](middleware/robot_ui/robot/styleguide.html)다. 새 컴포넌트 모음이나 화면별 버튼·입력 사본을 만들지 않는다. 갤러리에서 색상 역할, 다섯 버튼 종류, 입력, 상태, 증거, 읽기·되읽기, 작업 행·작업 선택을 함께 비교한다. 부품 변경은 사용 화면·갤러리·접근성/반응형 시험을 같은 변경에서 맞춘다.

기초 부품은 [`components.css`](shared/web/components.css)가 그리고 [`ui.js`](shared/web/ui.js)가 정의한다. 조합 부품은 아래 역할별 모듈과 [`component-controls.css`](shared/web/component-controls.css)에 둔다. 그림자 DOM을 쓰지 않는다. 견본은 [`styleguide.html`](middleware/robot_ui/robot/styleguide.html)이며 [상호작용 견본 장](shared/web/component-gallery.html)으로 이어진다.

### 입력·자료·복구의 조합 부품

[D-961](docs/adr/D-961-shared-task-links-and-page-compositions.md)의 이동 조작은 네이티브 `a.ui-action-link`와 명시적인 `data-kind="primary|quiet"`다. 실행 버튼과 같은 의미 토큰·48px 바닥을 사용하면서 링크의 새 탭·주소 복사·키보드 이동을 유지한다. 같은 시트의 `ui-task-page`는 작업 본문, 추가 `ui-auth-page`는 인증 본문의 폭과 간격을 맡는다. 지도·영상·경기판의 전용 배치를 이 구성에 억지로 맞추지 않는다.

기존 기초 부품과 네이티브 HTML을 조합한다. 쓰는 화면은 `components.css` 다음 `/common/component-controls.css`를 로드한다. 새 팔레트·버튼 사본이나 전체 UI 프레임워크는 추가하지 않는다. 함수가 반환한 `element`를 붙이고 화면을 해제할 때 `dispose`가 있는 부품은 호출한다.

| 모듈 | 공개 부품 | 사용·비사용 조건 |
|---|---|---|
| `form-controls.js` | `createFormErrors(form, summary)`, `createFilePicker({id,label,accept,maxBytes,onChange})` | 기존 네이티브 폼에 오류 요약·필드 설명을 연결한다. 파일 이름·크기 오류는 네이티브 폼 유효성에도 반영하고, 수정·선택 해제 시 오류를 푼다. 이 검사는 서버 검증을 대체하지 않는다. |
| `form-controls.js` | `createSearchSelect({id,label,choices,onChange})`, `createDateRange({id,label,onChange})`, `createDirtyGuard(form)` | 검색+네이티브 선택, 현지 달력 날짜 범위, 미저장 이탈 확인. 검색·자료 갱신으로 선택이 사라지면 빈 값을 한 번 알리고 유효한 선택은 유지한다. 단순 선택은 원래 select를 쓴다. 저장 성공 뒤에만 dirty guard의 `reset()`으로 기준선을 바꾼다. |
| `collection-controls.js` | `createListToolbar({id,filters,sortLabel,sortOptions,onChange})`, `createPagination({id,onChange})` | 검색·필터·정렬 의도와 페이지 사실만 처리한다. 정렬 이름과 `{value,label}` 선택지는 호출자가 정하며, 생략하면 기존 이름 오름차순·내림차순을 쓴다. 서버 검색·선택 범위·총량을 추측하지 않는다. |
| `collection-controls.js` | `createDataTable({id,columns,onOpen,onSelection,onActiveRemoved})`, `createSelectionBar({id,onClear,actions})` | 고유 문자열 ID로 행을 선택한다. `set(items,{allIds,label})`의 `allIds`는 현재 소유자가 유효함을 아는 범위다. 알 수 없는 전체 페이지 선택을 제공하지 않는다. 일괄 동작과 부분 실패는 호출자가 처리하며 선택을 자동 해제하지 않는다. |
| `collection-controls.js` | `createPrimaryDetail({id,label,list})` | PC는 목록 옆 상세, 전화는 상세 진입과 목록 복귀. `open({title,body},opener)`의 opener는 재렌더 후 대상을 찾는 함수도 된다. 표면은 `onActiveRemoved`를 상세의 `unavailable(message)`에 연결해 사라진 대상을 명시한다. 복귀 대상이 없어졌으면 목록으로 초점을 보낸다. |
| `interaction-controls.js` | `createTabs`, `createDisclosure`, `createActionMenu`, `createSupplementPanel` | 탭은 수동 활성화·방향키/Enter, 접힘은 native details. 보조 동작은 일반 Tab 순서의 disclosure이며 ARIA menu가 아니다. 보조 패널은 정지를 가리는 모달이 아니다. |
| `workflow-controls.js` | `createStatePanel`, `createActionBar`, `createOperationResult` | 로딩·빈 상태·권한·실패·재시도를 구분한다. 요청·접수·실제 재조회·불확실을 표시하며 경과 시간으로 완료를 만들지 않는다. 중요한 동작 이름은 좁은 폭에서도 줄바꿈한다. |
| `workflow-controls.js` | `createProgress`, `createTimeline`, `createSteps`, `createLogView` | 진행률 미확인은 `null`, 단계는 기존 stage strip을 쓴다. 로그는 호출자가 공개 가능한 내용만 전달한다. 단계·진행률 100%를 물리 완료로 해석하지 않는다. |

파일·검색 선택·날짜 범위는 네이티브 폼 초기화가 끝난 뒤 표시와 호출자 상태를 맞춘다. 검색 선택은 명시적인 미선택 항목으로 시작하며 폼 초기화가 첫 대상을 자동 선택하지 않는다. 취소된 초기화와 그 뒤의 명시적 선택은 유지하고, `dispose()` 뒤에는 늦은 초기화 콜백을 보내지 않는다.

실행 예시는 `/common/component-gallery.html`에 있다. 합성 데이터의 설정 폼·운영 목록·개입·파일 절차를 직접 조작하며 양 테마·작은 화면·오류·복귀를 확인한다. 견본 검증, 실제 제품 적용, 실물 수용은 서로 다른 근거다. 외부 참고 패턴은 Carbon의 목록 도구, PatternFly의 primary-detail/empty state, Fluent의 field/drawer, WAI-ARIA APG의 키보드 동작이다. 색·모션·정지 계약은 ROSY의 기존 ADR이 우선한다.

### 독립 작업의 선택 — `createTaskChooser()`

상세는 [ui-design-details.md](docs/reference/ui-design-details.md)의 「독립 작업의 선택 — `createTaskChooser()`」로 옮겼다.

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
- 모양은 노선이다([D-975](docs/adr/D-975-line-map-stage-track-and-app-lines.md)): 단계는 번호 역(`--size-stage-mark` 원, 순번 `--mono`)이고 역 사이를 `--size-stage-line` 굵기의 선이 잇는다. 단계는 같은 폭을 나눠 쓰고 라벨은 어절에서 줄바꿈한다. 30rem 미만에서는 세로 노선으로 접는다.
- 노선 색은 `data-line="learning|fleet|robot"`이 고른다(`--app-line-*`, 없으면 중립 `--border-strong`). 앱 정체성이지 상태가 아니며 지난 역의 테와 지난 구간에만 칠한다. 남은 구간은 `--border-default`다. 노선 팔레트는 단계 스트립 밖에서 쓰지 않는다(`test_palette_gates.py`).
- 상태는 `ui-tag`와 같은 어휘다. `done`은 지난 단계(노선 색 테), `now`는 지금(가장 밝은 중립 글자와 그 잉크로 채운 표식, 바깥에 노선 색 고리 — 정상은 색이 아니다, D-82), `blocked`는 주의 글자·테(`--status-warn`), `todo`는 남은 단계(중립 테). `data-state`가 없으면 `todo`다.
- 지금 단계의 뜻은 색 하나가 아니라 `aria-current`, 순번, 채움 셋이 함께 나른다.
- 규칙은 `/common/stage-strip.css`에 산다 — `components.css`는 D-766 한도(942줄)에서 동결됐으므로 쓰는 화면은 `components.css` 뒤에 이 시트를 링크한다.

### 아이콘 — `class="ui-icon"`
- 24 viewBox · 실선 2 · `currentColor`. 크기는 `--text-value` 박스 토큰이 정하고(D-405), 식별은 라벨이 나르며 아이콘은 보조다.

### 배치 묶음
- **`ui-actions`**: 버튼 줄. 줄바꿈하고, 좁은 칸에서 한 열로 늘어난다.
- **`.ui-form` / `.ui-field-label`**: 네이티브 폼의 필드 묶음. 좁은 칸에서 한 열.
- **`.ui-readout`**: `dl` 이름–값 두 열. 값은 등폭. 좁은 칸에서 한 열.
- **`.ui-readout[data-form="strip"]`** (`/common/readout-strip.css`): 화면 머리의 핵심 수치 띠. 항목은 `<div><dt>이름</dt><dd>값</dd><dd data-note>근거</dd></div>`. 한 상자를 1px 선으로 나누고 아이콘·색 면을 쓰지 않는다. 값이 주의일 때만 상태색. 좁은 칸에서 두 열. 수치는 서버가 준 값만 — 화면이 셈을 지어내지 않는다.
- **`.ui-readback`**: 쓰기 뒤 되읽기 결과 묶음.

### 조합 어휘
표면마다 다른 이름으로 다시 만들던 묶음을 한 이름으로 부른다. 새 부품이나 화면별 사본을 만들기 전에 이 표를 먼저 본다. 표에 없는 묶음이 두 표면에 필요해지면 구현을 옮긴 뒤 이 표에 한 줄을 더한다. 이름은 `test_content_vocabulary.py`가 지킨다. 화면 머리 두 줄(절차 단계·수치 띠)과 세 칸 틀 줄의 "지금 쓰는 곳"은 HTML 경로이고, 같은 시험이 실제로 그 부품을 쓰는 페이지와 대조한다. 값은 서버 응답만 보이고 노선·띠 모듈은 쓰기 요청을 보내지 않는다([D-978](docs/adr/D-978-screen-heads-show-server-answers-and-one-composition-table.md)).

| 개념 | 정본 이름 | 지금 쓰는 곳 |
| --- | --- | --- |
| 측정 행(이름–값) | `.ui-readout` · `.ui-readback` | 로봇 카드, Fleet 상세, 견본 |
| 작업 목록 행 | `.ui-task-row` · `taskRow()` | 로봇 작업, Fleet 작업 선택 |
| 절차 단계 | `.ui-stage-track` · `.ui-stage` | `applications/fleet/web/installation/install.html` · `applications/fleet/web/cell/cell.html` · `middleware/robot_ui/robot/styleguide.html` · `learning/curation/perception/review_app_web/learning.html` · `learning/curation/perception/review_app_web/index.html` · `learning/curation/perception/review_app_web/pixels.html` · `learning/curation/perception/review_app_web/omx.html` · `learning/curation/perception/review_app_web/vlm.html` |
| 화면 머리 수치 띠 | `.ui-readout[data-form="strip"]` | `shared/web/component-gallery.html` · `applications/fleet/web/accounts.html` · `applications/fleet/web/index.html` · `applications/fleet/web/robot/roster.js` · `applications/fleet/web/robot/roster-cards.js` · `applications/fleet/web/work/policy.html` · `applications/fleet/web/cell/cell.html` · `middleware/robot_ui/robot/styleguide.html` · `middleware/robot_ui/robot/panels/host/system.js` · `middleware/robot_ui/robot/panels/console/overview.js` · `applications/monitoring/web/index.html` · `learning/curation/perception/review_app_web/index.html` · `learning/curation/perception/review_app_web/pixels.html` · `operations/apps/games/games/web/index.html` |
| 증거 블록 | `<ui-evidence>` · `<ui-empty>` | 로봇 카드, Fleet 큐 |
| 절차 작업 열 | `--sidebar-track` | 설치·정비, Fleet 작업 선택 |
| 매체 칸 | `.ui-pane[data-pane]` | 로봇 셸, 감지·카메라 |
| 독립 대상·조작 묶음 상자 | `.ui-panel` | 견본(채택 화면은 Fleet 관제부터 옮긴다) |
| 상태 표시(아이콘+톤) | `statusTag()` | 견본, 연결 배너 |
| 세 칸 틀 | `.ui-stage-grid` | `applications/calibration/web/index.html` · `applications/fleet/web/index.html` · `learning/curation/perception/review_app_web/evaluate.html` · `middleware/robot_ui/robot/styleguide.html` · `shared/web/template.html` |
| 선택 묶음·목록·저장소 | `.choice-group` · `.choice-list` · `createChoiceGroup()` · `createChoiceList()` · `createSelection()` | 견본(채택 화면은 표면 슬라이스가 옮긴다) |

### 상단바 — `<ui-topbar>` (D-466)
- 자리는 셋이다. `brand`(장미색 워드마크 + 조용한 부제), `cluster`(화면 전환·상태·조용한 도구), `estop`(오른쪽 끝 비상 정지). cluster 안의 순서는 표면이 정하고, 바깥 자리는 더 만들지 않는다.
- 붙박이, `ground-deep` 바탕, `--topbar-height`. 64rem 미만은 두 줄이다. 첫째 줄은 이름·상태, 둘째 줄은 화면 전환, 비상 정지는 두 줄을 차지한다. 30rem 미만은 그 두 줄에서 여백과 부제만 줄인다.
- Fleet은 맥락 / 연결 / 알림·나 / 정지 네 영역의 한 줄 앱 바를 쓴다(D-741 3·5항). 높이는 `--appbar-height`에 아래 1px 선을 더한 값이고 320px까지 한 줄이다. 접힘은 셸 칸의 폭에 답한다: 64rem 아래에서 현장 이름과 래치 부제, 48rem 아래에서 시계와 평상 연결 글, 30rem 아래에서 워드마크 글과 계정 단추의 역할 글이 접힌다(역할은 단추의 접근 이름에 남는다). 48rem 아래에서 평상이 아닌 연결 글(`연결 대기`·`지연`·`연결 끊김`)은 앱 바 아래 자기 줄에 선다. 계정·화면 표시·토큰 접속은 계정 단추 아래에 접고, 접속이 필요할 때 저절로 펼친다. 문서 이동은 탐색 레일이 맡고 푸터는 없다.
- 워드마크는 한 줄이다. 칸이 모자라면 표면이 이름 칸에 `container-type: inline-size`를 주고 글자가 칸에 맞게 줄어든다(상한 title).

### 사이드바 — `--sidebar-track` (D-466)
- 절차 작업을 고르는 열이다. 로봇 작업 준비·설치·정비의 작업 레일과 Fleet 설치 작업 선택이 그 열이다.
- 넓은 단(64rem 이상)의 폭은 `--sidebar-track` 하나다. 그 미만에서는 레일을 숨기고 선택 필드를 보여 준다.
- 화면 전환, 입구의 작업 화면 목록, 명렬, 지도, 감지·관측·조작 열은 사이드바가 아니다. 화면 전환은 머리의 cluster이거나, 공용 셸을 쓰는 표면에서는 탐색 레일이다(D-741 6항).

### 공용 패턴 C1–C25와 동적 값 (D1)

정본 목록은 [`shared/web/patterns.yaml`](shared/web/patterns.yaml)(패턴 → 부품 → 게이트)이고 게이트 시험이 읽는다. 같은 필요가 두 화면에 나오면 화면별 해결 대신 이 부품을 쓴다.

| # | 필요 | 규칙 |
|---|---|---|
| C1 | 비활성 사유 | 묶음(둘 이상·버튼 아닌 컨트롤)은 `createCauseLine`(`cause-line.js`)이 보이는 원인 줄 하나를 두고 `disabled`가 바뀔 때마다 `aria-describedby`를 맞추며 비면 숨긴다. 단독 버튼은 `<ui-button reason>`, 둘 다 `describeBy`를 쓴다 |
| C2 | busy 잠금 | 구역 잠금은 `createBusyScope(root)`(`busy-scope.js`)만. 잠그기 전 상태 그대로 복원, 정지·`[data-always-live]` 항상 제외, 배경 조회는 `refresh`로 잠그지 않고 사용자 동작을 삼키지 않는다 |
| C3 | 계정 세션 | `createAccountGate`(`account-gate.js`, `gateState`). 상태는 operate·signed-in·view·unavailable. 읽기 실패는 `unavailable`이지 권한 없음이 아니다. 세션이 바뀌어도 정지는 산다 |
| C4 | 모르는·빈·오래된 값 | `valueText`·`renderValue`(`value-text.js`). 없음은 `EVIDENCE_LABEL.unavailable`, 오래되면 시각을 붙인다. 0·100%·정상·undefined로 채우지 않는다. 빈 목록은 `ui-empty` |
| C5 | 동적 기하·색 | `setGeometry`만(아래). 게이트: 실제 CSP 아래 위반 0건 + 계산된 크기 변화 |
| C6 | 위험 표시 | `ui-tag status=crit` / `--flag-danger-*` 채움. 빨간 글자 금지(D-202) |
| C7 | 되돌릴 수 없는 동작 | `confirmIrreversible` + 목록의 POST는 확인 없이 못 보낸다 |
| C8 | 탭 | `createTabs` 하나. `role="tab"` 직접 작성 금지. 옵션: `onChange`·`select`(조용함)·`label`, `beforeChange(next, current)`(동기·비동기 거부권, 대기 중 `aria-busy`), 탭별 `disabled`+`reason`(탭 줄 아래 원인 한 줄, 화살표가 건너뜀), `icon`·`iconOnly`(label이 접근성 이름), `activation: "manual"`(기본)·`"automatic"`(화살표가 곧 활성화) |
| C9 | 정지 | `createStopControl`(`stop-control.js`). 권한·busy·reload·계정 상태와 무관하게 항상 보이고 눌리며 누를 때마다 보낸다. 앱이 역할·세션으로 정지를 끄지 않고 서버 403은 글로 보인다(알려진 예외: Fleet 머리 `#estop`은 아직 권한 없으면 꺼진다, 별도 결정 전까지 이 슬라이스가 바꾸지 않는다). 거절은 글로 말하고 `보냄`은 `멈춤`이 아니다. `accept(response)`로 더 엄격한 증거(예: 본문 `estop === true`)를 요구할 수 있고 못 받으면 실패 글이다 |
| C10 | 연결 배너 | `createConnectionNotice`(`connection-notice.js`). 끊김은 주의(`ui-tag status=warn` + `wifi` 아이콘 + 글). 호출자가 실제 운용 위험을 알 때만 `set(state, text, {danger: true})`로 위험 채움. 인증 대기·모름은 차분한 글(2026-11-14, 예전 D2 대체) |
| C11 | 독립 대상·조작 상자 | `.ui-panel[data-surface=flat\|raised][data-density=standard\|compact]`(`component-controls.css`). 테 하나, 읽는 순서 제목·`ui-tag`·핵심 값(tnum)·근거 줄·행동(주 하나+보조 하나). `compact`는 64rem 이상 마우스 면만(D-976). 반복 행·수치는 상자가 아니라 행·띠. 카드 속 카드·카드 전체 위험 채움 금지 |
| C12 | 상태 표 | `statusTag(state, text?)`(`status-tag.js`). 정상은 아이콘 없이 조용, 지연 `history`·끊김 `wifi`(warn), 모름 `minus`+점선 테, 주의 `warn`, 위험 `safety`/`estop`(tag만 crit 채움), 잠김 `lock`. 모르는 값 문구는 `EVIDENCE_LABEL.unavailable`(정보 없음) 하나 |
| C13 | 아이콘·툴팁·토글팁 | 글리프 93종은 `ui.js` `actionIcon` 한 곳, 범주(`ICON_CATALOG`: nav·action·object·status·measure)와 한국어 이름을 곁에 둔다. 글자를 대신하지 않는다. 아이콘만 있는 단추는 접근성 이름+`data-ui-tooltip`(`title` 금지)이 필수이고 내비·정지·삭제·해제는 아이콘만 쓰지 않는다. 툴팁은 이름(1~4음절)이나 용어 정의(두 문장 이하)만, 판단 정보는 늘 보이는 근거 줄에. 터치는 `toggletip`. 규칙 1~18은 [콘셉트 문서](../docs/superpowers/plans/2026-11-14-rosy-ui-concept.md)의 「깊이·아이콘·글자 규칙」, 게이트는 `shared/web/test/test_icon_gates.py`(예외 목록은 줄이기만) |
| C14 | 반복 로봇 행(로봇암·이동로봇) | `createRobotRow`·`createRobotRoster`(`robot-row.js`)가 `robotProfile`(`robot-profile.js`, 순수)을 그린다. 반복 대상은 행이다(상자·카드 없음). 칸은 이름(종류·ID)·연결·전원(배터리 %·충전 / 토크·서보 전류·온도)·작업·위치·경보·행동으로 두 종류가 같고, 묶음 제목은 `로봇암 (N)`·`이동로봇 (N)`. 연결(신선도: 지연·끊김·정보 없음)과 경보(심각도: 주의·위험)는 다른 칸이고, 정상은 표시가 없다. 모르는 값은 `valueText`(정보 없음)이지 상수가 아니다. 보조 글은 `toggletip`. |
| C15 | 로봇 3D 보기(로봇암·이동로봇) | `createRobotView`(`robot-3d.js`, 순수부 `robot-3d-model.js`)가 로봇 저장소의 모델(`tools/robot_meshes.py`가 만든 `meshes/`, 예산 400 KB)을 같은 방식으로 그린다. three.js(`vendor/`, r183.2 MIT)는 첫 뷰에서 동적 import한다(없는 화면은 안 받는다). 그림은 상태가 바뀔 때(자세·선택·크기·테마·돌리기)만 그리고 반복 루프·보간이 없다(D-220). 선택 = 바닥 고리 + 윤곽 + 틀을 `--focus-ring` 한 색으로(행의 선택 표시와 같은 색), 선택 안 됨은 강조색 없음. 색은 그릴 때 CSS 토큰에서 읽고 크기는 CSS(`el.style` 금지). 캔버스는 `role=img`이고 같은 사실(종류·이름·선택·관절/자세·지연)을 곁 글로 둔다. 방향키 회전·+/- 확대·Home과 시점 단추가 키보드 대안이다. WebGL이 없으면 글만 남는다. 한 화면 6개 이하, 목록 행마다 두지 않는다. 새 부품은 `tools/robot_meshes.py`를 거치고, 지연·끊김은 바랜 색으로 그린다 |
| C16 | 단일 선택 목록 | `createChoiceList`(`choice-list.js`): 사진·프레임·AI 후보·승격 후보·클래스 전체처럼 행 안 동작이 없는 선택. `role=listbox`+`option aria-selected`, option 안에 단추·링크·입력 금지(APG), 위·아래·Home·End·글자 찾기, 선택은 Enter·Space(포커스는 선택이 아니다), 갱신 때 포커스·선택 유지, 빈 목록은 `ui-empty`. 항목 `status`는 상태 이름 문자열이거나 `{state, text, icon}`이라 항목이 자기 문구·아이콘을 `statusTag`로 낸다. 행에 동작이 있으면(로봇·작업) listbox가 아니라 행 목록 + `선택` 단추(`aria-pressed`) + `li[data-selected]`(C14). `role="option"`은 이 부품만 쓴다. |
| C17 | 선택 묶음 | `createChoiceGroup`(`choice-group.js`): `mode=single`은 네이티브 radio(fieldset+legend; 중간 값·모름·허용 안 됨처럼 "값 없음"이 상태면 `allowEmpty`, 사용자는 고르기만 하고 비우기는 화면이 `set(null)`로), 폼 밖 배타 2~5개(속도 단계·표시 방식·도구, 단축키 1~9에 묶인 클래스 칩만 ≤9). `mode=toggle`은 `kind=toggle`+`aria-pressed`, 즉시 효과 ≤8(지도 겹·필터), `master`(전체, `aria-pressed="mixed"`)·`max`+사유 선택. `mode=check`는 `label.ui-check`+checkbox, 폼 값·8개 초과. 글자만 있는 6개 이상 단일은 네이티브 select(사용자가 늘리는 16개 이상이면 `createSearchSelect`). 배타를 `aria-pressed`로 흉내 내지 않는다. 테마 선택(#71)은 문서화된 K1 예외다. `setItems`는 그릴 필드가 같으면 아무것도 다시 짓지 않고(폴링 호출자가 자기 변경 검사를 두지 않는다) 바뀌면 포커스를 지킨다. 라디오는 칩 전체를 덮는 투명 입력이라 시험도 `get_by_role("radio").check()`로 바로 누른다(라벨을 누르는 우회 없음). 30rem 미만에서는 미선택 칩의 체크 자리를 돌려준다(선택 칩은 줄·굵게·체크 유지). 손으로 쓴 칩 줄은 `test_choice_controls.py` 목록으로 줄이기만 한다. |
| C18 | 공유 선택·선택 표지 | `createSelection()`(`selection.js`, `{get,set(id,{source}),subscribe}`): 한 선택을 읽는 모든 보기(지도 표지·행 목록·상세·검사기·3D 보기 `createRobotView({selection, robotId})`)가 구독하고, window 이벤트·화면별 사본은 두지 않는다. 한 값에 고르개는 한 뷰포트에 하나(좁은 폭은 select, 넓은 폭은 행 목록). 표지는 어디서나 같다: `--selection`(= `--series-secondary`, D-1030) 굵은 inline-start 줄(`--space-1`) + 체크 아이콘 또는 `선택됨` 글자. 색만으로 알리지 않고 행 전체를 칠하지 않으며 `--focus-ring`과 다르다. 선택 속성은 종류별 하나: listbox `aria-selected`, 행·지도 표지 `li[data-selected]`(모양)+선택 단추 `aria-pressed`(의미), 독립 켜기·끄기 `aria-pressed`, 배타 단일 radio. `choice-controls.css`를 `component-controls.css` 뒤에 링크한다. |
| C19 | 위치 상태 하나 | `localizationState(view)`(`localization-state.js`, 순수): 8상태(`confirming > rotating > candidates > searching > localized(+suspect) > failed > blocked > unknown`)와 거절 문구(`refusalText`)·대기 큐(`queueStep`)·후보 확정 검증(`confirmRequest`)을 한 곳에서 계산한다. 신선도(`fresh\|delayed\|unknown`, 30초 기준)와 심각도(`neutral\|warn`)를 분리하고 `danger`는 절대 쓰지 않는다. 후보는 확정 전 후보(점선 윤곽 + `후보 · 확정 전` + 신뢰도)로만 그리며 `localized`에서는 비운다. `위치 다시 찾기`(relocalize)와 후보 확정은 기명 운영자만 보고 자동 재시도는 없다. 출발 대기는 위치 거절(`TRIP_POSE_UNTRUSTED`·`SITE_POSE_UNKNOWN`)에서만 기다리고 120초로 제한한다. |
| C20 | 팔 스킬 상태 | `skillState({lifecycle, executor, policyId, version, step, guard, measured, ageS, leaseS, blocking})`(`skill-state.js`, 순수)가 `{text, tag, readout}`를 낸다. 수명주기 9종: 승인 대기(제안됨·대기 같은 행)·승인됨 · 시작 대기·실행 중 n/N·측정 성공·측정 실패·정지 · HOLD·시간 초과 · HOLD·대체 제안됨 · 승인 필요. 정상 진행에는 태그가 없고 주의(`caution`)는 로봇을 막는 승인 대기·측정 실패·시간 초과·대체 제안, 위험은 정지(E-stop `estop`, owner HOLD `safety`)와 부하 든 채 또는 잠금(lock) 상태의 실패뿐. 원인 줄(C1) 조합은 패널(Fleet) 소유. 대체는 제자리 교체가 아니라 새 제안이며 새 승인이 필요하다. 측정 출처 없는 성공과 모르는 값은 `정보 없음`. 로봇 행 글자와 상세 패널이 같은 표를 쓰고 `fresh`는 신선도지 수명주기가 아니다 |
| C21 | 근거 줄 | `createEvidenceLine(items)`(`evidence-line.js`): 항목마다 출처를 글자로 나눈다. 원장·측정이 앞, `모델 자체 값 ... (측정 아님)`이 뒤, 출처가 없으면 `출처 정보 없음`이며 모델 값이 측정처럼 보이면 안 된다. 낡음(`staleAfterS` 초과)은 `지연 · N초 전` 태그, 값 없음은 `정보 없음` 태그, 정상은 태그 없음. 신선도와 심각도는 다른 축 |
| C22 | 샘플 데이터 | 실제가 아닌 행은 `sample: true`를 싣고 화면 영역 머리에 `sampleTag()`(`샘플 데이터`, `sample-data.js`)를 둔다. 후보는 `{id, label, reason}`뿐이고 좌표·관절·실행기 선택 필드를 갖지 않는다(`armAiCaseProblems`가 검사). 제안자는 자기 제안을 승인하지 못한다(AI·Assistant 제안 포함): 거절 견본을 둔다. 3D는 상태 줄 글자(`skill`)만 늘리고 제안됐지만 실행되지 않은 목표는 그리지 않는다 |
| C23 | 로봇 도크 | `createRobotDock({selection, profiles, onToggle, kinds})`(`robot-dock.js`, 순수부 `robot-dock-model.js`). 로봇 한 대 = 아이콘+짧은 id(42·45 / S·A·B) 단추 하나, 이동로봇 / 구분 / 로봇암 순. 지연(`history`)·끊김(`wifi`)·경보(`warn`·`estop`) 표지는 **정상이 아닐 때만** 모서리에 붙고 정상은 맨 아이콘이다. 단추는 `aria-pressed`(패널이 이 로봇을 연 동안), 선택 표지는 `--selection` 줄(한 `createSelection`, 지도·패널과 같은 값). 64rem 이상 오른쪽 56 px 세로 띠, 미만 지도 머리 아래 가로 한 줄(목표 44 px, 글자 id 유지). 도크는 우측 열의 로봇 행 목록(고르개)을 L1에서 대체하고, 행 목록(C14)은 작업 화면 단위 목록으로 내린다(S2 한 값 한 고르개). 금지: 도크 아이콘만으로 위험 동사 실행, 지도 클릭·행 선택으로 패널 열기(열기는 도크 아이콘만), 도크와 별개로 같은 선택을 가진 두 번째 고르개 |
| C24 | 로봇 패널 | `createRobotPanel({selection, onClose, sections, stop, resolve})`(`robot-panel.js`). 껍데기만 공용이다: 머리(이름·신선도 태그·닫기), 상태, 카메라, 명령, 설정(읽기 전용, 접히는 것은 이것뿐), 하단 고정 정지 줄. 구획 내용은 화면이 주입한다(어댑터). 64rem 이상 스테이지 그리드 왼쪽에 `minmax(18rem, 22rem)` 열을 더하는 밀기(덮지 않음, 비모달), 미만 **머리 아래** 전체 화면 시트(머리의 전체 비상 정지를 덮지 않는다). 열면 포커스는 제목(`tabindex=-1`), 같은 아이콘·닫기·Esc로 닫고 연 아이콘으로 돌아간다. 패널이 열려 있을 때만 선택을 따라가고 닫힌 채 선택이 바뀌어도 열지 않는다. 한 번에 패널 하나. 정지: 이동로봇은 `주행 취소 · 이 로봇`(상시 활성, `data-always-live`), 팔은 단추 없이 `팔 단독 정지 없음 · 위 머리의 전체 비상 정지를 쓴다` 한 줄. 금지: 패널·도크 모듈과 채택 어댑터의 `/api/fleet/pipeline/` 감독 우회 경로 호출(`pipeline/decision-gate`·`human-safety-gate`·`vision-auto-check`·`station-zones/dispatch`·`arm-holds/clear`; `patterns.yaml`의 `forbid`가 소스를 읽어 막는다), 토크·전원·가드·홀드 해제 단추(T4는 사람), 패널 안 승인(승인은 작업 큐 한 곳) |
| C25 | 알림 한 표면 | `createAlertCenter({listEl, toastEl, bellEl, announcer, isOnScreen})`(`alert-center.js`, 규칙은 순수부 `createAlertStore`)와 `getAnnouncer()`(`announcer.js`). 같은 key는 한 항목(×N), 일회성 실패는 1500 ms 병합, 목록 상한 12. 토스트는 목록이 화면 밖일 때 새 safety·crit와 목록에 없는 일회성 실패 둘뿐이고 warn·info는 토스트 없음. `resolve(key)`가 항목·토스트·벨 개수를 한 번에 닫고 safety는 `acknowledge` 전에는 안 닫는다. 방송은 페이지당 polite 1·assertive 1(announcer)이 하고 토스트 영역엔 aria-live가 없다. 벨 개수는 그 앱 목록의 미해결 항목 수 하나다(Fleet은 큐의 긴급·주의 행). 읽음·미읽음을 더하지 않고 누르면 목록으로 간다. 「알림」 이름과 아이콘은 목록 하나에만 쓴다. 이행 예외(`patterns.yaml` C25 debt): Fleet 카드는 `createAlertStore`만 쓰고 Robot 대시보드 `#triage`·`#hitl-escalation`은 손으로 그린다. 앱은 알림 배너·토스트·live 영역을 새로 만들지 않는다(정적 게이트 `alert-surface.test.mjs`, 이행 목록 A1-A4) |

패턴이 만들어졌는지(`planned`·`built`)는 [`shared/web/patterns.yaml`](shared/web/patterns.yaml)만 말한다. 이 표의 C행에는 상태 낱말을 적지 않고, `test_patterns_registry.py`가 지킨다.

동적 값(D1): 스크립트의 `el.style`·`style` 속성은 금지이고 예외는 [`geometry.js`](shared/web/geometry.js)의 `setGeometry(el, {…})` 하나다. `--g-*` 사용자 속성만 쓰며 이름 허용 목록과 값(유한 숫자+단위·`var(--토큰)`·`color`의 `#hex`)을 검사하고, CSS는 `var(--g-…, 기본값)`으로 읽는다. 그림은 SVG 속성·canvas, 이산 값은 `data-*` 선택자다. typed `attr()`와 `<table width>` 우회는 이행하면서 지운다(`test_no_element_style.py`가 목록으로 추적). 이행 부채: 진단 화면 `diagnostic-core.js`·`diagnostic-map.js`는 classic 스크립트라 아직 `.style`을 쓰며 `patterns.yaml` C5 `debt`에 이유와 함께 적혀 있다.

### 비상 정지
- `ui-button kind="irreversible"`. 로봇 셸 `#shell-estop`, Fleet `#estop`(팔각 아이콘과 보이는 동사 비상 정지. 넓은 머리의 래치 부제는 "래치 · 로봇별 관리자 해제". 명령은 [D-421](docs/adr/D-421-fleet-cancel-all-driving-separate-from-latched-estop.md)의 래치형 전체 비상 정지). 동사는 줄바꿈하지 않고, 모든 폭에서 첫 화면에 있다.
- 래치 없는 Fleet **전체 주행 취소**(`#cancel-all`)는 비상 정지가 아니다. 상단바가 아니라 발행 상태 줄에 `quiet`로 선다(위험 채움은 비상 정지 하나). 로봇 카드 `운행 취소`와 큐 펼침 `중단`도 `quiet`이고, 멈추는 동작이라 확인 없이 바로 나간다([D-540](docs/adr/D-540-fleet-console-structure-v2.md) 6항).

### 테마 선택
- K1 예외: 정본 패턴이 `kind="segment"`+`aria-pressed`이므로 C17 `mode=single`으로 옮기지 않는다(채택 화면이 이미 `theme.js`에 묶여 있다). 새 선택 묶음에는 이 예외를 복사하지 않는다.
- K20 현재 값 표지: `aria-current="true"`+비활성 `ui-button`은 흐리지 않고(`opacity: 1`) 굵은 글자(`--weight-strong`)와 아래 밑줄(`--selection-edge`, `--text-primary`)로 로봇이 보고한 현재 값을 보인다. 선택 가장자리(`--selection`)·포커스 링과 겹치지 않으며 색에만 기대지 않는다.
- `role="group"` 안에 `RosyTheme.choices` 하나마다 `ui-button kind="segment" data-theme-choice="값"`(지금은 어둡게·밝게·시스템). `theme.js`가 누름을 받아 `aria-pressed`를 맞춘다. 로봇은 `/device` 화면 설정 패널이다. Fleet은 이 묶음 대신 헤더의 순환 버튼 하나를 쓴다(D-668).

## 화면 콘셉트 (2026-11-14)

ROSY는 근거가 붙은 운용 기록의 관제반이다. ① 정상은 조용하다(색·아이콘은 임계·예외·근거 없음에만) ② 한 화면, 한 질문, 한 주역 ③ 신선도와 심각도는 다른 축이고 모르는 값은 정상으로 그리지 않는다 ④ 같은 것은 같은 부품(상자는 `ui-section`·`.ui-panel`·`.ui-pane`·`ui-state-panel` 넷뿐, 반복 대상은 행) ⑤ 아이콘은 글자를 대신하지 않는다. 상세·상태 표·화면별 주역은 [ui-design-details.md](docs/reference/ui-design-details.md)의 「화면 콘셉트」와 계획 [2026-11-14-rosy-ui-concept.md](../docs/superpowers/plans/2026-11-14-rosy-ui-concept.md)를 본다.

## 작업 화면의 기본 원칙 (D-461)

상세는 [ui-design-details.md](docs/reference/ui-design-details.md)의 「작업 화면의 기본 원칙 (D-461)」로 옮겼다.

## 운용자 말 (Copy)

- **운용자가 읽는 글은 한국어 평문이다.** 용어는 [`CONCEPTS.md`](CONCEPTS.md)를 따른다: 실행 모드(profile 아님), 기능·도킹 기능(capability 아님), 하드웨어 실행 모드, 내비게이션, 호스트 에이전트. `test_operator_copy.py`가 대시보드·Fleet·games의 한글 문자열에서 `profile|capability|hardware 모드|Navigation|프로필`과 맨 열거값(`IDLE`·`MANUAL`·`RUNNING`·`HOLDING`·`UNDOCKED`·`WAITING`·`STALE` 등)을 막는다.
- **열거값은 `title`에만 둔다.** 보이는 글은 공용 표의 한국어이고 원래 값은 `title`·`data-*`에 남는다. 공용 표는 [`core_ui_logic.js`](shared/web/core_ui_logic.js)의 `MODE_LABEL`(대기·수동·내비게이션·도킹·비상 정지), `NAVIGATION_LABEL`, `DOCK_STATE_LABEL`과 `enumLabel()`이다 — 로봇 대시보드와 Fleet이 `/common/`에서 같은 파일을 싣는다. 모르는 값은 받은 그대로 보인다.
- **증거 어휘도 공용 표다.** 네 상태의 한국어(최신·지연·연결 끊김·정보 없음)와 나이 뒤처리(` · N초 전`)는 [`core_ui_logic.js`](shared/web/core_ui_logic.js)의 `EVIDENCE_LABEL`·`evidenceAgeText()`가 단일 출처다(D-398). 주어를 앞에 붙인 문장(`릴레이 끊김`·`위치 지연`)은 이 표를 참조해 조립한다.
- **증거가 있는 값은 증거와 함께 말한다.** 지연은 `지연 · N초 전`, 끊김은 `연결 끊김`, 모름은 `정보 없음`이고 `data-evidence`를 단다. 카드에 홀로 붙는 알약은 무엇의 증거인지 말한다(`릴레이 끊김`).
- **사람에게 실측을 부탁하는 요청의 이름은 모든 앱에서 `보정 요청` 하나다**(2026-11-15 사용자 결정). `실측 요청`·`설치·보정`·`실측 교정`은 은퇴했다. `보정 중`은 요청이 진행 중이라는 상태에만 쓰고 요청의 이름으로 쓰지 않는다. `카메라 설치·보정`·`카메라 보정`은 다른 일이라 그대로다. `test_operator_copy.py`의 `test_calibration_request_has_one_name`이 은퇴한 이름을 막는다.
- **로봇 대시보드 안전 칸도 한국어다**(정지·정상·하드웨어 꺼짐 등). 영어를 유지하는 곳은 로봇 얼굴 LCD뿐이다(2026-11-06 결정).
- **한 원인은 한 번 말한다.** 같은 원인이 여러 버튼을 막으면 원인과 다음 할 일은 묶음 상태 한 줄에 두고, 버튼 사유는 짧은 `위 사유`로 `aria-describedby`가 그 줄을 가리킨다.
- **빈 목록·읽기 실패는 `ui-empty`다.** 목록 밖 한 줄로 두고(목록은 숨김), 지도 같은 무대에서는 무대 위에 얹고 다시 시도를 곁에 둔다.

## 픽셀 검수 화면 (Operate)

`learning/curation/perception/review_app_web/pixels.html`을 바꿀 때는 사진 확인 → 필요한 영역 표시 → 완료의 순서로 배치한다. 이 절이 픽셀 검수 화면 배치의 정본이다.

- 사진 바로 위 한 줄에 이전 사진·현재 사진 순번과 제목·다음 사진을 둔다. 순번은 현재 자료 범위와 필터에서의 순서이며, 저장된 사진 ID와 URL은 바꾸지 않는다. 60장 단위 이전·범위·다음은 별도 「사진 목록」 안에서 썸네일과 함께 둔다.
- 64rem 이상에서는 왼쪽 약 13rem 편집 도구·가운데 사진·오른쪽 약 18rem 완료/AI 영역의 세 열을 쓴다. 상단에는 압축된 작업 범위와 사진 이동만 두며, 도구 전체를 사진 위에 펼치지 않는다. 1440×900·2048×1080 첫 화면에서 사진 위쪽은 260px 이내, 표시 높이는 400px 이상이어야 한다. 태블릿은 편집 도구와 사진을 나란히 두고 결정 영역을 아래로 옮긴다.
- 왼쪽은 점·브러시·영역, 선택 클래스, 적용·취소·되돌리기, 세부 허용치 순서로 묶는다. 사진 보기·확대·마스크 표시 설정은 사진 곁에 둔다. 오른쪽은 완료를 먼저 보여주고, 별도 채우기와 AI 후보 비교·보완을 이어 둔다. AI 후보 보기·적용은 찾을 수 있는 이름으로 드러내고 긴 기준·원본 정보·과거 이력은 접는다.
- 사진 아래에는 미검수 수와 보기 설정을 먼저 둔다. 저장 결과·클래스 집계는 「검수 정보와 클래스 집계」, 기존 라벨까지 바꾸는 전체 채우기는 별도 이름의 접힘 안에 둔다. 현재 선택 클래스와 미검수만 채우는 조작은 편집·완료 영역에서 유지한다. 사진 목록은 제목·현재 범위·페이지 이동을 함께 묶고, 학습 자료 준비는 한 사진의 완료와 구분하는 별도 구획으로 둔다.
- 객체 검수의 작업 범위 선택은 사진이 준비되면 사진 제목 줄에 두고, 불러오기·빈 자료 상태에는 작업 영역 앞에 둔다. 같은 조작을 이동하며 선택값과 이벤트를 유지한다. 작업자·검수 이력은 결정 영역에서 확인한다.
- 40rem 미만에서는 범위·사진 이동 → 사진 → 핵심 편집 도구·선택 클래스 → 완료 순서로 읽힌다. 세부 브러시·허용치만 접을 수 있으며 사진을 전체 도구보다 먼저 보여준다. 도구는 자체 스크롤이나 잘림으로 숨기지 않는다. 확대된 사진의 이동 영역과 가로 썸네일 목록만 내부 스크롤을 허용한다. 화면 폭이 바뀌어도 포커스와 편집 상태를 유지하고, 포커스를 받은 조작은 페이지 스크롤로 보이게 한다.
- 사람의 명시적인 「완료」 한 번이 남은 미검수의 배경 채우기·저장·전체 사진과 배경 확인 기록·승인·다음 대기 사진 열기를 이어간다. 채우기 성공의 새 버전으로만 승인을 요청한다. 채우기 실패 시 승인을 보내지 않고, 승인 실패 시 저장된 결과는 대기로 남긴다. 전체가 미검수인 사진은 중요한 영역을 먼저 표시하거나 별도 배경 채우기를 실행해야 완료할 수 있다.
- 별도 전체 확인·배경 확인 체크박스를 만들지 않는다. 완료 버튼 설명이 확인 범위를 밝힌다. 별도 채우기 버튼과 AI 후보 완료는 승인하지 않으며, 기존 라벨 보호·되돌리기·버전 충돌·권한·기하 검사와 평가 전용 가림 확인은 유지한다.
- 390·800·1440·2048px에서 사진 이동 묶음, 목록 페이지 이동, 도구 전체, 결정 버튼, 키보드 포커스와 가로 넘침을 실제 Chromium으로 확인한다. 자동 시험은 `test/learning/perception/test_pixel_review_browser.py`가 맡고, 화면 캡처를 함께 남긴다.

배치 참고는 [CVAT의 annotation editor](https://docs.cvat.ai/docs/annotation/annotation-editor/)가 구분하는 탐색·작업 영역·도구·보조 정보의 역할이다. 해당 제품의 스타일이나 기능을 복사하지 않고 ROSY 토큰과 기존 `ui-*` 조작을 유지한다. 첫 화면의 사진 가시성과 세 열 배치는 `test/learning/perception/test_pixel_workspace_browser.py`로 확인한다.

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

상세는 [ui-design-details.md](docs/reference/ui-design-details.md)의 「Fleet 공용 헤더 영역 (D-658)」로 옮겼다.

