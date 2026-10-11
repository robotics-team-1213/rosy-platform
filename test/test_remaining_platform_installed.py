"""Decision namespace and Console assets survive Fleet wheel and sdist delivery."""

import hashlib
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tarfile

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
    support = staging / 'tools/packaging/fleet_sources.py'
    support.parent.mkdir(parents=True)
    shutil.copy2(ROOT / 'tools/packaging/fleet_sources.py', support)
    sources = []
    for relative in ('operations/fleet', 'operations/decision', 'operations/ui/console', 'operations/situation',
                     'contracts/foundation', 'contracts/skill', 'operations/world',
                     'operations/execution', 'middleware/skills/api'):
        copied = staging / relative
        shutil.copytree(ROOT / relative, copied,
                        ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', '*.egg-info'))
        if relative not in ('operations/decision', 'operations/ui/console', 'operations/situation'):
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
        with tarfile.open(sources[0]) as archive:
            assert any(name.endswith('/_build/fleet_sources.py') for name in archive.getnames())
            assessment_files = {Path(name).name for name in archive.getnames()
                                if '/_source_roots/assessment/' in name and name.endswith('.py')}
            assert assessment_files == {'__init__.py', 'assessment.py', 'snapshot_assessment.py'}
        # Removing the sibling holders proves the archive is self-contained.
        shutil.rmtree(staging / 'operations/decision')
        shutil.rmtree(staging / 'operations/ui/console')
        shutil.rmtree(staging / 'operations/situation')
        shutil.rmtree(staging / 'tools')
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
assert not (installed / '_build').exists()
from rosy_situation.assessment import AssessmentInput, AssessmentPolicy, EvidenceRef, assess
assert not any(name in sys.modules for name in ('fleet', 'sqlite3', 'httpx', 'rclpy'))
request = AssessmentInput('robot', None, 'state-1', 'core', 'normal',
                          (EvidenceRef('robot', 'core', 'state-1', 99.0),))
assert assess(request, now=100.0, policy=AssessmentPolicy('v1', 3, 0, 3)).necessity == 'DO_NOT_INTERVENE'
assert importlib.util.find_spec('fleet.server.model_feedback_dispatch') is not None
assert importlib.util.find_spec('rosy.decision.tool_dispatch') is None
for name in json.loads(sys.argv[2]):
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(installed), name
from rosy.decision.model_tool_contract import ModelToolCall
from fleet.server import proposal_store
assert proposal_store.ModelToolCall is ModelToolCall
assert importlib.util.find_spec('fleet.ai') is None
assert importlib.util.find_spec('rosy_situation.service') is None
assert importlib.util.find_spec('rosy_situation.analyzers') is None
assert importlib.util.find_spec('rosy_situation.incidents') is None
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
               'rosy.decision.tool_dispatch', 'rosy_situation.assessment', 'rosy_situation.snapshot_assessment']
    for order in (modules, list(reversed(modules))):
        run(['-I', '-c', probe, str(installed), json.dumps(order), json.dumps(expected)], tmp_path)


def test_fleet_source_image_keeps_only_the_pure_assessment_closure(tmp_path):
    image = tmp_path / 'image'
    dockerfile = ROOT / 'deploy/site/Dockerfile.fleet'
    for line in dockerfile.read_text(encoding='utf-8').splitlines():
        if not line.startswith('COPY '):
            continue
        words = shlex.split(line)
        destination = image / words[-1].lstrip('/')
        destination.mkdir(parents=True, exist_ok=True)
        for name in words[1:-1]:
            source = ROOT / name
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
            else:
                shutil.copy2(source, destination)
    roots = [image / 'opt/rosy/src' / path for path in
             ('site/fleet', 'contracts/foundation', 'operations/world')]
    probe = r'''
import importlib.util
import json
import sys
sys.path[:0] = json.loads(sys.argv[1])
from fleet.stuck.board import LineStuckBoard
from rosy_situation.assessment import Assessment
assert importlib.util.find_spec('rosy_situation.service') is None
board = LineStuckBoard(clock=lambda: 100.0, wall=lambda: 100.0)
board.observe([{'robot_id': 'pinky', 'online': False}])
assert isinstance(board.intervention_assessment('pinky'), Assessment)
assert board.intervention_assessment('pinky').necessity == 'ABSTAIN'
'''
    run(['-I', '-c', probe, json.dumps(list(map(str, roots)))], tmp_path)
    package = image / 'opt/rosy/src/site/situation/rosy_situation'
    assert {p.name for p in package.glob('*.py')} == {'__init__.py', 'assessment.py', 'snapshot_assessment.py'}
    allowed = {line for line in (ROOT / 'deploy/site/Dockerfile.fleet.dockerignore').read_text().splitlines()
               if line.startswith('!operations/situation')}
    assert allowed == {'!operations/situation/rosy_situation/' + name for name in
                       ('__init__.py', 'assessment.py', 'snapshot_assessment.py')}
