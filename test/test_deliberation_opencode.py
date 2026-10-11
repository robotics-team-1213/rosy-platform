import asyncio
import importlib
import json
import os
import signal
from contextlib import asynccontextmanager
from pathlib import Path

import pytest


def subject():
    return importlib.import_module('deploy.ai_pc.deliberation_opencode')


def test_fresh_config_has_one_model_and_denies_extra_calls():
    module = subject()
    assert module.GlmOpenCodeLauncher.cost_verified is False
    config = module.smoke_config()
    assert config['model'] == config['small_model'] == module.MODEL
    assert config['enabled_providers'] == ['zai-coding-plan']
    assert config['plugin'] == [] and config['mcp'] == {} and config['permission'] == 'deny'
    assert config['autoupdate'] is False and config['share'] == 'disabled'
    assert config['agent']['rosy']['steps'] == 1
    assert all(config['agent'][name]['disable'] for name in
               ('title', 'summary', 'compaction', 'build', 'plan', 'general', 'explore'))
    provider = config['provider']['zai-coding-plan']
    assert provider['options']['baseURL'] == 'http://127.0.0.1:18081/v1'
    assert provider['models']['glm-5.3-flash']['tool_call'] is False
    assert provider['models']['glm-5.3-flash']['limit']['output'] == 1024


def test_command_preserves_namespace_and_mounts_no_secret(tmp_path):
    module = subject()
    class Sandbox:
        def command(self, argv, unit):
            return ('/usr/bin/systemd-run', '--unit=' + unit, '--', '/bwrap',
                    '--unshare-all', '--clearenv', '--', '/provider', *argv[1:])
    command = module.isolated_command(Sandbox(), module.ARGV, 'rosy-deliberation-test.scope', tmp_path)
    assert '--unshare-all' in command and '--share-net' not in command
    assert '/gateway.sock' in command and '/relay.py' in command and '/runner.py' in command
    assert module.SECRET not in command and '/var/lib/rosy-deliberation' not in command
    assert command[-8:] == ('/usr/bin/python3', '/runner.py', *module.ARGV[1:])


def test_launcher_one_call_and_gateway_receipt_required(tmp_path, monkeypatch):
    module = subject()
    events = []
    class Sandbox:
        def __init__(self, kind, executable, digest):
            assert kind == 'opencode' and executable == module.EXECUTABLE and digest == module.EXECUTABLE_SHA256
        def command(self, argv, unit):
            return ('/usr/bin/systemd-run', '--', '/bwrap', '--unshare-all', '--', '/provider', *argv[1:])
        def close(self):
            events.append('close')
    @asynccontextmanager
    async def gateway(body, remaining, directory):
        events.append('ready')
        yield object()
        events.append('gateway-cleaned')
    async def bounded(argv, body, remaining, limit):
        events.append('cli')
        assert 0 < remaining <= 1 and limit == 100
        return 0, b'opinion'
    async def finish(process):
        events.append('receipt')
        return {'state': 'PASS_GLM_PROVIDER_ONLY', 'calls': 1, 'usage': {}}
    async def clean(unit):
        events.append('scope-cleaned')
    monkeypatch.setattr(module, 'SandboxLauncher', Sandbox)
    monkeypatch.setattr(module, 'gateway_session', gateway)
    monkeypatch.setattr(module, 'bounded_process', bounded)
    monkeypatch.setattr(module, 'finish_gateway', finish)
    monkeypatch.setattr(module, 'cleanup_scope', clean)
    with module.GlmOpenCodeLauncher() as launcher:
        assert asyncio.run(launcher(module.ARGV, b'{}', 1, 100, .1)) == (0, b'opinion')
        with pytest.raises(ValueError, match='ONE_SHOT_ALREADY_USED'):
            asyncio.run(launcher(module.ARGV, b'{}', 1, 100, .1))
    assert events == ['ready', 'cli', 'receipt', 'scope-cleaned', 'gateway-cleaned', 'close']


@pytest.mark.parametrize('argv,body,remaining,limit,budget', [
    (('opencode', 'run', '--auto'), b'{}', 1, 100, .1),
    (None, b'{}', 1, 100, .1), ((), b'{}', 1, 100, .1),
    ('argv', b'{}', 1, 100, .1),
    (None, b'{}', 31, 100, .1),
])
def test_invalid_inputs_refuse_before_gateway(argv, body, remaining, limit, budget, monkeypatch):
    module = subject()
    class Sandbox:
        def __init__(self, *args):
            pass
        def close(self):
            pass
    monkeypatch.setattr(module, 'SandboxLauncher', Sandbox)
    with module.GlmOpenCodeLauncher() as launcher:
        with pytest.raises(ValueError):
            asyncio.run(launcher(argv, body, remaining, limit, budget))


@pytest.mark.parametrize('state,calls,code', [('HOLD', 1, 0), ('PASS_GLM_PROVIDER_ONLY', 0, 0),
                                          ('PASS_GLM_PROVIDER_ONLY', 1, 1)])
def test_unknown_gateway_receipt_refuses(state, calls, code):
    from deploy.ai_pc.deliberation_opencode_process import finish_gateway
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps({'state': state, 'calls': calls}).encode())
        reader.feed_eof()
        class Process:
            stdout = reader
            async def wait(self):
                return code
        with pytest.raises(ValueError, match='GATEWAY_RESULT_UNKNOWN'):
            await finish_gateway(Process())
    asyncio.run(run())


def test_actual_gateway_child_ready_has_no_inherited_secret(tmp_path, monkeypatch):
    from deploy.ai_pc import deliberation_opencode_process as module
    real_spawn = asyncio.create_subprocess_exec
    monkeypatch.setenv('HOST_PRIVATE_TOKEN', 'fixture-no-inheritance')
    script = "import json,os,sys; job=json.loads(sys.stdin.readline()); assert set(os.environ)<= {'PATH','PYTHONPATH','LC_CTYPE'}; assert job['secret_path']=='/var/lib/rosy-deliberation/glm-coding-plan.json'; print('READY',flush=True); print(json.dumps({'state':'PASS_GLM_PROVIDER_ONLY','calls':1}),flush=True)"
    async def spawn(*argv, **kwargs):
        assert argv == ('/usr/bin/python3', '-m', 'deploy.ai_pc.deliberation_glm_gateway')
        return await real_spawn('/usr/bin/python3', '-c', script, **kwargs)
    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', spawn)
    async def run():
        async with module.gateway_session(b'{}', 1, tmp_path) as process:
            return await module.finish_gateway(process)
    assert asyncio.run(run())['calls'] == 1


def test_actual_gateway_child_cancel_reaps_process(tmp_path, monkeypatch):
    from deploy.ai_pc import deliberation_opencode_process as module
    real_spawn = asyncio.create_subprocess_exec
    seen = []
    async def spawn(*argv, **kwargs):
        process = await real_spawn('/usr/bin/python3', '-c',
            "import sys,time;sys.stdin.readline();print('READY',flush=True);time.sleep(60)", **kwargs)
        seen.append(process)
        return process
    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', spawn)
    async def run():
        ready = asyncio.Event()
        async def child():
            async with module.gateway_session(b'{}', 1, tmp_path):
                ready.set()
                await asyncio.Future()
        task = asyncio.create_task(child())
        await asyncio.wait_for(ready.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert len(seen) == 1 and seen[0].returncode == -signal.SIGKILL
    with pytest.raises(ProcessLookupError):
        os.kill(seen[0].pid, 0)


def test_v2_gateway_preserves_host_venv_and_foundation_closure(tmp_path, monkeypatch):
    import sys
    from deploy.ai_pc import deliberation_opencode_process as module
    from test_deliberation_glm_judgment import fixture
    real_spawn = asyncio.create_subprocess_exec
    _, _, body = fixture()
    script = "import json,os,sys;job=json.loads(sys.stdin.readline());assert job['credential_sha256']=='f'*64;assert any(p.endswith('/contracts/foundation') for p in os.environ['PYTHONPATH'].split(os.pathsep));print('READY',flush=True);print(json.dumps({'state':'PASS_GLM_PROVIDER_ONLY','calls':1}),flush=True)"
    async def spawn(*argv, **kwargs):
        assert argv == (sys.executable, '-m', 'deploy.ai_pc.deliberation_glm_gateway')
        return await real_spawn(sys.executable, '-c', script, **kwargs)
    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', spawn)
    async def run():
        async with module.gateway_session(body, 1, tmp_path, credential_sha256='f' * 64) as process:
            return await module.finish_gateway(process)
    assert asyncio.run(run())['calls'] == 1
