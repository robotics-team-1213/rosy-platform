"""D-204 — shell and panel structure rules, checked as text. No ROS, no browser."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from core_api_web.api.ui_registry import load_registry

REPO = Path(__file__).resolve().parents[4]
WEB = REPO / "middleware" / "ui" / "robot"
CAPABILITY_FILES = [
    *sorted((REPO / "deploy" / "robot" / "pinky_pro" / "config").glob("capabilities.*.yaml")),
    REPO / "middleware" / "devices" / "pinky" / "profile" / "config" / "capabilities.yaml",
]
BUDGET = {"shell": 300, "panels": 400}

# T10-a: a panel CSS rule must not open on a bare element/tag selector — panels
# are meant to scope every rule under a class that belongs to that panel, so a
# bare-tag rule is either a leak into shared layout or a future collision with
# another panel's markup. This is a pragmatic lexical check, not a full CSS
# parser: it looks at the first selector token of each rule (the text up to the
# first `{`, split on commas for grouped selectors) and flags one that starts
# with a bare identifier (element name) rather than `.`, `#`, `:`, `*`, `[`, or
# a combinator/at-rule.
_RULE_OPEN = re.compile(r"([^{}]+)\{")
_AT_RULE = re.compile(r"^\s*@")
_BARE_ELEMENT_START = re.compile(r"^[a-zA-Z][a-zA-Z0-9-]*")
# `@keyframes` steps (`from`, `to`, `50%`) are not element selectors — they name
# a point on the animation timeline and live inside an at-rule block.
_KEYFRAME_STEP = re.compile(r"^\d+(\.\d+)?%$")


def _css_selector_heads(text: str):
    # Strip comments first so `/* ... { ... */`-style text never confuses the
    # brace scan below.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    for match in _RULE_OPEN.finditer(text):
        prelude = match.group(1)
        if _AT_RULE.match(prelude):
            continue
        for part in prelude.split(","):
            selector = part.strip()
            if not selector or selector in ("from", "to") or _KEYFRAME_STEP.match(selector):
                continue
            yield selector


def _js(folder: str) -> list[Path]:
    return sorted((WEB / folder).rglob("*.js"))


def test_shell_and_panel_files_stay_inside_their_line_budget():
    over = [f"{path.relative_to(WEB)}: {len(path.read_text(encoding='utf-8').splitlines())}"
            for folder, limit in BUDGET.items() for path in _js(folder)
            if len(path.read_text(encoding="utf-8-sig").splitlines()) > limit]
    assert not over, over


def test_every_registered_panel_module_exports_mount():
    registry = load_registry(WEB / "panels.yaml", WEB)
    missing = [p.module for p in registry.panels
               if "export function mount(" not in (WEB / p.module).read_text(encoding="utf-8-sig")]
    assert not missing, missing


def test_no_inline_style_or_html_injection_in_shell_or_panels():
    bad = []
    for path in [*_js("shell"), *_js("panels"), WEB / "surface.html"]:
        text = path.read_text(encoding="utf-8-sig")
        for needle in ("style=", ".style.", "innerHTML", "insertAdjacentHTML", "<script>"):
            if needle in text:
                bad.append(f"{path.relative_to(WEB)}: {needle}")
    assert not bad, bad


def test_panel_css_does_not_open_a_rule_on_a_bare_element_selector():
    bad = []
    for path in sorted((WEB / "panels").rglob("*.css")):
        for selector in _css_selector_heads(path.read_text(encoding="utf-8-sig")):
            if _BARE_ELEMENT_START.match(selector) and not selector.startswith("body[data-surface="):
                bad.append(f"{path.relative_to(WEB)}: {selector!r}")
    assert not bad, bad


def test_the_css_selector_head_gate_ignores_keyframes_steps_and_still_catches_bare_tags():
    keyframes = """
    @keyframes spin {
      from { opacity: 0; }
      50% { opacity: .5; }
      to { opacity: 1; }
    }
    .spinner { animation: spin 1s; }
    """
    assert list(_css_selector_heads(keyframes)) == [".spinner"]

    bad = "li{color:red;}"
    heads = list(_css_selector_heads(bad))
    assert heads and _BARE_ELEMENT_START.match(heads[0])


def _flag_keys(data, prefix=""):
    for key, value in (data or {}).items():
        dotted = f"{prefix}{key}"
        yield dotted
        if isinstance(value, dict):
            yield from _flag_keys(value, f"{dotted}.")


def test_every_requires_key_exists_in_some_capability_file():
    known = set()
    for path in CAPABILITY_FILES:
        known |= set(_flag_keys(yaml.safe_load(path.read_text(encoding="utf-8-sig"))))
    registry = load_registry(WEB / "panels.yaml", WEB)
    unknown = [f"{p.id}: {key}" for p in registry.panels for key in p.requires if key not in known]
    assert not unknown, f"오타는 조용히 not_provided가 된다: {unknown}"
