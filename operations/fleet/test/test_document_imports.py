"""Fleet console documents reach only their own modules and shared reads.

D-410 splits operate and install. D-450 keeps Cell on `/console/cell`.
D-518 adds the site-map document and names the shared-read modules; D-519 adds password-login.js; D-540 adds fleet-header.js.
D-540 5 moves the start points and the background relearn from the console to install.
An entry that reaches another document's module fails this test.
"""

import re
import json
from pathlib import Path


WEB = Path(__file__).resolve().parents[3] / 'applications/fleet/web'
ASSETS = json.loads((WEB / 'assets.json').read_text(encoding='utf-8'))['assets']

_FROM = re.compile(r"""\bfrom\s+['"]([^'"]+)['"]""")
_DYNAMIC = re.compile(r"(?<![\w.])import\s*\(")
_ASSET = "/console/assets/"

SHARED = {
    "robot-profile-view.js",  # Read-only profiles shared by Console, Cell and Installation.
    "app-runtime.js",
    "address-drift.js",
    "authorization.js",
    "poll-gate.js",
    "uuid.js",  # DOM-free CSPRNG identifiers shared by Console, Cell and site-map documents.
    "development-auth.js",
    "password-login.js",
    "account-permissions.js",  # D-757: shared read-only session capability predicates
    "login-return.js",
    "fleet-header.js",  # D-540 2: the one header of the four documents
    "map-fit.js",
    "site-layer.js",  # metre grid lines used by the console map and the install plane
    "vision-view.js",
    "power-action.js",  # D-440 6: the robot card's sleep / wake button, out of roster.js
    "area-nav.js",  # D-741 6·7: the address view picks the area (rail and sub-nav state)
    "field-warp.js",
    "guide-layer.js",  # D-540 4: the site map draws the same /guide robot marks as the 관제 map
    "site-map-model.js",  # D-517 10: DOM-free lane/trip model; the console reads the traffic helpers
    "trip-display.js",  # DOM-free trip vocabulary shared by map and Console consumers.
    "route-attention.js",
    "drawing-errors.js",
}

OWN = {
    "account-page.js": set(),
    "console.js": {
        "assistant.js", "assistant-voice.js",  # D-810: operator dialogue belongs to Console.
        "work-view.js",  # D-664: common read view; execution stays with each owner
        "channel-request-view.js",  # D-680: named review and existing navigation submission
        "control-unit-view.js",  # D-855: delegation review belongs to Console.
        "arm-transfer-view.js",  # Neutral ARM admission belongs to Console, never install or Cell.
        "trip-proposal-view.js",  # D-908: neutral trip admission belongs to Console.
        "integrated-control-view.js",  # D-862: unit information and stop requests belong to Console.
        "inbox.js",  # D-632: console notification and context view owner
        "incident-view.js",  # D-362/D-641: incident evidence, review and export view
        "connection-view.js",
        "formation.js",
        "map-view.js",
        "map-overlays.js",  # D-798 3.2: map-view.js overlay drawing
        "map-polling.js",  # D-798 3.2: map-view.js polling
        "console-auth.js",  # D-798 3.2: console.js lock, session and token handling
        "console-goal.js",  # D-798 3.2: console.js goal targeting and operator pin
        "console-refresh.js",  # D-798 3.2: console.js dispatch, site path, state poll, cancel-all
        "roster.js",
        "roster-cards.js",  # Retains focused cards only within the robot workspace.
        "motor-health-view.js",  # Fleet robot rows adapt shared read-only motor evidence.
        "roster-presentation.js",
        "device-discovery.js",
        "queues.js",  # D-540 (d): the exception queues, moved out of roster.js
        "card-trip.js",  # D-540 (d): the card 운행… form and the 대형·대열 convoy
        "line-stuck.js",
        "stuck-evidence.js",  # network load: the stuck picture as raw JPEG (line-stuck.js)
        "device-watch.js",  # map-stage watch: ceiling toggle and the stuck front frame
        "trip-replan.js",  # D-540 3: the replan confirm in its queue row
        "signals.js",
        "tracking-view.js",
        "tracking-layer.js",
        "trail-view.js",
        "site-path.js",
        "confirmed-action.js",
        "camera-warp.js",
        "camera-backdrop.js",
        "map-datum.js",  # origin axes shared by the occupancy grid and the metre site view
        "traffic-view.js",
        "motion-readiness.js",
        "link-tag.js",
        "localization-badge.js",
        "power-health-view.js",
        "state-age.js",
    },
    "install.js": {
        "device-profiles.js", "device-care.js",  # Metadata and care editing stay in Installation.
        "enrollment.js",
        "camera-pairing.js",
        "camera-peer.js",
        "field-view.js",
        "field-layers.js",
        "map-fit-view.js",
        "measured-calibration-view.js",
        "peer-picker.js",
        "start-point-view.js",  # D-540 5: 카메라 설치·보정
        "start-point-layer.js",
        "tracking-relearn.js",  # D-540 5 / D-539: 배경 다시 학습
        "host-services.js",  # D-524 / D-530: 호스트 여유와 닫힌 서비스 제어
        "host-health.js",  # D-530: 읽기 전용 PC 상태 판정
    },
    "cell.js": {
        "cell-document-editor.js",
        "cell-observation.js",
    },
    "site-map.js": {
        "map-authoring.js", "map-editor.js", "drawing-import.js", "geometry-edit.js", "edit-history.js",
        "map-topology.js", "extraction-review.js",
        "site-map-teach.js",
        "site-map-survey.js",
        "site-map-camera.js",
        "site-map-sources.js",  # Map profile selection and read-only camera-plane presentation.
        "site-map-edit.js",  # D-655: pure draft edits belong to the map editor document
    },
}


def _local(spec):
    if spec.startswith("./"):
        return spec[2:]
    if spec.startswith(_ASSET):
        return spec[len(_ASSET):]
    return None


def _path(name):
    if name in ASSETS:
        return WEB / ASSETS[name]['path']
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
