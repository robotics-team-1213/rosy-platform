"""Every shared helper a dashboard script calls is imported (D-359 regression guard).

A missing `import { setTagState } from "./dom.js"` threw a ReferenceError at
render time and broke the whole legacy /dashboard render chain (30 browser
failures) while every host test stayed green. This scan needs no browser: for
each dashboard script, a call to a name exported by dom.js / core_ui_logic.js /
ui.js must be satisfied by an import or a local binding in that file.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

DASHBOARD = Path(__file__).resolve().parents[1]
WEB_COMMON = DASHBOARD.parent / "web_common"
PROVIDERS = {
    "dom.js": DASHBOARD / "dom.js",
    "core_ui_logic.js": WEB_COMMON / "core_ui_logic.js",
    "ui.js": WEB_COMMON / "ui.js",
}
EXPORT = re.compile(r"^export\s+(?:async\s+)?(?:function\*?|class|const|let)\s+([A-Za-z_$][\w$]*)", re.M)
IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"'][^\"']+[\"']", re.S)
COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def exported() -> dict[str, str]:
    names = {}
    for provider, path in PROVIDERS.items():
        for name in EXPORT.findall(path.read_text(encoding="utf-8-sig")):
            names.setdefault(name, provider)
    return names


def imported(text: str) -> set[str]:
    names = set()
    for group in IMPORT.findall(text):
        for part in group.split(","):
            part = part.strip()
            if part:
                names.add(part.split(" as ")[-1].strip())
    return names


def locally_bound(text: str, name: str) -> bool:
    n = re.escape(name)
    return bool(re.search(
        rf"\bfunction\s+{n}\b|\b(?:const|let|var)\s+{n}\b|\bclass\s+{n}\b"
        rf"|\(\s*\{{[^}}]*\b{n}\b[^}}]*\}}\s*\)"      # ({ a, name, b }) parameter destructuring
        rf"|\b(?:const|let|var)\s*\{{[^}}]*\b{n}\b[^}}]*\}}\s*="  # const { name } = ...
        rf"|\(\s*(?:[\w$]+\s*,\s*)*{n}\s*(?:,[^)]*)?\)\s*=>",  # (a, name) => ...
        text))


def missing_imports(text: str, names: dict[str, str]) -> list[str]:
    code = COMMENT.sub("", text)
    have = imported(code)
    out = []
    for name, provider in names.items():
        called = re.search(rf"(?<![\w$.]){re.escape(name)}\s*\(|\bnew\s+{re.escape(name)}\b", code)
        if called and name not in have and not locally_bound(code, name):
            out.append(f"{name} (from {provider})")
    return out


def scripts() -> list[Path]:
    return sorted(path for path in DASHBOARD.rglob("*.js")
                  if "test" not in path.parts and path.name != "dom.js")


@pytest.mark.parametrize("path", scripts(), ids=lambda p: p.relative_to(DASHBOARD).as_posix())
def test_every_called_shared_helper_is_imported(path):
    assert missing_imports(path.read_text(encoding="utf-8-sig"), exported()) == []


def test_the_scan_sees_the_shared_helpers():
    names = exported()
    assert {"setTagState", "setText", "setOff"} <= set(names)
    assert {"HeadlessState", "enumLabel"} <= set(names)


@pytest.mark.parametrize(("rel", "name"), [
    ("telemetry.js", "setTagState"),  # D-362 P1: the SLAM chip moved out of app.js
    ("ros-network.js", "setTagState"),
    ("settings.js", "setTagState"),
    ("panels/console/overview.js", "enumLabel"),
])
def test_removing_an_import_is_caught(rel, name):
    """Mutation proof: drop one real import and the scan names it."""
    text = (DASHBOARD / rel).read_text(encoding="utf-8-sig")
    code = COMMENT.sub("", text)
    assert name in imported(code), (rel, name)
    mutated = IMPORT.sub(lambda m: m.group(0).replace(name + ",", "").replace(", " + name, "")
                         .replace("{ " + name + " }", "{ }").replace(name, "")
                         if name in m.group(1) else m.group(0), text)
    assert name not in imported(COMMENT.sub("", mutated))
    assert any(item.startswith(name + " ") for item in missing_imports(mutated, exported()))
