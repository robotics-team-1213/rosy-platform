"""The signed Account artifact contains its own code and fixed UI, independently of Fleet."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMMON = {'tokens.css', 'components.css', 'theme.js', 'ui.js', 'ui-wiring.js',
          'confirmation.js', 'live-dialog-geometry.js', 'fleet-client.js', 'request.js',
          'icons/console.svg', 'brand/mark.svg'}


def bundle(repo, output):
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'operations/account')}
    return subprocess.run([sys.executable, '-m', 'rosy_account.web_assets',
                           '--repo', str(repo), '--output', str(output)],
                          cwd=output.parent, env=env, capture_output=True, text=True)


def test_account_bundle_has_only_account_pages_assets_and_common_dependencies(tmp_path):
    output = tmp_path / 'bundle'
    result = bundle(ROOT, output)
    assert result.returncode == 0, result.stderr
    registry = json.loads((output / 'console/assets.json').read_text())
    assert set(registry['pages']) == {'/console/login', '/console/profile', '/console/accounts'}
    assert len(registry['assets']) == 10
    common = json.loads((output / 'common/shared-assets.json').read_text())['shared_assets']
    assert set(common) == COMMON
    expected = {'console/assets.json', 'common/shared-assets.json'}
    expected.update('console/' + entry['path'] for group in ('pages', 'assets') for entry in registry[group].values())
    expected.update('common/' + name for name in common)
    assert {str(p.relative_to(output)).replace('\\', '/') for p in output.rglob('*') if p.is_file()} == expected
    assert (output / 'common/brand/mark.svg').read_bytes() == (ROOT / 'shared/web/brand/mark.svg').read_bytes()


@pytest.mark.parametrize('damage', ['missing', 'escape', 'undeclared'])
def test_account_bundle_refuses_incomplete_or_escaping_asset_closure(tmp_path, damage):
    repo = tmp_path / 'repo'
    shutil.copytree(ROOT / 'applications/fleet/web', repo / 'applications/fleet/web')
    shutil.copytree(ROOT / 'shared/web', repo / 'shared/web')
    if damage == 'missing':
        (repo / 'shared/web/confirmation.js').unlink()
    elif damage == 'escape':
        path = repo / 'applications/fleet/web/assets.json'
        registry = json.loads(path.read_text())
        registry['pages']['/console/login']['path'] = '../../../outside.html'
        path.write_text(json.dumps(registry))
    else:
        with (repo / 'applications/fleet/web/login.html').open('a') as stream:
            stream.write('<script type="module" src="/console/assets/site-map.js"></script>')
    result = bundle(repo, tmp_path / 'bundle')
    assert result.returncode != 0
    assert not (tmp_path / 'bundle').exists()


def test_account_image_context_has_no_control_python_or_runtime_dependency():
    docker = (ROOT / 'deploy/site/Dockerfile.account').read_text()
    assert not re.search(r'^FROM\s+.*rosy-site-fleet', docker, re.M | re.I)
    assert 'USER 10001:10001' in docker
    assert 'ENTRYPOINT ["python3", "-m", "rosy_account"]' in docker
    sources = []
    for line in docker.replace('\\\n', ' ').splitlines():
        words = line.split()
        if words and words[0] == 'COPY' and not any(w.startswith('--from=') for w in words):
            sources.extend(w for w in words[1:-1] if not w.startswith('--'))
    assert 'operations/account/rosy_account/' in sources
    assert all(not p.startswith(('operations/fleet/', 'middleware/', 'applications/fleet/gateway/',
                                 'operations/decision/', 'operations/world/')) for p in sources)
    foundation = [p for p in sources if p.startswith('contracts/')]
    assert set(foundation) == {'contracts/foundation/core_common/__init__.py',
                               'contracts/foundation/core_common/protocol/__init__.py',
                               'contracts/foundation/core_common/protocol/account_access.py'}
    dependencies = (ROOT / 'deploy/site/requirements-account.txt').read_text()
    assert not any(name in dependencies for name in ('opencv', 'numpy', 'Pillow', 'psycopg', 'zeroconf'))
