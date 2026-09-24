"""Shared browser controls live in one file, and surfaces do not invent type sizes."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
COMMON = Path(__file__).parent.parent
COMPONENTS = COMMON / "components.css"
UI = COMMON / "ui.js"

SURFACES = (
    ROOT / "core" / "core_api_web" / "core_api_web" / "web" / "styles.css",
    ROOT / "core" / "core_api_web" / "core_api_web" / "web" / "styleguide.css",
    ROOT / "site" / "fleet" / "fleet" / "server" / "web" / "styles.css",
    ROOT / "apps" / "games" / "games" / "web" / "styles.css",
    ROOT / "apps" / "control" / "web" / "dashboard.html",
)

RAW_SIZE = re.compile(r"font-size:\s*[0-9.]+(?:px|rem)")
RAW_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d")


def test_shared_controls_are_the_only_painted_components():
    css = COMPONENTS.read_text(encoding="utf-8")
    script = UI.read_text(encoding="utf-8")
    assert "ui-button" in css and "ui-field" in css and "ui-tag" in css and "ui-text" in css
    for name in ("ui-button", "ui-field", "ui-tag", "ui-text"):
        assert f'"{name}"' in script
    assert not RAW_COLOR.findall(css), "components.css에 원시 색이 있다"
    assert not RAW_SIZE.findall(css)


def test_browser_surfaces_use_the_type_scale():
    offenders = {}
    for path in SURFACES:
        hits = RAW_SIZE.findall(path.read_text(encoding="utf-8"))
        if hits:
            offenders[path.name] = hits
    assert not offenders, offenders
