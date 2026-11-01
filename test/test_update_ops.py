"""update_ops contract: one operator CLI for every update channel (D-957).

Selector resolution comes from lab_hosts + services.yaml (channel: updater), the
command mapping is pinned per surface, and no command may bypass a surface's own
gates: run-now only starts the existing unit/CLI once.
"""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('update_ops', ROOT / 'tools/remote/update_ops.py')
ops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ops)

CONFIG = {
    'robots': {'alpha': 'rosy-pinky-alpha.local', 'beta': 'ops@10.0.0.9'},
    'site_host': 'ops@site-pc',
    'sim_hosts': ['ml@model-pc=model', 'ai@ai-pc=ai'],
    'omx_hosts': ['ops@site-pc'],
    'test_hosts': [],
}
INVENTORY = {
    'model': {
        'rosy-model-code-update.service': {'run': 'oneshot', 'channel': 'updater'},
        'rosy-model-code-update.timer': {'run': 'timer', 'channel': 'updater'},
        'rosy-ollama.service': {'run': 'active', 'channel': 'host'},
        'rosy-learning-center-update.service': {'run': 'off', 'channel': 'retired'},
    },
    'ai': {
        'rosy-situation-autoupdate.service': {'run': 'oneshot', 'channel': 'updater'},
        'rosy-ai-gpu-watchdog.timer': {'run': 'timer', 'channel': 'copy'},
    },
    'site': {
        'rosy-site-tools-autoupdate.service': {'run': 'oneshot', 'channel': 'updater'},
    },
    'omx': {
        'rosy-omx-autoupdate.service': {'run': 'oneshot', 'channel': 'updater'},
    },
}
ROBOTS = CONFIG['robots']


def unit(name):
    return ('user-unit', name)


def test_all_resolves_robots_site_stack_and_declared_updaters():
    targets = ops.resolve(CONFIG, INVENTORY, 'all', robots=ROBOTS)
    found = {t['host']: t['channels'] for t in targets}
    assert found['rosy-pinky-alpha.local'] == [('robot', None)]
    assert found['ops@10.0.0.9'] == [('robot', None)]
    assert found['ops@site-pc'] == [
        ('site-stack', None), unit('rosy-omx-autoupdate.service'), unit('rosy-site-tools-autoupdate.service')]
    assert found['ml@model-pc'] == [unit('rosy-model-code-update.service')]
    assert found['ai@ai-pc'] == [unit('rosy-situation-autoupdate.service')]


def test_selector_narrows_to_one_robot_or_the_site():
    assert ops.resolve(CONFIG, INVENTORY, 'alpha', robots=ROBOTS) == [
        {'host': 'rosy-pinky-alpha.local', 'channels': [('robot', None)]}]
    site = ops.resolve(CONFIG, INVENTORY, 'site', robots=ROBOTS)
    assert [t['host'] for t in site] == ['ops@site-pc']
    assert site[0]['channels'][0] == ('site-stack', None)
    assert len(ops.resolve(CONFIG, INVENTORY, 'robots', robots=ROBOTS)) == 2


def test_host_selector_and_unknown_selector():
    assert [t['host'] for t in ops.resolve(CONFIG, INVENTORY, 'ml@model-pc', robots=ROBOTS)] == ['ml@model-pc']
    with pytest.raises(SystemExit):
        ops.resolve(CONFIG, INVENTORY, 'nope', robots=ROBOTS)


def test_unit_filter_narrows_and_refuses_to_empty():
    targets = ops.resolve(CONFIG, INVENTORY, 'site', robots=ROBOTS)
    narrowed = ops.apply_unit_filter(targets, 'rosy-omx-autoupdate.service')
    assert narrowed[0]['channels'] == [unit('rosy-omx-autoupdate.service')]
    with pytest.raises(SystemExit):
        ops.apply_unit_filter(targets, 'rosy-absent.service')


class FakeRun:
    def __init__(self, code=0, output=''):
        self.calls = []
        self.code = code
        self.output = output

    def __call__(self, argv, input=None):
        self.calls.append((argv, input))
        return self.code, self.output


def robot_opts(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    return (['-i', str(tmp_path / 'Rosy/ssh/rosy-operator-ed25519'),
             '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
             '-o', 'StrictHostKeyChecking=yes',
             '-o', f'UserKnownHostsFile={tmp_path}/Rosy/known_hosts',
             '-o', 'ConnectTimeout=5'])


def test_robot_commands_pin_the_device_cli(monkeypatch, tmp_path):
    args = robot_opts(monkeypatch, tmp_path)
    argv = ops.commands({'host': 'rosy-pinky-alpha.local', 'channels': [('robot', None)]}, 'run-now')[0][1]
    assert argv == ['ssh', *args, 'rosy@rosy-pinky-alpha.local',
                    'sudo -n systemctl start rosy-auto-update.service']
    argv = ops.commands({'host': 'rosy-pinky-alpha.local', 'channels': [('robot', None)]}, 'hold',
                        reason='demo prep', hours=4, holder='me@pc')[0][1]
    assert argv[-1] == ("sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py "
                        "hold --holder 'me@pc' --reason 'demo prep' --hours 4")
    argv = ops.commands({'host': 'rosy-pinky-alpha.local', 'channels': [('robot', None)]}, 'resume')[0][1]
    assert argv[-1].endswith('release-hold')
    argv = ops.commands({'host': 'rosy-pinky-alpha.local', 'channels': [('robot', None)]}, 'status')[0][1]
    assert argv[-1].endswith('status --json')


def test_robot_argv_keeps_a_listed_user_and_pins_the_site_cli():
    argv = ops.commands({'host': 'ops@10.0.0.9', 'channels': [('robot', None)]}, 'run-now')[0][1]
    assert argv[-2] == 'ops@10.0.0.9'
    argv = ops.commands({'host': 'ops@site-pc', 'channels': [('site-stack', None)]}, 'hold',
                        reason='site maintenance')[0][1]
    assert argv == ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'ops@site-pc',
                    "sudo -n /usr/bin/python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py "
                    "hold 'site maintenance'"]
    for action, tail in (('run-now', 'sudo -n systemctl start rosy-site-autoupdate.service'),
                         ('resume', 'resume'), ('status', 'status'),
                         ('forget-failed', 'forget-failed site-abc123')):
        argv = ops.commands({'host': 'ops@site-pc', 'channels': [('site-stack', None)]}, action,
                            tag='site-abc123')[0][1]
        assert argv[:5] == ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15']
        assert argv[-1].endswith(tail)


def test_unit_commands_start_the_service_and_toggle_the_timer():
    target = {'host': 'ml@model-pc', 'channels': [unit('rosy-model-code-update.service')]}
    assert ops.commands(target, 'run-now')[0][1] == [
        'ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'ml@model-pc',
        'systemctl --user start rosy-model-code-update.service']
    assert ops.commands(target, 'hold')[0][1][-1] == \
        'systemctl --user disable --now rosy-model-code-update.timer'
    assert ops.commands(target, 'resume')[0][1][-1] == \
        'systemctl --user enable --now rosy-model-code-update.timer'


def one(kind, host='ops@site-pc'):
    channel = ('robot', None) if kind == 'robot' else (
        ('site-stack', None) if kind == 'site-stack' else unit('rosy-model-code-update.service'))
    return {'host': host, 'channels': [channel]}


def test_execute_runs_every_command_and_reports_failures(capsys):
    run = FakeRun(code=1)
    code = ops.execute([one('robot', 'rosy-pinky-a.local'), one('user-unit', 'ml@model-pc')], 'run-now', run=run)
    assert code == 1 and len(run.calls) == 2
    printed = capsys.readouterr().out
    assert 'rosy-pinky-a.local' in printed and 'ml@model-pc' in printed  # each argv printed first
    assert ops.execute([one('user-unit', 'ml@model-pc')], 'run-now', run=FakeRun()) == 0


def test_hold_hours_are_robot_only_and_robot_hold_requires_them():
    with pytest.raises(ValueError):
        ops.execute([one('robot', 'rosy-pinky-a.local')], 'hold', run=FakeRun(), reason='seal')
    with pytest.raises(ValueError):
        ops.execute([one('robot', 'rosy-pinky-a.local')], 'hold', run=FakeRun(),
                    reason='seal', hours=169)
    with pytest.raises(ValueError):
        ops.execute([one('robot', 'rosy-pinky-a.local'), one('site-stack')], 'hold', run=FakeRun(),
                    reason='seal', hours=2)


def test_robot_reason_and_holder_charsets_are_the_ps1_contract():
    with pytest.raises(ValueError):
        ops.execute([one('robot', 'rosy-pinky-a.local')], 'hold', run=FakeRun(),
                    reason="it's running", hours=2)
    with pytest.raises(ValueError):
        ops.execute([one('robot', 'rosy-pinky-a.local')], 'hold', run=FakeRun(),
                    reason='ok reason', holder='bad holder!', hours=2)


def test_forget_failed_refuses_non_site_channels():
    with pytest.raises(ValueError):
        ops.execute([one('robot', 'rosy-pinky-a.local')], 'forget-failed', run=FakeRun(), tag='site-abc123')
    assert ops.execute([one('site-stack')], 'forget-failed', run=FakeRun(), tag='site-abc123') == 0


def test_hold_writes_the_ledger_run_now_warns_resume_clears(tmp_path, capsys):
    ledger = tmp_path / 'update-holds.json'
    run = FakeRun()
    assert ops.execute([one('user-unit', 'ml@model-pc')], 'hold', run=run,
                       reason='gpu bench', ledger=ledger) == 0
    saved = ops.load_ledger(ledger)
    assert saved['ml@model-pc|rosy-model-code-update.service']['reason'] == 'gpu bench'
    assert not list(tmp_path.glob('update-holds.json.new'))  # atomic: no temp left behind
    ops.execute([one('user-unit', 'ml@model-pc')], 'run-now', run=FakeRun(), ledger=ledger)
    assert 'held (gpu bench' in capsys.readouterr().out
    assert ops.execute([one('user-unit', 'ml@model-pc')], 'resume', run=FakeRun(), ledger=ledger) == 0
    assert 'ml@model-pc' not in ops.load_ledger(ledger)
    ops.execute([one('user-unit', 'ml@model-pc')], 'run-now', run=FakeRun(), ledger=ledger)
    assert 'held (' not in capsys.readouterr().out


def test_resume_without_a_ledger_entry_still_resumes_but_says_so(tmp_path, capsys):
    ops.execute([one('user-unit', 'ml@model-pc')], 'resume', run=FakeRun(), ledger=tmp_path / 'update-holds.json')
    assert 'no ledger entry' in capsys.readouterr().out


def test_status_filters_the_probe_to_the_hosts_updaters(tmp_path):
    ledger = tmp_path / 'update-holds.json'
    ops.add_hold(ledger, 'ml@model-pc', 'rosy-model-code-update.service', 'gpu bench', 'me@pc')
    now = 1_000_000.0
    probe = '\n'.join([
        'gate open',
        f'unit rosy-model-code-update.service success enabled {now - 60:.3f} {now - 30:.3f} host python3[1]: '
        '{"step": "up_to_date", "release": "8e542e6b4221"}',
        f'unit rosy-ollama.service success enabled {now - 60:.3f} {now - 30:.3f} host python3[1]: '
        '{"step": "other"}',
        f'unit rosy-situation-autoupdate.service success disabled - {now - 30:.3f} host python3[1]: '
        '{"step": "deferred"}',
    ])
    run = FakeRun(output=probe)
    target = {'host': 'ml@model-pc',
              'channels': [unit('rosy-model-code-update.service'), unit('rosy-situation-autoupdate.service')]}
    lines = ops.status_lines(target, run=run, ledger=ledger, now=now)
    text = '\n'.join(lines)
    assert 'gate open' in text
    assert 'rosy-model-code-update.service' in text and 'up_to_date' in text
    assert 'rosy-situation-autoupdate.service' in text and 'OFF' in text
    assert 'rosy-ollama.service' not in text  # not an updater channel of this target
    assert 'held (gpu bench' in text
    assert run.calls[0][0][-1] == 'bash -s' and run.calls[0][1] == ops.PROBE.encode()


def test_status_uses_the_native_cli_for_robot_and_site():
    run = FakeRun(output='{"hold": null}')
    lines = ops.status_lines(one('robot', 'rosy-pinky-a.local'), run=run, ledger=Path('/none'))
    assert '{"hold": null}' in '\n'.join(lines)
    assert run.calls[0][0][-1].endswith('status --json')
    run = FakeRun(output='{"last_run": {}}')
    lines = ops.status_lines(one('site-stack'), run=run, ledger=Path('/none'))
    assert '{"last_run": {}}' in '\n'.join(lines)


def test_main_targets_is_read_only_and_usage_fails_closed():
    assert ops.main(['targets', 'site'], config=CONFIG, inventory=INVENTORY,
                    robots=ROBOTS, run=FakeRun()) == 0
    assert ops.main(['run-now', 'nope'], config=CONFIG, inventory=INVENTORY,
                    robots=ROBOTS, run=FakeRun()) == 2
