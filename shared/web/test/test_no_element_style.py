"""Product scripts keep measured geometry in stylesheets.

CSP style-src 'self' already blocks a style attribute. Every registered web surface (surfaces.yaml) also
keeps the CSSOM free of element style writes: continuous values are element attributes read by typed attr(),
and the canvas colour probe is one adopted stylesheet rule. Known hits awaiting migration are listed below
with a reason; the list may only shrink (a stale entry fails the test).
"""

from pathlib import Path
import re

import yaml

REPO = Path(__file__).resolve().parents[3]
SURFACES = yaml.safe_load((REPO / "shared" / "web" / "surfaces.yaml").read_text(encoding="utf-8"))["surfaces"]
ROOTS = tuple(sorted({REPO / s["path"] for s in SURFACES if s.get("medium") == "web"}))
#: Known hits awaiting migration: file -> reason. A stale entry (no hit left) fails the test.
EXCEPTIONS = {
    "middleware/perception/web/diagnostic-core.js": "classic script (no import): battery fill width",
    "middleware/perception/web/diagnostic-map.js": "classic script (no import): gauge fill width",
    "integrations/simulation/gazebo/scripts/lane_live_view.html": "local Gazebo debug page with an inline script, not a product surface",
    "learning/curation/perception/review_app_web/app.js": "review app writes element style; moves to the shared geometry helper with its UI slice",
    "learning/curation/perception/review_app_web/pixels.js": "review app writes element style; moves to the shared geometry helper with its UI slice",
    "learning/curation/perception/review_app_web/sim.js": "review app writes element style; moves to the shared geometry helper with its UI slice",
    "learning/curation/perception/review_app_web/viewport.js": "review app writes element style; moves to the shared geometry helper with its UI slice",
}
WRITE = re.compile(r"\.style\b|setAttribute\(\s*[\"']style[\"']")


def _scripts():
    for root in ROOTS:
        for path in ([root] if root.is_file() else root.rglob("*")):
            if path.suffix in (".js", ".mjs", ".html") and "test" not in path.parts and "node_modules" not in path.parts and "vendor" not in path.parts:
                yield path


def _hits():
    return {p.relative_to(REPO).as_posix() for p in _scripts() if WRITE.search(p.read_text(encoding="utf-8", errors="ignore"))}


def test_registered_surfaces_are_scanned():
    names = {r.relative_to(REPO).as_posix() for r in ROOTS}
    assert {"learning/curation/perception/review_app_web", "operations/apps/games/games/web",
            "applications/monitoring", "applications/calibration/web", "shared/web"} <= names


def test_product_scripts_do_not_write_element_style():
    hits = _hits()
    assert sorted(hits - set(EXCEPTIONS)) == []
    assert sorted(set(EXCEPTIONS) - hits) == [], "stale exception: remove it"


def test_measured_geometry_is_declared_with_typed_attr():
    pilot = ''.join((REPO / 'middleware' / 'robot_ui' / 'pilot' / name).read_text(encoding='utf-8')
                    for name in ('styles.css', 'layout.css'))
    robot = (REPO / 'middleware' / 'robot_ui' / "robot" / "console-detail.css").read_text(encoding="utf-8")
    shared = (REPO / "shared" / "web" / "components.css").read_text(encoding="utf-8")
    assert "attr(data-knob-x type(<length>), 0px)" in pilot
    assert "attr(data-band type(<length>), 0px)" in pilot
    assert "attr(data-recordings-top type(<length>), 0px)" in pilot
    assert "attr(data-meter type(<percentage>), 0%)" in robot
    assert "attr(data-clip type(*), none)" in shared
    assert "replaceSync" in (REPO / "shared" / "web" / "ui.js").read_text(encoding="utf-8")
