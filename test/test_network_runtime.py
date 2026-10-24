"""Root glue must derive maintenance and recovery from installed evidence."""
import importlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from subprocess import CompletedProcess

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'deploy/robot/pinky_pro/native'


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(NATIVE))
    return importlib.import_module('network_runtime')


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)


def runner(core='inactive', io='inactive', navigation='inactive'):
    states = {'rosy-core.service': core, 'rosy-io.service': io, 'rosy-navigation.service': navigation}
    def run(argv, **_kw):
        return CompletedProcess(argv, 0, '\n\n'.join(f'Id={name}\nActiveState={state}'
                                                    for name, state in states.items()), '')
    return run


def test_boot_recovery_maintenance_requires_known_stopped_services(module, tmp_path):
    put(tmp_path, 'etc/rosy/runtime.env', 'ROSY_RUNTIME_MODE=core\nROSY_IO_DRIVE_ENABLED=false\n')
    put(tmp_path, 'run/rosy-boot/boot-status.json', {'stage': 'FAILED'})
    assert module.maintenance_ready(tmp_path, run=runner(), sleep=lambda _: None)
    assert not module.maintenance_ready(tmp_path, run=runner(io='active'), sleep=lambda _: None)
    assert not module.maintenance_ready(tmp_path, run=runner(navigation='unknown'), sleep=lambda _: None)


def test_live_core_needs_two_fresh_idle_observations(module, tmp_path):
    now = datetime.now(timezone.utc)
    put(tmp_path, 'etc/rosy/runtime.env', 'ROSY_RUNTIME_MODE=core\nROSY_IO_DRIVE_ENABLED=false\n')
    data = {'written_at': now.isoformat(), 'robot_mode': 'IDLE', 'nav_state': 'IDLE',
            'swarm_role': None, 'velocity_linear': 0.0, 'velocity_angular': 0.0,
            'docking_state': 'UNDOCKED', 'line_follow_mode': 'OFF', 'line_follow_state': 'OFF',
            'swarm_active': False, 'estop': False, 'activity_kind': None}
    put(tmp_path, 'run/rosy/status-inputs.json', data)
    clock = [now]
    def next_sample(_seconds):
        clock[0] += timedelta(seconds=10)
        put(tmp_path, 'run/rosy/status-inputs.json', {**data, 'written_at': clock[0].isoformat()})
    assert module.maintenance_ready(tmp_path, run=runner(core='active'), sleep=next_sample, now=lambda: clock[0])
    assert not module.maintenance_ready(tmp_path, run=runner(core='active'), sleep=lambda _: None,
                                        now=lambda: clock[0])


def test_recovery_identity_and_ap_are_actual_installed_state(module, tmp_path):
    put(tmp_path, 'proc/sys/kernel/random/boot_id', 'boot-1')
    put(tmp_path, 'sys/firmware/devicetree/base/serial-number', '12345678')
    put(tmp_path, 'etc/rosy/device-identity.json', {'device_uid': 'device-1'})
    put(tmp_path, 'var/lib/rosy/provisioning/hardware-binding.json',
        {'device_uid': 'device-1', 'hardware_serial': '12345678'})
    put(tmp_path, 'run/rosy-boot/network.json', {'mode': 'ap', 'address': '10.42.0.1', 'epoch': 'ap-1'})
    put(tmp_path, 'var/lib/rosy/provisioning/state.json', {'state': 'PROVISIONING_AP', 'reason': 'site_wifi_unreachable'})
    state = module.recovery_state(tmp_path, run=runner())
    assert state.eligible() and state.handoff_supported is False
    put(tmp_path, 'sys/firmware/devicetree/base/serial-number', 'different-board')
    assert not module.recovery_state(tmp_path, run=runner()).eligible()


def test_maintenance_claim_excludes_updater_and_detects_loss(module, tmp_path, monkeypatch):
    import rosy_claim
    (tmp_path / 'run').mkdir()
    rosy_claim.acquire(tmp_path, 'updater', 'test', 300)
    with pytest.raises(rosy_claim.ClaimBusy):
        with module.maintenance_claim(tmp_path):
            pytest.fail('must not acquire another owner claim')
    rosy_claim.release(tmp_path, 'updater')
    with module.maintenance_claim(tmp_path) as lease:
        monkeypatch.setattr(rosy_claim, 'refresh', lambda *_a, **_k: False)
        with pytest.raises(RuntimeError, match='claim_lost'):
            lease.refresh()
