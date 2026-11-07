"""host_ops (D-991): the Fleet-down path takes the screen's closed list to the same helper."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/remote'))
_spec = importlib.util.spec_from_file_location('host_ops', ROOT / 'tools/remote/host_ops.py')
ops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ops)

CONFIG = {'site_host': 'ops@site-pc', 'sim_hosts': ['ml@model-pc=model', 'ai@ai-pc=ai', 'x@spare-pc']}


def _runner(code=0):
    calls = []

    def run(argv, **_):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, code)
    return run, calls


def test_a_person_reboot_asks_the_helper_to_stop_at_jobs():
    run, calls = _runner()
    assert ops.run('model', 'reboot', None, CONFIG, runner=run) == 0
    assert calls[0][-5:] == ['ml@model-pc', 'sudo', '-n', ops.HELPER, 'reboot-if-free']


def test_only_the_second_word_passes_jobs():
    run, calls = _runner()
    assert ops.run('ai', 'reboot-over-jobs', None, CONFIG, runner=run) == 0
    assert calls[0][-1] == 'reboot' and 'ai@ai-pc' in calls[0]


@pytest.mark.parametrize('host, action, unit', [
    ('site', 'pkill', None), ('site', 'stop-unit', 'docker.service'), ('site', 'clean-storage', None),
    ('ai', 'restart-unit', 'pinky-frontend.service'), ('robot', 'reboot', None)])
def test_what_the_screen_refuses_never_reaches_ssh(host, action, unit):
    run, calls = _runner()
    assert ops.run(host, action, unit, CONFIG, runner=run) == 2
    assert calls == []


def test_a_helper_refusal_keeps_its_exit_code_and_says_why(capsys):
    run, _ = _runner(6)
    assert ops.run('site', 'reboot', None, CONFIG, runner=run) == 6
    assert 'arm session' in capsys.readouterr().err


def test_a_mistyped_confirm_stops_before_anything_loads(monkeypatch):
    monkeypatch.setattr(ops.lab_hosts, 'load', lambda: pytest.fail('read the host list'))
    with pytest.raises(SystemExit):
        ops.main(['model', 'reboot', '--confirm', 'site'])


def test_unbound_candidates_are_not_targets():
    assert ops.targets(CONFIG) == {'site': 'ops@site-pc', 'model': 'ml@model-pc', 'ai': 'ai@ai-pc'}
