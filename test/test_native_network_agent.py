"""Exercise the installed network authority rather than a broad HostAgent fake."""
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'deploy/robot/pinky_pro/native'


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(NATIVE))
    sys.modules.pop('network_agent', None)
    return importlib.import_module('network_agent')


def request(command, **params):
    return {'schema_version': 1, 'request_id': 'network-job-1', 'command': command,
            'actor': {'user_id': 'operator', 'role': 'administrator'},
            'confirmed': True, **({'params': params} if params else {})}


class Transaction:
    def __init__(self):
        self.calls = []

    def connect(self, ssid, psk, *, request_id):
        self.calls.append((ssid, psk, request_id))
        return {'state': 'committed', 'request_id': request_id, 'ssid': ssid}

    def status(self, request_id=None):
        return {'state': 'committed' if self.calls else 'idle', 'ssid': 'site'}


def test_retried_job_still_checks_role_and_request_identity(module, tmp_path):
    agent = module.make_agent(module.NetworkCommands(Transaction(), root=tmp_path))
    body = request('network.connect', ssid='site', psk='test-passphrase')
    body['idempotency_key'] = 'network-job-1'
    assert agent.handle(body)['ok']
    viewer = {**body, 'actor': {'role': 'viewer', 'user_id': 'other'}}
    assert not agent.handle(viewer)['ok']
    changed = {**body, 'params': {'ssid': 'changed', 'psk': 'test-passphrase'}}
    assert not agent.handle(changed)['ok']


def test_connect_prepares_before_explicit_acknowledgment(module, tmp_path):
    transaction, scheduled = Transaction(), []
    commands = module.NetworkCommands(transaction, root=tmp_path, submit=scheduled.append)
    agent = module.make_agent(commands)
    prepared = agent.handle(request('network.connect', ssid='site', psk='test-passphrase'))
    assert prepared['ok']
    assert prepared['data']['state'] == 'prepared'
    assert transaction.calls == scheduled == []
    accepted = agent.handle(request('network.start', request_id='network-job-1'))
    assert accepted['ok'] and len(scheduled) == 1
    assert transaction.calls == []
    scheduled.pop()()
    assert transaction.calls == [('site', 'test-passphrase', 'network-job-1')]


@pytest.mark.parametrize('command,params', [
    ('system.reboot', {}), ('release.rollback', {}),
    ('network.set_mode', {'mode': 'RELAY_AP_STA'}),
    ('network.apply_profile', {'profile_id': 'arbitrary'}),
    ('lane_perception.set', {'paint_source': 'learned'}),
])
def test_network_entrypoint_refuses_other_authorities(module, tmp_path, command, params):
    transaction = Transaction()
    agent = module.make_agent(module.NetworkCommands(transaction, root=tmp_path))
    reply = agent.handle(request(command, **params))
    assert reply['ok'] is False
    assert transaction.calls == []


def test_restart_needs_secret_resubmission_not_automatic_radio_work(module, tmp_path):
    first = module.NetworkCommands(Transaction(), root=tmp_path)
    module.make_agent(first).handle(request('network.connect', ssid='site', psk='test-passphrase'))
    transaction = Transaction()
    second = module.NetworkCommands(transaction, root=tmp_path)
    reply = module.make_agent(second).handle(request('network.start', request_id='network-job-1'))
    assert not reply['ok'] or reply['data']['state'] == 'needs_resubmit'
    assert transaction.calls == []
    assert all(b'test-passphrase' not in item.read_bytes() for item in tmp_path.rglob('*') if item.is_file())


def test_viewer_cannot_stage_or_start_network_change(module, tmp_path):
    transaction = Transaction()
    agent = module.make_agent(module.NetworkCommands(transaction, root=tmp_path))
    for command, params in [('network.connect', {'ssid': 'site', 'psk': 'test-passphrase'}),
                            ('network.start', {'request_id': 'network-job-1'})]:
        body = request(command, **params)
        body['actor']['role'] = 'viewer'
        assert agent.handle(body)['ok'] is False
    assert transaction.calls == []


def test_prejournal_refusal_is_retained_for_reconnecting_client(module, tmp_path):
    class Refused(Transaction):
        def connect(self, *_args, **_kwargs):
            return {'state': 'rejected', 'code': 'needs_maintenance', 'request_id': 'network-job-1'}
    scheduled = []
    agent = module.make_agent(module.NetworkCommands(Refused(), root=tmp_path, submit=scheduled.append))
    agent.handle(request('network.connect', ssid='site', psk='test-passphrase'))
    agent.handle(request('network.start', request_id='network-job-1'))
    scheduled.pop()()
    data = agent.handle(request('network.status', request_id='network-job-1'))['data']
    assert data['state'] == 'rejected' and data['code'] == 'needs_maintenance'


def test_blocking_previous_job_is_reported_under_the_submitted_job_id(module, tmp_path):
    class Blocked(Transaction):
        def connect(self, *_args, **_kwargs):
            return {'state': 'held', 'code': 'restore_unverified', 'request_id': 'older-job'}
    scheduled = []
    agent = module.make_agent(module.NetworkCommands(Blocked(), root=tmp_path, submit=scheduled.append))
    agent.handle(request('network.connect', ssid='site', psk='test-passphrase'))
    agent.handle(request('network.start', request_id='network-job-1'))
    scheduled.pop()()
    data = agent.handle(request('network.status', request_id='network-job-1'))['data']
    assert data['state'] == 'held' and data['request_id'] == 'network-job-1'
    assert data['blocked_request_id'] == 'older-job'


@pytest.mark.skipif(os.name != 'posix' or shutil.which('bash') is None, reason='Linux installer contract')
def test_installed_network_entrypoints_import_without_source_checkout(tmp_path):
    destination = tmp_path / 'native-runtime'
    subprocess.run(['bash', str(NATIVE / 'install-native-runtime.sh'), str(destination)], check=True,
                   capture_output=True, text=True)
    code = ('import sys; sys.path.insert(0, sys.argv[1]); '
            'import network_agent,network_runtime,recovery_launcher,recovery_display; '
            'assert network_agent.COMMANDS == ("network.status","network.connect","network.start")')
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(destination)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (destination / 'image-layer/boot/catalog.json').is_file()
    assert (destination / 'recovery-web/tokens.css').is_file()


def test_network_units_and_installer_keep_lane_scope_separate():
    root = NATIVE.parents[3]
    unit = (NATIVE / 'rosy-network-agent.service').read_text()
    lane = (NATIVE / 'rosy-host-agent.py').read_text()
    installer = (NATIVE / 'install-native-runtime.sh').read_text()
    assert 'After=rosy-core.service' not in unit
    assert 'rosy-network-agent.py' in unit
    assert 'network-core.sock' not in lane and '"network.connect"' not in lane
    assert 'network_transaction.py' in installer and 'nm_network.py' in installer
    assert (root / 'deploy/robot/pinky_pro/native/rosy-network-agent.py').is_file()
