"""Root helper contract tests; no root operation or device access."""
from pathlib import Path
import hashlib
import json
import os
import runpy
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'deploy/hosts/common/rosy-native-sim-control'
INSTALLER = ROOT / 'deploy/hosts/common/install-native-sim-control.py'
SHA = 'a' * 40
RUN = SHA + '-' + 'b' * 12


def config(role='ai'):
    return dict(schema='rosy.native-sim-control/1', role=role, account='worker',
                uid=1000, gid=1000, home='/home/worker',
                state_root='/var/lib/rosy-native-sim/1000')


def helper():
    return runpy.run_path(str(HELPER))


@pytest.mark.parametrize('bad', ['../escape', RUN.upper(), RUN + ';id', RUN + '/x',
                                 '--property=User=root', 'a' * 40 + '-short', ''])
def test_rejects_noncanonical_run_id(bad):
    with pytest.raises(ValueError):
        helper()['build_command'](config(), bad)


@pytest.mark.parametrize('role,cpu,memory', [('ai', '400%', '4G'), ('model', '800%', '6G')])
def test_fixed_bounded_nonroot_unit(role, cpu, memory):
    command = helper()['build_command'](config(role), RUN)
    assert command[:2] == ['/usr/bin/systemd-run', '--quiet']
    for prop in ['PrivateNetwork=yes', 'PrivateDevices=yes', 'ProtectSystem=strict',
                 'ProtectHome=read-only', 'NoNewPrivileges=yes', 'KillMode=control-group',
                 'Restart=no', 'UMask=0077', 'RuntimeMaxSec=7500',
                 'CPUQuota=' + cpu, 'MemoryMax=' + memory]:
        assert '--property=' + prop in command
    assert '--uid=worker' in command and '--gid=1000' in command
    assert '--unit=rosy-native-sim-' + RUN in command
    assert '--property=ReadWritePaths=/var/lib/rosy-native-sim/1000/state' in command
    assert command[-6:] == ['/usr/bin/python3', '-B',
        '/var/lib/rosy-native-sim/1000/releases/' + SHA + '/deploy/robot/omx/native_sim_job.py',
        'run', '--state', '/var/lib/rosy-native-sim/1000/state/' + RUN[-12:]]
    assert '--setenv=HOME=/home/worker' in command


@pytest.mark.parametrize('change', [dict(role='fleet'), dict(account='root'), dict(uid=0),
    dict(gid=0), dict(account='worker;id'), dict(home='/tmp/worker'),
    dict(state_root='/tmp/escape'), dict(uid=True), dict(extra='value')])
def test_rejects_config_privilege_or_path_changes(change):
    value = config()
    value.update(change)
    with pytest.raises(ValueError):
        helper()['validate_config'](value)


def test_sudo_identity_is_required_and_environment_does_not_supply_settings():
    api = helper()
    with pytest.raises(PermissionError):
        api['validate_caller'](config(), 0, {'SUDO_USER': 'intruder'})
    with pytest.raises(PermissionError):
        api['validate_caller'](config(), 1000, {'SUDO_USER': 'worker'})
    api['validate_caller'](config(), 0, {'SUDO_USER': 'worker', 'HOME': '/evil',
                                     'ROSY_NATIVE_SIM_CONFIG': '/evil', 'PYTHONPATH': '/evil'})
    assert HELPER.read_text().splitlines()[0] == '#!/usr/bin/python3 -I'


def test_probe_accepts_no_id_and_actions_accept_exactly_one():
    api = helper()
    assert api['parse_args'](['probe']) == ('probe', None)
    assert api['parse_args'](['start', RUN]) == ('start', RUN)
    for args in [[], ['probe', RUN], ['start'], ['shell', RUN], ['stop', RUN, 'extra']]:
        with pytest.raises(ValueError):
            api['parse_args'](args)


def test_install_dry_run_is_explicit_and_helper_specific():
    api = runpy.run_path(str(INSTALLER))
    account = SimpleNamespace(pw_name='worker', pw_uid=1000, pw_gid=1000, pw_dir='/home/worker')
    plan = api['build_plan']('ai', account, approved=True, site=False)
    assert plan['config'] == config()
    assert plan['sudoers'] == 'worker ALL=(root) NOPASSWD: /usr/local/sbin/rosy-native-sim-control\n'
    assert plan['helper'] == '/usr/local/sbin/rosy-native-sim-control'
    for approved, site, role in [(False, False, 'ai'), (True, True, 'ai'), (True, False, 'fleet')]:
        with pytest.raises((ValueError, PermissionError)):
            api['build_plan'](role, account, approved=approved, site=site)


def test_managed_entry_rejects_symlink_and_writable_root_directory(tmp_path):
    api = helper()
    target = tmp_path / 'target'
    target.mkdir(mode=0o755)
    alias = tmp_path / 'alias'
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(PermissionError):
        api['check_entry'](alias, owner=os.getuid(), directory=True)
    target.chmod(0o777)
    with pytest.raises(PermissionError):
        api['check_entry'](target, owner=os.getuid(), directory=True)
    target.chmod(0o755)
    api['check_entry'](target, owner=os.getuid(), directory=True)


def test_start_is_durable_and_not_replayed_after_ambiguous_launch(tmp_path, monkeypatch):
    api = helper()
    scope = api['start'].__globals__
    value = config()
    value['state_root'] = str(tmp_path)
    (tmp_path / 'start-intents').mkdir()
    (tmp_path / 'state' / RUN[-12:]).mkdir(parents=True)
    (tmp_path / 'releases' / SHA).mkdir(parents=True)
    calls = []

    def invoke(args):
        calls.append(args)
        if args[1] == 'list-units':
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        assert (tmp_path / 'start-intents' / (RUN + '.json')).exists()
        raise TimeoutError('unknown launch acknowledgement')

    # Root filesystem ownership is a separate tested guard; this test runs without root.
    monkeypatch.setitem(scope, 'check_entry', lambda *args, **kwargs: None)
    monkeypatch.setitem(scope, 'command', invoke)
    monkeypatch.setitem(scope, 'build_command', lambda *args: ['/usr/bin/systemd-run', '--quiet'])
    with pytest.raises(TimeoutError):
        api['start'](value, RUN)
    with pytest.raises(PermissionError, match='durable start intent'):
        api['start'](value, RUN)
    assert len(calls) == 2


def test_concurrent_unit_blocks_start_before_intent(tmp_path, monkeypatch):
    api = helper()
    scope = api['start'].__globals__
    value = config()
    value['state_root'] = str(tmp_path)
    monkeypatch.setitem(scope, 'check_entry', lambda *args, **kwargs: None)
    monkeypatch.setitem(scope, 'command', lambda args: SimpleNamespace(
        returncode=0, stdout='rosy-native-sim-other.service loaded active running\n'))
    with pytest.raises(PermissionError, match='another native simulation'):
        api['start'](value, RUN)
    assert not (tmp_path / 'start-intents' / (RUN + '.json')).exists()


def test_command_discards_caller_environment(monkeypatch):
    api = helper()
    calls = []
    monkeypatch.setenv('DBUS_SYSTEM_BUS_ADDRESS', 'unix:path=/evil')
    monkeypatch.setenv('LD_PRELOAD', '/evil.so')
    monkeypatch.setattr(api['subprocess'], 'run', lambda args, **kwargs: calls.append(kwargs))
    api['command'](['/usr/bin/systemctl', 'show', 'fixed.service'])
    assert calls[0]['env'] == {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'HOME': '/root'}


@pytest.mark.parametrize('mutation', ['remove_build_id_guard', 'disable_private_network'])
def test_guard_mutation_proof_in_external_copy(tmp_path, monkeypatch, mutation):
    """Run existing refusal/property assertions against real, isolated source mutations."""
    original = HELPER.read_bytes()
    copy = tmp_path / 'rosy-native-sim-control'
    copy.write_bytes(original)

    def checks(path):
        api = runpy.run_path(str(path))
        with monkeypatch.context() as patch:
            patch.setitem(test_rejects_noncanonical_run_id.__globals__, 'helper', lambda: api)
            if mutation == 'remove_build_id_guard':
                test_rejects_noncanonical_run_id('../escape')
            else:
                test_fixed_bounded_nonroot_unit('ai', '400%', '4G')

    checks(copy)
    if mutation == 'remove_build_id_guard':
        before = ('def build_command(config, run_id):\n'
                  '    validate_config(config)\n    validate_run_id(run_id)')
        after = ('def build_command(config, run_id):\n'
                 '    validate_config(config)\n    pass  # diagnostic mutation')
    else:
        before, after = 'PrivateNetwork=yes', 'PrivateNetwork=no'
    source = original.decode()
    assert source.count(before) == 1, 'mutation must match the real guarded implementation once'
    changed = source.replace(before, after, 1).encode()
    copy.write_bytes(changed)
    assert copy.read_bytes() == changed and changed != original
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        checks(copy)
    copy.write_bytes(original)
    assert copy.read_bytes() == HELPER.read_bytes() == original
    checks(copy)
    receipt = dict(scope='remote_source_only_external_copy_no_root_or_ROS', mutation=mutation,
                   source_sha256=hashlib.sha256(original).hexdigest(),
                   mutated_sha256=hashlib.sha256(changed).hexdigest(),
                   restored_sha256=hashlib.sha256(copy.read_bytes()).hexdigest(),
                   baseline='PASS', mutation_detected=True, restored='PASS')
    (tmp_path / 'receipt.json').write_text(json.dumps(receipt, sort_keys=True) + '\n')
    print('NATIVE_CONTROL_MUTATION_RECEIPT ' + json.dumps(receipt, sort_keys=True))
