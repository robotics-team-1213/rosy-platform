"""D-3: navigation must not carry a Flask (or any web-server) launch surface.

The four ``web_*.launch.xml`` entry points were the Flask-era transition
remnant: they started ``core`` where ``nav2_web_server.py`` used to run.
They were deleted (scorecard §6 task 3, 2026-09-29) — the guard now pins
that absence, so a regenerated web-server launch cannot slip back in
unnoticed.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "src" / "runtime" / "navigation" / "launch"

_REMOVED_WEB_LAUNCHES = (
    "web_nav2.launch.xml",
    "web_slam.launch.xml",
    "gz_web_nav2.launch.xml",
    "gz_web_slam.launch.xml",
)


def test_the_flask_era_web_launches_stay_deleted():
    for name in _REMOVED_WEB_LAUNCHES:
        assert not (LAUNCH / name).exists(), name


def test_no_navigation_xml_starts_a_web_server():
    for path in LAUNCH.glob("*.xml"):
        text = path.read_text(encoding="utf-8")
        assert "nav2_web_server" not in text, path.name
        assert 'pkg="core"' not in text, (
            f"{path.name}: core starts from its own launch/deploy, "
            "never from navigation XML")


def test_navigation_package_does_not_install_flask():
    cmake = (ROOT / "src" / "runtime" / "navigation" / "CMakeLists.txt").read_text(
        encoding="utf-8"
    )
    assert "nav2_web_server.py" not in cmake
    assert "index.html" not in cmake
    assert "pinklab_logo.png" not in cmake
