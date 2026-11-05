"""Run the operator guard through pinned-SSH stdin with a real loopback CORE."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_calibration_guard import ACTIVE, fake_core  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'deploy/robot/pinky_pro/rosy-calibration-guard.ps1'
PS = shutil.which('powershell') or shutil.which('pwsh')
TOKEN = 'ssh-loopback-guard-token'
pytestmark = pytest.mark.skipif(PS is None, reason='PowerShell required')


@pytest.fixture
def ssh_probe(tmp_path):
    runtime = tmp_path/'runtime.env'
    runtime.write_text('ROSY_API_TLS=none\n')
    log = tmp_path/'calls.jsonl'
    implementation = tmp_path/'ssh.py'
    implementation.write_text('''import json,os,sys
from pathlib import Path
args=sys.argv[1:]
assert os.environ['SSH_TEST_TOKEN'] not in ' '.join(args)
if 'python3 -I -c' not in args[-1]:sys.exit(5)
assert '-n' not in args
packet=json.load(sys.stdin)
assert packet['token']==os.environ['SSH_TEST_TOKEN']
with open(os.environ['SSH_TEST_LOG'],'a') as out:out.write(json.dumps({'args':args,'private_stdin':True})+'\\n')
namespace={'__name__':'calibration_probe'}
exec(compile(packet['source'],'calibration-probe-source','exec'),namespace)
original=namespace['Path']
namespace['Path']=lambda path:Path(os.environ['SSH_TEST_RUNTIME']) if path=='/etc/rosy/runtime.env' else original(path)
sys.exit(namespace['legacy_loopback'](packet))
''')
    if os.name == 'nt':
        fake = tmp_path/'ssh.cmd'
        fake.write_text(f'@echo off\r\n"{sys.executable}" "{implementation}" %*\r\n')
    else:
        fake = tmp_path/'ssh'
        fake.write_text(f'#!{sys.executable}\nexec(compile(open({str(implementation)!r}).read(),"ssh-test","exec"))\n')
        fake.chmod(0o755)
    env = dict(os.environ, ROSY_API_TOKEN=TOKEN, LOCALAPPDATA=str(tmp_path),
               SSH_TEST_TOKEN=TOKEN, SSH_TEST_LOG=str(log), SSH_TEST_RUNTIME=str(runtime))
    return fake, env, runtime, log


def invoke(core, probe, *extra):
    fake, env, _, _ = probe
    result = subprocess.run([PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(GUARD),
                             '-Robot', '127.0.0.2', '-ApiPort', str(core['port']), '-TimeoutSec', '2',
                             '-SshExe', str(fake), *extra], env=env, capture_output=True, text=True, timeout=25)
    assert TOKEN not in result.stdout+result.stderr
    return result


def test_ssh_loopback_confirms_idle_and_refuses_active(fake_core, ssh_probe):
    result = invoke(fake_core, ssh_probe)
    assert result.returncode == 0 and 'no active calibration session' in result.stdout, result.stdout+result.stderr
    fake_core['reply'] = ACTIVE
    result = invoke(fake_core, ssh_probe)
    assert result.returncode == 3 and 'REFUSED' in result.stdout+result.stderr
    assert fake_core['auth'] == ['Bearer '+TOKEN]*2
    calls = [json.loads(line) for line in ssh_probe[3].read_text().splitlines()]
    assert len(calls) == 2
    for call in calls:
        assert call['private_stdin'] and 'StrictHostKeyChecking=yes' in call['args']
        assert 'BatchMode=yes' in call['args'] and '-n' not in call['args']


@pytest.mark.parametrize('runtime', ['ROSY_API_TLS=required\n', ''])
def test_ssh_loopback_never_downgrades_required_or_unknown_tls(fake_core, ssh_probe, runtime):
    ssh_probe[2].write_text(runtime)
    result = invoke(fake_core, ssh_probe)
    assert 'no active calibration session' not in result.stdout
    assert fake_core['auth'] == []


@pytest.mark.parametrize('reply', [{'session': False}, {'anything': True}])
def test_ssh_loopback_does_not_turn_malformed_reply_into_idle(fake_core, ssh_probe, reply):
    fake_core['reply'] = reply
    result = invoke(fake_core, ssh_probe)
    assert 'no active calibration session' not in result.stdout
    assert fake_core['auth'] == ['Bearer '+TOKEN]
