"""D-359 §4 — 캔버스는 색·글꼴을 토큰에서 ui.js(window.RosyPalette)로 읽는다.

hex만 읽는 파서는 color-mix·oklch 토큰을 검정으로 만든다(US-001 뒤 실제로
그랬다). 캔버스 파일에 hex 리터럴·hexToRgb·직접 getPropertyValue가 남지 않고,
모든 `ctx.font`가 `--body`/`--mono` 글꼴과 12px 이상을 쓰는지 소스로 본다.
실제 색 해석은 test_canvas_palette_browser.py가 Chromium으로 본다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3]
COMMON = SRC / "hmi" / "web_common"
DASHBOARD = SRC / "hmi" / "dashboard"
FLEET = SRC / "site" / "fleet" / "fleet" / "server" / "web"
GAMES = SRC / "site" / "games" / "games" / "web"

CANVAS_FILES = [
    DASHBOARD / "map.js",
    DASHBOARD / "camera-capture.js",
    FLEET / "map-view.js",
    FLEET / "console.js",
    GAMES / "board.js",
]
HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{6}\b|[\"'`]#[0-9a-fA-F]{3,8}[\"'`]")
FONT_ASSIGN = re.compile(r"\.font\s*=\s*([^;]+);")
# canvasFont(size, family) 또는 그것을 감싼 지역 이름만 허용한다.
FONT_SOURCES = re.compile(r"^(window\.RosyPalette\.canvasFont\(|font\(|labelFont$)")


def _ids(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


@pytest.mark.parametrize("path", CANVAS_FILES, ids=_ids)
def test_canvas_files_read_colours_through_the_palette_not_hex(path):
    source = path.read_text(encoding="utf-8")
    assert "hexToRgb" not in source
    assert HEX_LITERAL.findall(source) == []
    assert "getPropertyValue" not in source, "색·글꼴은 window.RosyPalette로 읽는다"


@pytest.mark.parametrize("path", CANVAS_FILES, ids=_ids)
def test_canvas_fonts_use_the_token_family_at_12px_or_more(path):
    source = path.read_text(encoding="utf-8")
    assert re.findall(r"\d+px", source) == [], "글꼴 크기는 canvasFont가 12px 아래를 막는다"
    assert "sans-serif" not in source and "monospace" not in source
    for rhs in FONT_ASSIGN.findall(source):
        assert FONT_SOURCES.match(rhs.strip()), f"{path.name}: ctx.font = {rhs.strip()}"
    for local in re.findall(r"const (font|labelFont) = ([^;]+);", source):
        assert "canvasFont" in local[1] or local[1].startswith("font("), local


def test_canvas_font_reads_body_or_mono_and_floors_at_12px():
    source = (COMMON / "ui.js").read_text(encoding="utf-8")
    body = source.split("export function canvasFont", 1)[1].split("\n}\n", 1)[0]
    assert "getPropertyValue(`--${family}`)" in body
    assert "Math.max(12," in body


def test_games_pitch_colours_live_in_its_stylesheet():
    board = (GAMES / "board.js").read_text(encoding="utf-8")
    styles = (GAMES / "styles.css").read_text(encoding="utf-8")
    tokens = (COMMON / "tokens.css").read_text(encoding="utf-8")
    names = set(re.findall(r'tone\((?:[^)]*?)"(--[a-z-]+)"', board))
    assert {"--pitch", "--line", "--home", "--away", "--pitch-ink", "--ball"} <= names
    for name in names:
        assert re.search(rf"{name}:\s*#", styles) or f"{name}:" in tokens, name


def test_fleet_terrain_and_legend_use_the_raster_tokens():
    view = (FLEET / "map-view.js").read_text(encoding="utf-8")
    styles = (FLEET / "styles.css").read_text(encoding="utf-8")
    html = (FLEET / "index.html").read_text(encoding="utf-8")
    for kind in ("unknown", "free", "uncertain", "occupied"):
        assert f'"--raster-{kind}"' in view
        assert re.search(rf"\.sw\.{kind} \{{ background: var\(--raster-{kind}\); \}}", styles)
        assert f'class="sw {kind}"' in html
