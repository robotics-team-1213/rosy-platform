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

import surface_registry as registry

SRC = (Path(__file__).resolve().parents[3] / "src")
COMMON = SRC.parent / "shared" / "web"
DASHBOARD = SRC.parent / "middleware" / "ui" / "robot"
FLEET = SRC.parent / "operations" / "fleet" / "fleet" / "server" / "web"
GAMES = SRC.parent / "operations" / "apps" / "games" / "games" / "web"

CANVAS_FILES = [
    DASHBOARD / "map.js",
    # camera-capture.js는 재수출만 한다 — 본체는 web_common evidence.js(D-323 T9).
    COMMON / "evidence.js",
    FLEET / "map-view.js",
    FLEET / "field-view.js",
    FLEET / "map-fit-view.js",
    FLEET / "console.js",
    GAMES / "board.js",
    SRC.parent / "learning/training/perception/dataset/review_app_web/app.js",
]
HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{6}\b|[\"'`]#[0-9a-fA-F]{3,8}[\"'`]")
FONT_ASSIGN = re.compile(r"\.font\s*=\s*([^;]+);")
# canvasFont(size, family) 또는 그것을 감싼 지역 이름만 허용한다.
FONT_SOURCES = re.compile(r"^(window\.RosyPalette\.canvasFont\(|font\(|labelFont$)")


def _ids(path: Path) -> str:
    return path.relative_to(SRC.parent).as_posix()


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


#: 캔버스를 그리지만 위 판정을 받지 않는 파일 — 저장소 상대 경로 → 이유.
CANVAS_EXEMPT = {
    "shared/web/ui.js": "RosyPalette 자신 — 1×1 탐침 캔버스로 토큰 색을 되읽는 라이브러리이고 canvasFont가 12px 바닥을 소유한다",
    "middleware/perception/web/diagnostic.html": "PARKED(D-266) 한 파일 진단 표면 — surfaces.yaml raw_colours 예외와 같은 해제 회차에 옮긴다",
}
DRAWS = re.compile(r"""getContext\(\s*["']2d["']|\.font\s*=""")


def test_every_canvas_script_on_a_web_surface_is_under_the_contract():
    """§7.6 — 캔버스 목록은 손으로 적은 것이라, 새 캔버스 파일이 조용히 판정 밖에 설 수 있다.
    모든 웹 표면(레지스트리)의 JS·HTML에서 2D 컨텍스트나 `.font =`를 쓰는 파일은 CANVAS_FILES
    또는 이유 있는 CANVAS_EXEMPT에 있어야 한다."""
    listed = {_ids(path) for path in CANVAS_FILES}
    drawing = []
    for row in registry.load(registry.REPO):
        if row.get("medium") != "web":
            continue
        for suffix in (".js", ".html"):
            for page in registry._pages(registry.REPO, row["path"], suffix):
                here = page.relative_to(registry.REPO).as_posix()
                if "test" in page.relative_to(registry.REPO).parts:
                    continue
                if DRAWS.search(page.read_text(encoding="utf-8")):
                    drawing.append(here)
    unlisted = [here for here in drawing
                if here not in listed and here not in CANVAS_EXEMPT]
    stale = [here for here in CANVAS_EXEMPT if here not in drawing]
    assert unlisted == [], f"캔버스 판정 밖의 그리는 파일: {unlisted}"
    assert stale == [], f"더 그리지 않는 예외는 지운다: {stale}"
