# 역할별 화면 S0+S1 토대 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CORE가 패널 레지스트리를 capability와 역할로 걸러 매니페스트로 내주고, 셸이 그 목록의 패널 모듈만 조립하는 토대를 만든다. 첫 패널(최근 이벤트)을 `/device` 화면에 올려 흐름 전체를 증명한다.

**Architecture:** `web/panels.yaml` → `api/ui_registry.py`(로드·검증, 기동 실패) → `api/ui_manifest.py`(순수 필터) → `GET /api/v1/ui/surfaces/{surface}`. 화면 페이지 `/console`·`/setup`·`/device`는 한 템플릿(`web/shell/surface.html`)에서 문법·슬롯을 채워 서빙한다. 셸 JS(`web/shell/*.js`)는 매니페스트를 받아 `import()`로 패널을 mount하고, e-stop 하나와 화면 전환기를 소유한다. 기존 `/dashboard`는 이 단계에서 **손대지 않는다**(legacy 화면으로 계속 동작).

**Tech Stack:** Python 3.12, FastAPI 0.141, PyYAML, pytest, 순수 ES module(번들러 없음, D-75), 선택적 Playwright(Chromium).

**Spec:** [2026-09-24-role-surfaces-panel-composition-design.md](2026-09-24-role-surfaces-panel-composition-design.md)

---

## 작업 전 준비

- 다른 세션이 같은 체크아웃의 `main`에 커밋한다. **worktree에서 작업한다.**
  ```bash
  cd "F:/Dev/Control/Robot/ROS/Rosy/Rosy OS"
  git worktree add ../.worktrees/role-surfaces-s1 -b feat/role-surfaces-s1 main
  cd ../.worktrees/role-surfaces-s1
  ```
- 이후 모든 경로는 worktree 루트 기준이다. Windows 호스트에서는 `python`(not `python3`)을 쓴다.
- 기준선 확인:
  ```bash
  python -m pytest src/core/core_api_web/test src/core/core/test/test_dashboard.py src/core/core/test/test_dashboard_no_bundler.py -q
  ```
  Expected: 전부 PASS. 실패가 있으면 이 계획과 무관한 기존 실패인지 먼저 기록한다.

약어: `W = src/core/core_api_web/core_api_web/web`, `A = src/core/core_api_web/core_api_web/api`.

## 파일 구조

| 파일 | 책임 |
|---|---|
| `docs/adr/D-204-role-surfaces-and-panel-contract.md` | 결정 기록 |
| `W/panels.yaml` | 화면·슬롯·패널 선언(유일한 조립 규칙) |
| `A/ui_registry.py` | 레지스트리 로드와 검증. 자산 허용목록 산출 |
| `A/ui_manifest.py` | (레지스트리, 화면, 역할, CAP-001, descriptors) → 매니페스트. 순수 함수 |
| `A/v1/ui.py` | 매니페스트 라우터 |
| `A/app.py` | 레지스트리 적재, `/assets/*`, 화면 페이지 라우트 |
| `W/shell/surface.html` | 세 화면 공용 페이지 틀 |
| `W/shell/shell.js` | 부팅, 매니페스트 조립, 전환기, e-stop |
| `W/shell/mount.js` | 패널 mount/unmount와 실패 격리 |
| `W/shell/store.js` | 패널용 폴링 창구(패널별 scope) |
| `W/shell/shell.css` | 셸 레이아웃(토큰만) |
| `W/panels/system/events.js`, `.css` | 첫 패널: 최근 이벤트 |
| `src/core/core_api_web/test/test_ui_registry.py` | 레지스트리 검증 |
| `src/core/core_api_web/test/test_ui_manifest.py` | 매니페스트 필터 |
| `src/core/core_api_web/test/test_surface_pages.py` | 자산·화면 페이지 라우트 |
| `src/core/core_api_web/test/test_surface_contracts.py` | 정적 게이트: 줄 수, import, inline style, requires 키, 패키징 |
| `src/core/core/test/test_ui_surfaces_api.py` | 실제 CoreServices로 매니페스트 API |
| `test/test_surface_shell_browser.py` | 선택적 Chromium: 조립·격리·e-stop |

---

### Task 1: ADR D-204

**Files:**
- Create: `docs/adr/D-204-role-surfaces-and-panel-contract.md`
- Modify: `docs/concept/16_ROSY_Interface_Design_Principles.md` (§2 표)

- [ ] **Step 1: 다른 세션이 D-204를 먼저 썼는지 확인**

Run: `ls docs/adr | grep "^D-204"`
Expected: 출력 없음. 있으면 다음 빈 번호를 쓰고 이 계획의 `D-204`를 모두 그 번호로 바꾼다.

- [ ] **Step 2: ADR 작성**

```markdown
## D-204 역할별 CORE 화면과 패널 계약

**Status:** Accepted (2026-09-24)

**Context:** CORE `/dashboard` 한 페이지가 현장 운용, 작업 준비, 설치·정비를 모두 싣는다.
concept 16 §2는 Robot console과 Device runtime을 다른 화면으로 정의했지만 Device runtime은
`/dashboard`의 `점검` 뷰로 살아 있다. 패널은 HTML에 항상 있고 capability 판단은 JS 곳곳에
흩어져 있어 §8의 "`not_provided`는 생략"이 구조로 보장되지 않는다. 자산 허용목록은 손으로
적는 목록이다. 설계: `docs/plans/2026-09-24-role-surfaces-panel-composition-design.md`.

**Decision:**

1. **조립 축은 역할→화면, capability→패널이다.** 기기는 renderer를 싣지 않는다(concept 16 §8).
2. **CORE 화면은 세 개다.** `/console`(운용, spatial), `/setup`(작업 준비, procedure),
   `/device`(설치·정비, procedure). e-stop은 패널이 아니라 셸이 세 화면 같은 자리에 하나만 둔다.
3. **패널 레지스트리 `web/panels.yaml`이 유일한 조립 규칙이다.** CORE는 기동 때 검증하고 틀리면
   기동을 거부한다.
4. **`GET /api/v1/ui/surfaces/{surface}`가 매니페스트다.** CAP-001(`withhold_hardware_flags` 적용 후)과
   inventory descriptors를 읽기만 한다(D-68). `requires`가 거짓이거나 descriptor가 `not_provided`면
   패널을 뺀다. 역할이 낮으면 뺀다. UI의 역할 판단은 표시용이며 권한의 정본은 API `require_role`이다.
5. **패널 계약:** `export function mount(el, ctx) → unmount`. `ctx = { api, store, role, panel }`.
   패널은 `/common/*` 외에는 import하지 않고, 서로 부르지 않으며, inline style을 쓰지 않는다.
   한 패널의 실패는 그 슬롯에만 머문다.
6. **자산 허용목록은 셸 파일과 레지스트리에서 기동 때 만든다.** 정확히 일치하는 집합이며 폴더 스캔이
   아니다. 새 접두 `/assets/*`로 서빙하고 `/dashboard/assets/*`는 이관이 끝날 때까지 같은 목록을 쓴다.
7. **파일 예산:** 패널 JS ≤ 400줄, 셸 JS ≤ 300줄.

**Consequences:** 로봇마다 다른 화면은 코드가 아니라 capability YAML이 만든다. 새 기기 기능은
패널 파일 하나와 레지스트리 한 줄로 붙는다. `/dashboard`는 S4에서 `/console`로 리다이렉트되고
`app.js`는 해체된다. Fleet 콘솔의 같은 계약 이관은 별도 결정이다.
```

- [ ] **Step 3: concept 16 §2 표 갱신**

`docs/concept/16_ROSY_Interface_Design_Principles.md`의 §2 표에서 두 줄의 `v1 status` 열을 바꾼다.

- `Robot console` 행: `live (\`core\` \`/dashboard\` only — D-77)` → `live (\`core\` \`/dashboard\`; moving to \`/console\` — D-204)`
- `Device runtime` 행: `live (\`/dashboard\` host and ROS-graph panels)` → `live (\`/dashboard\` inspect view; moving to \`/device\` — D-204)`

표 아래에 한 줄을 추가한다.

```markdown
Work preparation (`/setup`, operator: maps, waypoints, docks, traffic policy) is a CORE surface of its own
under D-204; it uses the procedure grammar.
```

- [ ] **Step 4: 커밋**

```bash
git add docs/adr/D-204-role-surfaces-and-panel-contract.md docs/concept/16_ROSY_Interface_Design_Principles.md
git commit -m "docs(adr): D-204 role surfaces and panel contract"
```

---

### Task 2: 레지스트리 로더와 검증

**Files:**
- Create: `A/ui_registry.py`
- Create: `W/panels.yaml`
- Create: `W/panels/system/events.js` (Task 8에서 본문 작성, 여기서는 존재만)
- Create: `W/panels/system/events.css` (Task 8에서 본문 작성)
- Test: `src/core/core_api_web/test/test_ui_registry.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""D-204 — 패널 레지스트리는 기동 때 검증되고, 틀리면 기동을 거부한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_api_web.api.ui_registry import RegistryError, load_registry

WEB_ROOT = Path(__file__).resolve().parents[1] / "core_api_web" / "web"

SURFACES = """
version: 1
surfaces:
  console: {title: 운용, min_role: viewer, grammar: spatial, slots: [banner, sense, observe, act]}
  device: {title: 설치·정비, min_role: administrator, grammar: procedure, slots: [main]}
"""


def _web(tmp_path: Path, panels: str, *, files=("panels/a/one.js", "panels/a/one.css")) -> Path:
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("export function mount() {}\n", encoding="utf-8")
    (tmp_path / "panels.yaml").write_text(SURFACES + panels, encoding="utf-8")
    return tmp_path


ONE = """
panels:
  - id: a.one
    title: 하나
    surface: device
    slot: main
    order: 10
    module: panels/a/one.js
"""


def test_the_shipped_registry_loads():
    registry = load_registry(WEB_ROOT / "panels.yaml", WEB_ROOT)
    assert set(registry.surfaces) == {"console", "setup", "device"}
    assert "system.events" in {panel.id for panel in registry.panels}


def test_a_minimal_panel_takes_the_surface_role_and_no_requirements(tmp_path):
    registry = load_registry(_web(tmp_path, ONE) / "panels.yaml", tmp_path)
    (panel,) = registry.panels
    assert panel.min_role == "administrator"
    assert panel.requires == ()
    assert panel.css == ()
    assert registry.assets() == {"panels/a/one.js": "application/javascript"}


def test_css_is_listed_as_an_asset(tmp_path):
    text = ONE + "    css: [panels/a/one.css]\n"
    registry = load_registry(_web(tmp_path, text) / "panels.yaml", tmp_path)
    assert registry.assets()["panels/a/one.css"] == "text/css"


@pytest.mark.parametrize("change, message", [
    (("surface: device", "surface: garage"), "unknown surface"),
    (("slot: main", "slot: act"), "unknown slot"),
    (("module: panels/a/one.js", "module: panels/a/missing.js"), "missing file"),
    (("module: panels/a/one.js", "module: ../api/app.py"), "outside panels/"),
    (("module: panels/a/one.js", "module: panels/a/one.css"), ".js"),
    (("order: 10", "order: ten"), "order"),
    (("    title: 하나\n", ""), "title"),
])
def test_a_wrong_panel_refuses_to_load(tmp_path, change, message):
    text = ONE.replace(*change)
    with pytest.raises(RegistryError, match=message):
        load_registry(_web(tmp_path, text) / "panels.yaml", tmp_path)


def test_an_unknown_role_refuses_to_load(tmp_path):
    with pytest.raises(RegistryError, match="unknown role"):
        load_registry(_web(tmp_path, ONE + "    min_role: root\n") / "panels.yaml", tmp_path)


def test_a_duplicate_id_refuses_to_load(tmp_path):
    twice = ONE + ONE.replace("panels:\n", "").replace("order: 10", "order: 20")
    with pytest.raises(RegistryError, match="duplicate id"):
        load_registry(_web(tmp_path, twice) / "panels.yaml", tmp_path)


def test_a_duplicate_order_in_one_slot_refuses_to_load(tmp_path):
    twice = ONE + ONE.replace("panels:\n", "").replace("a.one", "a.two")
    with pytest.raises(RegistryError, match="duplicate order"):
        load_registry(_web(tmp_path, twice) / "panels.yaml", tmp_path)


def test_a_bad_requires_key_refuses_to_load(tmp_path):
    with pytest.raises(RegistryError, match="requires"):
        load_registry(_web(tmp_path, ONE + "    requires: [Teleop!]\n") / "panels.yaml", tmp_path)


@pytest.mark.parametrize("surfaces, message", [
    ("version: 2\nsurfaces: {}\n", "version"),
    ("version: 1\nsurfaces:\n  api: {title: x, min_role: viewer, grammar: procedure, slots: [main]}\n",
     "reserved"),
    ("version: 1\nsurfaces:\n  device: {title: x, min_role: viewer, grammar: exception, slots: [main]}\n",
     "grammar"),
    ("version: 1\nsurfaces:\n  device: {title: x, min_role: viewer, grammar: procedure, slots: []}\n",
     "slots"),
])
def test_a_wrong_surface_refuses_to_load(tmp_path, surfaces, message):
    (tmp_path / "panels.yaml").write_text(surfaces + "panels: []\n", encoding="utf-8")
    with pytest.raises(RegistryError, match=message):
        load_registry(tmp_path / "panels.yaml", tmp_path)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/core_api_web/test/test_ui_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core_api_web.api.ui_registry'`

- [ ] **Step 3: `A/ui_registry.py` 구현**

```python
"""core_api_web.api.ui_registry — 역할별 화면의 패널 레지스트리 (D-204). ROS 무의존.

`web/panels.yaml`은 어느 화면의 어느 슬롯에 어떤 패널이 어떤 capability와 역할로
끼는지를 적는 유일한 조립 규칙이다. 틀린 레지스트리는 기동을 거부한다 — 반쯤
조립된 운용 화면보다 뜨지 않는 서버가 현장에서 더 빨리 발견된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import yaml

from core_api_web.api.deps import ROLE_RANK

#: `web_common/ui.js` GRAMMARS 중 CORE 화면이 쓰는 둘.
GRAMMARS = frozenset({"spatial", "procedure"})
#: 화면 id가 곧 URL 첫 조각이다. 기존 라우트와 겹치는 이름은 금지한다.
RESERVED = frozenset({"api", "assets", "common", "ui", "dashboard", "styleguide", "docs", "redoc", "ws"})
PANEL_ROOT = "panels"

_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_PANEL_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_CAP_KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_MEDIA = {".js": "application/javascript", ".css": "text/css"}


class RegistryError(ValueError):
    """panels.yaml 이 D-204 계약을 어겼다."""


@dataclass(frozen=True)
class Surface:
    id: str
    title: str
    min_role: str
    grammar: str
    slots: tuple[str, ...]


@dataclass(frozen=True)
class Panel:
    id: str
    title: str
    surface: str
    slot: str
    order: int
    requires: tuple[str, ...]
    inventory: str | None
    min_role: str
    module: str
    css: tuple[str, ...]


@dataclass(frozen=True)
class Registry:
    surfaces: Mapping[str, Surface]
    panels: tuple[Panel, ...]

    def assets(self) -> dict[str, str]:
        """`web/` 기준 상대 경로 → media type. 허용목록에 그대로 합쳐진다."""
        found: dict[str, str] = {}
        for panel in self.panels:
            for path in (panel.module, *panel.css):
                found[path] = _MEDIA[PurePosixPath(path).suffix]
        return found


def _role(value: Any, where: str) -> str:
    if value not in ROLE_RANK:
        raise RegistryError(f"{where}: unknown role {value!r}")
    return value


def _asset(value: Any, suffix: str, web_root: Path, where: str) -> str:
    if not isinstance(value, str):
        raise RegistryError(f"{where}: asset path must be a string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.parts[:1] != (PANEL_ROOT,):
        raise RegistryError(f"{where}: {value!r} is outside panels/")
    if path.suffix != suffix:
        raise RegistryError(f"{where}: {value!r} must end with {suffix}")
    if not (web_root / value).is_file():
        raise RegistryError(f"{where}: missing file {value!r}")
    return value


def _surface(sid: str, raw: Any) -> Surface:
    where = f"surface {sid!r}"
    if not isinstance(sid, str) or not _ID.match(sid):
        raise RegistryError(f"{where}: id must match {_ID.pattern}")
    if sid in RESERVED:
        raise RegistryError(f"{where}: reserved route name")
    if not isinstance(raw, dict):
        raise RegistryError(f"{where}: must be a mapping")
    if raw.get("grammar") not in GRAMMARS:
        raise RegistryError(f"{where}: grammar must be one of {sorted(GRAMMARS)}")
    slots = raw.get("slots")
    if not isinstance(slots, list) or not slots or not all(isinstance(s, str) and _ID.match(s) for s in slots):
        raise RegistryError(f"{where}: slots must be a non-empty list of ids")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RegistryError(f"{where}: title is required")
    return Surface(sid, title, _role(raw.get("min_role"), where), raw["grammar"], tuple(slots))


def _panel(raw: Any, surfaces: Mapping[str, Surface], web_root: Path) -> Panel:
    if not isinstance(raw, dict):
        raise RegistryError("panel entries must be mappings")
    pid = raw.get("id")
    where = f"panel {pid!r}"
    if not isinstance(pid, str) or not _PANEL_ID.match(pid):
        raise RegistryError(f"{where}: id must look like domain.name")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RegistryError(f"{where}: title is required")
    surface = surfaces.get(raw.get("surface"))
    if surface is None:
        raise RegistryError(f"{where}: unknown surface {raw.get('surface')!r}")
    if raw.get("slot") not in surface.slots:
        raise RegistryError(f"{where}: unknown slot {raw.get('slot')!r} on {surface.id}")
    order = raw.get("order")
    if not isinstance(order, int) or isinstance(order, bool):
        raise RegistryError(f"{where}: order must be an integer")
    requires = raw.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(k, str) and _CAP_KEY.match(k) for k in requires):
        raise RegistryError(f"{where}: requires must be dotted CAP-001 keys")
    inventory = raw.get("inventory")
    if inventory is not None and (not isinstance(inventory, str) or not _PANEL_ID.match(inventory)):
        raise RegistryError(f"{where}: inventory must be a concept id like mobility.move")
    css = raw.get("css", [])
    if not isinstance(css, list):
        raise RegistryError(f"{where}: css must be a list")
    return Panel(
        id=pid,
        title=title,
        surface=surface.id,
        slot=raw["slot"],
        order=order,
        requires=tuple(requires),
        inventory=inventory,
        min_role=_role(raw.get("min_role", surface.min_role), where),
        module=_asset(raw.get("module"), ".js", web_root, where),
        css=tuple(_asset(item, ".css", web_root, where) for item in css),
    )


def load_registry(path: Path, web_root: Path) -> Registry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("version") != 1:
        raise RegistryError("panels.yaml: version must be 1")
    raw_surfaces = raw.get("surfaces")
    if not isinstance(raw_surfaces, dict):
        raise RegistryError("panels.yaml: surfaces must be a mapping")
    surfaces = {sid: _surface(sid, body) for sid, body in raw_surfaces.items()}
    panels: list[Panel] = []
    seen_ids: set[str] = set()
    seen_orders: set[tuple[str, str, int]] = set()
    for entry in raw.get("panels") or []:
        panel = _panel(entry, surfaces, web_root)
        if panel.id in seen_ids:
            raise RegistryError(f"panel {panel.id!r}: duplicate id")
        key = (panel.surface, panel.slot, panel.order)
        if key in seen_orders:
            raise RegistryError(f"panel {panel.id!r}: duplicate order {panel.order} in {panel.surface}/{panel.slot}")
        seen_ids.add(panel.id)
        seen_orders.add(key)
        panels.append(panel)
    return Registry(surfaces=surfaces, panels=tuple(panels))
```

- [ ] **Step 4: 출하 레지스트리와 첫 패널 자리 만들기**

`W/panels.yaml`:

```yaml
# D-204 — 역할별 CORE 화면의 유일한 조립 규칙.
# 화면은 역할이 정하고(concept 16 §9.1), 패널은 capability가 끼운다(§8).
# requires: CAP-001 키. 하나라도 거짓이면 패널은 매니페스트에서 빠진다(not_provided).
# min_role: 생략하면 화면의 min_role. UI 판단은 표시용이고 권한은 API가 지킨다.
version: 1
surfaces:
  console: {title: 운용, min_role: viewer, grammar: spatial, slots: [banner, sense, observe, act]}
  setup: {title: 작업 준비, min_role: operator, grammar: procedure, slots: [main]}
  device: {title: 설치·정비, min_role: administrator, grammar: procedure, slots: [main]}
panels:
  - id: system.events
    title: 최근 이벤트
    surface: device
    slot: main
    order: 90
    module: panels/system/events.js
    css: [panels/system/events.css]
```

`W/panels/system/events.js` (임시, Task 8에서 교체):

```js
export function mount() {}
```

`W/panels/system/events.css` (임시, Task 8에서 교체):

```css
/* D-204 system.events — Task 8에서 채운다. */
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest src/core/core_api_web/test/test_ui_registry.py -q`
Expected: PASS (전부)

- [ ] **Step 6: 커밋**

```bash
git add src/core/core_api_web/core_api_web/api/ui_registry.py src/core/core_api_web/core_api_web/web/panels.yaml src/core/core_api_web/core_api_web/web/panels src/core/core_api_web/test/test_ui_registry.py
git commit -m "feat(core_api_web): D-204 panel registry with startup validation"
```

---

### Task 3: 매니페스트 필터 (순수 함수)

**Files:**
- Create: `A/ui_manifest.py`
- Test: `src/core/core_api_web/test/test_ui_manifest.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""D-204 — 매니페스트는 CAP-001과 역할로 패널을 거르고, not_provided는 생략한다."""

from __future__ import annotations

from core_api_web.api.ui_manifest import build_manifest
from core_api_web.api.ui_registry import Panel, Registry, Surface

SURFACES = {
    "console": Surface("console", "운용", "viewer", "spatial", ("banner", "sense", "observe", "act")),
    "setup": Surface("setup", "작업 준비", "operator", "procedure", ("main",)),
    "device": Surface("device", "설치·정비", "administrator", "procedure", ("main",)),
}


def _panel(pid, surface="console", slot="act", order=10, requires=(), inventory=None, min_role="viewer"):
    return Panel(pid, pid, surface, slot, order, tuple(requires), inventory, min_role,
                 f"panels/{pid.replace('.', '/')}.js", ())


REGISTRY = Registry(SURFACES, (
    _panel("drive.teleop", order=40, requires=["teleop"], inventory="mobility.move", min_role="operator"),
    _panel("safety.hero", slot="sense", order=10),
    _panel("vision.front", slot="observe", order=10, requires=["vision.enabled"]),
    _panel("docking.run", order=50, requires=["docking.supported"], inventory="mobility.dock"),
    _panel("nav.slam", surface="setup", slot="main", requires=["slam"], min_role="operator"),
    _panel("system.events", surface="device", slot="main", order=90, min_role="administrator"),
))

CAPS = {"teleop": True, "slam": True, "vision": {"enabled": False}, "docking": {"supported": True}}


def ids(manifest):
    return [panel["id"] for panel in manifest["panels"]]


def test_a_false_or_missing_flag_is_omitted_not_greyed():
    manifest = build_manifest(REGISTRY, "console", "operator", CAPS, [])
    assert "vision.front" not in ids(manifest)
    assert "vision.front" not in ids(build_manifest(REGISTRY, "console", "operator", {"teleop": True}, []))


def test_panels_come_in_slot_then_order_sequence():
    manifest = build_manifest(REGISTRY, "console", "operator", CAPS, [])
    assert ids(manifest) == ["safety.hero", "drive.teleop", "docking.run"]


def test_a_lower_role_does_not_see_the_panel():
    assert "drive.teleop" not in ids(build_manifest(REGISTRY, "console", "viewer", CAPS, []))


def test_an_inventory_descriptor_carries_state_and_reason():
    descriptors = [{"id": "mobility.move", "state": "blocked", "reason": "runtime_mode:core"}]
    manifest = build_manifest(REGISTRY, "console", "operator", CAPS, descriptors)
    teleop = next(p for p in manifest["panels"] if p["id"] == "drive.teleop")
    assert (teleop["state"], teleop["reason"]) == ("blocked", "runtime_mode:core")
    hero = next(p for p in manifest["panels"] if p["id"] == "safety.hero")
    assert (hero["state"], hero["reason"]) == ("available", None)


def test_a_not_provided_descriptor_is_omitted():
    descriptors = [{"id": "mobility.dock", "state": "not_provided", "reason": None}]
    assert "docking.run" not in ids(build_manifest(REGISTRY, "console", "operator", CAPS, descriptors))


def test_surfaces_lists_only_what_this_role_can_open_with_titles():
    viewer = build_manifest(REGISTRY, "console", "viewer", CAPS, [])
    assert viewer["surfaces"] == [{"id": "console", "title": "운용"}]
    admin = build_manifest(REGISTRY, "console", "administrator", CAPS, [])
    assert [s["id"] for s in admin["surfaces"]] == ["console", "setup", "device"]


def test_the_manifest_names_the_surface_role_grammar_and_asset_paths():
    manifest = build_manifest(REGISTRY, "device", "administrator", CAPS, [])
    assert manifest["surface"] == "device"
    assert manifest["grammar"] == "procedure"
    assert manifest["role"] == "administrator"
    assert manifest["panels"][0]["module"] == "/assets/panels/system/events.js"
    assert manifest["panels"][0]["title"] == "system.events"


def test_the_revision_moves_only_when_the_content_moves():
    one = build_manifest(REGISTRY, "console", "operator", CAPS, [])["revision"]
    assert one == build_manifest(REGISTRY, "console", "operator", dict(CAPS), [])["revision"]
    assert one != build_manifest(REGISTRY, "console", "operator", {**CAPS, "teleop": False}, [])["revision"]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/core_api_web/test/test_ui_manifest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core_api_web.api.ui_manifest'`

- [ ] **Step 3: `A/ui_manifest.py` 구현**

```python
"""core_api_web.api.ui_manifest — 화면 매니페스트 (D-204). 순수 함수, ROS 무의존.

CAP-001은 기능 게이트, inventory descriptors는 동적 상태다(D-68). 둘을 읽기만 하고
합치지 않는다. `not_provided`는 회색이 아니라 생략이다(concept 16 §8).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from core_common.capability import Capability

from core_api_web.api.deps import ROLE_RANK
from core_api_web.api.ui_registry import Panel, Registry

ASSET_PREFIX = "/assets/"
NOT_PROVIDED = "not_provided"


def _visible(panel: Panel, role: str, capability: Capability, by_id: Mapping[str, Mapping[str, Any]]) -> bool:
    if ROLE_RANK.get(role, -1) < ROLE_RANK[panel.min_role]:
        return False
    if not all(capability.supports(key) for key in panel.requires):
        return False
    descriptor = by_id.get(panel.inventory) if panel.inventory else None
    return not (descriptor and descriptor.get("state") == NOT_PROVIDED)


def build_manifest(
    registry: Registry,
    surface_id: str,
    role: str,
    capabilities: Mapping[str, Any],
    descriptors: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    surface = registry.surfaces[surface_id]
    capability = Capability(dict(capabilities))
    by_id = {str(item.get("id")): item for item in descriptors}
    visible = [panel for panel in registry.panels if _visible(panel, role, capability, by_id)]
    slot_rank = {slot: index for index, slot in enumerate(surface.slots)}
    mine = sorted((p for p in visible if p.surface == surface.id), key=lambda p: (slot_rank[p.slot], p.order))
    open_surfaces = {panel.surface for panel in visible}
    panels = []
    for panel in mine:
        descriptor = by_id.get(panel.inventory, {}) if panel.inventory else {}
        panels.append({
            "id": panel.id,
            "title": panel.title,
            "slot": panel.slot,
            "order": panel.order,
            "module": ASSET_PREFIX + panel.module,
            "css": [ASSET_PREFIX + path for path in panel.css],
            "state": descriptor.get("state", "available"),
            "reason": descriptor.get("reason"),
        })
    body = {
        "surface": surface.id,
        "grammar": surface.grammar,
        "role": role,
        "surfaces": [{"id": s.id, "title": s.title} for s in registry.surfaces.values() if s.id in open_surfaces],
        "panels": panels,
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {**body, "revision": f"sha256:{digest}"}
```

테스트 `REGISTRY`의 `_panel`은 `title`에 id를 넣으므로 `test_the_manifest_names...`의 `title == "system.events"`가 성립한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/core/core_api_web/test/test_ui_manifest.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/core/core_api_web/core_api_web/api/ui_manifest.py src/core/core_api_web/test/test_ui_manifest.py
git commit -m "feat(core_api_web): D-204 surface manifest filters panels by CAP-001 and role"
```

---

### Task 4: 매니페스트 API와 레지스트리 적재

**Files:**
- Create: `A/v1/ui.py`
- Modify: `A/v1/routes.py` (import와 `__all__`)
- Modify: `A/app.py` (레지스트리 적재, 라우터 등록)
- Test: `src/core/core/test/test_ui_surfaces_api.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""D-204 — 실제 CoreServices 위에서 매니페스트 API가 역할과 CAP-001을 따른다."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.services import CoreServices
from core_api_web.api.app import create_app
from core_common.profile import RobotProfile

CONFIG = Path(__file__).parent.parent / "config"
ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


@pytest.fixture
def tc(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", tmp_path / "rosy.yaml")
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    config = yaml.safe_load((CONFIG / "rosy_default.yaml").read_text(encoding="utf-8"))
    config.update(yaml.safe_load((CONFIG / "rosy_dev_auth.yaml").read_text(encoding="utf-8")))
    profile = RobotProfile.load(CONFIG / "profile.pinky_pro.yaml")
    caps = yaml.safe_load((CONFIG / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
    return TestClient(create_app(config, services))


def test_an_administrator_gets_the_device_surface_with_the_events_panel(tc):
    body = tc.get("/api/v1/ui/surfaces/device", headers=ADMIN).json()
    assert body["surface"] == "device"
    assert body["role"] == "administrator"
    assert "system.events" in [panel["id"] for panel in body["panels"]]
    assert "device" in [surface["id"] for surface in body["surfaces"]]


def test_a_viewer_gets_no_device_panels_and_no_device_link(tc):
    body = tc.get("/api/v1/ui/surfaces/device", headers=VIEWER).json()
    assert body["panels"] == []
    assert "device" not in [surface["id"] for surface in body["surfaces"]]


def test_an_unknown_surface_is_404(tc):
    assert tc.get("/api/v1/ui/surfaces/garage", headers=ADMIN).status_code == 404


def test_the_manifest_needs_a_token(tc):
    assert tc.get("/api/v1/ui/surfaces/device").status_code == 401
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/core/test/test_ui_surfaces_api.py -q`
Expected: FAIL — 404 (라우트 없음), 첫 테스트는 `KeyError: 'surface'`

- [ ] **Step 3: `A/v1/ui.py` 작성**

```python
"""core_api_web.api.v1.ui — 역할별 화면 매니페스트 (D-204)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.ui_manifest import build_manifest
from core_api_web.api.v1.common import viewer
from core_common.domain.capabilities import hardware_runtime_reason, withhold_hardware_flags

ui_router = APIRouter(prefix="/api/v1/ui", tags=["ui"])


@ui_router.get("/surfaces/{surface}")
def surface_manifest(surface: str, request: Request, auth: AuthContext = Depends(viewer),
                     svc: CoreServicesLike = Depends(get_services)):
    registry = request.app.state.ui_registry
    if surface not in registry.surfaces:
        raise ApiError("NOT_FOUND", 404, "unknown surface")
    # /system/capabilities 와 같은 CAP-001 본문을 읽는다 — 화면과 게이트가 다른 사실을 보면 안 된다.
    caps = svc.capability.to_dict()
    reason = hardware_runtime_reason(svc.config, svc.state)
    if reason:
        caps = withhold_hardware_flags(caps, reason)
    descriptors = svc.inventory().get("descriptors", [])
    return build_manifest(registry, surface, auth.role, caps, descriptors)
```

(`system.py:34`와 같은 출처 `core_common.domain.capabilities`에서 import한다. `test_v1_import_boundary.py`는 `core_features`만 막는다. `svc.inventory()`는 dict이고 `descriptors`는 이미 dict 목록이다 — `core/services.py:485`.)

- [ ] **Step 4: `routes.py`에 등록**

`A/v1/routes.py`의 import 블록 알파벳 순서 자리(`from core_api_web.api.v1.traffic import traffic_router` 다음)에 추가:

```python
from core_api_web.api.v1.ui import ui_router
```

`__all__` 목록의 `"traffic_router",` 다음에 `"ui_router",`를 추가한다.

- [ ] **Step 5: `app.py`에서 레지스트리 적재와 라우터 등록**

import 블록:

```python
from core_api_web.api.ui_registry import load_registry
```

`from core_api_web.api.v1.routes import (...)` 목록에 `ui_router,`를 추가한다(`traffic_router,` 다음).

`dashboard_assets = {...}` 딕셔너리 바로 뒤에:

```python
    # D-204 — 역할별 화면의 조립 규칙. 틀리면 여기서 예외로 기동이 멈춘다.
    ui_registry = load_registry(web_root / "panels.yaml", web_root)
    app.state.ui_registry = ui_registry
```

`app.include_router(intent_router)` 다음 줄에:

```python
    app.include_router(ui_router)
```

- [ ] **Step 6: 통과 확인**

Run: `python -m pytest src/core/core/test/test_ui_surfaces_api.py src/core/core_api_web/test -q`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add src/core/core_api_web/core_api_web/api/v1/ui.py src/core/core_api_web/core_api_web/api/v1/routes.py src/core/core_api_web/core_api_web/api/app.py src/core/core/test/test_ui_surfaces_api.py
git commit -m "feat(api): D-204 GET /api/v1/ui/surfaces/{surface}"
```

---

### Task 5: `/assets/*` 허용목록과 화면 페이지 라우트

**Files:**
- Create: `W/shell/surface.html`
- Create: `W/shell/shell.js`, `W/shell/mount.js`, `W/shell/store.js`, `W/shell/shell.css` (Task 6·7에서 본문, 여기서는 한 줄 주석)
- Modify: `A/app.py`
- Modify: `src/core/core/test/test_dashboard_no_bundler.py` (허용목록 문구)
- Test: `src/core/core_api_web/test/test_surface_pages.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""D-204 — 화면 페이지는 한 템플릿에서 문법·슬롯을 채우고, 자산은 정확한 허용목록으로만 나간다."""

from __future__ import annotations

import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core_api_web.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app({}, SimpleNamespace()))


def test_shell_and_registered_panel_assets_are_served():
    client = _client()
    for path in ("shell/shell.js", "shell/mount.js", "shell/store.js", "shell/shell.css",
                 "panels/system/events.js", "panels/system/events.css", "client.js", "dom.js"):
        response = client.get(f"/assets/{path}")
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-cache"


def test_anything_outside_the_allowlist_is_404():
    client = _client()
    for path in ("panels/nope.js", "../api/app.py", "shell/surface.html", "panels.yaml", "AGENTS.md"):
        assert client.get(f"/assets/{path}").status_code == 404, path


def test_the_legacy_dashboard_assets_still_work():
    assert _client().get("/dashboard/assets/app.js").status_code == 200


def test_each_surface_page_declares_its_grammar_and_slots():
    client = _client()
    device = client.get("/device")
    assert device.status_code == 200
    assert 'data-surface="device"' in device.text
    assert '<ui-shell grammar="procedure">' in device.text
    assert re.findall(r'data-slot="([a-z_]+)"', device.text) == ["main"]
    console = client.get("/console").text
    assert '<ui-shell grammar="spatial">' in console
    assert re.findall(r'data-slot="([a-z_]+)"', console) == ["banner", "sense", "observe", "act"]


def test_a_surface_page_keeps_the_dashboard_csp_and_has_no_inline_code():
    response = _client().get("/setup")
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp
    assert "<script>" not in response.text
    assert "style=" not in response.text
    assert "{{" not in response.text


def test_the_one_estop_is_in_the_shell_topbar():
    text = _client().get("/device").text
    assert text.count('id="shell-estop"') == 1
    assert 'kind="irreversible"' in text
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/core_api_web/test/test_surface_pages.py -q`
Expected: FAIL — `/assets/...` 404, `/device` 404

- [ ] **Step 3: 셸 파일 자리 만들기**

`W/shell/shell.js`, `W/shell/mount.js`, `W/shell/store.js` 각각 내용 한 줄:

```js
// D-204 shell — Task 6/7에서 채운다.
```

`W/shell/shell.css`:

```css
/* D-204 shell — Task 7에서 채운다. */
```

- [ ] **Step 4: `W/shell/surface.html` 작성**

```html
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#111614">
  <title>Rosy OS — {{title}}</title>
  <link rel="stylesheet" href="/common/tokens.css">
  <link rel="stylesheet" href="/common/components.css">
  <link rel="stylesheet" href="/assets/shell/shell.css">
  <script type="module" src="/common/ui.js"></script>
  <script type="module" src="/assets/shell/shell.js"></script>
</head>
<body data-surface="{{surface}}">
  <ui-shell grammar="{{grammar}}">
    <ui-topbar>
      <ui-brand><b>ROSY</b><small>{{title}}</small></ui-brand>
      <nav id="surface-switch" class="surface-switch" aria-label="화면 전환"></nav>
      <span data-spacer></span>
      <ui-text id="shell-notice" scale="label" role="status"></ui-text>
      <ui-tag id="shell-role">인증 대기</ui-tag>
      <ui-button kind="irreversible" id="shell-estop" type="button">비상 정지</ui-button>
    </ui-topbar>
    <main id="surface-main" class="surface-main">
      <ui-empty id="surface-status">화면을 불러오는 중입니다.</ui-empty>
{{slots}}
    </main>
  </ui-shell>
</body>
</html>
```

- [ ] **Step 5: `app.py`에 허용목록과 화면 라우트 추가**

import 블록에 `import html`과 `from fastapi.responses import HTMLResponse`를 추가한다(`FileResponse, RedirectResponse`와 같은 줄로 합친다).

Task 4에서 넣은 `app.state.ui_registry = ui_registry` 다음에:

```python
    # 셸 파일은 레지스트리 밖의 고정 집합이다. surface.html 은 템플릿이라 자산으로 내보내지 않는다.
    shell_assets = {
        "shell/shell.js": "application/javascript",
        "shell/mount.js": "application/javascript",
        "shell/store.js": "application/javascript",
        "shell/shell.css": "text/css",
    }
    # 정확히 일치하는 집합이다 — 폴더 스캔으로 바꾸지 않는다(경로 순회 방어).
    web_assets = {**dashboard_assets, **shell_assets, **ui_registry.assets()}
    surface_template = (web_root / "shell" / "surface.html").read_text(encoding="utf-8")
    page_csp = (
        "default-src 'self'; connect-src 'self' ws: wss:; "
        "img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'"
    )
```

기존 `/dashboard` 라우트의 CSP 문자열을 `page_csp`로 바꾼다:

```python
    @app.get("/dashboard", include_in_schema=False)
    def dashboard():
        return FileResponse(
            web_root / "index.html",
            media_type="text/html",
            headers={"Cache-Control": "no-cache", "Content-Security-Policy": page_csp},
        )
```

기존 `dashboard_asset` 함수를 두 라우트가 공유하는 형태로 바꾼다:

```python
    def _web_asset(asset_name: str):
        media_type = web_assets.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return FileResponse(web_root / asset_name, media_type=media_type,
                            headers={"Cache-Control": "no-cache"})

    # D-204 — 새 접두. /dashboard/assets 는 S4에서 /dashboard 가 사라질 때 함께 사라진다.
    app.add_api_route("/assets/{asset_name:path}", _web_asset, include_in_schema=False)
    app.add_api_route("/dashboard/assets/{asset_name:path}", _web_asset, include_in_schema=False)

    def _surface_page(surface):
        slots = "\n".join(
            f'      <div class="surface-slot" data-slot="{slot}"></div>' for slot in surface.slots
        )
        body = (surface_template
                .replace("{{title}}", html.escape(surface.title))
                .replace("{{surface}}", surface.id)
                .replace("{{grammar}}", surface.grammar)
                .replace("{{slots}}", slots))

        def page():
            return HTMLResponse(body, headers={"Cache-Control": "no-cache", "Content-Security-Policy": page_csp})

        return page

    for surface in ui_registry.surfaces.values():
        app.add_api_route(f"/{surface.id}", _surface_page(surface), include_in_schema=False, methods=["GET"])
```

(`surface.id`, `surface.grammar`, 슬롯 이름은 레지스트리 검증에서 `^[a-z][a-z0-9_]*$`로 제한되므로 escape가 필요 없다. 제목만 사람이 쓴 글이라 escape한다.)

- [ ] **Step 6: `test_dashboard_no_bundler.py` 문구 갱신**

`test_dashboard_assets_are_an_explicit_allowlist`는 `app.py`에 `"dashboard_assets"`, `'"styles.css"'`, `'"app.js"'`, `"index.html"` 문자열이 남아 있는지만 본다. 위 변경 뒤에도 모두 남으므로 수정 없이 통과해야 한다. 한 줄만 추가해 새 허용목록이 스캔이 아님을 고정한다:

```python
    assert "web_assets = {**dashboard_assets, **shell_assets, **ui_registry.assets()}" in app
```

- [ ] **Step 7: 통과 확인**

Run: `python -m pytest src/core/core_api_web/test src/core/core/test/test_dashboard.py src/core/core/test/test_dashboard_no_bundler.py src/core/core/test/test_ui_surfaces_api.py -q`
Expected: PASS

- [ ] **Step 8: 커밋**

```bash
git add src/core/core_api_web/core_api_web/api/app.py src/core/core_api_web/core_api_web/web/shell src/core/core_api_web/test/test_surface_pages.py src/core/core/test/test_dashboard_no_bundler.py
git commit -m "feat(core_api_web): D-204 surface pages and a generated asset allowlist"
```

---

### Task 6: 패널 mount와 store

**Files:**
- Modify: `W/shell/mount.js`
- Modify: `W/shell/store.js`

JS 단위 실행기는 이 저장소에 없다(D-75, 새 도구 체인을 들이지 않는다). 동작은 Task 9의 브라우저 테스트가, 구조는 Task 10의 정적 게이트가 확인한다.

- [ ] **Step 1: `W/shell/store.js`**

```js
// 패널이 서버 상태를 받는 유일한 창구(D-204 §4).
// S1은 폴링만 싣는다. 공유 WebSocket 구독(select)은 운용 화면을 옮길 때 이 파일에 더한다.
// scope 하나가 패널 하나다. 패널이 내려가면 셸이 scope를 닫아 남은 타이머와 늦은 응답을 끊는다.

export function createStore(api) {
  return {
    scope() {
      const timers = new Set();
      let closed = false;
      return {
        poll(path, intervalMs, onData, onError = () => {}) {
          let stopped = false;
          const live = () => !stopped && !closed;
          const tick = () => api(path).then(
            (data) => { if (live()) onData(data); },
            (error) => { if (live()) onError(error); },
          );
          tick();
          const timer = setInterval(tick, intervalMs);
          timers.add(timer);
          return () => {
            stopped = true;
            clearInterval(timer);
            timers.delete(timer);
          };
        },
        stopAll() {
          closed = true;
          timers.forEach(clearInterval);
          timers.clear();
        },
      };
    },
  };
}
```

- [ ] **Step 2: `W/shell/mount.js`**

```js
// 매니페스트의 패널을 슬롯에 끼우고 내린다(D-204 §4).
// 한 패널의 import 실패나 mount 예외는 그 자리에만 머문다 — 나머지 패널과 e-stop은 계속 돈다.
// 자리(ui-section)를 await 전에 먼저 붙이므로 화면 순서는 매니페스트 순서 그대로다.

function failure(section, panel, error) {
  const note = document.createElement("ui-empty");
  note.textContent = `${panel.title} 패널을 열지 못했습니다: ${error.message || error}`;
  section.replaceChildren(note);
  section.dataset.failed = "true";
}

export async function mountPanels(root, panels, contextFor) {
  const handles = [];
  for (const panel of panels) {
    const slot = root.querySelector(`[data-slot="${panel.slot}"]`);
    if (!slot) continue;
    const section = document.createElement("ui-section");
    section.dataset.panel = panel.id;
    section.dataset.state = panel.state;
    section.setAttribute("aria-label", panel.title);
    slot.append(section);
    const ctx = contextFor(panel);
    const handle = { section, ctx, unmount: null };
    handles.push(handle);
    try {
      const module = await import(panel.module);
      const unmount = module.mount(section, ctx);
      handle.unmount = typeof unmount === "function" ? unmount : null;
    } catch (error) {
      ctx.store.stopAll();
      failure(section, panel, error);
    }
  }
  return {
    unmountAll() {
      for (const { section, ctx, unmount } of handles) {
        try {
          if (unmount) unmount();
        } catch (_error) {
          // A broken unmount must not keep the next panel mounted.
        }
        ctx.store.stopAll();
        section.remove();
      }
    },
  };
}
```

- [ ] **Step 3: 문법 확인**

Run: `node --check src/core/core_api_web/core_api_web/web/shell/store.js && node --check src/core/core_api_web/core_api_web/web/shell/mount.js`
Expected: 출력 없음, exit 0. (`node`는 문법 검사에만 쓰고 저장소 도구로 들이지 않는다.)

- [ ] **Step 4: 커밋**

```bash
git add src/core/core_api_web/core_api_web/web/shell/store.js src/core/core_api_web/core_api_web/web/shell/mount.js
git commit -m "feat(web): D-204 panel mount isolation and per-panel polling scope"
```

---

### Task 7: 셸 부팅, 화면 전환기, e-stop

**Files:**
- Modify: `W/shell/shell.js`
- Modify: `W/shell/shell.css`

- [ ] **Step 1: `W/shell/shell.js`**

```js
// 역할별 화면의 셸(D-204). 매니페스트를 받아 패널을 조립하고,
// 세 화면이 공유하는 것 — 화면 전환기, 역할 표시, 비상 정지 하나 — 만 소유한다.
// 로그인은 아직 /dashboard 가 소유한다(같은 탭의 sessionStorage 토큰을 그대로 쓴다, D-193 6).

import { api, session } from "../client.js";
import { mountPanels } from "./mount.js";
import { createStore } from "./store.js";

const REFRESH_MS = 5_000;
const surface = document.body.dataset.surface;
const status = document.getElementById("surface-status");
const notice = document.getElementById("shell-notice");
const store = createStore(api);
let mounted = null;
let revision = null;

function showStatus(text) {
  status.hidden = !text;
  status.textContent = text || "";
}

function renderSwitch(surfaces) {
  const nav = document.getElementById("surface-switch");
  nav.replaceChildren(...surfaces.map(({ id, title }) => {
    const link = document.createElement("a");
    link.href = `/${id}`;
    link.textContent = title;
    if (id === surface) link.setAttribute("aria-current", "page");
    return link;
  }));
}

async function assemble() {
  const manifest = await api(`/api/v1/ui/surfaces/${surface}`);
  if (manifest.revision === revision) return;
  revision = manifest.revision;
  document.getElementById("shell-role").textContent = manifest.role;
  renderSwitch(manifest.surfaces);
  if (mounted) mounted.unmountAll();
  mounted = await mountPanels(document, manifest.panels, (panel) => ({
    api,
    store: store.scope(),
    role: manifest.role,
    panel,
  }));
  showStatus(manifest.panels.length ? "" : "이 역할로 이 화면에 보일 패널이 없습니다.");
}

function refresh() {
  assemble().catch((error) => {
    revision = null;
    showStatus(`화면 구성을 받지 못했습니다: ${error.message}. 잠시 뒤 다시 시도합니다.`);
  });
}

document.getElementById("shell-estop").addEventListener("click", async () => {
  try {
    await api("/api/v1/safety/stop", { method: "POST" });
    notice.textContent = "비상 정지를 보냈습니다.";
  } catch (error) {
    notice.textContent = `비상 정지 실패: ${error.message}`;
  }
});

if (!session.token) {
  showStatus("로그인이 필요합니다. 같은 탭에서 /dashboard 로 로그인한 뒤 이 화면을 다시 여세요.");
} else {
  refresh();
  setInterval(refresh, REFRESH_MS);
}
```

- [ ] **Step 2: `W/shell/shell.css`**

```css
/* D-204 셸 — 배치만 정한다. 색과 크기는 토큰만 쓴다(D-129, D-203). */
.surface-switch { display: flex; gap: var(--space-3); }
.surface-switch a { color: var(--nominal-quiet); font: var(--text-label)/1.4 var(--body); text-decoration: none; }
.surface-switch a[aria-current="page"] { color: inherit; text-decoration: underline; }
.surface-main { display: grid; gap: var(--space-5); padding: var(--space-5); }
.surface-slot { display: grid; gap: var(--space-5); min-width: 0; }
.surface-slot:empty { display: none; }
ui-section[data-failed="true"] { border-style: dashed; }
```

- [ ] **Step 3: 토큰 이름 확인**

Run: `grep -c -- "--space-3:\|--space-5:\|--nominal-quiet:\|--text-label:\|--body:" src/core/web_common/tokens.css`
Expected: 5 (2026-09-24 기준 모두 존재 확인됨).

- [ ] **Step 4: 문법 확인**

Run: `node --check src/core/core_api_web/core_api_web/web/shell/shell.js`
Expected: exit 0

- [ ] **Step 5: 기존 공용 컨트롤 게이트 실행**

Run: `python -m pytest src/core/core/test -q -k "shared_controls or type_scale or palette or dashboard"`
Expected: PASS. 게이트가 `web/` 아래 CSS를 스캔하다 `shell.css`의 값을 거부하면, 그 게이트가 허용하는 토큰으로 고친다(게이트를 완화하지 않는다).

- [ ] **Step 6: 커밋**

```bash
git add src/core/core_api_web/core_api_web/web/shell/shell.js src/core/core_api_web/core_api_web/web/shell/shell.css
git commit -m "feat(web): D-204 surface shell with switcher and the one e-stop"
```

---

### Task 8: 첫 패널 — 최근 이벤트

**Files:**
- Modify: `W/panels/system/events.js`
- Modify: `W/panels/system/events.css`

`/dashboard`의 이벤트 카드(`index.html:660-670`, `app.js` `renderEvents`)는 S2에서 지운다. 이 단계에서는 둘이 공존한다.

- [ ] **Step 1: `W/panels/system/events.js`**

```js
// D-204 system.events — 설치·정비 화면. "방금 무슨 일이 있었나"를 최신순 10개로 본다.
// 서버가 붙인 severity만 색이 된다. info는 정상이므로 색이 없다(D-82).

const LIMIT = 10;
const REFRESH_MS = 5_000;

function text(scale, value) {
  const node = document.createElement("ui-text");
  node.setAttribute("scale", scale);
  node.textContent = value;
  return node;
}

function emptyRow(message) {
  const row = document.createElement("li");
  const note = document.createElement("ui-empty");
  note.textContent = message;
  row.append(note);
  return row;
}

function eventRow(event) {
  const row = document.createElement("li");
  const time = document.createElement("time");
  time.className = "event-time";
  time.textContent = event.ts ? new Date(event.ts).toLocaleTimeString("ko-KR") : "—";
  const type = document.createElement("span");
  type.className = "event-type";
  type.textContent = event.type || "unknown.event";
  const severity = document.createElement("span");
  const level = event.severity || "info";
  severity.className = `event-severity ${level}`;
  severity.textContent = level.toUpperCase();
  row.append(time, type, severity);
  return row;
}

export function mount(el, ctx) {
  const head = document.createElement("ui-head");
  head.append(text("label", "최근 이벤트"));
  const list = document.createElement("ol");
  list.className = "event-list";
  list.append(emptyRow("불러오는 중입니다."));
  el.append(head, list);

  function render(payload) {
    const events = [...(payload.events || [])].reverse().slice(0, LIMIT);
    list.replaceChildren(...(events.length ? events.map(eventRow) : [emptyRow("수신된 이벤트가 없습니다.")]));
  }

  function fail(error) {
    list.replaceChildren(emptyRow(`이벤트를 받지 못했습니다: ${error.message}`));
  }

  return ctx.store.poll(`/api/v1/events?limit=${LIMIT}`, REFRESH_MS, render, fail);
}
```

- [ ] **Step 2: `W/panels/system/events.css`**

`W/styles.css:907-921`, `941`, `961-962`의 규칙을 그대로 옮긴다(S2에서 `styles.css` 쪽을 지운다).

```css
/* D-204 system.events — 이관 중 styles.css 의 같은 규칙과 공존한다(S2에서 그쪽을 지운다). */
.event-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0 var(--space-5); margin: 0; padding: 0; list-style: none; }
.event-list li:not(:has(ui-empty)) {
  display: grid;
  grid-template-columns: 76px 1fr auto;
  align-items: start;
  gap: var(--space-3);
  min-width: 0;
  padding: var(--space-3) 0;
  border-top: 1px solid var(--surface-line);
}
.event-time, .event-severity { color: var(--nominal-quiet); font: var(--text-micro)/1.4 var(--mono); }
.event-type { overflow: hidden; font: var(--text-label)/1.4 var(--mono); text-overflow: ellipsis; white-space: nowrap; }
/* info는 정상이므로 색이 없다. 경고와 오류만 색을 쓴다. */
.event-severity.error, .event-severity.critical { color: var(--status-crit); }
.event-severity.warning { color: var(--status-warn); }
```

`styles.css:941`, `961-962`의 반응형 규칙을 읽고, 감싸는 `@media` 조건을 그대로 복사해 파일 끝에 붙인다:

Run: `sed -n 930,965p src/core/core_api_web/core_api_web/web/styles.css`
Expected: `.event-list { grid-template-columns: 1fr; }`와 `.event-list li... 62px 1fr`를 감싸는 `@media (...)` 블록 두 개. 그 두 블록에서 `.event-*` 규칙만 남겨 붙인다.

- [ ] **Step 3: 셸이 패널 CSS를 링크하게 하기**

`W/shell/mount.js`의 `mountPanels` 안, `const section = ...` 앞에 한 줄을 넣는다:

```js
    for (const href of panel.css || []) linkStyle(href);
```

파일 위쪽 `failure` 함수 앞에 추가한다:

```js
function linkStyle(href) {
  if (document.head.querySelector(`link[data-panel-css="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.panelCss = href;
  document.head.append(link);
}
```

(`<link>` 삽입은 `style-src 'self'`로 허용된다. inline style이 아니다.)

- [ ] **Step 4: 문법과 기존 게이트**

Run: `node --check src/core/core_api_web/core_api_web/web/panels/system/events.js && node --check src/core/core_api_web/core_api_web/web/shell/mount.js && python -m pytest src/core/core/test -q -k "shared_controls or type_scale or palette"`
Expected: exit 0, PASS

- [ ] **Step 5: 커밋**

```bash
git add src/core/core_api_web/core_api_web/web/panels/system src/core/core_api_web/core_api_web/web/shell/mount.js
git commit -m "feat(web): D-204 first panel, recent events on the device surface"
```

---

### Task 9: 브라우저 테스트 (선택 실행)

**Files:**
- Test: `test/test_surface_shell_browser.py`

실제 FastAPI 앱을 TestClient로 띄우고, Playwright 라우트가 모든 요청을 그 앱으로 넘긴다. 매니페스트 응답에만 깨진 패널 하나를 끼워 넣어 격리를 확인한다.

- [ ] **Step 1: 테스트 작성**

```python
"""D-204 — 셸이 매니페스트대로 조립하고, 깨진 패널 하나가 화면을 멈추지 않는다."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "src" / "core" / "core" / "config"
for name in ("core", "core_api_web", "core_common", "core_events", "core_features"):
    path = str(ROOT / "src" / "core" / name)
    if path not in sys.path:
        sys.path.insert(0, path)

from browser_harness import open_page  # noqa: E402

TOKEN = "sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-admin');"
BROKEN = {"id": "broken.panel", "title": "깨진 패널", "slot": "main", "order": 1,
          "module": "/assets/panels/broken/missing.js", "css": [], "state": "available", "reason": None}


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from core.services import CoreServices
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile

    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", tmp_path / "rosy.yaml")
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    config = yaml.safe_load((CONFIG / "rosy_default.yaml").read_text(encoding="utf-8"))
    config.update(yaml.safe_load((CONFIG / "rosy_dev_auth.yaml").read_text(encoding="utf-8")))
    profile = RobotProfile.load(CONFIG / "profile.pinky_pro.yaml")
    caps = yaml.safe_load((CONFIG / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
    return TestClient(create_app(config, services)), services


def _proxy(page, client, *, break_one=False):
    def handle(route):
        request = route.request
        url = urlparse(request.url)
        path = url.path + (f"?{url.query}" if url.query else "")
        response = client.request(request.method, path, headers=request.headers,
                                  content=request.post_data_buffer)
        body = response.content
        if break_one and url.path == "/api/v1/ui/surfaces/device":
            manifest = response.json()
            manifest["panels"].insert(0, BROKEN)
            manifest["revision"] = "sha256:broken"
            body = json.dumps(manifest).encode("utf-8")
        headers = {k: v for k, v in response.headers.items() if k.lower() not in {"content-length", "content-encoding"}}
        route.fulfill(status=response.status_code, headers=headers, body=body)

    page.route("http://rosy.test/**", handle)


def test_the_device_surface_mounts_the_events_panel(app_client):
    sync_api = pytest.importorskip("playwright.sync_api")
    client, services = app_client
    services.events.publish("system.test", severity="warning", source="test", data={})
    with sync_api.sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1280, 800)
        try:
            _proxy(page, client)
            page.add_init_script(script=TOKEN)
            page.goto("http://rosy.test/device", wait_until="domcontentloaded")
            page.wait_for_selector('ui-section[data-panel="system.events"] .event-type')
            assert page.locator(".event-type").first.text_content() == "system.test"
            assert page.locator('#surface-switch a[aria-current="page"]').text_content() == "설치·정비"
            assert page.locator("#shell-role").text_content() == "administrator"
            assert not errors
        finally:
            browser.close()


def test_a_broken_panel_stays_in_its_slot(app_client):
    sync_api = pytest.importorskip("playwright.sync_api")
    client, _ = app_client
    with sync_api.sync_playwright() as playwright:
        browser, page, _errors = open_page(playwright, 1280, 800)
        try:
            _proxy(page, client, break_one=True)
            page.add_init_script(script=TOKEN)
            page.goto("http://rosy.test/device", wait_until="domcontentloaded")
            page.wait_for_selector('ui-section[data-panel="broken.panel"][data-failed="true"]')
            page.wait_for_selector('ui-section[data-panel="system.events"] ol.event-list')
            order = page.eval_on_selector_all("ui-section[data-panel]", "els => els.map(e => e.dataset.panel)")
            assert order == ["broken.panel", "system.events"]
        finally:
            browser.close()


def test_the_shell_estop_reaches_the_safety_route(app_client):
    sync_api = pytest.importorskip("playwright.sync_api")
    client, services = app_client
    with sync_api.sync_playwright() as playwright:
        browser, page, _errors = open_page(playwright, 1280, 800)
        try:
            _proxy(page, client)
            page.add_init_script(script=TOKEN)
            page.goto("http://rosy.test/device", wait_until="domcontentloaded")
            page.click("#shell-estop")
            page.wait_for_function("document.getElementById('shell-notice').textContent.length > 0")
            assert page.locator("#shell-notice").text_content() == "비상 정지를 보냈습니다."
            assert client.get("/api/v1/safety/state",
                              headers={"Authorization": "Bearer rosy-dev-admin"}).json()["estop"] is True
        finally:
            browser.close()
```

(`/api/v1/safety/state`의 e-stop 필드는 `estop`이다 — `api/v1/safety.py` `_safety_payload`.)

- [ ] **Step 2: 실행**

Run: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_surface_shell_browser.py -q`
(PowerShell: `$env:ROSY_RUN_BROWSER_TESTS='1'; python -m pytest test/test_surface_shell_browser.py -q`)
Expected: 3 passed. Playwright/Chromium이 없으면 skip — 그 경우 결과 보고에 "브라우저 확인 안 됨"을 적는다.

- [ ] **Step 3: 커밋**

```bash
git add test/test_surface_shell_browser.py
git commit -m "test(web): D-204 browser check for assembly, isolation and the shell e-stop"
```

---

### Task 10: 정적 게이트와 패키징

**Files:**
- Test: `src/core/core_api_web/test/test_surface_contracts.py`
- Modify: `src/core/core_api_web/setup.py` (`package_data`)
- Modify: `src/core/core_api_web/package.xml` (`python3-yaml`)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""D-204 — 셸·패널의 구조 규칙과 설치 누락을 텍스트로 고정한다. ROS·브라우저 없이 돈다."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

import yaml

from core_api_web.api.ui_registry import load_registry

PKG = Path(__file__).resolve().parents[1]
WEB = PKG / "core_api_web" / "web"
REPO = PKG.parents[2]
CAPABILITY_FILES = [
    *sorted((REPO / "deploy" / "robot" / "config").glob("capabilities.*.yaml")),
    REPO / "src" / "core" / "core" / "config" / "capabilities.yaml",
]
BUDGET = {"shell": 300, "panels": 400}
IMPORT = re.compile(r"""(?:^|\n)\s*import\s[^;]*?from\s+["']([^"']+)["']|import\(\s*["']([^"']+)["']""")


def _js(folder: str) -> list[Path]:
    return sorted((WEB / folder).rglob("*.js"))


def test_shell_and_panel_files_stay_inside_their_line_budget():
    over = [f"{path.relative_to(WEB)}: {len(path.read_text(encoding='utf-8').splitlines())}"
            for folder, limit in BUDGET.items() for path in _js(folder)
            if len(path.read_text(encoding="utf-8").splitlines()) > limit]
    assert not over, over


def test_panels_import_nothing_but_the_shared_common_modules():
    bad = []
    for path in _js("panels"):
        for match in IMPORT.finditer(path.read_text(encoding="utf-8")):
            spec = match.group(1) or match.group(2)
            if not spec.startswith("/common/"):
                bad.append(f"{path.relative_to(WEB)} imports {spec}")
    assert not bad, bad


def test_every_panel_exports_mount():
    missing = [str(p.relative_to(WEB)) for p in _js("panels")
               if "export function mount(" not in p.read_text(encoding="utf-8")]
    assert not missing, missing


def test_no_inline_style_or_html_injection_in_shell_or_panels():
    bad = []
    for path in [*_js("shell"), *_js("panels"), WEB / "shell" / "surface.html"]:
        text = path.read_text(encoding="utf-8")
        for needle in ("style=", ".style.", "innerHTML", "insertAdjacentHTML", "<script>"):
            if needle in text:
                bad.append(f"{path.relative_to(WEB)}: {needle}")
    assert not bad, bad


def _flag_keys(data, prefix=""):
    for key, value in (data or {}).items():
        dotted = f"{prefix}{key}"
        yield dotted
        if isinstance(value, dict):
            yield from _flag_keys(value, f"{dotted}.")


def test_every_requires_key_exists_in_some_capability_file():
    known = set()
    for path in CAPABILITY_FILES:
        known |= set(_flag_keys(yaml.safe_load(path.read_text(encoding="utf-8"))))
    registry = load_registry(WEB / "panels.yaml", WEB)
    unknown = [f"{p.id}: {key}" for p in registry.panels for key in p.requires if key not in known]
    assert not unknown, f"오타는 조용히 not_provided가 된다: {unknown}"


def test_package_data_installs_every_served_web_file():
    setup = (PKG / "setup.py").read_text(encoding="utf-8")
    patterns = re.findall(r"'(web/[^']+)'", setup)
    served = [path for path in WEB.rglob("*")
              if path.is_file() and path.suffix in {".js", ".css", ".html", ".yaml"}]
    # PurePosixPath.match 는 fnmatch 와 달리 `*` 가 `/` 를 넘지 않는다 — setuptools glob 과 같다.
    relative = [PurePosixPath(p.relative_to(WEB.parent).as_posix()) for p in served]
    missing = [str(rel) for rel in relative if not any(rel.match(pat) and len(rel.parts) == len(PurePosixPath(pat).parts)
                                                       for pat in patterns)]
    assert not missing, f"복사 설치에서 404가 된다: {missing}"


def test_the_registry_reader_declares_yaml():
    assert "<exec_depend>python3-yaml</exec_depend>" in (PKG / "package.xml").read_text(encoding="utf-8")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/core_api_web/test/test_surface_contracts.py -q`
Expected: FAIL — `test_package_data_installs_every_served_web_file`(shell/panels/yaml 누락), `test_the_registry_reader_declares_yaml`. 나머지는 PASS여야 한다. 다른 것이 실패하면 해당 파일을 고친다.

- [ ] **Step 3: `setup.py` 갱신**

```python
    package_data={package_name: [
        'web/*.css', 'web/*.html', 'web/*.js', 'web/*.yaml',
        'web/shell/*.css', 'web/shell/*.html', 'web/shell/*.js',
        'web/panels/*/*.css', 'web/panels/*/*.js',
    ]},
```

- [ ] **Step 4: `package.xml` 갱신**

`<exec_depend>python3-fastapi</exec_depend>` 다음 줄에:

```xml
  <exec_depend>python3-yaml</exec_depend>
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest src/core/core_api_web/test -q`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add src/core/core_api_web/test/test_surface_contracts.py src/core/core_api_web/setup.py src/core/core_api_web/package.xml
git commit -m "test(core_api_web): D-204 static gates for panels and install coverage"
```

---

### Task 11: 스펙 정합, 에이전트 문서, 전체 회귀

**Files:**
- Modify: `docs/plans/2026-09-24-role-surfaces-panel-composition-design.md`
- Modify: `src/core/core_api_web/core_api_web/web/AGENTS.md`

- [ ] **Step 1: 스펙을 구현과 맞추기**

설계 문서에서 다음을 고친다.

- §3 표 `문법` 열과 §5.1 예시의 `procedural` → `procedure` (`web_common/ui.js` GRAMMARS 이름).
- §5.1 검증 목록의 "`requires`가 CAP-001 스키마에 없는 키" → "`requires`가 점 표기 키 형식이 아님. 키가 어느 capability 파일에도 없으면 저장소 테스트(`test_surface_contracts.py`)가 잡는다 — 프로필마다 키가 달라 기동 시 검증은 not_provided와 구분할 수 없다."
- §5.1 예시 패널에 `title: 텔레옵` 줄 추가.
- §5.2 JSON 예시: `"role": "operator"` 추가, `"surfaces": [{"id": "console", "title": "운용"}, {"id": "setup", "title": "작업 준비"}]`, 패널에 `"title"`, 자산 경로 접두를 `/assets/`로.
- §7 S1 행: "기존 패널은 임시로 legacy 패널 하나로 감싸" → "`/dashboard`는 그대로 두고 legacy 화면으로 계속 쓴다. `/device`에 첫 패널(최근 이벤트)을 올려 흐름을 증명한다. 로그인은 S4까지 `/dashboard`가 소유한다."
- §4 `ctx.store` 설명: "S1은 `poll(path, ms, onData, onError) → stop`만 싣는다. 공유 WebSocket `select`는 운용 화면 이관(S4) 때 더한다."
- §8 매니페스트 실패: "5초 간격으로 재시도" 유지(셸 `REFRESH_MS = 5_000`).

- [ ] **Step 2: `web/AGENTS.md`에 규칙 추가**

파일 끝에 섹션을 붙인다:

```markdown
## Role surfaces (D-204)

- `/console`, `/setup`, `/device` are assembled from `panels.yaml`. `/dashboard` is the legacy surface until S4.
- A new panel is one file under `panels/<domain>/` plus one registry entry. Do not add it to `index.html`.
- Panels export `mount(el, ctx)`, import only `/common/*`, never call each other, never set inline style.
- `requires` keys must exist in a capability YAML; a typo silently hides the panel (`test_surface_contracts.py`).
- The e-stop belongs to the shell. Never put a stop button in a panel.
```

- [ ] **Step 3: 전체 회귀**

Run:
```bash
python -m pytest src/core/core/test/ src/core/core_api_web/test src/apps/control/test/ src/site/fleet/test test/ -q
```
Expected: PASS(브라우저 테스트는 skip). `src/apps/control/test/`가 없으면(control 이동 중) `src/core/control/test/`로 바꾼다. 실패가 기준선(준비 단계)에도 있던 것이면 보고에 그대로 적고, 새 실패면 고친다.

- [ ] **Step 4: 모듈 하네스**

Run: `python tools/module_harness.py --changed 2>/dev/null || ls tools | grep -i harness`
Expected: 하네스가 있으면 PASS. 이름이 다르면 `ls tools`로 찾은 D-61 하네스를 실행한다.

- [ ] **Step 5: 커밋**

```bash
git add docs/plans/2026-09-24-role-surfaces-panel-composition-design.md src/core/core_api_web/core_api_web/web/AGENTS.md
git commit -m "docs: align the role-surfaces spec with S1 and record panel rules"
```

---

## 완료 기준

- `GET /api/v1/ui/surfaces/{console|setup|device}`가 역할·CAP-001·inventory로 걸러진 매니페스트를 준다.
- `/console`, `/setup`, `/device`가 뜨고, `/device`에서 관리자에게 최근 이벤트 패널이 보인다.
- 틀린 `panels.yaml`은 CORE 기동을 거부한다.
- `/dashboard`와 기존 테스트는 그대로 통과한다.
- host pytest 통과는 기기 인수가 아니다. 기기(Pinky)에서 `/device` 확인은 S2 계획의 인수 항목으로 넘긴다.

## 다음 계획 (이 계획의 범위 밖)

- **S2** `/device` 패널 이관(호스트·네트워크·ROS·릴리스·identity·토큰·안전 한계·capability) + `/dashboard` 점검 뷰 제거.
- **S3** `/setup` 패널 이관 + `settings.js` 삭제.
- **S4** `/console` 이관, 로그인 서랍을 셸로, 공유 WebSocket `select`, `/dashboard` 리다이렉트, `app.js` 삭제.
