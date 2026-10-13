"""Configured owner only; no real systemd/GPU or operational reviews."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest


WORKSPACE = 'b' * 32


class Systemd:
    def __init__(self, home, service):
        self.home, self.service = home, service
        self.commands = []
        self.active, self.automatic = False, False
        self.invocation = ''
        self.dropins = ''
        self.command_override = None
        self.kill_mode = 'control-group'

    def __call__(self, argv, **kwargs):
        assert argv[:2] == ['systemctl', '--user']
        args = argv[2:]; self.commands.append(args)
        if args[0] == 'show':
            unit = args[1]; timer = unit.endswith('.timer')
            values = dict(ActiveState='active' if (self.automatic if timer else self.active) else 'inactive',
                SubState='running' if self.active else 'dead', Result='success', ExecMainStatus='0',
                InvocationID=self.invocation, UnitFileState='enabled' if self.automatic else 'disabled',
                FragmentPath=str(self.home / '.config/systemd/user' / unit), DropInPaths=self.dropins,
                Triggers=self.service if timer else '', KillMode=self.kill_mode, ExecStop='', ExecStopPost='',
                ExecStartPre='', ExecStartPost='')
            command = next(line.partition('=')[2] for line in (self.home / '.config/systemd/user' / self.service).read_text().splitlines() if line.startswith('ExecStart='))
            values['ExecStart'] = '{ argv[]=' + (self.command_override or command) + ' ; ignore_errors=no ; }'
            return SimpleNamespace(returncode=0, stdout='\n'.join(f'{k}={v}' for k, v in values.items()))
        if args[0] == 'enable': self.automatic = True
        elif args[0] == 'disable': self.automatic = False
        elif args[0] == 'start': self.active = True; self.invocation = 'c' * 32
        elif args[0] == 'stop': self.active = False
        return SimpleNamespace(returncode=0, stdout='')


def binding(tmp_path, workspace=WORKSPACE):
    home = tmp_path / 'home'; units = home / '.config/systemd/user'; units.mkdir(parents=True)
    out = tmp_path / 'cycle-state'; out.mkdir()
    config = tmp_path / 'pipeline.json'
    config.write_text(json.dumps({'cycle': {'max_attempts': 3, 'authority': {'workspace_id': workspace}}, 'review': {}}))
    service = 'rosy-review-pipeline-test.service'
    command = (f'{home}/rosy-ml/.venv/bin/python -I {home}/.local/lib/rosy-model-code/rosy_model_code.py '
        f'--config {home}/.config/rosy/model-code.json exec training/review_pipeline.py '
        f'{config} --out {out} --once')
    (units / service).write_text('[Service]\nType=oneshot\nExecStart=' + command + '\n')
    (units / service.replace('.service', '.timer')).write_text('[Timer]\nUnit=' + service + '\n')
    file = tmp_path / 'control.json'
    file.write_text(json.dumps(dict(schema='rosy.learning.control/1', workspace_id=workspace,
        service=service, config_path=str(config), out_path=str(out))))
    return file, home, out, config, Systemd(home, service)


def control(tmp_path):
    from learning_control import Control
    file, home, out, config, runner = binding(tmp_path)
    return Control(file, WORKSPACE, home=home, runner=runner), runner, out, config, file


def test_start_stop_retry_are_bounded_and_read_back(tmp_path):
    target, runner, out, _, _ = control(tmp_path)
    initial = target.status()
    assert initial['can_start'] and not initial['active']
    started = target.action({'action': 'start', 'version': initial['version']})
    assert started['automatic'] and started['active']
    stopped = target.action({'action': 'stop', 'version': started['version']})
    assert not stopped['automatic'] and not stopped['active']
    retried = target.action({'action': 'retry', 'version': stopped['version']})
    assert retried['active'] and not retried['automatic']
    actions = [args for args in runner.commands if args[0] != 'show']
    assert actions == [['enable', '--now', 'rosy-review-pipeline-test.timer'],
        ['start', '--no-block', runner.service], ['disable', '--now', 'rosy-review-pipeline-test.timer'],
        ['stop', '--no-block', runner.service], ['start', '--no-block', runner.service]]
    assert not (out / 'state.json').exists()


@pytest.mark.parametrize('status,attempts', [('ready', 1), ('candidate', 1), ('rejected', 1), ('gave_up', 3), ('retry', 3)])
def test_retry_never_resets_terminal_states_or_budgets(tmp_path, status, attempts):
    target, runner, out, _, _ = control(tmp_path)
    state = out / 'state.json'
    state.write_text(json.dumps({'cycles': {'one': {'status': status, 'attempts': attempts}}}))
    before = state.read_bytes(); value = target.status()
    assert not value['can_retry']
    with pytest.raises(ValueError): target.action({'action': 'retry', 'version': value['version']})
    assert before == state.read_bytes()
    assert not [args for args in runner.commands if args[0] != 'show']


def test_interrupted_attempt_can_retry_without_mutating_ledger(tmp_path):
    target, _, out, _, _ = control(tmp_path)
    state = out / 'state.json'
    state.write_text(json.dumps({'cycles': {'one': {'status': 'running', 'attempts': 1}}}))
    before = state.read_bytes(); value = target.status()
    assert value['can_retry']
    assert target.action({'action': 'retry', 'version': value['version']})['active']
    assert state.read_bytes() == before


def test_stale_invocation_and_arbitrary_action_inputs_are_refused(tmp_path):
    target, runner, _, _, _ = control(tmp_path)
    version = target.status()['version']; runner.invocation = 'd' * 32
    with pytest.raises(ValueError, match='state|상태'): target.action({'action': 'start', 'version': version})
    for body in [{'action': 'kill', 'version': version}, {'action': 'start', 'version': version, 'unit': 'ssh.service'}]:
        with pytest.raises(ValueError): target.action(body)
    assert not [args for args in runner.commands if args[0] != 'show']


@pytest.mark.parametrize('change', ['config', 'binding', 'unit', 'dropin', 'loaded', 'kill_mode'])
def test_binding_drift_disables_actions(tmp_path, change):
    target, runner, _, config, file = control(tmp_path)
    version = target.status()['version']
    if change == 'config': config.write_text('{}')
    elif change == 'binding': file.write_text('{}')
    elif change == 'unit': (runner.home / '.config/systemd/user' / runner.service).write_text('ExecStart=/bin/false')
    elif change == 'dropin': runner.dropins = '/tmp/changed.conf'
    elif change == 'loaded': runner.command_override = '/bin/sleep 99'
    else: runner.kill_mode = 'process'
    assert target.status()['available'] is False
    with pytest.raises(ValueError): target.action({'action': 'start', 'version': version})
    assert not [args for args in runner.commands if args[0] != 'show']


def test_other_workspace_is_not_an_owner_binding(tmp_path):
    from learning_control import Control
    file, home, _, _, runner = binding(tmp_path)
    with pytest.raises(ValueError): Control(file, 'a' * 32, home=home, runner=runner)
    assert not runner.commands
