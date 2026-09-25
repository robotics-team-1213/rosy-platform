"""D-243: the operator screens are static files, not an API module."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_shell_and_modules_are_here():
    for name in ("index.html", "styles.css", "app.js", "client.js", "dom.js",
                 "map.js", "settings.js", "triage.js", "status-summary.js"):
        assert (ROOT / name).is_file(), name


def test_the_shell_has_no_inline_script():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "onclick=" not in html


def test_the_summary_line_builds_no_markup_from_server_text():
    # D-260 5: state, reason, devices and todos come from CORE; they are text only.
    script = (ROOT / "status-summary.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script and "insertAdjacentHTML" not in script
    assert 'import { createStatusSummary } from "./status-summary.js";' in (ROOT / "app.js").read_text(
        encoding="utf-8")
    assert '"/api/v1/host/status-summary"' in (ROOT / "app.js").read_text(encoding="utf-8")


def test_every_module_the_shell_imports_is_installed_and_served():
    # A module missing from either list 404s on the robot and the page dies at import.
    import re

    imported = set(re.findall(r'from "\./([a-z-]+\.js)"', (ROOT / "app.js").read_text(encoding="utf-8")))
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8-sig")
    served = (ROOT.parents[2] / "src/runtime/api_web/core_api_web/api/app.py").read_text(encoding="utf-8")
    assert "status-summary.js" in imported
    for name in imported:
        assert f"  {name}" in cmake, name
        assert f'"{name}": "application/javascript"' in served, name
