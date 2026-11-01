"""D-939: app link code lives once under shared/android, never as a renamed copy in each app."""

from itertools import combinations
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / 'shared/android/peer'
APPS = {
    'pilot': ROOT / 'middleware/robot_ui/pilot/android/app',
    'cam': ROOT / 'operations/site_ui/cam/app',
}
PRODUCT_SETS = ('main', 'debug')
DECLARATION = re.compile(r'^\s*(?:(?:internal|private|data|sealed|abstract|open|enum)\s+)*'
                         r'(?:class|object|interface)\s+([A-Z]\w*)', re.M)
APP_PREFIX = re.compile(r'\b(?:Pilot|Camera|Cam|Peer|Robot|Site)(?=[A-Z])')
COPY_RATIO, COPY_MIN_LINES = 0.85, 10


def _product_sources(app):
    for source_set in PRODUCT_SETS:
        yield from sorted((app / 'src' / source_set).rglob('*.kt'))


def _normalized(path):
    lines = set()
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith(('package ', 'import ', '//', '/*', '*')):
            continue
        line = APP_PREFIX.sub('X', line)
        lines.add(re.sub(r'"(?:pilot|cam)[^"]*"', '"A"', line))
    return lines


def test_every_app_compiles_the_shared_peer_sources():
    for name, app in APPS.items():
        build = (app / 'build.gradle.kts').read_text(encoding='utf-8')
        assert re.search(r'srcDir\("(?:\.\./)+shared/android/peer"\)', build), f'{name} must compile shared/android/peer'


def _stem(name):
    # AndroidCameraIdentity, CameraProof and PilotProof all redeclare AndroidPeerIdentity / PeerProof.
    return re.sub(r'Pilot|Camera|Cam|Peer', '', name)


def test_apps_do_not_redeclare_shared_types():
    shared = {name for path in SHARED.rglob('*.kt') for name in DECLARATION.findall(path.read_text(encoding='utf-8'))}
    assert {'PeerProof', 'PeerTls', 'AndroidPeerIdentity'} <= shared
    stems = {_stem(name) for name in shared}
    found = [f'{path.relative_to(ROOT)}: {declared}'
             for app in APPS.values() for path in _product_sources(app)
             for declared in DECLARATION.findall(path.read_text(encoding='utf-8')) if _stem(declared) in stems]
    assert not found, 'use shared/android/peer instead of redeclaring (D-939):\n' + '\n'.join(found)


def test_apps_hold_no_renamed_copies_of_each_other():
    sources = {name: [(path, _normalized(path)) for path in _product_sources(app)] for name, app in APPS.items()}
    copies = []
    for left, right in combinations(sources, 2):
        for (a, la) in sources[left]:
            for (b, lb) in sources[right]:
                if min(len(la), len(lb)) < COPY_MIN_LINES:
                    continue
                ratio = len(la & lb) / min(len(la), len(lb))
                if ratio >= COPY_RATIO:
                    copies.append(f'{a.relative_to(ROOT)} ~ {b.relative_to(ROOT)} ({ratio:.2f})')
    assert not copies, 'move the common code to shared/android (D-939):\n' + '\n'.join(copies)
