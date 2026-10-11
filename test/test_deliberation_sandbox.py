import asyncio
import hashlib
import os
import sys

import pytest

from deploy.site.deliberation_sandbox import SandboxLauncher, bounded_process


def test_fixed_sandbox_has_no_host_home_network_or_environment(tmp_path):
    executable = tmp_path / 'provider'
    executable.write_bytes(b'trusted executable fixture')
    launcher = SandboxLauncher('claude', executable, hashlib.sha256(executable.read_bytes()).hexdigest())
    command = launcher.command(('claude', '--bare', '-p'), 'rosy-deliberation-test.scope')
    assert '--unshare-all' in command and '--new-session' in command
    assert '--clearenv' in command and '--cap-drop' in command
    assert 'MemoryMax=1G' in command and 'TasksMax=32' in command
    assert '--share-net' not in command and '/home' not in command
    assert command[-4:] == ('--', '/provider', '--bare', '-p')
    executable.write_bytes(b'changed')
    with pytest.raises(ValueError, match='digest'):
        launcher.command(('claude', '-p'), 'rosy-deliberation-test.scope')


def test_scope_cleanup_uses_exact_generated_scope(tmp_path, monkeypatch):
    from deploy.site import deliberation_sandbox as module
    executable = tmp_path / 'provider'
    executable.write_bytes(b'fixture')
    launcher = SandboxLauncher('opencode', executable, hashlib.sha256(b'fixture').hexdigest())
    calls = []
    async def fake_process(argv, body, remaining, limit):
        calls.append(argv)
        return 0, b'{}'
    monkeypatch.setattr(module, 'bounded_process', fake_process)
    assert asyncio.run(launcher(('opencode', 'run'), b'{}', 1, 32, .1)) == (0, b'{}')
    scope = next(arg.split('=', 1)[1] for arg in calls[0] if arg.startswith('--unit='))
    assert scope.endswith('.scope') and calls[1] == ('/usr/bin/systemctl', '--user', 'stop', scope)


def test_stdout_is_bounded_and_stderr_is_not_returned():
    async def run():
        code, raw = await bounded_process((sys.executable, '-c',
            'import sys;sys.stderr.write("private diagnostic");print("ok")'), b'', 2, 32)
        assert code == 0 and raw == b'ok\n'
        with pytest.raises(ValueError, match='OUTPUT_LIMIT'):
            await bounded_process((sys.executable, '-c', 'print("x"*100000)'), b'', 2, 32)
    asyncio.run(run())


@pytest.mark.parametrize('cancel', [False, True])
def test_timeout_and_cancel_reap_child_group(tmp_path, cancel):
    pid_file = tmp_path / 'child-pid'
    script = ('import subprocess,sys,time;'
              'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);'
              'open(sys.argv[1],"w").write(str(p.pid));time.sleep(60)')
    async def run():
        task = asyncio.create_task(bounded_process((sys.executable, '-c', script, str(pid_file)), b'', 1, 32))
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(.01)
        assert pid_file.exists()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        pid = int(pid_file.read_text())
        for _ in range(100):
            status = f'/proc/{pid}/stat'
            if not os.path.exists(status) or open(status).read().split()[2] == 'Z':
                break
            await asyncio.sleep(.01)
        else:
            pytest.fail('provider child remains running')
    asyncio.run(run())


def test_invalid_launch_input_never_spawns():
    async def run():
        for deadline in (0, True, float('nan'), 31):
            with pytest.raises(ValueError):
                await bounded_process((sys.executable,), b'', deadline, 32)
        with pytest.raises(ValueError):
            await bounded_process((sys.executable,), b'x'*16385, 1, 32)
    asyncio.run(run())
