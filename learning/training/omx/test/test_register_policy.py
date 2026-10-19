"""D-793: a finished offline cycle becomes an L0 proposal, never an execution grant."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


register = _load('omx_register_policy', 'register_policy.py')


def _cycle(tmp_path, **overrides):
    receipt = dict(offline_only=True, device_execution=False, promotion=False, source_mode='scripted_teacher',
                   split_receipt_sha256='c' * 64, policy_revision='act-0123456789abcdef', rig_revision='rig-1',
                   calibration_revision='cal-1', evaluation={'mae': 0.12})
    receipt.update(overrides)
    (tmp_path / 'cycle-receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    return tmp_path


def test_offline_cycle_becomes_an_l0_proposal_bound_to_its_receipt(tmp_path):
    body = register.proposal(_cycle(tmp_path))
    raw = (tmp_path / 'cycle-receipt.json').read_bytes()
    assert body['to_stage'] == 'L0' and body['operator_confirmed'] is True
    assert body['evidence_sha256'] == hashlib.sha256(raw).hexdigest()
    assert (body['policy_revision'], body['rig_revision'], body['calibration_revision']) == (
        'act-0123456789abcdef', 'rig-1', 'cal-1')
    assert 'eval MAE 0.12' in body['note']


@pytest.mark.parametrize('override', [
    {'offline_only': False}, {'device_execution': True}, {'promotion': True},
    {'policy_revision': None}, {'rig_revision': 'bad rig'}, {'calibration_revision': ''}])
def test_non_offline_or_unbound_cycles_are_refused(tmp_path, override):
    with pytest.raises(ValueError):
        register.proposal(_cycle(tmp_path, **override))


def test_submit_posts_to_the_workcell_policy_route_with_the_env_token(tmp_path):
    sent = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"proposal_id": "prop-1", "state": "PENDING"}'

    def opener(req, timeout, context):
        sent.update(url=req.full_url, auth=req.headers['Authorization'], body=json.loads(req.data))
        return Response()

    body = register.proposal(_cycle(tmp_path))
    result = register.submit('https://fleet.local:8443/', 'cell-1', body, 'secret-token', opener=opener)
    assert result['state'] == 'PENDING'
    assert sent['url'] == 'https://fleet.local:8443/api/fleet/workcells/cell-1/policy/proposals'
    assert sent['auth'] == 'Bearer secret-token' and sent['body'] == body
    with pytest.raises(ValueError):
        register.submit('https://fleet.local', '../x', body, 't', opener=opener)


def test_cli_dry_run_sends_nothing_and_confirm_needs_the_env_token(tmp_path, capsys, monkeypatch):
    cycle = _cycle(tmp_path)
    assert register.main(['--cycle', str(cycle), '--fleet', 'https://f', '--workcell', 'cell-1', '--dry-run']) == 0
    assert json.loads(capsys.readouterr().out)['to_stage'] == 'L0'
    monkeypatch.delenv('ROSY_FLEET_TOKEN', raising=False)
    with pytest.raises(SystemExit, match='ROSY_FLEET_TOKEN'):
        register.main(['--cycle', str(cycle), '--fleet', 'https://f', '--workcell', 'cell-1', '--confirm'])


def test_policy_revision_names_the_exact_model_file_set():
    cycle = _load('omx_native_cycle_revision', 'native_cycle.py')
    files = {'config.json': 'a' * 64, 'model.safetensors': 'b' * 64}
    assert cycle.policy_revision(files) == cycle.policy_revision(dict(reversed(list(files.items()))))
    assert cycle.policy_revision(files) != cycle.policy_revision({**files, 'model.safetensors': 'c' * 64})
    assert cycle.policy_revision(files).startswith('act-') and len(cycle.policy_revision(files)) == 20
