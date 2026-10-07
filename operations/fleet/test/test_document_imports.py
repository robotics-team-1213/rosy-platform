"""Fleet console documents import only their own modules.

D-410 splits operate and install. D-450 keeps Cell on `/console/cell`.
An entry that imports another document's module fails this test.
"""

import re
from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "fleet" / "server" / "web"

_FROM = re.compile(r"""\bfrom\s+['"]([^'"]+)['"]""")
_DYNAMIC = re.compile(r"(?<![\w.])import\s*\(")

ALLOWED = {
    "console.js": {
        "connection-view.js",
        "formation.js",
        "map-view.js",
        "roster.js",
        "line-stuck.js",
        "signals.js",
        "tracking-view.js",
        "start-point-view.js",
        "vision-view.js",
        "authorization.js",
        "address-drift.js",
        "site-path.js",
        "poll-gate.js",
        "confirmed-action.js",
        "/common/fleet-client.js",
        "/common/ui.js",
        "/common/scope.js",
    },
    "install.js": {
        "authorization.js",
        "development-auth.js",
        "enrollment.js",
        "camera-pairing.js",
        "camera-peer.js",
        "vision-view.js",
        "field-view.js",
        "map-fit-view.js",
        "poll-gate.js",
        "peer-picker.js",
        "address-drift.js",
        "/common/fleet-client.js",
        "/common/scope.js",
        "/common/task-chooser.js",
        "/common/ui.js",
    },
    "cell.js": {
        "/console/assets/development-auth.js",
        "/common/fleet-client.js",
        "/common/ui.js",
        "/console/assets/cell-document-editor.js",
    },
}


def _imports(name):
    text = (WEB / name).read_text(encoding="utf-8")
    assert not _DYNAMIC.search(text), f"{name} uses a dynamic import"
    found = set()
    for spec in _FROM.findall(text):
        found.add(spec[2:] if spec.startswith("./") else spec)
    return found


def test_each_console_document_imports_only_its_modules():
    for name, allowed in ALLOWED.items():
        extra = _imports(name) - allowed
        assert not extra, f"{name} imports outside its document: {sorted(extra)}"
