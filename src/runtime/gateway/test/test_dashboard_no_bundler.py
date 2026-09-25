"""D-75: robot-local UI is hand-written static assets, not a React/Vite build."""

from pathlib import Path

API = Path(__file__).resolve().parents[2] / "api_web"
WEB = Path(__file__).resolve().parents[3] / "hmi" / "dashboard"


def test_core_has_no_frontend_bundler():
    assert not (API / "package.json").exists()
    assert not list(API.glob("vite.config.*"))
    assert not list(API.glob("**/webpack.config.*"))
    assert (WEB / "index.html").is_file()
    assert (WEB / "styles.css").is_file()


def test_dashboard_assets_are_an_explicit_allowlist():
    app = (API / "core_api_web" / "api" / "app.py").read_text(encoding="utf-8")
    assert "dashboard_assets" in app
    assert '"styles.css"' in app
    assert '"app.js"' in app
    assert "index.html" in app
