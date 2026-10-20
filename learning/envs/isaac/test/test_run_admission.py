"""Real Linux locks cooperate with both existing learning owner paths."""
import fcntl
import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    assert (ROOT / 'run_admission.py').is_file(), 'Isaac GPU admission is missing'
    sys.path.insert(0, str(ROOT))
    return importlib.import_module('run_admission')


@pytest.fixture
def binding(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    root = tmp_path / '.local/share/rosy/model-code'
    root.mkdir(parents=True)
    config = tmp_path / '.config/rosy/model-code.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'root': str(root)}))
    gpu = tmp_path / '.cache/rosy-learning/gpu.lock'
    gpu.parent.mkdir(parents=True)
    gpu.touch()
    return {'uid': os.getuid(), 'model_code_root': str(root)}


@pytest.mark.parametrize('name', ['work', 'gpu'])
def test_existing_learning_lock_refuses_sdk_start(binding, name):
    mod = module()
    path = (Path(binding['model_code_root']) / 'work.lock' if name == 'work'
            else Path.home() / '.cache/rosy-learning/gpu.lock')
    with path.open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError):
            with mod.acquire(binding, probe=lambda: {'ready': True}):
                pytest.fail('GPU lease must not overlap a learning owner')


def test_isaac_blocks_both_owners_and_releases_on_exit(binding):
    mod = module()
    paths = [Path(binding['model_code_root']) / 'work.lock',
             Path.home() / '.cache/rosy-learning/gpu.lock']
    with mod.acquire(binding, probe=lambda: {'ready': True}) as descriptors:
        assert len(descriptors) == 2
        for path in paths:
            with path.open('a+b') as lock:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    for path in paths:
        with path.open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert all(path.exists() for path in paths)


def test_child_keeps_locks_after_supervisor_exit(binding, tmp_path):
    mod = module()
    pid_file = tmp_path / 'child.pid'
    program = '''import sys,os,json,subprocess
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from run_admission import acquire
binding=json.loads(sys.argv[2])
with acquire(binding,probe=lambda:{'ready':True}) as fds:
 child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],
   pass_fds=tuple(fds),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 Path(sys.argv[3]).write_text(str(child.pid))
 os._exit(72)
'''
    result = subprocess.run([sys.executable, '-c', program, str(ROOT), json.dumps(binding),
                             str(pid_file)], capture_output=True, timeout=5)
    assert result.returncode == 72, result.stderr.decode(errors='replace')
    pid = int(pid_file.read_text())
    try:
        with pytest.raises(ValueError):
            with mod.acquire(binding, probe=lambda: {'ready': True}):
                pytest.fail('child must keep both inherited owner locks')
    finally:
        os.kill(pid, signal.SIGTERM)
    import time
    for _ in range(50):
        try:
            with mod.acquire(binding, probe=lambda: {'ready': True}):
                break
        except ValueError:
            time.sleep(0.02)
    else:
        pytest.fail('terminated child did not release its inherited locks')


def test_wrong_account_or_root_cannot_acquire(binding, tmp_path):
    mod = module()
    for bad in [dict(binding, uid=os.getuid() + 1),
                dict(binding, model_code_root=str(tmp_path / 'other-root'))]:
        with pytest.raises(ValueError):
            with mod.acquire(bad, probe=lambda: {'ready': True}):
                pytest.fail('unapproved account/root must be refused')


def test_gpu_observation_failure_refuses_and_releases_locks(binding):
    mod = module()
    with pytest.raises(ValueError):
        with mod.acquire(binding, probe=lambda: {'ready': False, 'reason': 'probe failed'}):
            pytest.fail('unknown GPU must not be admitted')
    with mod.acquire(binding, probe=lambda: {'ready': True}):
        pass


def test_gpu_probe_rejects_command_failure_and_foreign_compute_pid():
    mod = module()
    from types import SimpleNamespace

    def failure(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout='', stderr='unavailable')

    assert mod.gpu_state(runner=failure)['ready'] is False

    def occupied(args, **kwargs):
        text = '99999\n' if '--query-compute-apps=pid' in args else 'GPU-test, Test GPU, 1.0, 16000, 15000, 0\n'
        return SimpleNamespace(returncode=0, stdout=text, stderr='')

    assert mod.gpu_state(runner=occupied)['ready'] is False
