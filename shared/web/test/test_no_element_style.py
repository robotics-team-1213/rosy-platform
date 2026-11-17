"""Product scripts keep measured geometry in stylesheets.

CSP style-src 'self' already blocks a style attribute. Every registered web surface
(surfaces.yaml) also keeps the CSSOM free of element style writes. Dynamic values go through
setGeometry (shared/web/geometry.js, D1), the only module allowed to touch `.style`: it writes
`--g-*` custom properties that a stylesheet reads with a default. Drawings use SVG attributes
or canvas, discrete values use data-* selectors. Typed attr() remains only where listed below
and is removed as each surface migrates.
"""

from pathlib import Path
import re

import yaml

REPO = Path(__file__).resolve().parents[3]
SURFACES = yaml.safe_load((REPO / "shared" / "web" / "surfaces.yaml").read_text(encoding="utf-8"))["surfaces"]
ROOTS = tuple(sorted({REPO / s["path"] for s in SURFACES if s.get("medium") == "web"}))
SANCTIONED = "shared/web/geometry.js"
#: Known hits awaiting migration: file -> reason. A stale entry (no hit left) fails the test.
EXCEPTIONS = {
    "middleware/perception/web/diagnostic-core.js": "classic script (no import); battery fill width moves to setGeometry when the diagnostic loads ES modules",
    "middleware/perception/web/diagnostic-map.js": "classic script (no import); gauge fill width moves to setGeometry with diagnostic-core.js",
    "integrations/simulation/gazebo/scripts/lane_live_view.html": "local Gazebo debug page with an inline script, not a product surface",
}
WRITE = re.compile(r"\.style\b|setAttribute\(\s*[\"']style[\"']")


def _scripts():
    for root in ROOTS:
        for path in ([root] if root.is_file() else root.rglob("*")):
            if path.suffix in (".js", ".mjs", ".html") and "test" not in path.parts and "node_modules" not in path.parts and "vendor" not in path.parts:  # vendored three.js (C15)
                yield path


def _hits():
    return {p.relative_to(REPO).as_posix() for p in _scripts() if WRITE.search(p.read_text(encoding="utf-8", errors="ignore"))}


def test_registered_surfaces_are_scanned():
    names = {r.relative_to(REPO).as_posix() for r in ROOTS}
    assert {"learning/curation/perception/review_app_web", "operations/apps/games/games/web",
            "applications/monitoring", "applications/calibration/web", "shared/web"} <= names


def test_product_scripts_do_not_write_element_style():
    hits = _hits()
    assert sorted(hits - {SANCTIONED} - set(EXCEPTIONS)) == []
    assert sorted(set(EXCEPTIONS) - hits) == [], "stale exception: remove it"
    assert SANCTIONED in hits


def test_measured_geometry_is_declared_with_typed_attr():
    pilot = ''.join((REPO / 'middleware' / 'robot_ui' / 'pilot' / name).read_text(encoding='utf-8')
                    for name in ('styles.css', 'layout.css'))
    robot = (REPO / 'middleware' / 'robot_ui' / "robot" / "console-detail.css").read_text(encoding="utf-8")
    shared = (REPO / "shared" / "web" / "components.css").read_text(encoding="utf-8")
    assert "var(--g-x, 0px)" in pilot and "var(--g-left, 0px)" in pilot  # stick knob + float: setGeometry
    assert "attr(data-knob" not in pilot and "attr(data-float" not in pilot
    assert "attr(data-band type(<length>), 0px)" in pilot
    assert "attr(data-recordings-top type(<length>), 0px)" in pilot
    assert "attr(data-meter type(<percentage>), 0%)" in robot
    assert "attr(data-clip type(*), none)" in shared
    assert "replaceSync" in (REPO / "shared" / "web" / "ui.js").read_text(encoding="utf-8")
