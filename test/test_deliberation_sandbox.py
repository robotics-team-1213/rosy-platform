import asyncio
import hashlib
import os
import sys
import uuid

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
    assert 'RuntimeMaxSec=35s' in command
    assert '--share-net' not in command and '/home' not in command
    assert command[-4:] == ('--', '/provider', '--bare', '-p')
    executable.write_bytes(b'changed')
    assert launcher.executable.read_bytes() == b'trusted executable fixture'
    assert launcher.command(('claude', '-p'), 'rosy-deliberation-test.scope')[-2:] == ('/provider', '-p')
    launcher.executable.chmod(0o700)
    launcher.executable.write_bytes(b'changed snapshot')
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
    assert scope.endswith('.scope') and calls[1] == ('/usr/bin/systemctl', '--user', 'kill',
        '--kill-whom=all', '--signal=KILL', scope)


def test_provider_factory_connects_translator_and_closes_snapshot(tmp_path):
    from deploy.site.deliberation_sandbox import sandbox_provider
    executable = tmp_path / 'provider'
    executable.write_bytes(b'fixture')
    with sandbox_provider(kind='claude', executable=executable,
            executable_sha256=hashlib.sha256(b'fixture').hexdigest(),
            model='reviewed-model', profile_id='reviewed-profile') as provider:
        snapshot = provider.launch.executable
        assert provider.kind == 'claude' and snapshot.exists()
    assert not snapshot.exists()


def test_stdout_is_bounded_and_stderr_is_not_returned():
    async def run():
        code, raw = await bounded_process((sys.executable, '-c',
            'import sys;sys.stderr.write("private diagnostic");print("ok")'), b'', 2, 32)
        assert code == 0 and raw == b'ok\n'
        with pytest.raises(ValueError, match='OUTPUT_LIMIT'):
            await bounded_process((sys.executable, '-c', 'print("x"*100000)'), b'', 2, 32)
    asyncio.run(run())


def test_repeated_cancel_during_delayed_spawn_still_reaps(tmp_path, monkeypatch):
    from deploy.site import deliberation_sandbox as module
    original = asyncio.create_subprocess_exec
    processes = []
    async def delayed(*args, **kwargs):
        await asyncio.sleep(.1)
        process = await original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', delayed)
    async def run():
        task = asyncio.create_task(bounded_process((sys.executable, '-c',
            'import time;time.sleep(60)'), b'', 2, 32))
        await asyncio.sleep(.01)
        task.cancel()
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes and all(p.returncode is not None for p in processes)
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
            try:
                with open(status) as stream:
                    exited = stream.read().split()[2] == 'Z'
            except (FileNotFoundError, ProcessLookupError):
                exited = True
            if exited:
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


@pytest.mark.parametrize('load_state,allowed', [(b'not-found\n', True), (b'loaded\n', False), (b'', False)])
def test_collected_scope_requires_explicit_absence_readback(monkeypatch, load_state, allowed):
    from deploy.site import deliberation_sandbox as module
    calls = []
    async def fake(argv, *args):
        calls.append(argv)
        return (1, b'') if len(calls) == 1 else (0, load_state)
    monkeypatch.setattr(module, 'bounded_process', fake)
    async def run():
        if allowed:
            await module.cleanup_scope('rosy-deliberation-test.scope')
        else:
            with pytest.raises(RuntimeError, match='CLEANUP_UNCONFIRMED'):
                await module.cleanup_scope('rosy-deliberation-test.scope')
    asyncio.run(run())
    assert calls[1][-2:] == ('--value', 'rosy-deliberation-test.scope')


def test_cleanup_cannot_target_other_units(monkeypatch):
    from deploy.site import deliberation_sandbox as module
    async def forbidden(*args):
        pytest.fail('invalid unit must never reach systemctl')
    monkeypatch.setattr(module, 'bounded_process', forbidden)
    async def run():
        for unit in ('--all', 'fleet.service', 'rosy-deliberation-test.scope\n', None):
            with pytest.raises(ValueError):
                await module.cleanup_scope(unit)
    asyncio.run(run())


def test_actual_user_manager_confirms_absent_generated_scope():
    from deploy.site.deliberation_sandbox import cleanup_scope
    unit = 'rosy-deliberation-' + uuid.uuid4().hex + '.scope'
    asyncio.run(cleanup_scope(unit))


def test_sandbox_provider_forwards_pinned_opencode_version_and_closes(monkeypatch):
    from deploy.site import deliberation_sandbox as module
    closed = []
    class Launcher:
        def __init__(self, *args):
            pass
        async def __call__(self, *args):
            pytest.fail('version wiring must not invoke a model')
        def close(self):
            closed.append(True)
    monkeypatch.setattr(module, 'SandboxLauncher', Launcher)
    with module.sandbox_provider(kind='opencode', executable='/pinned', executable_sha256='a'*64,
                                 model='ollama/pinned', profile_id='local', cli_version='1.18.35') as provider:
        assert provider.cli_version == '1.18.35'
    assert closed == [True]
    with pytest.raises(ValueError, match='UNSUPPORTED_OPENCODE_VERSION'):
        with module.sandbox_provider(kind='opencode', executable='/pinned', executable_sha256='a'*64,
                                     model='ollama/pinned', profile_id='local', cli_version='latest'):
            pytest.fail('unsupported version must not yield a provider')
    assert closed == [True, True]
