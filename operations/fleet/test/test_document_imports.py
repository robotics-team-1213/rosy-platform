"""Fleet console documents reach only their own modules and shared reads.

D-410 splits operate and install. D-450 keeps Cell on `/console/cell`.
D-518 adds the site-map document and names the shared-read modules; D-519 adds password-login.js.
An entry that reaches another document's module fails this test.
"""

import re
from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "fleet" / "server" / "web"

_FROM = re.compile(r"""\bfrom\s+['"]([^'"]+)['"]""")
_DYNAMIC = re.compile(r"(?<![\w.])import\s*\(")
_ASSET = "/console/assets/"

SHARED = {
    "address-drift.js",
    "authorization.js",
    "poll-gate.js",
    "development-auth.js",
    "password-login.js",
    "map-fit.js",
    "vision-view.js",
    "field-warp.js",
}

OWN = {
    "console.js": {
        "connection-view.js",
        "formation.js",
        "map-view.js",
        "roster.js",
        "line-stuck.js",
        "signals.js",
        "tracking-view.js",
        "tracking-layer.js",
        "start-point-view.js",
        "start-point-layer.js",
        "site-path.js",
        "site-layer.js",
        "confirmed-action.js",
        "camera-warp.js",
        "motion-readiness.js",
        "link-tag.js",
        "localization-badge.js",
        "power-health-view.js",
        "state-age.js",
    },
    "install.js": {
        "enrollment.js",
        "camera-pairing.js",
        "camera-peer.js",
        "field-view.js",
        "field-layers.js",
        "map-fit-view.js",
        "peer-picker.js",
    },
    "cell.js": {
        "cell-document-editor.js",
    },
    "site-map.js": {
        "site-map-model.js",
        "site-map-teach.js",
    },
}


def _local(spec):
    if spec.startswith("./"):
        return spec[2:]
    if spec.startswith(_ASSET):
        return spec[len(_ASSET):]
    return None


def _path(name):
    for folder in ("shared", "cell"):
        path = WEB / folder / name
        if path.is_file():
            return path
    return WEB / name


def _imports(name):
    text = _path(name).read_text(encoding="utf-8")
    found = set()
    for spec in _FROM.findall(text):
        local = _local(spec)
        if local is not None:
            found.add(local)
    return found


def _reached(entry):
    seen = set()
    stack = [entry]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        stack.extend(sorted(_imports(name)))
    seen.discard(entry)
    return seen


def test_each_console_document_reaches_only_its_modules():
    for entry, owned in OWN.items():
        text = _path(entry).read_text(encoding="utf-8")
        assert not _DYNAMIC.search(text), f"{entry} uses a dynamic import"
        extra = _reached(entry) - owned - SHARED
        assert not extra, f"{entry} reaches another document: {sorted(extra)}"
