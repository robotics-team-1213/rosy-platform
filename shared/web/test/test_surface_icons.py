"""D-377 names and the D-370 3항 icon family with distinct silhouettes.

Icons are ``icons/<surface-id>.svg`` on a 108 grid (safe zone = centre circle of
diameter 66). Every colour is a ``tokens.css`` value: ``--ground`` plate, one
``--brand-rose`` dot, and one glyph token per surface. ``--status-*`` never
appears, because red is kept for the stop button (D-280).
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
from itertools import combinations

import pytest

import surface_registry as registry
import token_themes

WEB = registry.REPO / "shared/web"
ICONS = WEB / "icons"
#: Icons are drawn in the default (dark) palette. D-359 adds a light theme block that
#: redefines the same keys, so the whole-file regex would read the light values.
TOKENS = {f"--{name}": value for name, value in
          token_themes.palettes(token_themes.read(WEB / "tokens.css"))["dark"].items()}

#: D-370 3항 table: icon file -> glyph colour token.
GLYPH_TOKEN = {
    "cam": "--series-primary",
    "pilot": "--brand-rose",
    "console": "--ink",
    "robot": "--robot-1",
}
#: D-377 2항 table: display name, English name and short name are all `Rosy <Word>`.
NAMES = {
    "cam": ("Rosy Cam", "Rosy Cam", "Rosy Cam"),
    "console": ("Rosy Console", "Rosy Console", "Rosy Console"),
    "robot": ("Rosy Robot", "Rosy Robot", "Rosy Robot"),
    "pilot": ("Rosy Pilot", "Rosy Pilot", "Rosy Pilot"),
}
DOT = "M70,34A4,4 0 1,1 78,34A4,4 0 1,1 70,34Z"
SAFE_RADIUS = 33.0


def _renderer():
    path = registry.REPO / "tools/icons/render_png.py"
    spec = importlib.util.spec_from_file_location("rosy_icon_render", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RENDER = _renderer()


def _svg(ident):
    return ICONS / f"{ident}.svg"


def test_every_icon_uses_only_its_tokens():
    assert sorted(path.stem for path in ICONS.glob("*.svg")) == sorted(GLYPH_TOKEN)
    for ident, token in GLYPH_TOKEN.items():
        allowed = {TOKENS["--ground"], TOKENS["--brand-rose"], TOKENS[token]}
        text = _svg(ident).read_text(encoding="utf-8")
        colours = {value.lower() for value in re.findall(r"#[0-9a-fA-F]{3,8}\b", text)}
        assert colours == allowed, (ident, colours, allowed)


def test_token_names_are_defined_once():
    """TOKENS is a dict: a second definition would silently win. D-359 theme blocks each
    redefine the palette keys, so the rule holds per selector block, not per file."""
    for selector, body in token_themes.blocks(token_themes.read(WEB / "tokens.css")):
        names = re.findall(r"(--[a-z0-9-]+)\s*:", body)
        repeated = sorted({name for name in names if names.count(name) > 1})
        assert repeated == [], (selector, repeated)


def test_no_icon_uses_a_status_colour():
    status = {value.lower() for name, value in TOKENS.items() if name.startswith("--status-")}
    assert status, "tokens.css has no --status-* values; the guard would be vacuous"
    for path in ICONS.glob("*.svg"):
        text = path.read_text(encoding="utf-8").lower()
        assert not status & set(re.findall(r"#[0-9a-f]{6}", text)), path.name
        assert "--status-" not in text, path.name


def test_family_shape_ground_plate_and_one_brand_dot():
    for ident in GLYPH_TOKEN:
        shapes = RENDER.shapes(_svg(ident))
        assert shapes[0]["id"] == "background" and shapes[0]["fill"] == TOKENS["--ground"]
        dots = [shape for shape in shapes if shape["fill"] == TOKENS["--brand-rose"]
                and shape["id"] == "brand-dot"]
        assert len(dots) == 1 and dots[0]["d"] == DOT, ident
        assert shapes[-1]["id"] == "brand-dot", ident


def test_glyphs_stay_inside_the_adaptive_safe_zone():
    for ident in GLYPH_TOKEN:
        for shape in RENDER.shapes(_svg(ident))[1:]:
            reach = shape["width"] / 2
            for points, _closed in RENDER.subpaths(shape["d"]):
                for x, y in points:
                    assert math.hypot(x - 54, y - 54) + reach <= SAFE_RADIUS + 0.01, (ident, shape["id"])


def test_monochrome_silhouettes_are_distinct():
    """Themed (monochrome) icons must still tell the four apart by outline alone."""
    pytest.importorskip("PIL")
    masks = {}
    for ident in GLYPH_TOKEN:
        alpha = RENDER.render(_svg(ident), 48, mono=True).getchannel("A")
        masks[ident] = {i for i, value in enumerate(alpha.tobytes()) if value > 127}
    for first, second in combinations(masks, 2):
        a, b = masks[first], masks[second]
        iou = len(a & b) / len(a | b)
        assert iou < 0.5, (first, second, round(iou, 2))
    signatures = {ident: tuple(sorted((shape["fill"] != "none", round(shape["width"], 1))
                                      for shape in RENDER.shapes(_svg(ident))[1:-1]))
                  for ident in GLYPH_TOKEN}
    assert len(set(signatures.values())) == len(signatures), signatures


def test_registry_names_and_icons_follow_the_naming_table():
    rows = {row["id"]: row for row in registry.load()}
    for ident, (name, name_en, short) in NAMES.items():
        row = rows[ident]
        assert (row.get("app_name"), row.get("app_name_en"), row.get("short_name")) == \
            (name, name_en, short), ident
        assert row.get("icon") == f"shared/web/icons/{ident}.svg", ident
        assert (registry.REPO / row["icon"]).is_file()
        assert name.startswith("Rosy ") and short.startswith("Rosy ")
    for row in rows.values():
        if "icon" in row:
            assert (registry.REPO / row["icon"]).is_file(), row["id"]


def test_web_icons_are_on_the_common_allowlist_and_linked_as_favicons():
    assets = json.loads((WEB / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]
    for ident in GLYPH_TOKEN:
        assert assets.get(f"icons/{ident}.svg") == "image/svg+xml"
    pages = {
        "operations/fleet/fleet/server/web/index.html": "console",
        "operations/fleet/fleet/server/web/install.html": "console",
        "operations/fleet/fleet/server/web/cell.html": "console",
        "middleware/ui/robot/index.html": "robot",
        "middleware/ui/robot/surface.html": "robot",
        "middleware/ui/pilot/index.html": "pilot",
    }
    for page, ident in pages.items():
        text = (registry.REPO / page).read_text(encoding="utf-8")
        assert (f'<link rel="icon" type="image/svg+xml" href="/common/icons/{ident}.svg">'
                in text), page


def test_android_launcher_label_is_the_registered_app_name():
    strings = (registry.REPO / "operations/ui/cam/app/src/main/res/values/strings.xml"
               ).read_text(encoding="utf-8")
    label = re.search(r'<string name="app_name">([^<]*)</string>', strings).group(1)
    camera = next(row for row in registry.load() if row["id"] == "cam")
    assert label == camera["app_name"] == NAMES["cam"][0]
