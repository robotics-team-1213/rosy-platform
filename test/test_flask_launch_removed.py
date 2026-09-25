"""D-3: navigation web launches must not start the Flask server."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "src" / "runtime" / "navigation" / "launch"

_WEB_LAUNCHES = (
    "web_nav2.launch.xml",
    "web_slam.launch.xml",
    "gz_web_nav2.launch.xml",
    "gz_web_slam.launch.xml",
)


def test_web_launches_do_not_start_flask():
    for name in _WEB_LAUNCHES:
        text = (LAUNCH / name).read_text(encoding="utf-8")
        assert 'exec="nav2_web_server.py"' not in text, name


def test_web_launches_start_core_instead():
    for name in _WEB_LAUNCHES:
        text = (LAUNCH / name).read_text(encoding="utf-8")
        assert 'pkg="core"' in text, name
        assert "core" in text, name


def test_navigation_package_does_not_install_flask():
    cmake = (ROOT / "src" / "runtime" / "navigation" / "CMakeLists.txt").read_text(
        encoding="utf-8"
    )
    assert "nav2_web_server.py" not in cmake
    assert "index.html" not in cmake
    assert "pinklab_logo.png" not in cmake
