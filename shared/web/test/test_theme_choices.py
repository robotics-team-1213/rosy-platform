"""Fleet and device selectors consume RosyTheme choices without another preference list."""

from __future__ import annotations

from pathlib import Path
import re

SRC = (Path(__file__).resolve().parents[3] / "src")
THEME_JS = SRC.parent / "shared" / "web" / "theme.js"
DISPLAY_JS = SRC.parent / 'middleware' / 'robot_ui' / "robot" / "panels" / "system" / "display.js"
FLEET_HTML = SRC.parent / 'applications' / 'fleet' / 'web' / "index.html"

CHOICE = re.compile(
    r"""\{\s*value:\s*"([\w-]+)",\s*label:\s*"([^"]+)"(?:,\s*icon:\s*(?:ICONS\.\w+|"[^"]+"))?\s*\}"""
)


def theme_choices(source: str) -> list[tuple[str, str]]:
    block = source.split("var CHOICES = [", 1)[1].split("];", 1)[0]
    return CHOICE.findall(block)


def test_theme_js_exposes_the_choices_it_validates_against():
    source = THEME_JS.read_text(encoding="utf-8")
    choices = theme_choices(source)
    assert [value for value, _ in choices][:2] == ["dark", "light"] and choices[-1][0] == "system"
    assert "PREFERENCES = CHOICES.map(" in source, "선호 검증도 같은 목록에서 온다"
    assert "choices: Object.freeze(CHOICES" in source


LEARNING_WEB = SRC.parent / "learning" / "curation" / "perception" / "review_app_web"


def test_the_shared_cycle_button_is_wired_once_from_the_single_source():
    source = (SRC.parent / "shared" / "web" / "ui-wiring.js").read_text(encoding="utf-8")
    assert 'import "./ui-wiring.js"' in (SRC.parent / "shared" / "web" / "ui.js").read_text(encoding="utf-8")
    assert source.count('closest("[data-theme-cycle]")') == 1
    assert 'window.RosyTheme' in source and 'theme.choices' in source
    assert 'theme.get()' in source and 'window.RosyTheme.set(themeCycleStep()[1].value)' in source
    assert 'RosyTheme' not in (FLEET_HTML.parent / "shared/fleet-header.js").read_text(encoding="utf-8")


def test_the_fleet_selector_uses_one_cycle_button():
    html = FLEET_HTML.read_text(encoding="utf-8")
    assert html.count('data-theme-cycle=""') == 1
    assert 'data-theme-choice=' not in html
    for name in ("console.js", "installation/install.js"):
        assert ':not([data-theme-cycle])' in (FLEET_HTML.parent / name).read_text(encoding="utf-8")




def test_the_device_panel_renders_from_the_single_source():
    source = DISPLAY_JS.read_text(encoding="utf-8")
    assert "window.RosyTheme?.choices" in source
    for _, label in theme_choices(THEME_JS.read_text(encoding="utf-8")):
        assert f'"{label}"' not in source, f"display.js가 선택지 이름 {label}을 따로 적는다"
