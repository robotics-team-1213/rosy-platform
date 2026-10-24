"""Recovered association survives the original one-time bundle retry."""
import importlib
import json
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'deploy/robot/pinky_pro/native'


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(NATIVE))
    return importlib.import_module('network_handoff')


def private_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    path.chmod(0o600)


def transaction():
    return {'request_id': 'recovered-1', 'profile_uuid': 'candidate-uuid', 'ssid': 'correct-site',
            'observation': {'uuid': 'candidate-uuid', 'ssid': 'correct-site',
                            'active': True, 'interface': 'wlan0', 'ipv4': '192.0.2.2'}}


def resolve(module, root, **overrides):
    args = {'device_uid': 'device-1', 'hardware_serial': '12345678',
            'bundle_checksum': 'a' * 64, 'inspect_profile': lambda _uuid: transaction()['observation']}
    return module.resolve_override(root, **{**args, **overrides})


def write_override(module, root):
    module.write_override(root, device_uid='device-1', hardware_serial='12345678',
                          bundle_checksum='a' * 64, transaction=transaction())


def commit(root):
    private_json(root / 'var/lib/rosy/network/transaction.json',
                 {**transaction(), 'state': 'committed'})


def test_only_verified_commit_overrides_original_bundle(module, tmp_path):
    assert resolve(module, tmp_path) is None
    write_override(module, tmp_path)
    with pytest.raises(ValueError):
        resolve(module, tmp_path)
    commit(tmp_path)
    recovered = resolve(module, tmp_path)
    assert recovered['ssid'] == 'correct-site' and recovered['profile_uuid'] == 'candidate-uuid'
    assert 'psk' not in repr(recovered)


@pytest.mark.parametrize('changes', [
    {'device_uid': 'different-device'}, {'hardware_serial': 'different-board'},
    {'bundle_checksum': 'b' * 64},
    {'inspect_profile': lambda _uuid: {**transaction()['observation'], 'ssid': 'old-site'}},
    {'inspect_profile': lambda _uuid: {**transaction()['observation'], 'active': False}},
])
def test_handoff_never_rebinds_or_invents_connection(module, tmp_path, changes):
    write_override(module, tmp_path)
    commit(tmp_path)
    with pytest.raises(ValueError):
        resolve(module, tmp_path, **changes)


def test_committed_job_archive_can_prove_handoff_after_new_job(module, tmp_path):
    write_override(module, tmp_path)
    private_json(tmp_path / 'var/lib/rosy/network/jobs/recovered-1.json',
                 {**transaction(), 'state': 'committed'})
    private_json(tmp_path / 'var/lib/rosy/network/transaction.json', {'state': 'rejected'})
    assert resolve(module, tmp_path)['ssid'] == 'correct-site'


def test_handoff_does_not_follow_symlink(module, tmp_path):
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    path = tmp_path / 'var/lib/rosy/network/first-boot-override.json'
    path.parent.mkdir(parents=True)
    path.symlink_to(outside)
    with pytest.raises((OSError, ValueError)):
        resolve(module, tmp_path)
    assert outside.read_text() == '{}'
