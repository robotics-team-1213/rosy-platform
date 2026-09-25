"""D-243: the operator screens are static files, not an API module."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_shell_and_modules_are_here():
    for name in ("index.html", "styles.css", "app.js", "client.js", "dom.js",
                 "map.js", "settings.js", "triage.js"):
        assert (ROOT / name).is_file(), name


def test_the_shell_has_no_inline_script():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "onclick=" not in html
