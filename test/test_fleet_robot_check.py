"""Fleet/robot E2E decision checks without SSH or device access."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

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
    fleet['expires_at'] = '2029-01-01T00:00:00+00:00'
    assert next(row for row in check.decide('robot-1', robot, fleet, now=1700000000)
                if row['check'] == 'token')['result'] == 'FAIL'
    assert all(row['result'] == 'FAIL' for row in check.decide('robot-1', None, fleet)
               if row['check'] in ('ssh', 'release', 'checksum', 'core', 'recover', 'token'))


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
