"""One definition per shared need (2026-11-18 S3): .sr-only lives in components.css, and a token nobody reads is deleted."""

from pathlib import Path
import re

WEB = Path(__file__).resolve().parents[1]
REPO = WEB.parents[1]
SKIP = {".git", "node_modules", ".worktrees", "vendor", "docs", "__pycache__"}


def _sources(suffixes):
    for path in REPO.rglob("*"):
        if path.suffix in suffixes and path.is_file() and not SKIP & set(path.relative_to(REPO).parts):
            yield path


def test_sr_only_is_defined_once_in_components_css():
    pattern = re.compile(r"\.sr-only\b[^{}]*\{[^}]*(?:clip|1px)")
    stray = [p.relative_to(REPO).as_posix() for p in _sources({".css"}) if p.name != "components.css" and pattern.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert not stray, f".sr-only is redefined in {stray}; use the shared class"


def test_every_token_in_tokens_css_is_read_somewhere():
    tokens = set(re.findall(r"^\s*(--[a-z0-9-]+):", (WEB / "tokens.css").read_text(encoding="utf-8"), re.M))
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in _sources({".css", ".js", ".html", ".mjs", ".py", ".kt", ".gradle", ".xml", ".yaml"}) if p.name != "tokens.css")
    unused = sorted(t for t in tokens if t not in text and not re.search(rf"var\({re.escape(t)}\b", (WEB / "tokens.css").read_text(encoding="utf-8")))
    assert not unused, f"tokens nobody reads: {unused}"


def test_gallery_only_robot_panel_classes_stay_out_of_the_product_stylesheet():
    css = (WEB / "robot-dock.css").read_text(encoding="utf-8")
    for name in ("robot-panel-kv", "robot-panel-ev", "robot-panel-cam", "robot-panel-cause", "robot-demo-map", "robot-demo-note"):
        assert f".{name}" not in css, f".{name} is gallery-only and belongs in component-gallery.css"
