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
    # 값이 str이 아니면(list/dict) `in`이 해시를 요구해 TypeError로 죽는다 — 먼저 걸러
    # RegistryError 하나로만 죽는다(review batch A).
    if not isinstance(value, str) or value not in ROLE_RANK:
        raise RegistryError(f"{where}: unknown role {value!r}")
    return value


def _asset(value: Any, suffix: str, web_root: Path, panels_root: Path, where: str) -> str:
    if not isinstance(value, str):
        raise RegistryError(f"{where}: asset path must be a string")
    # 백슬래시는 PurePosixPath에서 구분자가 아니라 리터럴 문자지만, Windows에서
    # `web_root / value`는 실제로 그걸 구분자로 쓴다 — panels/ 밖으로 나가는 통로다.
    if "\\" in value:
        raise RegistryError(f"{where}: {value!r} is outside panels/")
    path = PurePosixPath(value)
    # 정규형이 아닌 표기(./, 중복 슬래시)는 문자열 비교 기반 방어를 우회할 수 있다.
    if value != path.as_posix() or "." in path.parts:
        raise RegistryError(f"{where}: {value!r} is not in normal form")
    if path.is_absolute() or ".." in path.parts or path.parts[:1] != (PANEL_ROOT,):
        raise RegistryError(f"{where}: {value!r} is outside panels/")
    if path.suffix != suffix:
        raise RegistryError(f"{where}: {value!r} must end with {suffix}")
    if not (web_root / value).is_file():
        raise RegistryError(f"{where}: missing file {value!r}")
    # 심볼릭 링크는 존재·접미사 검사를 통과하고도 panels/ 밖 실제 파일을 가리킬 수
    # 있다 — resolve() 뒤 포함 관계로 다시 확인한다.
    real = (web_root / value).resolve()
    allowed_root = panels_root.resolve()
    if allowed_root not in real.parents and real != allowed_root:
        raise RegistryError(f"{where}: {value!r} is outside panels/")
    return value


def _surface(sid: str, raw: Any) -> Surface:
    where = f"surface {sid!r}"
    if not isinstance(sid, str) or not _ID.fullmatch(sid):
        raise RegistryError(f"{where}: id must match {_ID.pattern}")
    if sid in RESERVED:
        raise RegistryError(f"{where}: reserved route name")
    if not isinstance(raw, dict):
        raise RegistryError(f"{where}: must be a mapping")
    grammar = raw.get("grammar")
    # 값이 str이 아니면(list/dict) `in`이 해시를 요구해 TypeError로 죽는다 — 먼저 걸러낸다.
    if not isinstance(grammar, str) or grammar not in GRAMMARS:
        raise RegistryError(f"{where}: grammar must be one of {sorted(GRAMMARS)}")
    slots = raw.get("slots")
    if not isinstance(slots, list) or not slots or not all(isinstance(s, str) and _ID.fullmatch(s) for s in slots):
        raise RegistryError(f"{where}: slots must be a non-empty list of ids")
    if len(slots) != len(set(slots)):
        raise RegistryError(f"{where}: duplicate slot name")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RegistryError(f"{where}: title is required")
    return Surface(sid, title, _role(raw.get("min_role"), where), grammar, tuple(slots))


def _panel(raw: Any, surfaces: Mapping[str, Surface], web_root: Path, panels_root: Path) -> Panel:
    if not isinstance(raw, dict):
        raise RegistryError("panel entries must be mappings")
    pid = raw.get("id")
    where = f"panel {pid!r}"
    if not isinstance(pid, str) or not _PANEL_ID.fullmatch(pid):
        raise RegistryError(f"{where}: id must look like domain.name")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RegistryError(f"{where}: title is required")
    surface_id = raw.get("surface")
    # 값이 str이 아니면(list/dict) dict.get()이 해시를 요구해 TypeError로 죽는다.
    surface = surfaces.get(surface_id) if isinstance(surface_id, str) else None
    if surface is None:
        raise RegistryError(f"{where}: unknown surface {surface_id!r}")
    slot = raw.get("slot")
    if not isinstance(slot, str) or slot not in surface.slots:
        raise RegistryError(f"{where}: unknown slot {slot!r} on {surface.id}")
    order = raw.get("order")
    if not isinstance(order, int) or isinstance(order, bool):
        raise RegistryError(f"{where}: order must be an integer")
    requires = raw.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(k, str) and _CAP_KEY.fullmatch(k) for k in requires):
        raise RegistryError(f"{where}: requires must be dotted CAP-001 keys")
    inventory = raw.get("inventory")
    if inventory is not None and (not isinstance(inventory, str) or not _PANEL_ID.fullmatch(inventory)):
        raise RegistryError(f"{where}: inventory must be a concept id like mobility.move")
    css = raw.get("css", [])
    if not isinstance(css, list):
        raise RegistryError(f"{where}: css must be a list")
    css_paths = [_asset(item, ".css", web_root, panels_root, where) for item in css]
    if len(css_paths) != len(set(css_paths)):
        raise RegistryError(f"{where}: duplicate css entry")
    return Panel(
        id=pid,
        title=title,
        surface=surface.id,
        slot=slot,
        order=order,
        requires=tuple(requires),
        inventory=inventory,
        min_role=_role(raw.get("min_role", surface.min_role), where),
        module=_asset(raw.get("module"), ".js", web_root, panels_root, where),
        css=tuple(css_paths),
    )


def load_registry(path: Path, web_root: Path) -> Registry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # colcon --symlink-install keeps panels.yaml and each asset linked to the
    # package source tree. Use the resolved registry's sibling panels directory
    # as the asset boundary so those links stay inside the same panel tree.
    panels_root = path.resolve().parent / PANEL_ROOT
    if not isinstance(raw, dict):
        raise RegistryError("panels.yaml: document must be a mapping")
    if raw.get("version") != 1:
        raise RegistryError("panels.yaml: version must be 1")
    raw_surfaces = raw.get("surfaces")
    if not isinstance(raw_surfaces, dict):
        raise RegistryError("panels.yaml: surfaces must be a mapping")
    surfaces = {sid: _surface(sid, body) for sid, body in raw_surfaces.items()}
    raw_panels = raw.get("panels")
    if raw_panels is None:
        raw_panels = []
    elif not isinstance(raw_panels, list):
        raise RegistryError("panels.yaml: panels must be a list")
    panels: list[Panel] = []
    seen_ids: set[str] = set()
    seen_orders: set[tuple[str, str, int]] = set()
    for entry in raw_panels:
        panel = _panel(entry, surfaces, web_root, panels_root)
        if panel.id in seen_ids:
            raise RegistryError(f"panel {panel.id!r}: duplicate id")
        key = (panel.surface, panel.slot, panel.order)
        if key in seen_orders:
            raise RegistryError(f"panel {panel.id!r}: duplicate order {panel.order} in {panel.surface}/{panel.slot}")
        seen_ids.add(panel.id)
        seen_orders.add(key)
        panels.append(panel)
    return Registry(surfaces=surfaces, panels=tuple(panels))
