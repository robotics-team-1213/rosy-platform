import asyncio

import pytest

from deploy.site import deliberation_preflight as module


@pytest.mark.parametrize('changes,expected', [
    ({}, True), ({'PWD': '/tmp'}, True), ({'PWD': '/home/operator'}, False),
    ({'API_TOKEN': 'fixture'}, False), ({'HOME': '/home/operator'}, False),
    ({'PATH': '/home/operator/bin'}, False),
])
def test_probe_environment_accepts_only_fixed_sandbox_paths(changes, expected):
    import ast
    import inspect
    from types import SimpleNamespace
    tree = ast.parse(inspect.getsource(module.check))
    script = next(node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value.startswith('import errno,json,os'))
    line = next(line for line in script.splitlines() if line.startswith("checks['environment_empty']="))
    environment = {'HOME': '/tmp/home', 'PATH': '/usr/bin:/bin', 'LC_CTYPE': 'C.UTF-8', **changes}
    checks = {}
    exec(line, {'os': SimpleNamespace(environ=environment), 'checks': checks})
    assert checks['environment_empty'] is expected


def test_missing_install_holds_without_spawning(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'BWRAP', tmp_path / 'missing-bwrap')
    def forbidden(*args, **kwargs):
        pytest.fail('must not spawn without trusted install')
    monkeypatch.setattr(module, 'SandboxLauncher', forbidden)
    result = asyncio.run(module.check())
    assert result['state'] == 'HOLD' and result['reason'] == 'ADMIN_INSTALL_REQUIRED'


@pytest.mark.parametrize('quota,expected', [('100000 100000', True), ('200000 100000', False), ('max 100000', False)])
def test_resource_readback_checks_kernel_limits(tmp_path, quota, expected):
    for key, value in [('memory.max', '1073741824'), ('pids.max', '32'), ('cpu.max', quota)]:
        (tmp_path / key).write_text(value)
    properties = {'MemoryMax': '1073741824', 'TasksMax': '32',
        'CPUQuotaPerSecUSec': '1s', 'RuntimeMaxUSec': '35s'}
    assert module.resource_checks(properties, tmp_path)['cgroup_limits'] is expected


def test_descendant_probe_never_passes_without_live_child(monkeypatch):
    class Launcher:
        def command(self, *args):
            return ('fixture',)
    async def process(argv, *args):
        if argv == ('fixture',):
            await asyncio.sleep(60)
        return 0, b''
    async def cleanup(*args):
        return None
    monkeypatch.setattr(module, 'bounded_process', process)
    monkeypatch.setattr(module, 'cleanup_scope', cleanup)
    assert asyncio.run(module.descendant_probe(Launcher(), True)) is False
