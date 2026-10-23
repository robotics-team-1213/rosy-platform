"""update_status flags a channel that has stopped being healthy, not one that is briefly waiting."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_status', ROOT / 'tools/remote/update_status.py')
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)

NOW = 1_000_000.0
DAY = 86400


def channel(unit, result='success', timer='enabled', healthy=NOW - 60, last='{"step": "up_to_date", "release": "8e542e6b4221"}'):
    stamp = '-' if healthy is None else f'{healthy:.3f}'
    return f'unit {unit} {result} {timer} {stamp} {NOW - 30:.3f} host python3[1]: {last}'


def verdicts(*lines):
    host = status.parse('\n'.join(['gate open', *lines]), NOW, 6.0)
    return [c['verdict'] for c in host['channels']], host


def test_a_recent_healthy_step_is_ok_even_while_a_job_holds_the_switch():
    found, host = verdicts(channel('rosy-model-code-update.service',
                                   last='{"result": "held", "reason": "GPU compute job", "desired_commit": "3cdfd40ac2abb05e"}'))
    assert found == ['ok'] and host['channels'][0]['release'] == '3cdfd40ac2ab'


def test_days_of_deferrals_or_failed_fetches_are_stuck():
    found, _ = verdicts(
        channel('rosy-omx-autoupdate.service', healthy=NOW - 4 * DAY,
                last='{"step": "deferred", "reason": "follower_torque_not_off"}'),
        channel('rosy-situation-autoupdate.service', result='exit-code', healthy=NOW - 3 * DAY, last=''),
        channel('rosy-new-pc-autoupdate.service', healthy=None))
    assert found == ['STUCK', 'STUCK', 'STUCK']


def test_a_deliberately_disabled_timer_is_off_not_stuck():
    found, host = verdicts(channel('rosy-review-release-update.service', timer='disabled', healthy=None, last=''),
                           'failed rosy-pilot-fetch@9dfk.service')
    assert found == ['OFF'] and host['failed'] == ['rosy-pilot-fetch@9dfk.service'] and host['gate'] == 'open'
