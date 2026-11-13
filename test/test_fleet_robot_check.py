"""Fleet/robot E2E decision checks without SSH or device access."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import json

_FILE = Path(__file__).resolve().parents[1] / 'tools/remote/fleet_robot_check.py'
_SPEC = spec_from_file_location('fleet_robot_check', _FILE)
check = module_from_spec(_SPEC)
_SPEC.loader.exec_module(check)


def _facts():
    robot = dict(release='2026.11.14-101', checksum=True, signed=True, tls=True,
                 core='active', recover='active', tokens=[{
                     'id': 'secret-id', 'expires_at': '2030-01-01T00:00:00+00:00'}])
    fleet = dict(token_id='secret-id', expires_at='2030-01-01T00:00:00+00:00',
                 fleet_expires_at=1893456000, state='active', hub_linked=True)
    return robot, fleet


def test_pass_and_no_token_identifier_in_verdicts():
    robot, fleet = _facts()
    rows = check.decide('robot-1', robot, fleet, now=1700000000)
    assert all(row['result'] == 'PASS' for row in rows if row['check'] not in ('hub_online', 'lamp', 'update'))
    assert 'secret-id' not in str(rows)


def test_expiry_mismatch_and_down_robot_fail_closed():
    robot, fleet = _facts()
    fleet['expires_at'] = '2031-01-01T00:00:00+00:00'
    assert next(row for row in check.decide('robot-1', robot, fleet, now=1700000000)
                if row['check'] == 'token')['result'] == 'FAIL'
    assert all(row['result'] == 'FAIL' for row in check.decide('robot-1', None, fleet)
               if row['check'] in ('ssh', 'release', 'checksum', 'core', 'recover', 'token'))


def test_token_uses_matching_robot_record_and_reports_both_expiries():
    robot, fleet = _facts()
    robot['tokens'] = [{'id': 'unrelated', 'expires_at': '2035-01-01T00:00:00Z'},
                       {'id': 'secret-id', 'expires_at': '2030-02-01T00:00:00Z'}]
    fleet['fleet_expires_at'] = None
    token = next(row for row in check.decide('robot-1', robot, fleet, now=1700000000)
                 if row['check'] == 'token')
    assert token['result'] == 'PASS'
    assert '2030-02-01' in token['reason'] and '2030-01-01' in token['reason']
    assert 'secret-id' not in str(token)
    robot['tokens'][1]['expires_at'] = '2029-12-31T00:00:00Z'
    assert next(row for row in check.decide('robot-1', robot, fleet, now=1700000000)
                if row['check'] == 'token')['result'] == 'FAIL'


def test_robot_probe_reads_deployed_tls_defaults_tokens_and_agent_journal(monkeypatch, capsys):
    import http.client
    import socket
    import ssl
    import subprocess
    import yaml

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def sendall(self, data):
            assert b'GET /api/v1 HTTP/1.1' in data

        def wrap_socket(self, raw, server_hostname):
            assert server_hostname == 'rosy-pinky-example.local'
            return self

    def read_text(path, *args, **kwargs):
        if str(path) == '/etc/rosy/runtime.env':
            return ('ROSY_API_TLS=required\nROSY_API_TLS_HOST=rosy-pinky-example.local\n'
                    'ROSY_API_TLS_CA_FILE=/etc/rosy/tls/ca.pem\n')
        return 'auth: tokens'

    def run(argv, **kwargs):
        if argv[0] == 'journalctl':
            assert '_SYSTEMD_INVOCATION_ID=test-invocation' in argv
            return SimpleNamespace(returncode=0, stdout='Fleet agent welcomed by hub\n')
        if argv[:2] == ['systemctl', 'show']:
            return SimpleNamespace(returncode=0, stdout='test-invocation\n')
        return SimpleNamespace(returncode=0, stdout='active')

    monkeypatch.setattr(Path, 'read_text', read_text)
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(yaml, 'safe_load', lambda _: {'auth': {'tokens': [
        {'id': 'secret-id', 'source': 'restored', 'expires_at': '2030-02-01T00:00:00Z'}]}})
    monkeypatch.setattr(ssl, 'create_default_context', lambda **kwargs: Connection())
    monkeypatch.setattr(socket, 'create_connection', lambda *args, **kwargs: Connection())
    monkeypatch.setattr(http.client, 'HTTPResponse', lambda _: SimpleNamespace(status=200, begin=lambda: None))
    exec(check.ROBOT_PROBE, {})
    facts = json.loads(capsys.readouterr().out)
    assert facts['tls'] is True and facts['hub_online'] is True
    assert facts['tokens'] == [{'id': 'secret-id', 'expires_at': '2030-02-01T00:00:00Z'}]


def test_hub_status_uses_robot_journal_only_with_enrollment():
    robot, fleet = _facts()
    robot['hub_online'] = True
    assert next(row for row in check.decide('robot-1', robot, fleet)
                if row['check'] == 'hub_online')['result'] == 'PASS'
    robot['hub_online'] = False
    assert next(row for row in check.decide('robot-1', robot, fleet)
                if row['check'] == 'hub_online')['result'] == 'FAIL'
    assert next(row for row in check.decide('robot-1', robot, None)
                if row['check'] == 'hub_online')['result'] == 'SKIP'


def test_short_lab_identity_resolves_unique_enrollment():
    row = {'robot_id': 'rosy_26', 'hostname': 'rosy-pinky-9dfk', 'address': '192.0.2.8'}
    assert check.enrollment([row], '9dfk', 'rosy-pinky-9dfk.local') is row
    assert check.enrollment([row, dict(row)], '9dfk', 'rosy-pinky-9dfk.local') is None


def test_probe_parses_json_and_refuses_failed_ssh(monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append((argv, kwargs['input']))
        return SimpleNamespace(returncode=0, stdout='{"core":"active"}')

    monkeypatch.setattr(check.subprocess, 'run', fake_run)
    assert check.probe(['ssh', 'robot'], 'script') == ({'core': 'active'}, None)
    assert seen == [(['ssh', 'robot'], 'script')]
    monkeypatch.setattr(check.subprocess, 'run',
                        lambda *args, **kwargs: SimpleNamespace(returncode=255, stdout='secret'))
    assert check.probe(['ssh', 'robot'], 'script') == (None, 'command exit 255')
