"""Decision namespace and Console assets survive Fleet wheel and sdist delivery."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tarfile
import zipfile

import pytest
import yaml
from setuptools.command.develop import develop

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd):
    result = subprocess.run([sys.executable, *args], cwd=cwd,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_offline_installers_use_the_current_learning_contract_wheel():
    import tomllib
    version = tomllib.loads((ROOT / 'contracts/learning/pyproject.toml').read_text())['project']['version']
    for path in ('.github/workflows/ci.yml', 'middleware/robot_execution/local/pyproject.toml'):
        assert f'rosy-contracts-learning=={version}' in (ROOT / path).read_text()


@pytest.mark.parametrize('delivery', ['wheel', 'sdist'])
def test_fleet_delivery_keeps_decision_namespace_and_console_resources(tmp_path, delivery):
    from test_incident_operation_contract import APPROVE, KEY, binding, signed
    staging = tmp_path / 'source'
    support = staging / 'tools/packaging/fleet_sources.py'
    support.parent.mkdir(parents=True)
    shutil.copy2(ROOT / 'tools/packaging/fleet_sources.py', support)
    sources = []
    for relative in ('operations/fleet', 'operations/decision', 'applications/fleet/web', 'operations/situation',
                     'contracts/foundation', 'contracts/skill', 'contracts/motion', 'contracts/learning', 'operations/world',
                     'operations/site_execution', 'operations/processes/palletizing', 'applications/fleet/gateway',
                     'middleware/core/api', 'middleware/skills/api', 'integrations/messaging/discord'):
        copied = staging / relative
        shutil.copytree(ROOT / relative, copied,
                        ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', '*.egg-info'))
        if relative not in ('operations/decision', 'applications/fleet/web', 'operations/situation',
                            'integrations/messaging/discord'):
            sources.append(copied)
    expected = {p.relative_to(ROOT / 'applications/fleet/web').as_posix():
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ROOT / 'applications/fleet/web').rglob('*')
                if p.is_file() and (p.suffix in ('.py', '.html', '.css', '.js') or p.name == 'assets.json')}
    assert {'asset_registry.py', 'assets.json', 'runtime.js'} <= expected.keys()
    assert not any(p.startswith(('dev/', 'sample/')) for p in expected)
    assert {'shared/host-health.js', 'shared/stuck-evidence.js',
            'shared/robot-video.js', 'shared/robot-video.css'} <= expected.keys()
    assert {'calibration/__init__.py', 'calibration/measured-calibration-view.js',
            'calibration/measured-calibration.css'} <= expected.keys()
    assert {'devices/__init__.py', 'devices/device-discovery.js'} <= expected.keys()
    assert {'accounts.html', 'shared/account-page.js', 'shared/account-permissions.js'} <= expected.keys()
    assert {'login.html', 'shared/login-page.js', 'shared/login-return.js'} <= expected.keys()
    assert {'profile.html', 'shared/profile-page.js'} <= expected.keys()
    assert {'incident-view.js', 'sitemap/site-map-survey.js', 'sitemap/site-map-camera.js', 'shared/site-map-edit.js',
            'work/__init__.py', 'work/work-view.js', 'work/work.css', 'shared/power-action.js', 'shared/area-nav.js', 'work/channel-request-view.js'} <= expected.keys()
    assert {'sitemap/edit-history.js', 'sitemap/geometry-edit.js', 'sitemap/drawing-import.js', 'sitemap/map-editor.js',
            'sitemap/map-authoring.js', 'sitemap/map-editor.css', 'sitemap/map-topology.js',
            'sitemap/extraction-review.js', 'shared/drawing-errors.js', 'cell/cell-observation.js',
            'motor-health-view.js', 'roster-cards.js', 'learning.html'} <= expected.keys()
    # Colcon selects full install for external holders instead of unsafe editable cleanup.
    develop_help = run(['setup.py', '--help', 'develop'], staging / 'operations/fleet').stdout
    assert not any(line.lstrip().startswith('--editable') for line in develop_help.splitlines()), develop_help
    if {'editable', 'uninstall'} <= {option[0] for option in develop.user_options}:
        uninstall_help = run(['setup.py', 'develop', '--uninstall', '--help'], staging / 'operations/fleet').stdout
        assert any(line.lstrip().startswith('--editable') for line in uninstall_help.splitlines()), uninstall_help
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
        shutil.rmtree(staging / 'applications/fleet/web')
        shutil.rmtree(staging / 'operations/situation')
        shutil.rmtree(staging / 'integrations/messaging/discord')
        shutil.rmtree(staging / 'tools')
    wheels = tmp_path / 'wheels'
    run(['-m', 'pip', '--disable-pip-version-check', 'wheel', '--no-deps',
         '--no-build-isolation', '--wheel-dir', str(wheels), *map(str, sources)], tmp_path)
    with zipfile.ZipFile(next(wheels.glob('fleet-*.whl'))) as wheel:
        names = wheel.namelist()
        assert not any(name.startswith(('fleet_app_dev/', 'fleet/server/web/dev/', 'fleet/server/web/sample/'))
                       or name.endswith('runtime-sample.js') for name in names)
        for holder in ('peer', 'cell', 'auth', 'console', 'ledger', 'missions', 'work', 'trips', 'trip_checks', 'trip_progress', 'tracking',
                       'evidence', 'sitemap', 'pose', 'recognition', 'rightofway'):
            for source in (ROOT / 'operations/fleet/fleet/server' / holder).glob('*.py'):
                target = 'fleet/server/' + source.name
                assert names.count(target) == 1
                assert wheel.read(target) == source.read_bytes()
            assert not any(name.startswith('fleet/server/' + holder + '/') for name in names)
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
from rosy.execution.site.goal_evidence import GoalEvidence, GoalEvidenceError, GoalPredicate, verify_goal
from rosy.execution.site.workflow import project_progress
assert not any(name in sys.modules for name in ('fleet', 'sqlite3', 'httpx', 'rclpy', 'core'))
try:
    GoalPredicate.from_mapping({'predicate_id': 'p', 'condition': 'object_in_destination',
                                'object_id': 'o', 'destination_id': 'd', 'evidence_source': 'model_summary'})
except ValueError:
    pass
else:
    raise AssertionError('model summary admitted as independent goal evidence')
from rosy_situation.assessment import AssessmentInput, AssessmentPolicy, EvidenceRef, assess
from rosy.execution.site.goal_evidence import GoalEvidence
from rosy.execution.site.workflow import mission_step_state, project_progress
assert not any(name in sys.modules for name in ('fleet', 'sqlite3', 'httpx', 'rclpy'))
assert 'core_common' not in sys.modules
assert mission_step_state('ACTION_SUCCEEDED') == 'AWAITING_GOAL_EVIDENCE'
import importlib.metadata
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
distributions = {canonicalize_name(d.metadata['Name']): d
                 for d in importlib.metadata.distributions(path=[sys.argv[1]])}
for distribution in distributions.values():
    for raw_requirement in distribution.requires or []:
        requirement = Requirement(raw_requirement)
        dependency = distributions.get(canonicalize_name(requirement.name))
        if dependency is not None:
            assert dependency.version in requirement.specifier, (distribution.metadata['Name'], raw_requirement)
execution_requirements = {(canonicalize_name(r.name), str(r.specifier), tuple(sorted(r.extras)), r.marker, r.url)
                          for r in map(Requirement, importlib.metadata.requires('rosy-execution'))}
assert ('core-common', '==0.0.2', (), None, None) in execution_requirements, execution_requirements
from datetime import datetime, timezone
projected = project_progress({
    'mission': {'status': 'ACTION_SUCCEEDED', 'updated_at': '1970-01-01T00:01:40+00:00',
                'reason': None, 'dispatch_generation': 1, 'action_id': 'a', 'attempt_id': 't'},
    'progress_events': [], 'snapshot_event_id': 1, 'stop_control': None,
    'history': [], 'history_truncated': False,
}, now=datetime.fromtimestamp(100, timezone.utc))
assert projected['progress']['step']['state'] == 'AWAITING_GOAL_EVIDENCE'
assert projected['progress']['goal_evidence']['state'] == 'PENDING'
assert projected['progress']['stop']['physical_state'] == 'UNKNOWN'
assert not any(name in sys.modules for name in ('fleet', 'sqlite3', 'httpx', 'rclpy'))
fleet_files = importlib.metadata.distribution('fleet').files
assert not any(str(name).startswith('rosy/execution/') for name in fleet_files)
fleet_requirements = {(canonicalize_name(r.name), str(r.specifier), tuple(sorted(r.extras)), r.marker, r.url)
                      for r in map(Requirement, importlib.metadata.requires('fleet'))}
assert ('rosy-execution', '==0.1.2', (), None, None) in fleet_requirements, fleet_requirements
foundation_floor = [r for r in map(Requirement, importlib.metadata.requires('fleet'))
                    if canonicalize_name(r.name) == 'core-common']
assert len(foundation_floor) == 1
assert '0.0.1' not in foundation_floor[0].specifier
assert '0.0.2' in foundation_floor[0].specifier
api_floor = [r for r in map(Requirement, importlib.metadata.requires('core_api_web'))
             if canonicalize_name(r.name) == 'core-common']
assert len(api_floor) == 1
assert '0.0.1' not in api_floor[0].specifier and '0.0.2' in api_floor[0].specifier
from core_common.protocol.schemas import LineStuckPrecondition
from core_common.protocol.line_stuck import LineStuckPrecondition as OwnedPrecondition
from core_common.protocol.native.operation import NativeOperation
from core_common.protocol.native_operation import NativeOperation as LegacyNativeOperation
from core_common.protocol.native.receipts import NativeReceipts
from core_common.protocol.native_receipts import NativeReceipts as LegacyNativeReceipts
assert NativeOperation is LegacyNativeOperation
assert NativeReceipts is LegacyNativeReceipts
assert LineStuckPrecondition is OwnedPrecondition
assert Path(__import__('core_common.protocol.line_stuck', fromlist=['']).__file__).is_relative_to(installed)
assert LineStuckPrecondition(phase='ASKING', attempts=0).model_dump() == {'phase': 'ASKING', 'attempts': 0}
assert ('rosy-contracts-learning', '>=0.1.12', (), None, None) in fleet_requirements, fleet_requirements
from rosy.contracts.learning import incident_rule
assert Path(incident_rule.__file__).is_relative_to(installed)
from rosy.contracts.learning import incident_operation
assert Path(incident_operation.__file__).is_relative_to(installed)
operation = json.loads(sys.argv[4])
assert incident_operation.verify_operation_receipt(operation,
    trusted={'reviewer': {'key': bytes.fromhex(sys.argv[6]), 'kinds': {incident_operation.APPROVE}}},
    expected_binding=json.loads(sys.argv[5]), epoch=3, now=101,
    kind=incident_operation.APPROVE) == operation
assert 'action_admissible' not in operation
from fleet.incidents.automation.recovery_candidates import RecoveryCandidates
from fleet.incidents.automation.operating.candidates import RecoveryCandidates as OperatingCandidates
assert RecoveryCandidates is OperatingCandidates
from fleet.stuck.loop import StuckResolverLoop
for name in ('requests', 'workflow', 'missions', 'incidents', 'replies', 'gateway',
             'deliberation', 'model_worker', 'model_runtime'):
    legacy = importlib.import_module('fleet.server.channel_' + name)
    owner = importlib.import_module('fleet.server.channel.' + name)
    assert legacy is owner
    assert Path(owner.__file__).resolve().is_relative_to(installed / 'fleet/server/channel')

from fleet.stuck.board import LineStuckBoard
from fleet.stuck.resolver import StuckResolver, ResolverConfig
from fleet.swarm.transport import HttpRobotClient, RobotApiError
from fleet.swarm.robots import RobotEndpoint
import asyncio
import httpx
async def check_installed_submission_guard():
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={'stuck': {'conditional_back': True}})
    async def refuse():
        assert calls == ['GET']
        return False
    client = HttpRobotClient(RobotEndpoint('robot', 'http://robot:8080', 'test-token'),
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://robot:8080'))
    try:
        await client.line_stuck_decision('case', 'BACK_AND_RETRY',
            expected_stuck={'phase': 'ASKING', 'attempts': 0}, before_submit=refuse)
        raise AssertionError('installed submission guard did not refuse')
    except RobotApiError as error:
        assert error.code == 'STUCK_DECISION_REFUSED' and calls == ['GET']
    finally:
        await client.aclose()
asyncio.run(check_installed_submission_guard())
loop = StuckResolverLoop(None, LineStuckBoard(), StuckResolver(ResolverConfig()), clients=lambda: {})
assert loop.rule_selections is None
request = AssessmentInput('robot', None, 'state-1', 'core', 'normal',
                          (EvidenceRef('robot', 'core', 'state-1', 99.0),))
assert assess(request, now=100.0, policy=AssessmentPolicy('v1', 3, 0, 3)).necessity == 'DO_NOT_INTERVENE'
assert importlib.util.find_spec('fleet.server.model_feedback_dispatch') is not None
assert importlib.util.find_spec('rosy.decision.tool_dispatch') is None
from rosy_discord.intake import project_message, signed_request
from rosy_discord.gateway import DiscordGateway
from fleet.server.channel_incidents import incident_view, install_channel_incident_routes
from core_common.protocol.channel_requests import ChannelIncidentClaimRequest
from core_common.protocol.schemas import ChannelIncidentClaimRequest as ExportedIncidentRequest
assert ExportedIncidentRequest is ChannelIncidentClaimRequest
assert Path(importlib.util.find_spec('fleet.server.channel_incidents').origin).is_relative_to(installed)
assert Path(importlib.util.find_spec('rosy_discord.intake').origin).is_relative_to(installed)
assert Path(importlib.util.find_spec('rosy_discord.gateway').origin).is_relative_to(installed)
from fleet.server.channel.health import BareDiscordPublisher, HourlyHealth
health_spec = importlib.util.find_spec('fleet.server.channel.health')
assert Path(health_spec.origin).resolve().is_relative_to(installed / 'fleet/server/channel/health')
assert importlib.util.find_spec('fleet.server.goal_evidence') is None
for name in json.loads(sys.argv[2]):
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(installed), name
from rosy.decision.model_tool_contract import ModelToolCall
from rosy.decision.deliberation import calibration, cli, judgment, profiles
from rosy.decision.deliberation.contracts import judgment as judgment_owner, profiles as profile_owner
from rosy.decision.deliberation.providers import cli as cli_owner
from rosy.decision.deliberation.evaluation import calibration as calibration_owner
assert profiles.ModelProfile is profile_owner.ModelProfile
assert judgment.Judgment is judgment_owner.Judgment
assert cli.CliProvider is cli_owner.CliProvider
assert cli._argv is cli_owner._argv
assert cli._decode_result is cli_owner._decode_result
assert calibration.CalibrationArtifact is calibration_owner.CalibrationArtifact
assert calibration.evaluate_calibration is calibration_owner.evaluate_calibration
assert calibration.wilson_lower is calibration_owner.wilson_lower
from fleet.incidents.automation import contract, store
from fleet.incidents.automation.ledger import contract as ledger_contract, store as ledger_store
from fleet.incidents.automation import closure, worker
from fleet.incidents.automation.execution import worker as execution_worker
assert worker.IncidentCaseWorker is execution_worker.IncidentCaseWorker
for name in ('dataclass', 'Decimal', 'ROUND_CEILING', 'ROUND_FLOOR', 'math', 're',
             'CHOICES', 'canonical', 'identifier', 'sha256', 'micros',
             'CaseScope', 'CaseBudget', 'summary_json'):
    assert getattr(contract, name) is getattr(ledger_contract, name), name
for name in ('closing', 'contextmanager', 'asdict', 'json', 'math', 'Path', 'sqlite3',
             'time', 'canonical', 'identifier', 'CaseBudget', 'CaseScope', 'micros',
             'sha256', 'summary_json', 'configure_connection', 'IncidentCaseStore'):
    assert getattr(store, name) is getattr(ledger_store, name), name
assert closure.CaseScope is ledger_contract.CaseScope
assert worker.CaseScope is ledger_contract.CaseScope
assert worker.CaseBudget is ledger_contract.CaseBudget
from fleet.server import proposal_store
from fleet.server import mission_store, mission_service, goal_evidence_service
assert proposal_store.ModelToolCall is ModelToolCall
assert mission_store.GoalEvidence is mission_service.GoalEvidence is goal_evidence_service.GoalEvidence is GoalEvidence
assert importlib.util.find_spec('rosy.decision.tool_dispatch') is None
assert importlib.util.find_spec('fleet.server.goal_evidence') is None
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
from fleet.server.cell_compiler import PalletizingCellJobCompiler
from fleet.server.cell_goal_evidence import make_cell_job_resolver
import rosy.processes.palletizing.submission as process_submission
assert Path(process_submission.__file__).resolve().is_relative_to(installed)
recipe, cell = json.loads(sys.argv[7])
compiler = PalletizingCellJobCompiler(tol_m=.001)
compilation = compiler.compile(recipe, cell)
candidate = dict(kind='cell_job', recipe=recipe, cell=cell, job=compilation.job,
                 recipe_sha256=compilation.plan_bundle.recipe_digest,
                 cell_sha256=compilation.plan_bundle.cell_digest)
resolve = make_cell_job_resolver(compiler, None)
document = resolve(candidate, workcell_id='cell-1', instance_id='arm-1')
assert document['resources'] == [['workcell', 'cell-1'], ['pallet', 'A'], ['pallet', 'B']]
assert len(document['steps']) == 18
assert document['ledger_markers'] == [{'after_step_ordinal': 9, 'pallet_id': 'A'},
                                     {'after_step_ordinal': 18, 'pallet_id': 'B'}]
candidate['job']['steps'][1]['target']['x'] += .001
try:
    resolve(candidate, workcell_id='cell-1', instance_id='arm-1')
except ValueError as exc:
    assert 'differs from the recompiled Job' in str(exc)
else:
    raise AssertionError('installed Fleet accepted tampered process Job')
print('installed namespace, resources, HTTP guards and Fleet Cell submission verified')
'''
    modules = ['rosy.decision.deliberation.evaluation.reasoning_candidate',
               'rosy.decision.conversation.codec', 'fleet.server.channel.conversation.jobs',
               'fleet.server.channel.conversation.worker', 'fleet.server.channel.conversation.runtime',
               'fleet.server.channel.execution.instructions', 'fleet.server.channel.execution.journal',
               'fleet.server.channel.execution.worker', 'fleet.server.channel.execution.runtime',
               'fleet.server.channel.execution.receipts', 'fleet.server.intent_execution',
               'fleet.server.channel.execution.outcomes.evidence',
               'fleet.server.channel.execution.outcomes.receipts',
               'fleet.server.channel.execution.outcomes.reconcile',
               'fleet.server.channel.execution.outcomes.task_receipt',
               'fleet.server.channel.execution.outcomes.stops',
               'fleet.swarm.dispatch_guard',
               'fleet.server.channel.model_journal', 'fleet.server.channel.broker_transport',
               'rosy.world.api', 'rosy.execution.api', 'rosy.skills.api',
               'fleet.server.proposal_store', 'rosy.decision.model_tool_contract',
               'fleet.server.model_feedback_dispatch', 'rosy.decision.deliberation',
               'rosy.decision.deliberation.cli', 'fleet.server.deliberation_journal',
               'fleet.server.context_log', 'fleet.server.context_options',
               'rosy.decision.deliberation.profiles', 'rosy.decision.deliberation.judgment',
               'rosy.decision.deliberation.calibration', 'rosy.decision.deliberation.versioned_request',
               'rosy.decision.deliberation.versioned_cli', 'rosy.decision.deliberation.local',
               'rosy.decision.deliberation.contracts.profiles',
               'rosy.decision.deliberation.contracts.judgment',
               'rosy.decision.deliberation.contracts.recovery',
               'rosy.decision.deliberation.providers.cli',
               'rosy.decision.deliberation.providers.versioned_cli',
               'rosy.decision.deliberation.providers.versioned_request',
               'rosy.decision.deliberation.providers.local',
               'rosy.decision.deliberation.evaluation.calibration',
               'rosy.decision.deliberation.evaluation.comparison',
               'rosy.decision.deliberation.evaluation.calibration_metrics',
               'rosy.decision.deliberation.evaluation.calibration_selection',
               'fleet.incidents.automation.contract', 'fleet.incidents.automation.store',
               'fleet.incidents.automation.observation',
               'fleet.incidents.automation.closure', 'fleet.incidents.automation.worker',
               'fleet.incidents.automation.execution.worker',
               'fleet.incidents.automation.recovery_candidates',
               'fleet.incidents.automation.operating.candidates',
               'fleet.incidents.automation.operating.state',
               'fleet.stuck.submission.dispatch', 'fleet.stuck.submission.owned',
               'fleet.incidents.automation.ledger.contract', 'fleet.incidents.automation.ledger.store',
               'fleet.server.incident_deliberation',
               'rosy_situation.assessment', 'rosy_situation.snapshot_assessment',
               'fleet.incidents.notifications', 'fleet.incidents.handoff', 'rosy.execution.site.goal_evidence',
               'rosy.execution.site.workflow']
    examples = ROOT / 'operations/processes/cell/examples/omx_sim'
    documents = json.dumps([yaml.safe_load((examples / name).read_text(encoding='utf-8'))
                            for name in ('recipe.yaml', 'cell.yaml')])
    for order in (modules, list(reversed(modules))):
        run(['-I', '-c', probe, str(installed), json.dumps(order), json.dumps(expected),
             json.dumps(signed(kind=APPROVE)), json.dumps(binding()), KEY.hex(), documents], tmp_path)
    if delivery == 'wheel':
        native = tmp_path / 'native/lib/python3.12/site-packages'
        excluded = ('rosy_execution-', 'rosy_contracts_skill-', 'rosy_contracts_motion-')
        dependencies = [str(path) for path in wheels.glob('*.whl')
                        if not path.name.startswith(excluded)]
        run(['-m', 'pip', 'install', '--no-deps', '--no-index', '--target', str(native),
             *dependencies], tmp_path)
        script = ROOT / 'deploy/robot/pinky_pro/image/install-motion-contracts.sh'
        environment = {**os.environ, 'TMPDIR': str(tmp_path),
                       'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']}
        command = ['bash', str(script), str(staging), str(tmp_path / 'native')]
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stdout + result.stderr
        native_probe = '''
import sys
sys.path.insert(0, sys.argv[1])
from fleet.server.mission_service import MissionService
from rosy_discord.intake import project_message, signed_request
from rosy_discord.gateway import DiscordGateway
from fleet.server.channel_requests import ChannelRequests
from fleet.server.mission_progress import MissionProgressService
from rosy.execution.site.goal_evidence import GoalPredicate
from rosy.execution.site.workflow import project_progress
from rosy.decision.model_tool_contract import ModelToolCall
from rosy.contracts.motion import BaseTwist
assert BaseTwist(0.0, 0.0).linear_mps == 0
'''
        run(['-I', '-c', native_probe, str(native)], tmp_path)
        before = {path.relative_to(native).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in native.rglob('*') if path.is_file() and '__pycache__' not in path.parts}
        repeated = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=180)
        assert repeated.returncode != 0
        after = {path.relative_to(native).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in native.rglob('*') if path.is_file() and '__pycache__' not in path.parts}
        assert before == after


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
from pathlib import Path
sys.path[:0] = json.loads(sys.argv[1])
roots = [Path(path) for path in json.loads(sys.argv[1])]
from fleet.stuck.board import LineStuckBoard
from fleet.server.mission_service import MissionService
from rosy.execution.site.goal_evidence import verify_goal
from rosy.execution.site.workflow import project_progress
from fleet.server.model_feedback_dispatch import MissionFeedbackToolDispatcher
from fleet.server.channel_incidents import incident_view, install_channel_incident_routes
import importlib
for name in ('requests', 'workflow', 'missions', 'incidents', 'replies', 'gateway',
             'deliberation', 'model_worker', 'model_runtime'):
    assert importlib.import_module('fleet.server.channel_' + name) is importlib.import_module('fleet.server.channel.' + name)
from fleet.server.channel.health import BareDiscordPublisher, HourlyHealth
health_spec = importlib.util.find_spec('fleet.server.channel.health')
assert Path(health_spec.origin).resolve().is_relative_to(roots[0] / 'fleet/server/channel/health')

from fleet.server import mission_service
from rosy.execution.site.goal_evidence import GoalEvidence
assert mission_service.GoalEvidence is GoalEvidence
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
