# 통합 셸 · 공용 자리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모든 웹 표면이 같이 쓸 자리(탐색 레일, 하위 탐색, 경로 줄, 본문 격자, 오른쪽 칸)를 공용 토큰과 공용 시트 하나로 만든다. 이 계획은 [통합 셸 계획](2026-10-13-unified-app-shell.md)의 조각 1과 2다. 어떤 표면도 아직 이 자리를 쓰지 않는다.

**Architecture:** 치수와 간격은 `shared/web/tokens.css`의 토큰이다. 배치는 새 시트 `shared/web/app-shell.css`가 갖고 `@container`로만 접힌다(`components.css`에는 `@media`를 넣을 수 없고, 48rem은 세 단이 아니다). 표면은 `ui-shell`에 `class="ui-app-shell"`을 달아 자리를 쓴다.

**Tech Stack:** 순수 CSS, 번들러 없음. 계약 시험은 pytest(소스 읽기). 시험은 노트북에서 돌리지 않고 `tools/remote/remote_pytest.py`로 돌린다. 원격 러너는 커밋한 HEAD만 보내므로 시험을 돌리기 전에 커밋한다.

**읽고 시작할 것:** `rosy-platform/AGENTS.md`의 「같이 하는 깃」, `shared/web/AGENTS.md`, [D-741](../adr/D-741-unified-app-shell-seats.md), D-359 §6.

---

### Task 0: 작업 위치

- [ ] **Step 1: 워크트리와 브랜치를 만든다**

```bash
cd F:/Dev/Control/Robot/Rosy/rosy-platform
git status --short --branch
git worktree list
git worktree add --relative-paths .worktrees/shell-seats -b feat/app-shell-seats main
cd .worktrees/shell-seats
git branch --show-current
```

Expected: 마지막 줄이 `feat/app-shell-seats`.

---

### Task 1: 자리 토큰

**Files:**
- Create: `shared/web/test/test_app_shell_seats.py`
- Modify: `shared/web/tokens.css` (`--line-30` 줄 다음, `--sidebar-track` 줄 다음, `--border-strong` 줄 다음)

- [ ] **Step 1: 실패하는 시험을 쓴다**

`shared/web/test/test_app_shell_seats.py`:

```python
"""D-741 — 공용 셸 자리: 토큰, 공용 시트, 등록."""
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
TOKENS = (WEB / "tokens.css").read_text(encoding="utf-8")
BASE_SCALE = {f"--space-{i}" for i in range(1, 7)}


def _decl(name: str) -> str | None:
    found = re.search(rf"^\s*{re.escape(name)}\s*:\s*([^;]+);", TOKENS, re.MULTILINE)
    return found.group(1).strip() if found else None


def test_seat_dimensions_are_tokens():
    assert _decl("--appbar-height") == "64px"
    assert _decl("--rail-track") == "72px"
    assert _decl("--subnav-track") == "232px"
    assert _decl("--context-track") == "360px"
    assert _decl("--pathbar-height") == "56px"


def test_seat_spacing_roles_reference_the_base_scale():
    for role in ("--inset-rail", "--gap-rail", "--inset-subnav", "--inset-pathbar",
                 "--gap-pathbar", "--inset-pane", "--gap-pane"):
        value = _decl(role)
        assert value, f"{role} 토큰이 없다"
        refs = set(re.findall(r"var\((--[a-z0-9-]+)", value))
        assert refs and refs <= BASE_SCALE, f"{role}은 기본 간격 척도만 참조해야 한다: {value}"


def test_control_line_and_chrome_surface_are_roles():
    assert _decl("--line-40") == "color-mix(in oklab, var(--ink) 40%, transparent)"
    assert _decl("--control-line") == "var(--line-40)"
    assert _decl("--surface-chrome") == "var(--ground-raise)"
    assert _decl("--border-default") == "var(--line-14)", "면을 가르는 선은 그대로 둔다"
```

- [ ] **Step 2: 커밋하고 원격에서 실패를 확인한다**

```bash
git add shared/web/test/test_app_shell_seats.py
git commit -m "test(web): pin app shell seat tokens (D-741)"
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/shell-seats -- shared/web/test/test_app_shell_seats.py
```

Expected: 3 failed. 첫 실패 문구에 `assert None == '64px'`.

- [ ] **Step 3: 토큰을 넣는다**

`shared/web/tokens.css`에서 `--line-30: color-mix(in oklab, var(--ink) 30%, transparent);` 줄 바로 다음에:

```css
  --line-40: color-mix(in oklab, var(--ink) 40%, transparent);
```

`--sidebar-track: minmax(13rem, 18rem);` 줄 바로 다음에:

```css
  /* D-741 — 모든 앱이 같이 쓰는 자리의 치수. 표면 시트는 이 값을 다시 정하지 않는다. */
  --appbar-height: 64px;
  --rail-track: 72px;
  --subnav-track: 232px;
  --context-track: 360px;
  --pathbar-height: 56px;
  --inset-rail: var(--space-2);
  --gap-rail: var(--space-1);
  --inset-subnav: var(--space-3) var(--space-2) var(--space-4);
  --inset-pathbar: var(--space-1) var(--space-4);
  --gap-pathbar: var(--space-2) var(--space-3);
  --inset-pane: var(--space-2) var(--space-4) var(--space-4);
  --gap-pane: var(--space-3);
```

`--border-strong: var(--line-30);` 줄 바로 다음에:

```css
  /* D-741 — 단추와 입력의 경계. 면을 가르는 --border-default보다 진해 3:1을 넘는다. */
  --control-line: var(--line-40);
  /* D-741 — 옆의 틀(레일, 하위 탐색, 오른쪽 칸)의 면. */
  --surface-chrome: var(--ground-raise);
```

- [ ] **Step 4: 커밋하고 원격에서 통과를 확인한다**

```bash
git add shared/web/tokens.css
git commit -m "feat(web): add app shell seat tokens (D-741)"
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/shell-seats -- shared/web/test
python test/known_failures.py X:/DevTemp/shell-seats/run-2.txt
```

Expected: `test_app_shell_seats.py` 3 passed, `known_failures.py`가 `NEW` 0으로 끝난다. `shared/web/test` 전체를 돌리는 이유는 토큰 계약 시험(`test_ui_token_contracts.py`, `test_token_parity.py`, `test_native_token_export.py`)이 새 토큰에 반응하는지 보기 위해서다. 그 가운데 하나가 새 토큰 이름을 닫힌 목록에 올리라고 실패하면, 그 시험이 말하는 목록에 이름을 더하고 같은 커밋에 넣는다.

---

### Task 2: 공용 시트

**Files:**
- Create: `shared/web/app-shell.css`
- Modify: `shared/web/shared-assets.json`, `shared/web/CMakeLists.txt`, `shared/web/surfaces.yaml`, `shared/web/test/test_design_scope_gates.py` (`ROSE_FILES`)
- Test: `shared/web/test/test_app_shell_seats.py`

- [ ] **Step 1: 실패하는 시험을 더한다**

`shared/web/test/test_app_shell_seats.py` 끝에 붙인다:

```python
SHEET = WEB / "app-shell.css"
SEATS = (".ui-app-shell", ".ui-app-body", ".ui-rail", ".ui-rail-nav", ".ui-rail-item",
         ".ui-subnav", ".ui-subnav-nav", ".ui-subnav-head", ".ui-subnav-item",
         ".ui-app-main", ".ui-pathbar", ".ui-crumbs", ".ui-stage-grid", ".ui-pane")


def test_sheet_is_served_and_installed():
    assets = json.loads((WEB / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]
    assert assets.get("app-shell.css") == "text/css"
    assert "\n  app-shell.css\n" in (WEB / "CMakeLists.txt").read_text(encoding="utf-8")


def test_sheet_defines_every_seat():
    css = SHEET.read_text(encoding="utf-8")
    for seat in SEATS:
        assert re.search(rf"(?m)^{re.escape(seat)}\b", css), f"{seat} 자리가 없다"
    for pane in ("stage", "now", "more", "sense", "cam"):
        assert f'[data-pane="{pane}"] {{ grid-area: {pane}; }}' in css


def test_sheet_answers_its_container_not_the_viewport():
    css = SHEET.read_text(encoding="utf-8")
    assert "@media" not in css, "공용 자리는 칸에 반응한다(D-359 §6.3)"
    conditions = set(re.findall(r"@container \(([^)]+)\)", css))
    assert conditions == {"width < 64rem", "width < 48rem"}
    assert css.count("container-type: inline-size") == 2, "셸과 본문 둘만 칸이다"


def test_sheet_takes_sizes_and_paint_from_tokens():
    css = SHEET.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(", css), "원시 색을 쓰지 않는다"
    assert not re.search(r"var\(--space-", css), "간격은 역할 토큰으로 쓴다(D-292)"
    assert not re.search(r"font-size:\s*\d", css), "글자 크기는 토큰이다"
    for token in ("--rail-track", "--subnav-track", "--context-track", "--pathbar-height",
                  "--surface-chrome", "--inset-pane", "--gap-pane"):
        assert f"var({token})" in css, f"{token}을 쓰지 않는다"


def test_web_common_lists_the_48rem_container_breakpoint():
    registry = (WEB / "surfaces.yaml").read_text(encoding="utf-8")
    row = registry.split("- id: web-common", 1)[1].split("\n  - id:", 1)[0]
    assert re.search(r"container_breakpoints:(?:\n\s+-.*)*\n\s+- \{?value: 48rem", row) or (
        "value: 48rem" in row.split("container_breakpoints:", 1)[1])
```

- [ ] **Step 2: 커밋하고 원격에서 실패를 확인한다**

```bash
git add shared/web/test/test_app_shell_seats.py
git commit -m "test(web): pin the shared app shell sheet (D-741)"
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/shell-seats -- shared/web/test/test_app_shell_seats.py
```

Expected: 새 시험 5개 실패. `FileNotFoundError: ... app-shell.css` 또는 `assert None == 'text/css'`.

- [ ] **Step 3: 시트를 쓴다**

`shared/web/app-shell.css`:

```css
/* D-741 — 모든 앱이 같이 쓰는 자리: 탐색 레일 | 하위 탐색 | 본문(경로 줄, 본문 격자).
   배치만 한다. 색은 역할 토큰, 치수는 자리 토큰에서 온다. 접히는 폭 둘은 칸 질의다
   (D-359 §6.3): 셸은 뷰포트가 아니라 자기 폭에 답한다. */
.ui-app-shell { container-type: inline-size; }
.ui-app-body { flex: 1 1 auto; min-height: 0; display: grid; grid-template-columns: var(--rail-track) var(--subnav-track) minmax(0, 1fr); }
.ui-app-body[data-seats="rail"] { grid-template-columns: var(--rail-track) minmax(0, 1fr); }
.ui-app-body[data-seats="none"] { grid-template-columns: minmax(0, 1fr); }

.ui-rail { min-width: 0; background: var(--surface-chrome); border-inline-end: 1px solid var(--border-default); }
.ui-rail-nav { display: flex; flex-direction: column; align-items: center; gap: var(--gap-rail); padding: var(--inset-rail); }
.ui-rail-item { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--gap-rail); inline-size: 3.5rem; min-block-size: 3.5rem; border-radius: var(--radius-button); color: var(--text-secondary); font: var(--weight-label) var(--text-micro)/var(--leading-control) var(--body); text-decoration: none; white-space: nowrap; }
.ui-rail-item[aria-current="page"] { background: var(--brand-rose-wash); color: var(--brand-rose); }

.ui-subnav { min-width: 0; background: var(--surface-chrome); border-inline-end: 1px solid var(--border-default); }
.ui-subnav-nav { display: flex; flex-direction: column; gap: var(--gap-rail); padding: var(--inset-subnav); }
.ui-subnav-head { padding: var(--inset-button); color: var(--text-secondary); font: var(--weight-label) var(--text-micro)/var(--leading-control) var(--body); }
.ui-subnav-item { flex: none; display: flex; align-items: center; min-block-size: var(--target-secondary); padding: var(--inset-button); border-radius: var(--radius-button); color: var(--text-secondary); font: var(--weight-label) var(--text-label)/var(--leading-control) var(--body); text-decoration: none; white-space: nowrap; }
.ui-subnav-item[aria-current="page"] { background: var(--brand-rose-wash); color: var(--text-primary); }

.ui-app-main { min-width: 0; display: flex; flex-direction: column; container-type: inline-size; }
.ui-pathbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-pathbar); min-block-size: var(--pathbar-height); padding: var(--inset-pathbar); border-block-end: 1px solid var(--border-default); }
.ui-crumbs { display: flex; align-items: center; gap: var(--gap-pathbar); color: var(--text-secondary); font: var(--weight-medium) var(--text-label)/var(--leading-control) var(--body); }
.ui-crumbs a { display: inline-flex; align-items: center; min-block-size: var(--target-secondary); color: inherit; }

/* 본문 격자: 본문 + 지금 상태 + 나머지. 좁으면 지금 상태가 먼저 온다. */
.ui-stage-grid { flex: 1 1 auto; display: grid; grid-template-columns: minmax(0, 1fr) var(--context-track); grid-template-rows: auto 1fr; grid-template-areas: "stage now" "stage more"; }
.ui-stage-grid[data-layout="watch"] { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); }
.ui-stage-grid[data-layout="solo"] { grid-template-columns: minmax(0, 1fr); grid-template-areas: "stage" "stage"; }
.ui-stage-grid[data-layout="sense"] { grid-template-columns: minmax(13rem, 17.5rem) minmax(0, 1fr) var(--context-track); grid-template-areas: "sense stage now" "sense cam now"; }
.ui-pane { min-width: 0; display: flex; flex-direction: column; gap: var(--gap-pane); padding: var(--inset-pane); }
[data-pane="stage"] { grid-area: stage; }
[data-pane="now"] { grid-area: now; }
[data-pane="more"] { grid-area: more; }
[data-pane="sense"] { grid-area: sense; }
[data-pane="cam"] { grid-area: cam; }
.ui-pane[data-pane="now"], .ui-pane[data-pane="more"] { background: var(--surface-chrome); border-inline-start: 1px solid var(--border-default); }
.ui-pane[data-pane="sense"] { background: var(--surface-chrome); border-inline-end: 1px solid var(--border-default); }

@container (width < 64rem) {
  .ui-app-body, .ui-app-body[data-seats="rail"] { grid-template-columns: minmax(0, 1fr); }
  .ui-rail, .ui-subnav { border-inline-end: 0; border-block-end: 1px solid var(--border-default); }
  .ui-rail-nav { flex-direction: row; }
  .ui-rail-item { flex-direction: row; inline-size: auto; min-block-size: var(--target-secondary); padding: var(--inset-button); font-size: var(--text-label); }
  .ui-subnav-nav { flex-direction: row; overflow-x: auto; padding: var(--inset-rail); }
  .ui-subnav-head { display: none; }
  .ui-stage-grid[data-layout="sense"] { grid-template-columns: minmax(0, 1fr) var(--context-track); grid-template-rows: auto; grid-template-areas: "stage now" "cam now" "sense sense"; }
}

@container (width < 48rem) {
  .ui-stage-grid, .ui-stage-grid[data-layout="watch"] { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto; grid-template-areas: "now" "stage" "more"; }
  .ui-stage-grid[data-order="stage-first"] { grid-template-areas: "stage" "now" "more"; }
  .ui-stage-grid[data-layout="solo"] { grid-template-areas: "stage"; }
  .ui-stage-grid[data-layout="sense"] { grid-template-columns: minmax(0, 1fr); grid-template-areas: "cam" "now" "stage" "sense"; }
  .ui-pane[data-pane="now"], .ui-pane[data-pane="more"], .ui-pane[data-pane="sense"] { border-inline: 0; border-block-end: 1px solid var(--border-default); }
}
```

- [ ] **Step 4: 시트를 등록한다**

`shared/web/shared-assets.json`의 `"template.css": "text/css",` 줄 다음에:

```json
    "app-shell.css": "text/css",
```

`shared/web/CMakeLists.txt`의 `  template.css` 줄 다음에:

```cmake
  app-shell.css
```

`shared/web/surfaces.yaml`의 `web-common` 행 `container_breakpoints:` 아래, 22rem 항목 다음에(들여쓰기는 22rem 항목과 같게):

```yaml
      - value: 48rem
        reason: 공용 셸 본문이 한 줄로 쌓이는 칸 폭 — 오른쪽 칸 360px과 본문 최소 폭이 같이 설 수 없는 폭이다. 모든 앱이 같은 값을 쓴다(D-741 5항)
```

`shared/web/test/test_design_scope_gates.py`의 `ROSE_FILES`에 `app-shell.css`의 경로를 더한다. 그 목록의 다른 항목과 같은 표기(저장소 루트 기준 경로)를 따른다. 장미색은 레일의 현재 위치 표식 한 곳뿐이다(D-277이 허용한 "현재 선택된 역할 메뉴").

- [ ] **Step 5: 커밋하고 원격에서 통과를 확인한다**

```bash
git add shared/web/app-shell.css shared/web/shared-assets.json shared/web/CMakeLists.txt shared/web/surfaces.yaml shared/web/test/test_design_scope_gates.py
git commit -m "feat(web): add the shared app shell sheet (D-741)"
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/shell-seats -- shared/web/test test/architecture middleware/robot_ui/pilot/test/test_shell_assets.py
python test/known_failures.py X:/DevTemp/shell-seats/run-4.txt
```

Expected: `test_app_shell_seats.py` 8 passed, `NEW` 0. 같이 봐야 하는 기존 시험과 실패했을 때 할 일:

| 시험 | 실패 문구가 말하는 것 | 할 일 |
|---|---|---|
| `test_asset_manifest.py` | 설치 목록과 허용 목록이 다르다 | Step 4의 두 줄이 같은 이름인지 본다 |
| `test_responsive_tiers.py` | 등재한 48rem을 쓰는 `@container`가 없다, 또는 등재하지 않은 값이 있다 | 시트의 조건이 정확히 `(width < 48rem)`, `(width < 64rem)`인지 본다 |
| `test_ui_token_contracts.py` | 시트가 없는 토큰을 쓴다 | 그 토큰을 `tokens.css`에서 찾아 이름을 맞춘다 |
| `test_design_scope_gates.py` | 장미색이 허용 목록 밖 파일에 있다 | `ROSE_FILES` 줄을 본다 |
| `test_surface_typography_focus_contracts.py` | 굵기·행간이 토큰이 아니다 | 시트의 `font:` 값을 토큰으로 고친다 |

---

### Task 3: 견본과 문서

**Files:**
- Modify: `shared/web/template.html`, `middleware/robot_ui/robot/styleguide.html`, `DESIGN.md`, `shared/web/logs.md`

- [ ] **Step 1: 견본 틀에 자리를 넣는다**

`shared/web/template.html`의 `<head>`에서 `/common/template.css` 링크 다음에:

```html
  <link rel="stylesheet" href="/common/app-shell.css">
```

같은 파일의 `<ui-shell grammar="...">` 여는 태그에 `class="ui-app-shell"`을 더하고, `<main>`을 아래로 바꾼다. 기존 `<main>` 안의 내용은 `data-pane="stage"` 안으로 옮긴다.

```html
    <div class="ui-app-body" data-seats="rail">
      <div class="ui-rail">
        <nav class="ui-rail-nav" aria-label="영역 이동">
          <a class="ui-rail-item" href="#" aria-current="page" data-action-icon="list"><span>화면</span></a>
        </nav>
      </div>
      <main class="ui-app-main">
        <div class="ui-pathbar"><h1 class="ui-page-heading">화면 제목</h1></div>
        <div class="ui-stage-grid">
          <section class="ui-pane" data-pane="stage"></section>
          <aside class="ui-pane" data-pane="now" aria-label="지금 상태"></aside>
          <aside class="ui-pane" data-pane="more" aria-label="입력과 근거"></aside>
        </div>
      </main>
    </div>
```

- [ ] **Step 2: 스타일 갤러리에 자리 견본을 넣는다**

`middleware/robot_ui/robot/styleguide.html`의 `<head>`에 `<link rel="stylesheet" href="/common/app-shell.css">`를 더하고, `id="task-choice"` 구획 다음에:

```html
  <section class="entry" id="app-shell-seats">
    <h2>앱 셸의 자리 (D-741)</h2>
    <p>탐색 레일, 하위 탐색, 경로 줄, 본문, 오른쪽 칸. 이 상자의 폭을 줄이면 64rem과 48rem에서 접힌다.</p>
    <div class="ui-app-shell">
      <div class="ui-app-body">
        <div class="ui-rail"><nav class="ui-rail-nav" aria-label="견본 영역">
          <a class="ui-rail-item" href="#app-shell-seats" aria-current="page"><span>관제</span></a>
          <a class="ui-rail-item" href="#app-shell-seats"><span>작업</span></a>
        </nav></div>
        <div class="ui-subnav"><nav class="ui-subnav-nav" aria-label="견본 화면">
          <div class="ui-subnav-head">진행</div>
          <a class="ui-subnav-item" href="#app-shell-seats" aria-current="page">전체 작업</a>
          <a class="ui-subnav-item" href="#app-shell-seats">승인 대기</a>
        </nav></div>
        <div class="ui-app-main">
          <div class="ui-pathbar"><nav class="ui-crumbs" aria-label="경로"><a href="#app-shell-seats">작업</a></nav><strong>전체 작업</strong></div>
          <div class="ui-stage-grid">
            <div class="ui-pane" data-pane="stage">본문</div>
            <div class="ui-pane" data-pane="now">지금 상태</div>
            <div class="ui-pane" data-pane="more">입력과 근거</div>
          </div>
        </div>
      </div>
    </div>
  </section>
```

- [ ] **Step 3: `DESIGN.md`에 자리 절을 넣는다**

`## Layout` 절의 "동등한 창은 같은 폭" 항목 다음에:

```markdown
### 앱 셸의 자리 (D-741)

모든 웹 표면은 같은 자리를 쓴다. 치수는 `tokens.css`의 자리 토큰이고 배치는 [`app-shell.css`](shared/web/app-shell.css)가 갖는다. 표면 시트는 자리 안의 내용만 배치한다.

| 자리 | 토큰 | 담는 것 |
|---|---|---|
| 탐색 레일 | `--rail-track` 72px | 그 앱의 영역. 아이콘 아래에 이름 |
| 하위 탐색 | `--subnav-track` 232px | 영역 안의 화면이나 작업. 없으면 `data-seats="rail"` |
| 경로 줄 | `--pathbar-height` 56px | `영역 / 화면`과 만들기 단추 |
| 본문 | 남는 폭 | 지도, 영상, 목록, 미리보기, 폼 |
| 오른쪽 칸 | `--context-track` 360px | 위는 지금 상태, 아래는 입력·조작·근거 |

셸 폭 64rem 아래에서 레일과 하위 탐색이 가로 한 줄이 되고, 본문 폭 48rem 아래에서 지금 상태, 본문, 나머지 순서로 쌓인다. 둘 다 칸 질의다.
```

- [ ] **Step 4: 모듈 일지에 한 줄을 더하고 커밋한다**

`shared/web/logs.md` 끝에(파일의 다른 항목과 같은 머리 형식, 해시는 Task 2의 커밋):

```markdown
## 2026-10-13 · <Task 2 커밋 해시> · feat(web): shared app shell seats (D-741)
- 변경: 자리 토큰과 `app-shell.css`를 더하고 견본 틀·스타일 갤러리·DESIGN.md에 자리를 넣었다. 어떤 제품 표면도 아직 이 자리를 쓰지 않는다.
- 증거: 원격 `shared/web/test` 통과, `known_failures` NEW 0. 브라우저 시험과 화면 캡처는 없다.
- gate 변화: 없음.
```

```bash
git add shared/web/template.html middleware/robot_ui/robot/styleguide.html DESIGN.md shared/web/logs.md
git commit -m "docs(web): show the app shell seats in the template and style gallery (D-741)"
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/shell-seats -- shared/web/test middleware/robot_ui/robot/test middleware/core/api/test/test_ui_route.py test/architecture
python test/known_failures.py X:/DevTemp/shell-seats/run-5.txt
python tools/harness/rosy_harness.py lint
```

Expected: `NEW` 0. `test_shared_controls.py`가 `template.html`의 필수 요소(`<ui-brand`, `<ui-section`, `<ui-empty`, 단추 세 종류)를 찾으므로, Step 1에서 기존 내용을 지우지 않고 `data-pane="stage"` 안으로 옮겼는지 본다.

---

### Task 4: 착지

- [ ] **Step 1: 사용자가 착지를 말한 뒤에만**

```bash
python tools/land.py --tests auto
```

Expected: 도구가 `main`을 합치고 관련 시험과 lint를 다시 돌린 뒤 `--ff-only`로 착지한다. 푸시는 하지 않는다. 착지 보고에 "브라우저 시험은 원격에서 돌지 않았고 CI 대기"라고 적는다.

---

## 이 계획이 하지 않는 것

- 어떤 제품 표면도 고치지 않는다. Fleet은 조각 4부터다.
- 단추와 입력의 테두리를 `--control-line`으로 바꾸지 않는다. 조각 3이다.
- `--topbar-height`(88px)를 지우지 않는다. 마지막 표면이 `--appbar-height`로 옮긴 뒤에 지운다.
