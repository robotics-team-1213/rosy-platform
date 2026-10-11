"""Decision namespace and Console assets survive Fleet wheel and sdist delivery."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd):
    result = subprocess.run([sys.executable, *args], cwd=cwd,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.mark.parametrize('delivery', ['wheel', 'sdist'])
def test_fleet_delivery_keeps_decision_namespace_and_console_resources(tmp_path, delivery):
    staging = tmp_path / 'source'
    sources = []
    for relative in ('operations/fleet', 'operations/decision', 'operations/ui/console',
                     'contracts/foundation', 'contracts/skill', 'operations/world',
                     'operations/execution', 'middleware/skills/api'):
        copied = staging / relative
        shutil.copytree(ROOT / relative, copied,
                        ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', '*.egg-info'))
        if relative not in ('operations/decision', 'operations/ui/console'):
            sources.append(copied)
    expected = {p.relative_to(ROOT / 'operations/ui/console').as_posix():
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ROOT / 'operations/ui/console').rglob('*')
                if p.is_file() and p.suffix in ('.py', '.html', '.css', '.js')}
    assert len(expected) == 66  # AGENTS.md and source-only package.json were not installed.
    assert 'incident-view.js' in expected
    if delivery == 'sdist':
        archives = tmp_path / 'archives'
        run(['setup.py', 'sdist', '--dist-dir', str(archives)], staging / 'operations/fleet')
        sources[0] = next(archives.glob('fleet-*.tar.gz'))
        # Removing the sibling holders proves the archive is self-contained.
        shutil.rmtree(staging / 'operations/decision')
        shutil.rmtree(staging / 'operations/ui/console')
    wheels = tmp_path / 'wheels'
    run(['-m', 'pip', '--disable-pip-version-check', 'wheel', '--no-deps',
         '--no-build-isolation', '--wheel-dir', str(wheels), *map(str, sources)], tmp_path)
    installed = tmp_path / 'installed'
    run(['-m', 'pip', '--disable-pip-version-check', 'install', '--no-deps', '--no-index',
         '--target', str(installed), *map(str, wheels.glob('*.whl'))], tmp_path)
    shutil.copytree(ROOT / 'shared/web', installed / 'shared-web',
                    ignore=shutil.ignore_patterns('__pycache__', 'test', '*.md'))
    probe = r'''
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
installed = Path(sys.argv[1]).resolve()
for name in json.loads(sys.argv[2]):
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(installed), name
from rosy.decision.model_tool_contract import ModelToolCall
from fleet.server import proposal_store
assert proposal_store.ModelToolCall is ModelToolCall
assert importlib.util.find_spec('fleet.ai') is None
from fleet.server.static_routes import WEB_ROOT, CONSOLE_ASSETS, CONSOLE_CSP, install_static_routes
assert WEB_ROOT == installed / 'fleet/server/web'
actual = {p.relative_to(WEB_ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in WEB_ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
assert actual == json.loads(sys.argv[3])
from fastapi import FastAPI
from fastapi.testclient import TestClient
app = FastAPI()
app.state.web_common = installed / 'shared-web'
install_static_routes(app)
with TestClient(app) as client:
    response = client.get('/console')
    assert response.status_code == 200
    assert response.headers['content-security-policy'] == CONSOLE_CSP
    for name in CONSOLE_ASSETS:
        assert client.get('/console/assets/' + name).status_code == 200, name
    assert client.get('/console/assets/not-allowed.js').status_code == 404
    assert client.get('/console/assets/%2e%2e/package.xml').status_code == 404
print('installed namespace, resources and HTTP guards verified')
'''
    modules = ['rosy.world.api', 'rosy.execution.api', 'rosy.skills.api',
               'fleet.server.proposal_store', 'rosy.decision.model_tool_contract',
               'rosy.decision.tool_dispatch']
    for order in (modules, list(reversed(modules))):
        run(['-I', '-c', probe, str(installed), json.dumps(order), json.dumps(expected)], tmp_path)
