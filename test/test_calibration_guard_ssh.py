"""Run the operator guard through pinned-SSH stdin with a real loopback CORE."""
import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

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
    implementation.write_text('''import json,os,sys,shlex,subprocess
from pathlib import Path
args=sys.argv[1:]
assert os.environ['SSH_TEST_TOKEN'] not in ' '.join(args)
if 'python3 -I -c' not in args[-1]:sys.exit(5)
assert '-n' not in args
packet=json.load(sys.stdin)
assert packet['token']==os.environ['SSH_TEST_TOKEN']
with open(os.environ['SSH_TEST_LOG'],'a') as out:out.write(json.dumps({'args':args,'private_stdin':True})+'\\n')
remote=shlex.split(args[-1])
assert remote[:5]==['sudo','-n','python3','-I','-c'] and len(remote)==6
packet['source']=packet['source'].replace("Path('/etc/rosy/runtime.env')",'Path('+repr(os.environ['SSH_TEST_RUNTIME'])+')')
packet['source']+='\\ncore_tls_mode=lambda: '+repr(os.environ['SSH_TEST_TLS'])+'\\n'
done=subprocess.run([sys.executable,'-I','-c',remote[-1]],input=json.dumps(packet).encode())
sys.exit(done.returncode)
''')
    if os.name == 'nt':
        fake = tmp_path/'ssh.cmd'
        fake.write_text(f'@echo off\r\n"{sys.executable}" "{implementation}" %*\r\n')
    else:
        fake = tmp_path/'ssh'
        fake.write_text(f'#!{sys.executable}\nexec(compile(open({str(implementation)!r}).read(),"ssh-test","exec"))\n')
        fake.chmod(0o755)
    env = dict(os.environ, ROSY_API_TOKEN=TOKEN, LOCALAPPDATA=str(tmp_path),
               SSH_TEST_TOKEN=TOKEN, SSH_TEST_LOG=str(log), SSH_TEST_RUNTIME=str(runtime), SSH_TEST_TLS='none')
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


@pytest.mark.parametrize('runtime, effective', [('ROSY_API_TLS=required\n', 'none'), ('', 'required'), ('', 'unknown')])
def test_ssh_loopback_never_downgrades_required_or_unknown_tls(fake_core, ssh_probe, runtime, effective):
    ssh_probe[2].write_text(runtime)
    ssh_probe[1]['SSH_TEST_TLS'] = effective
    result = invoke(fake_core, ssh_probe)
    assert 'no active calibration session' not in result.stdout
    assert fake_core['auth'] == []


def test_missing_runtime_tls_requires_positive_core_producer_evidence(fake_core, ssh_probe):
    ssh_probe[2].write_text('')
    result = invoke(fake_core, ssh_probe)
    assert result.returncode == 0 and 'no active calibration session' in result.stdout, result.stdout+result.stderr
    assert fake_core['auth'] == ['Bearer '+TOKEN]


@pytest.mark.parametrize('reply', [{'session': False}, {'anything': True}])
def test_ssh_loopback_does_not_turn_malformed_reply_into_idle(fake_core, ssh_probe, reply):
    fake_core['reply'] = reply
    result = invoke(fake_core, ssh_probe)
    assert 'no active calibration session' not in result.stdout
    assert fake_core['auth'] == ['Bearer '+TOKEN]


@pytest.mark.skipif(os.name == 'nt', reason='Linux device CORE process evidence')
@pytest.mark.parametrize('mode, second_pid, accepted', [('none', '123', True), ('required', '123', True),
                                                      ('unknown', '123', False), ('none', '124', False)])
def test_tls_producer_runs_as_core_and_binds_the_service_generation(monkeypatch, mode, second_pid, accepted):
    import pwd
    spec = importlib.util.spec_from_file_location('calibration_probe', GUARD.parent/'calibration_tls_read.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pids = iter(['123', second_pid])
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **kw: next(pids))
    read_bytes = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: b'HOME=/var/lib/rosy/core\0PYTHONPATH=/opt/rosy/current/install/lib\0'
                        if str(path) == '/proc/123/environ' else read_bytes(path))
    stat = Path.stat
    monkeypatch.setattr(Path, 'stat', lambda path, **kw: SimpleNamespace(st_uid=123)
                        if str(path) == '/proc/123' else stat(path, **kw))
    monkeypatch.setattr(pwd, 'getpwnam', lambda name: SimpleNamespace(pw_uid=123, pw_gid=456))
    monkeypatch.setattr(os, 'getgrouplist', lambda *a: [456])
    observed = {}
    def run(command, **kwargs):
        observed.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout=mode+'\n')
    monkeypatch.setattr(subprocess, 'run', run)
    if accepted:
        assert module.core_tls_mode() == mode
    else:
        with pytest.raises(ValueError):
            module.core_tls_mode()
    assert observed['user'] == 123 and observed['group'] == 456
    assert observed['env']['HOME'] == '/var/lib/rosy/core'
    assert 'server_tls_options' in observed['command'][-1]
