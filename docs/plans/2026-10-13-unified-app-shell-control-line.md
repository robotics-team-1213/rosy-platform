# 통합 셸 · 조작 테두리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 단추와 입력 필드의 테두리를 `--control-line` 역할로 옮기고, 그 값이 두 테마의 다섯 바탕 위에서 3:1을 넘게 한다. 이 계획은 [통합 셸 계획](2026-10-13-unified-app-shell.md)의 조각 3이다.

**Architecture:** `--control-line`은 잉크에 알파만 준 파생 토큰이다. 파생 층은 테마마다 따로 정할 수 없고 팔레트 블록만 테마마다 바뀐다(D-359 §1). 그래서 잉크 백분율 하나가 두 테마를 다 넘어야 한다. 그 값은 잉크 50%다. `--line-40`을 `--line-50`으로 바꾸고 `--control-line`이 그것을 가리킨다. 조작의 경계만 바꾼다: 공용 `ui-button`, `ui-button[kind="quiet"]`·`a.docs-link`, `.ui-disclosure-row`, 그리고 `--field-line`. 면을 가르는 `--border-default`·`--surface-line`·`--flag-line`은 그대로다.

잉크 50%를 불투명한 면 위에 얹은 색과 그 면의 대비(sRGB source-over, WCAG 상대 휘도):

| 바탕 | 어둡게 | 밝게 |
|---|---|---|
| `--ground` | 4.75:1 | 3.25:1 |
| `--ground-deep` | 4.76:1 | 3.31:1 |
| `--ground-raise` | 4.63:1 | 3.18:1 |
| `--ground-soft` | 4.55:1 | 3.15:1 |
| `--ground-card` | 4.20:1 | 3.11:1 |

잉크 49%도 다섯 바탕을 넘지만 밝게 `--ground-card`에서 3.02:1이라 여유가 없다. 잉크 40%는 밝게에서 2.38–2.48:1이다. 관문 밖인 `--ground-card-2`는 50%에서 어둡게 3.84:1, 밝게 3.00:1이다.

**Tech Stack:** 순수 CSS, 번들러 없음. 관문 시험은 pytest(소스 읽기)이고 색 계산은 `shared/web/test/test_palette_gates.py`의 `contrast`·`resolve`를 그대로 쓴다. 시험은 노트북에서 돌리지 않고 `tools/remote/remote_pytest.py`로 돌린다. 원격 러너는 커밋한 HEAD만 보내므로 시험을 돌리기 전에 커밋한다. 러너는 호출마다 `run-1.txt`부터 다시 쓰므로, 단계마다 로그를 이름 붙인 파일로 복사한 뒤 `test/known_failures.py`에 넘긴다.

**읽고 시작할 것:** `rosy-platform/AGENTS.md`의 「같이 하는 깃」, `shared/web/AGENTS.md`, [D-741](../adr/D-741-unified-app-shell-seats.md) 10항, D-359 §1, `DESIGN.md`의 필수 색상 법칙(D-624).

---

### Task 0: 작업 위치

- [ ] **Step 1: 워크트리와 브랜치를 만든다**

```bash
cd F:/Dev/Control/Robot/Rosy/rosy-platform
git status --short --branch
git worktree list
git worktree add --relative-paths .worktrees/control-line -b uiux/control-line-contrast main
cd .worktrees/control-line
git branch --show-current
grep -n "control-line\|line-40" shared/web/tokens.css
```

Expected: `git branch --show-current`가 `uiux/control-line-contrast`. `grep`이 세 줄을 찍는다: `--line-40: color-mix(in oklab, var(--ink) 40%, transparent);`, D-741 주석 줄, `--control-line: var(--line-40);`. 이 세 줄이 없으면 조각 1(공용 토큰)이 `main`에 없는 것이므로 멈추고 알린다.

---

### Task 1: 대비 관문

**Files:**
- Create: `shared/web/test/test_control_line_contrast.py`

- [ ] **Step 1: 실패하는 관문을 쓴다**

`shared/web/test/test_control_line_contrast.py`:

```python
"""D-741 10 — 조작(단추·입력)의 경계는 두 테마의 다섯 바탕 위에서 3:1을 넘는다.

`--control-line`은 잉크에 알파만 준 파생 토큰이다
(`color-mix(in oklab, var(--ink) N%, transparent)`). 파생 층은 테마마다 따로 정할 수
없으므로(D-359 §1) N 하나가 두 테마를 다 넘어야 한다. 색 공간과 대비 계산은
`test_palette_gates.py`의 것을 그대로 쓴다.

변이 증명: tokens.css의 `--line-50`을 `--line-40`·40%로 되돌리면 밝게 테마 다섯 건이 빨갛다.
"""

import re
from pathlib import Path

import pytest

import token_themes
from test_palette_gates import THEMES, contrast, resolve

WEB = Path(__file__).resolve().parents[1]
DERIVED = token_themes.derived_body(token_themes.read())
SURFACES = ("ground", "ground-deep", "ground-raise", "ground-soft", "ground-card")
MIN_CONTROL_CONTRAST = 3.0  # WCAG 2.2 SC 1.4.11 비텍스트 대비


def _decl(name: str) -> str:
    found = re.search(rf"^\s*{re.escape(name)}\s*:\s*([^;]+);", DERIVED, re.MULTILINE)
    assert found, f"{name} 토큰이 없다"
    return found.group(1).strip()


def control_line_share() -> float:
    alias = re.fullmatch(r"var\((--line-\d+)\)", _decl("--control-line"))
    assert alias, "--control-line은 --line-N 파생 하나를 가리킨다"
    mix = re.fullmatch(r"color-mix\(in oklab, var\(--ink\) ([\d.]+)%, transparent\)", _decl(alias.group(1)))
    assert mix, f"{alias.group(1)}은 잉크 알파 파생이다"
    assert alias.group(1) == f"--line-{mix.group(1)}", "이름의 숫자가 값의 백분율이다"
    return float(mix.group(1))


def over(ink: str, share: float, face: str) -> str:
    """알파 share%의 잉크를 불투명한 면 위에 얹은 색(sRGB source-over). 브라우저가 테두리를 칠하는 방식이다."""
    def channels(colour: str) -> list[int]:
        return [int(colour[i:i + 2], 16) for i in (1, 3, 5)]

    t = share / 100.0
    return "#%02x%02x%02x" % tuple(round(i * t + f * (1 - t)) for i, f in zip(channels(ink), channels(face)))


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("surface", SURFACES)
def test_control_line_reaches_three_to_one(theme, surface):
    palette = resolve(theme)
    ratio = contrast(over(palette["ink"], control_line_share(), palette[surface]), palette[surface])
    assert ratio >= MIN_CONTROL_CONTRAST, f"{theme}/{surface}: {ratio:.2f}:1"


def test_the_gate_is_not_vacuous():
    """잉크 40%는 밝게 테마에서 모자란다. 계산이 늘 통과하는 식이 아님을 고정한다."""
    light = resolve("light")
    assert contrast(over(light["ink"], 40, light["ground"]), light["ground"]) < MIN_CONTROL_CONTRAST
```

- [ ] **Step 2: 커밋하고 원격에서 실패를 확인한다**

```bash
git add shared/web/test/test_control_line_contrast.py
git commit -m "test(web): gate the control line at 3:1 on five grounds in both themes (D-741)"
rm -f X:/DevTemp/control-line/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/control-line -- shared/web/test/test_control_line_contrast.py
cp X:/DevTemp/control-line/run-1.txt X:/DevTemp/control-line/t1-red.txt
```

Expected: `5 failed, 6 passed`. 실패는 전부 `light`이고 문구에 `light/ground: 2.46:1`, `light/ground-card: 2.38:1`이 있다. 어둡게 다섯 건과 `test_the_gate_is_not_vacuous`는 통과한다. 이 단계에서는 `known_failures.py`를 돌리지 않는다(이 다섯 건은 이 브랜치가 일부러 만든 실패다).

---

### Task 2: 토큰 값

**Files:**
- Modify: `shared/web/tokens.css` (`--line-40` 줄, `--control-line` 줄과 그 위 주석)
- Modify: `shared/web/test/test_app_shell_seats.py:34-35`, `shared/web/test/test_design_scope_gates.py:60-61`, `shared/web/test/test_ui_token_contracts.py:319`

- [ ] **Step 1: 파생 토큰의 이름과 값을 바꾼다**

`shared/web/tokens.css`에서:

```css
  --line-40: color-mix(in oklab, var(--ink) 40%, transparent);
```

을

```css
  --line-50: color-mix(in oklab, var(--ink) 50%, transparent);
```

로 바꾼다. 같은 파일에서:

```css
  /* D-741 — 단추와 입력의 경계. 어둡게 테마에서 3:1을 넘는다. 밝게 테마에서는 2.4:1이라 쓰기 전에 값을 다시 정한다. 아직 쓰는 곳이 없다. */
  --control-line: var(--line-40);
```

을

```css
  /* D-741 10 — 단추와 입력의 경계. 잉크 50%는 다섯 바탕(ground, -deep, -raise, -soft, -card) 위에서
     어둡게 4.20–4.76:1, 밝게 3.11–3.31:1이다(test_control_line_contrast.py). 면을 가르는 선에 쓰지 않는다. */
  --control-line: var(--line-50);
```

로 바꾼다.

- [ ] **Step 2: 옛 값을 고정한 시험 세 곳을 같은 커밋에서 고친다**

`shared/web/test/test_app_shell_seats.py`:

```python
    assert _decl("--line-40") == "color-mix(in oklab, var(--ink) 40%, transparent)"
    assert _decl("--control-line") == "var(--line-40)"
```

을

```python
    assert _decl("--line-50") == "color-mix(in oklab, var(--ink) 50%, transparent)"
    assert _decl("--line-40") is None, "잉크 40%는 밝게 테마에서 2.4:1이라 남기지 않는다"
    assert _decl("--control-line") == "var(--line-50)"
```

로 바꾼다.

`shared/web/test/test_design_scope_gates.py`의 `COLOR_ROLES`:

```python
    "border-color": {"--line-10": "--border-subtle", "--line-14": "--border-default",
                     "--line-30": "--border-strong"},
```

을

```python
    "border-color": {"--line-10": "--border-subtle", "--line-14": "--border-default",
                     "--line-30": "--border-strong", "--line-50": "--control-line"},
```

로 바꾼다. 이 표는 표면 시트가 `border-color: var(--line-50)`처럼 파생 이름을 직접 쓰는 것을 막고, `test_semantic_colour_aliases_keep_existing_theme_values`가 `--control-line: var(--line-50)` 별칭을 확인한다.

`shared/web/test/test_ui_token_contracts.py`의 `test_component_token_layer_exists`:

```python
        "--field-bg", "--field-line", "--field-invalid",
```

을

```python
        "--field-bg", "--field-line", "--field-invalid", "--control-line",
```

로 바꾼다.

- [ ] **Step 3: 커밋하고 원격에서 통과를 확인한다**

```bash
git add shared/web/tokens.css shared/web/test/test_app_shell_seats.py shared/web/test/test_design_scope_gates.py shared/web/test/test_ui_token_contracts.py
git diff --cached --name-only
git commit -m "feat(web): set the control line to ink 50% so both themes reach 3:1 (D-741)"
rm -f X:/DevTemp/control-line/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/control-line -- shared/web/test test/architecture
for f in X:/DevTemp/control-line/run-*.txt; do cp "$f" "X:/DevTemp/control-line/t2-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/control-line/t2-$(basename "$f")"; done
```

Expected: `git diff --cached --name-only`가 위 네 경로만 찍는다. `test_control_line_contrast.py` 11 passed. `known_failures.py`가 로그마다 `NEW` 0으로 끝난다. 이 커밋은 화면을 바꾸지 않는다(`--control-line`을 쓰는 규칙이 아직 없다).

같이 봐야 하는 기존 시험과 실패했을 때 할 일:

| 시험 | 실패 문구가 말하는 것 | 할 일 |
|---|---|---|
| `test_app_shell_seats.py::test_control_line_and_chrome_surface_are_roles` | `--line-40`이 아직 있다 | Step 1의 첫 치환이 이름까지 바꿨는지 본다 |
| `test_design_scope_gates.py::test_semantic_colour_aliases_keep_existing_theme_values` | `aliases['--control-line']`이 `--line-50`이 아니다 | Step 1의 둘째 치환을 본다 |
| `test_ui_token_contracts.py`의 토큰 참조 검사 | 어떤 시트가 없는 토큰 `--line-40`을 쓴다 | 그 시트가 이 브랜치 뒤에 `main`에 들어온 것이면 `--control-line`으로 고쳐 같은 커밋에 넣는다 |
| `test_native_token_export.py` | 건너뜀(`ROSY_RUN_NATIVE_TOKEN_TESTS` 없음) | 할 일 없음. 네이티브 내보내기는 `--line-14`와 `--gauge-track`의 알파만 읽는다(`shared/web/native-tokens.gradle:33`) |
| `test_token_parity.py` | 통과 | 할 일 없음. 사본은 팔레트 hex만 비교한다 |

---

### Task 3: 조작에 적용한다

**Files:**
- Modify: `shared/web/tokens.css` (`--field-line`)
- Modify: `shared/web/components.css` (`.ui-disclosure-row`, `ui-button`, `ui-button[kind="quiet"], a.docs-link`)
- Modify: `operations/ui/console/cell/cell.css:8`
- Modify: `operations/ui/cam/app/src/main/java/io/github/livsbittt/rosy/cam/ui/RosyTheme.kt:48` (주석)
- Test: `shared/web/test/test_control_line_contrast.py`

- [ ] **Step 1: 실패하는 시험을 더한다**

`shared/web/test/test_control_line_contrast.py` 끝에 붙인다:

```python
COMPONENTS = (WEB / "components.css").read_text(encoding="utf-8")


def test_controls_take_the_control_line_and_dividers_keep_theirs():
    assert _decl("--field-line") == "var(--control-line)"
    for selector in ("ui-button", 'ui-button[kind="quiet"],\na.docs-link', ".ui-disclosure-row"):
        block = COMPONENTS.split(f"\n{selector} {{", 1)[1].split("}", 1)[0]
        assert "border: 1px solid var(--control-line);" in block, selector
    for divider in ("--surface-line", "--flag-line"):
        assert _decl(divider) == "var(--border-default)", divider
    assert _decl("--border-default") == "var(--line-14)"
```

- [ ] **Step 2: 커밋하고 원격에서 실패를 확인한다**

```bash
git add shared/web/test/test_control_line_contrast.py
git commit -m "test(web): pin which borders are control boundaries (D-741)"
rm -f X:/DevTemp/control-line/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/control-line -- shared/web/test/test_control_line_contrast.py
cp X:/DevTemp/control-line/run-1.txt X:/DevTemp/control-line/t3-red.txt
```

Expected: `1 failed, 11 passed`. 실패 문구에 `assert 'var(--border-default)' == 'var(--control-line)'`.

- [ ] **Step 3: 입력의 경계를 옮긴다**

`shared/web/tokens.css`에서:

```css
  --field-line: var(--border-default);
```

을

```css
  --field-line: var(--control-line);
```

로 바꾼다.

- [ ] **Step 4: 단추와 펼침 행의 경계를 옮긴다**

`shared/web/components.css`에서 아래 세 규칙의 `border` 줄만 바꾼다. 세 곳 모두 지금 값은 `border: 1px solid var(--surface-line);`이고 새 값은 `border: 1px solid var(--control-line);`이다.

`.ui-disclosure-row {` 규칙(27번째 줄 근처):

```css
  background: var(--surface-canvas);
  border: 1px solid var(--control-line);
  border-radius: var(--radius-button);
```

`ui-button {` 규칙(170번째 줄 근처):

```css
  padding: 0 var(--inset-button);
  border: 1px solid var(--control-line);
  border-radius: var(--radius-button);
  color: var(--text-primary);
```

`ui-button[kind="quiet"],` `a.docs-link {` 규칙(194번째 줄 근처):

```css
  padding: 0 var(--inset-button);
  border: 1px solid var(--control-line);
  border-radius: var(--radius-button);
  color: var(--nominal-quiet);
```

같은 파일의 나머지 `var(--surface-line)` 아홉 곳은 그대로 둔다. 그것들은 조작의 경계가 아니다: `ui-button[disabled][reason]`의 점선(할 수 없음), `ui-tag`, `ui-chip`, `ui-evidence[state="unavailable"]`, 확인 창, `ui-topbar` 아래 선, 행 구분선이다. `ui-button[kind="primary"]`, `[kind="irreversible"]`, 눌린 `toggle`·`segment`는 `border-color: transparent`를 이미 갖고 있어 바뀌지 않는다. 줄 수는 그대로 939줄이다.

- [ ] **Step 5: `--field-line`을 면 구분에 쓰던 한 곳을 되돌린다**

`--field-line`을 쓰는 표면 규칙은 저장소에 둘이고 둘 다 `operations/ui/console/cell/cell.css`에 있다. `.file-picker-button`(14번째 줄)은 누르는 조작이라 그대로 둔다. `.document-group`(8번째 줄)은 폼 묶음을 가르는 선이므로:

```css
.document-group { min-width: 0; margin: var(--space-3) 0; padding: var(--space-3); border: 1px solid var(--field-line); border-radius: var(--radius-control); }
```

을

```css
.document-group { min-width: 0; margin: var(--space-3) 0; padding: var(--space-3); border: 1px solid var(--border-default); border-radius: var(--radius-control); }
```

로 바꾼다.

- [ ] **Step 6: Cam 사본의 주석을 맞춘다**

`operations/ui/cam/app/src/main/java/io/github/livsbittt/rosy/cam/ui/RosyTheme.kt`에서:

```kotlin
    val Line14 = Paper.copy(alpha = RosyMetrics.Line14Alpha) // derived: --line-14 (= --surface-line, --field-line)
```

을

```kotlin
    val Line14 = Paper.copy(alpha = RosyMetrics.Line14Alpha) // derived: --line-14 (= --surface-line). --field-line is --control-line (ink 50%) on the web since D-741.
```

로 바꾼다. 값은 바꾸지 않는다. Cam의 `outline`은 잉크 14%로 남는다(열린 결정 2).

- [ ] **Step 7: 커밋하고 원격에서 통과를 확인한다**

```bash
git add shared/web/tokens.css shared/web/components.css operations/ui/console/cell/cell.css operations/ui/cam/app/src/main/java/io/github/livsbittt/rosy/cam/ui/RosyTheme.kt
git diff --cached --name-only
git commit -m "feat(web): draw button and field borders with the control line (D-741)"
rm -f X:/DevTemp/control-line/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/control-line -- shared/web/test test/architecture
for f in X:/DevTemp/control-line/run-*.txt; do cp "$f" "X:/DevTemp/control-line/t3-web-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/control-line/t3-web-$(basename "$f")"; done
rm -f X:/DevTemp/control-line/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/control-line -- operations/fleet/test/test_fleet_header.py operations/fleet/test/test_grammar_separation.py operations/fleet/test/test_console_palette.py middleware/ui/robot/test middleware/ui/pilot/test
for f in X:/DevTemp/control-line/run-*.txt; do cp "$f" "X:/DevTemp/control-line/t3-surfaces-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/control-line/t3-surfaces-$(basename "$f")"; done
```

Expected: `test_control_line_contrast.py` 12 passed. 로그마다 `NEW` 0. 검증 종류는 **원격 pytest (소스)** 다. 테두리의 실제 색을 재는 브라우저 시험은 저장소에 없다(`*_browser.py` 가운데 조작 테두리 색을 단언하는 곳은 없다). 화면은 Task 5에서 사람이 본다.

---

### Task 4: 견본과 문서

**Files:**
- Modify: `middleware/ui/robot/styleguide.html`, `middleware/ui/robot/styleguide.css`, `DESIGN.md`, `docs/adr/D-741-unified-app-shell-seats.md`, `shared/web/logs.md`, `operations/ui/console/logs.md`

- [ ] **Step 1: 스타일 갤러리에 견본을 넣는다**

`middleware/ui/robot/styleguide.html`의 `id="color-roles"` 목록에서:

```html
        <li><span class="color-sample sample-strong" aria-hidden="true"></span><code>border-strong</code> · 강조 경계</li>
```

줄 바로 다음에:

```html
        <li><span class="color-sample sample-control" aria-hidden="true"></span><code>control-line</code> · 단추·입력 경계</li>
```

`middleware/ui/robot/styleguide.css`의 `.sample-strong { border-color: var(--border-strong); }` 줄 바로 다음에:

```css
.sample-control { border-color: var(--control-line); }
```

- [ ] **Step 2: `DESIGN.md`의 역할 표에 한 줄을 더한다**

색상 역할 표에서:

```markdown
| 경계선 | `--border-subtle` / `--border-default` / `--border-strong` | 행 구분 / 면 구분 / 강조 경계. 안전 신호를 대신하지 않는다 |
```

줄 바로 다음에:

```markdown
| 조작 경계 | `--control-line` | 단추·입력·펼침 행의 테두리. 잉크 50%이고 두 테마의 다섯 바탕 위에서 3:1 이상이다(D-741 10항, `test_control_line_contrast.py`). 면을 가르는 선에는 쓰지 않는다 |
```

- [ ] **Step 3: D-741 10항의 숫자를 맞춘다**

먼저 상태를 본다.

```bash
grep -n "^\*\*Status:\*\*" docs/adr/D-741-unified-app-shell-seats.md
```

`Proposed`이면 10항을 제자리에서 고친다. 지금 글:

```markdown
**10. 조작의 테두리.** 단추와 입력 필드의 테두리는 새 역할 `--control-line`(잉크 40%)을 쓴다. `--border-default`(잉크 14%)는 면을 가르는 선으로 남긴다. 어둡게 테마에서 조작 경계의 대비가 3:1을 넘는다. 밝게 테마에서는 잉크 40%가 2.4:1이라, 조작에 적용하는 조각에서 밝게 값을 따로 정한다.
```

새 글:

```markdown
**10. 조작의 테두리.** 단추와 입력 필드의 테두리는 새 역할 `--control-line`(잉크 50%)을 쓴다. `--border-default`(잉크 14%)는 면을 가르는 선으로 남긴다. 파생 토큰은 테마마다 따로 정할 수 없어(D-359 §1) 값은 하나다. 잉크 50%는 다섯 바탕(`--ground`, `-deep`, `-raise`, `-soft`, `-card`) 위에서 어둡게 4.20–4.76:1, 밝게 3.11–3.31:1이다. 잉크 40%는 밝게에서 2.4:1이라 쓰지 않는다.
```

`Accepted`이면 10항을 고치지 않고 문서 끝(`계획:` 줄 앞)에 아래를 붙인다.

```markdown
### 2026-10-13 부기: 10항의 값

10항의 "잉크 40%, 밝게 값을 따로 정한다"는 구현에서 "잉크 50%, 두 테마 같은 값"이 됐다. 파생 토큰은 테마마다 따로 정할 수 없다(D-359 §1). 잉크 50%는 다섯 바탕 위에서 어둡게 4.20–4.76:1, 밝게 3.11–3.31:1이다.
```

ADR 제목과 Status는 바뀌지 않으므로 `docs/reference/ROSY ADR Log.md`는 고치지 않는다.

- [ ] **Step 4: 모듈 일지에 한 줄씩 더하고 커밋한다**

`shared/web/logs.md` 끝에(해시는 Task 3 Step 7의 커밋):

```markdown
## 2026-10-13 · <Task 3 커밋 해시> · feat(web): control line at ink 50% on buttons and fields (D-741)

- 변경: `--line-40`을 `--line-50`으로 바꾸고 `--control-line`이 그것을 가리킨다. 공용 `ui-button`, `ui-button[kind="quiet"]`·`a.docs-link`, `.ui-disclosure-row`와 `--field-line`이 이 역할을 쓴다. `--border-default`·`--surface-line`·`--flag-line`은 그대로다.
- 증거: 원격 `shared/web/test`, `test/architecture` 통과, `known_failures` NEW 0. `test_control_line_contrast.py`가 두 테마 × 다섯 바탕에서 3:1을 계산으로 확인한다. 브라우저 측정과 화면 캡처는 없다.
- gate 변화: 없음. 모든 웹 표면의 조용한 단추·토글·입력 테두리가 진해지므로 D-153 G2 기준 캡처는 표면마다 다시 찍어야 한다.
```

`operations/ui/console/logs.md` 끝에:

```markdown
## 2026-10-13 · <Task 3 커밋 해시> · feat(web): control line (D-741), Cell 묶음 선 유지

- 변경: `cell/cell.css`의 `.document-group` 테두리를 `--field-line`에서 `--border-default`로 옮겼다. `--field-line`이 조작 경계(잉크 50%)가 되어도 폼 묶음 선은 면 구분으로 남는다. `.file-picker-button`은 조작이라 `--field-line`을 그대로 쓴다.
- 증거: 원격 소스 시험 통과. 화면 확인 없음.
- gate 변화: 없음.
```

```bash
git add middleware/ui/robot/styleguide.html middleware/ui/robot/styleguide.css DESIGN.md docs/adr/D-741-unified-app-shell-seats.md shared/web/logs.md operations/ui/console/logs.md
git diff --cached --name-only
git commit -m "docs(web): show the control line in the style gallery and DESIGN.md (D-741)"
rm -f X:/DevTemp/control-line/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/control-line -- shared/web/test middleware/ui/robot/test middleware/core/api/test/test_ui_route.py test/architecture test/test_harness_contracts.py
for f in X:/DevTemp/control-line/run-*.txt; do cp "$f" "X:/DevTemp/control-line/t4-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/control-line/t4-$(basename "$f")"; done
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
git status --short
```

Expected: 로그마다 `NEW` 0, lint 통과. `generate`가 `shared/web/index.md`나 `operations/ui/console/index.md`, `STATUS.md`를 바꿨으면 `git status --short`에 나온 그 생성 파일만 이름으로 `git add` 하고 `git commit -m "docs: regenerate module indexes"`로 따로 커밋한다.

---

### Task 5: 사람이 볼 것

브라우저 시험이 테두리 색을 재지 않으므로 이 단계가 화면 증거의 전부다. 본 사람과 날짜를 `shared/web/logs.md`의 위 항목에 한 줄로 더한다. 보지 못했으면 "화면 확인 없음"으로 둔다.

- [ ] **Step 1: 로봇 `/styleguide`를 두 테마로 연다.** `색상 역할`의 `control-line` 견본이 `border-default` 견본보다 진하다. 조용한 단추, 토글, 입력 필드, 펼침 행의 테두리가 밝게 테마에서 바탕과 구분된다.
- [ ] **Step 2: 어둡게 테마에서 과하지 않은지 본다.** 대비가 1.44:1에서 4.2–4.8:1로 오른다. Fleet `/console`의 로봇 카드 단추 줄, 로봇 `/console`의 조작 열, Pilot 주행 화면, 학습 검수 목록을 연다. 단추 테두리가 주의·위험 상태색(`--status-warn`, `--status-crit`)보다 먼저 눈에 들어오면 열린 결정 1로 돌아간다.
- [ ] **Step 3: 꺼진 단추가 구분되는지 본다.** 이유가 붙은 꺼진 단추(`ui-button[disabled][reason]`)는 점선과 `--surface-line`(잉크 14%)으로 남는다. 켜진 단추와 한 줄에 있을 때 꺼진 쪽이 더 흐리다.
- [ ] **Step 4: Fleet `/console/cell`을 연다.** 문서 묶음(`.document-group`)의 선은 전과 같고, 파일 고르기 단추의 테두리만 진해졌다.

---

### Task 6: 착지

- [ ] **Step 1: 사용자가 착지를 말한 뒤에만**

```bash
PYTHONIOENCODING=utf-8 python tools/land.py --tests auto
```

Expected: 도구가 `main`을 합치고 관련 시험과 lint를 다시 돌린 뒤 `--ff-only`로 착지한다. 푸시는 하지 않는다. 착지 보고에 "테두리 색은 계산 관문만 확인했고, 브라우저 측정은 없으며, 화면은 Task 5의 사람 확인이 증거"라고 적는다.

---

## 이 계획이 하지 않는 것

- 표면 시트가 직접 그린 네이티브 조작의 테두리를 고치지 않는다. 공용 `ui-button`·`ui-field`·`.ui-disclosure-row`를 쓰지 않는 `button`, `select`, `summary`와 표면 고유 단추는(예: Pilot `styles.css`에는 `--border-strong`을 쓰는 규칙이 다섯 곳 있다) 이 계획이 세지 않았다. 표면마다 그 표면의 조각(4, 9, 11, 12, 13)에서 본다.
- `--border-default`, `--surface-line`, `--flag-line`, `--border-subtle`, `--border-strong`의 값을 바꾸지 않는다.
- 꺼진 단추의 점선 테두리(`ui-button[disabled][reason]`, `--surface-line`)를 바꾸지 않는다. 꺼진 조작은 WCAG 1.4.11의 대상이 아니고, D-741 9항이 점선을 "할 수 없음"에 남겼다.
- 팔레트 블록에 키를 더하지 않는다. 테마마다 다른 조작 선 색을 주려면 닫힌 팔레트 키 집합(D-359 §2)을 여는 결정이 따로 있어야 한다.
- Cam(Android)의 `outline` 값을 바꾸지 않는다. 주석만 맞춘다.
- D-153 G2 캡처를 찍지 않는다.

## 열린 결정

1. **어둡게 테마의 선이 진해진다.** 한 값으로 밝게의 3:1을 넘기려면 어둡게는 3.21–3.47:1(잉크 40%)에서 4.20–4.76:1(잉크 50%)이 된다. 이 계획은 지시대로 한 값을 썼다. 어둡게를 40%로 두고 밝게만 올리려면 팔레트에 테마별 키(예: `--control-ink`)를 더해야 하고, 그것은 D-359 §2의 닫힌 키 집합과 `test_every_theme_defines_the_same_palette_keys`를 고치는 별도 결정이다.
2. **Cam의 입력 외곽선.** `RosyTheme.kt`의 `outline = RosyColors.Line14`는 잉크 14%다. 웹 입력은 50%가 되므로 두 매체가 달라진다. 맞추려면 `shared/web/native-tokens.gradle`의 알파 내보내기 목록(`['line-14', 'gauge-track']`)에 `line-50`을 더하고 Cam 테마를 고친다. 조각 14(Cam 앱 바)에서 정한다.
3. **`--ground-card-2` 위의 조작.** 관문은 지시한 다섯 바탕만 본다. `--ground-card-2` 위에서는 밝게 3.00:1로 여유가 없다. 지금 그 면은 눌린 `segment`의 채움에만 쓰이고(`border-color: transparent`), 그 위에 테두리 있는 조작을 얹는 화면이 생기면 관문에 그 바탕을 더하고 값을 다시 계산한다(51%면 밝게 3.06:1).
4. **이유가 붙은 꺼진 단추.** 지금처럼 `--surface-line` 점선으로 뒀다. 꺼진 단추도 `--control-line` 점선으로 올릴지는 Task 5 Step 3에서 본 뒤 정한다.
