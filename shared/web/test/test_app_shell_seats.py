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
