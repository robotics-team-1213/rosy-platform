"""Product scripts keep measured geometry in stylesheets.

CSP style-src 'self' already blocks a style attribute. These screens also
keep the CSSOM free of element style writes: continuous values are element
attributes read by typed attr(), and the canvas colour probe is one adopted
stylesheet rule.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOTS = (
    REPO / "middleware" / "ui" / "robot",
    REPO / "middleware" / "ui" / "pilot",
    REPO / "shared" / "web",
)


def test_product_scripts_do_not_write_element_style():
    offenders = []
    for root in ROOTS:
        for path in root.rglob("*.js"):
            if "test" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if ".style" in text or 'setAttribute("style"' in text or "setAttribute('style'" in text:
                offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == []


def test_measured_geometry_is_declared_with_typed_attr():
    pilot = (REPO / "middleware" / "ui" / "pilot" / "styles.css").read_text(encoding="utf-8")
    robot = (REPO / "middleware" / "ui" / "robot" / "console-detail.css").read_text(encoding="utf-8")
    shared = (REPO / "shared" / "web" / "components.css").read_text(encoding="utf-8")
    assert "attr(data-knob-x type(<length>), 0px)" in pilot
    assert "attr(data-band type(<length>), 0px)" in pilot
    assert "attr(data-recordings-top type(<length>), 0px)" in pilot
    assert "attr(data-meter type(<percentage>), 0%)" in robot
    assert "attr(data-clip type(*), none)" in shared
    assert "replaceSync" in (REPO / "shared" / "web" / "ui.js").read_text(encoding="utf-8")
