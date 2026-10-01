"""D-359 §2.5 (P2-5 review) — theme choices have one source: `RosyTheme.choices` in theme.js.

The /device display panel renders its buttons from `window.RosyTheme.choices`.
Fleet keeps static markup (the selector must exist before any module runs), so
this test holds that markup to the same list, in order, value and Korean label.
A new theme is then one palette block in tokens.css plus one line in theme.js;
this test names the one other place that has to follow.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re

SRC = Path(__file__).resolve().parents[3]
THEME_JS = SRC / "hmi" / "web_common" / "theme.js"
DISPLAY_JS = SRC / "hmi" / "dashboard" / "panels" / "system" / "display.js"
FLEET_HTML = SRC / "site" / "fleet" / "fleet" / "server" / "web" / "index.html"

CHOICE = re.compile(r"""\{\s*value:\s*"([\w-]+)",\s*label:\s*"([^"]+)"\s*\}""")


def theme_choices(source: str) -> list[tuple[str, str]]:
    block = source.split("var CHOICES = [", 1)[1].split("];", 1)[0]
    return CHOICE.findall(block)


class _ChoiceButtons(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found: list[list[str]] = []
        self._open: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        value = dict(attrs).get("data-theme-choice")
        if tag == "ui-button" and value is not None:
            self._open = [value, ""]

    def handle_data(self, data):
        if self._open is not None:
            self._open[1] += data

    def handle_endtag(self, tag):
        if tag == "ui-button" and self._open is not None:
            self.found.append(self._open)
            self._open = None


def markup_choices(html: str) -> list[tuple[str, str]]:
    parser = _ChoiceButtons()
    parser.feed(html)
    return [(value, label.strip()) for value, label in parser.found]


def test_theme_js_exposes_the_choices_it_validates_against():
    source = THEME_JS.read_text(encoding="utf-8")
    choices = theme_choices(source)
    assert [value for value, _ in choices][:2] == ["dark", "light"] and choices[-1][0] == "system"
    assert "PREFERENCES = CHOICES.map(" in source, "선호 검증도 같은 목록에서 온다"
    assert "choices: Object.freeze(CHOICES" in source


def test_the_fleet_selector_matches_the_single_source():
    choices = theme_choices(THEME_JS.read_text(encoding="utf-8"))
    assert markup_choices(FLEET_HTML.read_text(encoding="utf-8")) == choices


def test_the_device_panel_renders_from_the_single_source():
    source = DISPLAY_JS.read_text(encoding="utf-8")
    assert "window.RosyTheme?.choices" in source
    for _, label in theme_choices(THEME_JS.read_text(encoding="utf-8")):
        assert f'"{label}"' not in source, f"display.js가 선택지 이름 {label}을 따로 적는다"


def test_a_drifted_selector_is_caught():
    """Mutation proof: a theme added to theme.js but not to Fleet, or a renamed label, fails."""
    choices = theme_choices(THEME_JS.read_text(encoding="utf-8"))
    html = FLEET_HTML.read_text(encoding="utf-8")
    assert markup_choices(html.replace(">밝게<", ">라이트<", 1)) != choices
    grown = THEME_JS.read_text(encoding="utf-8").replace(
        '{ value: "system", label: "시스템" },',
        '{ value: "contrast", label: "고대비" },\n    { value: "system", label: "시스템" },', 1)
    assert theme_choices(grown) != choices and markup_choices(html) != theme_choices(grown)
