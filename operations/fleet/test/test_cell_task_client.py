"""Agent-selected topics enter the actual Fleet proposal owner, never bypass admission."""
import importlib.util
import json
import os
from pathlib import Path
from hashlib import sha256
import subprocess
import sys

import pytest

import yaml

from test_cell_app_api import _save
from test_cell_job_api import _setup, _candidate
from fleet.server.cell_compiler import PalletizingCellJobCompiler

ROOT = Path(__file__).resolve().parents[3]


def test_topic_client_exists():
    assert (ROOT/'operations/fleet/fleet/server/work/cell_task_client.py').exists(), 'topic-to-task client is missing'


def test_cli_loads_through_existing_fleet_module_layout():
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join([
        str(ROOT/'operations/fleet'), str(ROOT/'contracts/foundation'), os.environ.get('PYTHONPATH', '')]))
    result = subprocess.run([sys.executable, '-m', 'fleet.server.cell_task_client', '--help'],
                            env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'prepare' in result.stdout and 'admit' in result.stdout and 'status' in result.stdout


def system(tmp_path):
    return _setup(tmp_path, cell_app_service_id='cell-service', compiler=PalletizingCellJobCompiler(tol_m=.001))


@pytest.fixture
def module():
    path = ROOT/'operations/fleet/fleet/server/work/cell_task_client.py'
    assert path.exists(), 'topic-to-task client has not been implemented'
    spec = importlib.util.spec_from_file_location('cell_task_client', path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class Api:
    def __init__(self, client):
        self.client, self.calls = client, []

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        response = self.client.request(method, path, json=body,
                                       headers={'Authorization': 'Bearer operator-secret'})
        if response.status_code != 200:
            raise ValueError('Fleet refused: '+str(response.status_code))
        return response.json()


def binding(client):
    refs = dict(workcell_id='omx_01', instance_id='omx_01_control')
    for kind in ('recipe', 'cell'):
        path = ROOT/'operations/processes/cell/examples/omx_sim'/f'{kind}.yaml'
        response = _save(client, kind, 'demo', yaml.safe_load(path.read_text()))
        assert response.status_code == 200, response.text
        refs[kind+'_id'] = 'demo'
        refs[kind+'_digest'] = response.json()['digest']
    return refs


def test_topic_compiles_to_actual_fleet_proposal_without_admission(module, tmp_path):
    client, tasks, _ = system(tmp_path)
    api = Api(client)
    refs = binding(client)
    result = module.prepare_task(api, '박스를 지정 팔레트로 옮겨', refs, tmp_path/'request')
    assert result['mission']['status'] == 'PROPOSED'
    assert result['task_success'] is None and result['admission_required'] is True
    assert [path for _, path in api.calls] == ['/api/fleet/cell-app/compile',
                                              '/api/fleet/cell-app/proposals']
    saved = json.loads((tmp_path/'request/request.json').read_text())
    assert saved['topic'] == '박스를 지정 팔레트로 옮겨' and saved['binding'] == refs
    assert (tmp_path/'request/submission-intent.json').exists()
    assert tasks.store.resource_claims(resource_kind='workcell', resource_id='omx_01') == []
    assert not tasks.store.dispatch_control()['dispatch_enabled']


def test_changed_document_never_submits_proposal(module, tmp_path):
    client, _, _ = system(tmp_path)
    refs = {**binding(client), 'recipe_digest': '0'*64}
    api = Api(client)
    with pytest.raises(ValueError, match='Fleet refused'):
        module.prepare_task(api, 'move box', refs, tmp_path/'request')
    assert api.calls == [('POST', '/api/fleet/cell-app/compile')]
    assert (tmp_path/'request/failure.json').exists()


def test_new_user_request_can_repeat_the_same_task_and_read_actual_fleet_job(module, tmp_path):
    client, _, _ = system(tmp_path)
    api, refs = Api(client), binding(client)
    first = module.prepare_task(api, 'move box', refs, tmp_path/'first')
    second = module.prepare_task(api, 'move box', refs, tmp_path/'second')
    assert first['request_key'] != second['request_key']
    assert first['mission']['mission_id'] != second['mission']['mission_id']
    status = module.read_status(api, first['mission']['mission_id'], tmp_path/'read')
    assert status['status'] == 'PROPOSED' and status['task_success'] is None


def test_lost_submit_response_preserves_intent_and_never_retries(module, tmp_path):
    client, _, _ = system(tmp_path)
    api = Api(client)
    real = api.request

    def lose(method, path, body=None):
        result = real(method, path, body)
        if path.endswith('/proposals'):
            raise TimeoutError('response lost')
        return result

    api.request = lose
    refs = binding(client)
    with pytest.raises(TimeoutError):
        module.prepare_task(api, 'move box', refs, tmp_path/'request')
    assert len(api.calls) == 2
    assert json.loads((tmp_path/'request/failure.json').read_text())['submission_uncertain'] is True
    with pytest.raises(FileExistsError):
        module.prepare_task(api, 'move box', refs, tmp_path/'request')
    assert len(api.calls) == 2


@pytest.mark.parametrize('status,success', [('PROPOSED', None), ('ACTION_SUCCEEDED', None),
                                         ('GOAL_CONFIRMED', True), ('HOLD', None), ('FAILED', False)])
def test_status_requires_independent_goal_confirmation(module, tmp_path, status, success):
    class ReadApi:
        def request(self, method, path, body=None):
            assert method == 'GET' and path == '/api/fleet/cell-jobs/job-1'
            return {'job': {'mission_id': 'job-1', 'status': status}}
    result = module.read_status(ReadApi(), 'job-1', tmp_path/status)
    assert result['task_success'] is success


@pytest.mark.parametrize('url', ['http://example.com', 'https://user:secret@example.com',
                                'https://example.com/other', 'file:///tmp/fleet'])
def test_transport_refuses_untrusted_base_urls(module, url):
    with pytest.raises(ValueError):
        module.validate_url(url)


def test_compiler_mismatch_stops_before_submit(module, tmp_path):
    class ChangedApi:
        def request(self, method, path, body=None):
            assert path.endswith('/compile')
            return {'candidate': {**_candidate(), 'recipe_sha256': '0'*64}}
    with pytest.raises(ValueError, match='digest'):
        module.prepare_task(ChangedApi(), 'move box', {
            'recipe_id': 'demo', 'cell_id': 'demo', 'recipe_digest': 'b'*64,
            'cell_digest': 'c'*64, 'workcell_id': 'omx_01', 'instance_id': 'omx_01_control'}, tmp_path/'request')
    assert not (tmp_path/'request/submission-intent.json').exists()


def test_explicit_execution_uses_existing_named_operator_admission(module, tmp_path):
    client, tasks, _ = system(tmp_path)
    api = Api(client)
    module.prepare_task(api, 'move box', binding(client), tmp_path/'request')
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(expected_generation=control['generation'], actor_id='operator-1')['generation']
    result = module.admit_task(api, tmp_path/'request', generation, tmp_path/'admission')
    assert result['admission_accepted'] is True and result['task_success'] is None
    assert result['mission']['status'] == 'READY'
    assert api.calls[-1][0] == 'POST' and api.calls[-1][1].endswith('/admit')
    assert not any('rearm' in path for _, path in api.calls)


def test_closed_dispatch_does_not_rearm_or_retry(module, tmp_path):
    client, _, _ = system(tmp_path)
    api = Api(client)
    module.prepare_task(api, 'move box', binding(client), tmp_path/'request')
    with pytest.raises(ValueError, match='Fleet refused'):
        module.admit_task(api, tmp_path/'request', 0, tmp_path/'admission')
    assert sum(path.endswith('/admit') for _, path in api.calls) == 1
    assert json.loads((tmp_path/'admission/failure.json').read_text())['submission_uncertain'] is True


def test_changed_local_request_does_not_admit(module, tmp_path):
    client, _, _ = system(tmp_path)
    api = Api(client)
    module.prepare_task(api, 'move box', binding(client), tmp_path/'request')
    p = tmp_path/'request/request.json'
    changed = json.loads(p.read_text())
    changed['topic'] = 'different work'
    p.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='digest'):
        module.admit_task(api, tmp_path/'request', 0, tmp_path/'admission')
    assert len(api.calls) == 2


class G2FleetClient:
    """Existing role-keyed request boundary backed by the actual authenticated Fleet app."""
    def __init__(self, client, tasks, *, stale=False, lost=False):
        self.client, self.tasks, self.calls = client, tasks, []
        self.stale, self.lost = stale, lost

    def request(self, method, path, body=None, *, role="approver"):
        self.calls.append((method, path, role))
        if self.stale and method == "POST" and path.endswith("/admit"):
            self.tasks.store.trip_stop_latch(actor_id="g2-approver", reason="GENERATION_CHANGED")
        response = self.client.request(method, path, json=body,
            headers={"Authorization": "Bearer g2-" + role + "-secret"})
        if response.status_code != 200:
            raise ValueError("Fleet refused: " + str(response.status_code))
        if self.lost and path == "/api/fleet/cell-app/proposals":
            raise TimeoutError("proposal response lost")
        return response.json()


def g2_setup(tmp_path, monkeypatch, *, box_only=True):
    import test_cell_job_api as fixture
    actual_create = fixture.create_app
    def create(*args, **kwargs):
        users = dict(kwargs["site_users"])
        for role in ("proposer", "approver"):
            users[sha256(("g2-" + role + "-secret").encode()).hexdigest()] = {
                "principal_id": "g2-" + role, "role": "operator"}
        return actual_create(*args, **{**kwargs, "site_users": users})
    monkeypatch.setattr(fixture, "create_app", create)
    sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
    from g2_common import box_only_document
    client, tasks, _ = system(tmp_path)
    refs = {"workcell_id": "omx_cell_sim", "instance_id": "omx_cell_sim_01"}
    for kind in ("recipe", "cell"):
        document = yaml.safe_load((ROOT / "operations/processes/cell/examples/omx_sim" / (kind + ".yaml")).read_text())
        if kind == "recipe" and box_only:
            document = box_only_document(document)
        saved = _save(client, kind, "g2-" + kind, document)
        assert saved.status_code == 200, saved.text
        refs[kind + "_id"], refs[kind + "_digest"] = "g2-" + kind, saved.json()["digest"]
    control = tasks.store.dispatch_control()
    tasks.store.rearm_dispatch(expected_generation=control["generation"], actor_id="g2-approver")
    return client, tasks, refs


def test_g2_topic_path_uses_real_proposer_and_approver_before_canonical_admission(tmp_path, monkeypatch):
    client, tasks, refs = g2_setup(tmp_path, monkeypatch)
    from g2_task import submit_topic_task, SIM_TOPIC
    api = G2FleetClient(client, tasks)
    mission_id = submit_topic_task(tmp_path / "run", api, refs)
    receipt = json.loads((tmp_path / "run/topic-task/prepare/receipt.json").read_text())
    assert mission_id == receipt["mission"]["mission_id"]
    request = json.loads((tmp_path / "run/topic-task/prepare/request.json").read_text())
    assert request["topic"] == SIM_TOPIC and request["binding"] == refs
    job = client.get("/api/fleet/cell-jobs/" + mission_id,
                     headers={"Authorization": "Bearer g2-approver-secret"}).json()["job"]
    assert job["status"] == "READY" and len(job["steps"]) == 16
    assert any(row["event_type"] == "CELL_JOB_ADMITTED" and row["actor_id"] == "g2-approver"
               for row in job["events"])
    assert api.calls[:2] == [("POST", "/api/fleet/cell-app/compile", "proposer"),
                             ("POST", "/api/fleet/cell-app/proposals", "proposer")]
    assert all(role == "approver" for _, _, role in api.calls[2:])
    assert sum(path.endswith("/admit") for _, path, _ in api.calls) == 1
    assert not any("rearm" in path for _, path, _ in api.calls)
    assert (tmp_path / "run/topic-task/admission/admission-intent.json").exists()


def test_g2_topic_stale_generation_never_rearms_or_retries_admission(tmp_path, monkeypatch):
    client, tasks, refs = g2_setup(tmp_path, monkeypatch)
    from g2_task import submit_topic_task
    api = G2FleetClient(client, tasks, stale=True)
    with pytest.raises(ValueError, match="Fleet refused"):
        submit_topic_task(tmp_path / "run", api, refs)
    assert sum(path.endswith("/admit") for _, path, _ in api.calls) == 1
    assert not any("rearm" in path for _, path, _ in api.calls)
    failure = json.loads((tmp_path / "run/topic-task/admission/failure.json").read_text())
    assert failure["submission_uncertain"] is True and failure["automatically_retried"] is False
    assert tasks.store.resource_claims(resource_kind="workcell", resource_id="omx_cell_sim") == []


@pytest.mark.parametrize("failure", ["digest", "shape"])
def test_g2_topic_failed_compile_or_unreviewed_shape_never_admits(tmp_path, monkeypatch, failure):
    client, tasks, refs = g2_setup(tmp_path, monkeypatch, box_only=failure != "shape")
    from g2_task import submit_topic_task
    if failure == "digest":
        refs["recipe_digest"] = "0" * 64
    api = G2FleetClient(client, tasks)
    with pytest.raises((ValueError, RuntimeError)):
        submit_topic_task(tmp_path / "run", api, refs)
    assert not any(path.endswith("/admit") or "rearm" in path for _, path, _ in api.calls)
    if failure == "digest":
        assert api.calls == [("POST", "/api/fleet/cell-app/compile", "proposer")]
    assert tasks.store.resource_claims(resource_kind="workcell", resource_id="omx_cell_sim") == []


def test_g2_topic_lost_proposal_response_never_admits_or_replays(tmp_path, monkeypatch):
    client, tasks, refs = g2_setup(tmp_path, monkeypatch)
    from g2_task import submit_topic_task
    api = G2FleetClient(client, tasks, lost=True)
    with pytest.raises(TimeoutError):
        submit_topic_task(tmp_path / "run", api, refs)
    assert (tmp_path / "run/topic-task/prepare/submission-intent.json").exists()
    failure = json.loads((tmp_path / "run/topic-task/prepare/failure.json").read_text())
    assert failure["submission_uncertain"] is True and failure["automatically_retried"] is False
    assert len(api.calls) == 2
    with pytest.raises(FileExistsError):
        submit_topic_task(tmp_path / "run", api, refs)
    assert len(api.calls) == 2
    assert not any(path.endswith("/admit") or "rearm" in path for _, path, _ in api.calls)
