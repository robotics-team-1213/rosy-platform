import asyncio

import pytest

from deploy.site import deliberation_preflight as module


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
