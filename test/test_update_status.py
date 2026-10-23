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


def test_service_sources_name_adhoc_copies_pinned_releases_and_updated_links():
    host = status.parse('\n'.join([
        'gate open',
        'svc rosy-omx-camera-readiness.service /home/robttt/rosy-test/omx-camera-environment-c6c9366d8',
        'svc rosy-omx-observer@arm_a.service /home/robttt/.local/share/rosy/omx-observation/releases/d227b0c2c50a3c310a514f2b45524b69825ddb1a',
        'svc rosy-learning-center.service /home/rosy/.local/share/rosy-learning-center/source/c643281c4493c06df8d9ae7434a81444a0855b9e',
        'svc rosy-review-v13.service /home/rosy/rosy-ml/review-v13-code/current',
        'svc rosy-ollama.service -']), NOW, 6.0)
    assert [(s['kind'], s['where']) for s in host['sources']] == [
        ('ADHOC', 'omx-camera-environment-c6c9366d8'), ('release', 'd227b0c2c50a'),
        ('release', 'c643281c4493'), ('current', 'review-v13-code'), ('other', '-')]


def test_the_review_release_updater_plain_text_results_count_as_healthy():
    line = f'unit rosy-review-release-update.service success enabled {NOW - 120:.3f} {NOW - 60:.3f} host python3[9]: already active: model-code-31-3cdfd40ac2ab'
    found, host = verdicts(line)
    assert found == ['ok'] and host['channels'][0]['step'] == 'already active'


RUNS = {'active', 'timer', 'oneshot', 'off'}
CHANNELS = {'autoupdate', 'updater', 'signed', 'snapshot', 'installer', 'copy', 'host', 'external', 'adhoc', 'retired'}


def test_every_declared_unit_names_a_known_run_channel_and_existing_repo_paths():
    roles = status.load_inventory()
    assert set(roles) == {'model', 'ai', 'site'}
    for role, units in roles.items():
        for name, entry in units.items():
            assert name.startswith(('rosy-', 'pinky-')) and name.endswith(('.service', '.timer')), name
            assert entry['run'] in RUNS and entry['channel'] in CHANNELS, name
            assert ('instances' in entry) <= ('@.' in name), name
            paths = [entry['doc'], entry.get('template'), *(entry.get('copies') or {}).values()]
            for path in filter(None, paths):
                if not path.startswith('rosy-ops:'):
                    assert (ROOT / path).is_file(), f'{role} {name}: {path}'


def test_roles_come_from_the_site_host_and_sim_host_suffixes():
    assert status.roles({'site_host': 'site@h', 'sim_hosts': ['m@h=model', 'a@h=ai', 'x@h']}) == {
        'm@h': 'model', 'a@h': 'ai', 'site@h': 'site'}


def observed(**files):
    host = dict(files={}, instances={}, copies={}, paths={})
    for name, record in files.items():
        host['files'][name.replace('_', '-')] = dict(dict(enabled='enabled', active='active', sha256='t', dropins=[]), **record)
    return host


def findings(declared, host, digests=None):
    return [(v, u) for v, u, _ in status.audit(declared, host, (digests or {}).get)]


def test_audit_reports_undeclared_missing_down_and_unexpected_units():
    declared = {'rosy-a.service': {'run': 'active', 'channel': 'host', 'doc': 'x'},
                'rosy-b.timer': {'run': 'timer', 'channel': 'host', 'doc': 'x'},
                'rosy-c.service': {'run': 'off', 'channel': 'retired', 'doc': 'x'},
                'rosy-d.service': {'run': 'oneshot', 'channel': 'host', 'doc': 'x'}}
    host = observed(rosy_a_service={'active': 'failed'}, rosy_b_timer={'enabled': 'disabled'},
                    rosy_c_service={}, rosy_z_service={})
    host['files'] = {k.replace('-service', '.service').replace('-timer', '.timer'): v for k, v in host['files'].items()}
    assert sorted(findings(declared, host)) == sorted([
        ('UNDECLARED', 'rosy-z.service'), ('DOWN', 'rosy-a.service'), ('DOWN', 'rosy-b.timer'),
        ('UNEXPECTED', 'rosy-c.service'), ('MISSING', 'rosy-d.service')])


def test_audit_reports_drift_in_unit_copies_dropins_and_code_path_unless_known():
    entry = {'run': 'active', 'channel': 'snapshot', 'doc': 'x', 'template': 'deploy/u.service', 'instances': ['a'],
             'copies': {'bin/tool.py': 'deploy/tool.py'}, 'dropins': ['ok.conf'],
             'source': '.local/share/rosy/x/releases/*'}
    host = dict(files={'rosy-x@.service': dict(enabled='indirect', active='template', sha256='old', dropins=[])},
                instances={'rosy-x@a.service': dict(active='active', dropins=['ok.conf', 'extra.conf'])},
                copies={'bin/tool.py': 'stale'}, paths={'rosy-x@a.service': '/home/u/rosy-test/x'})
    digests = {'deploy/u.service': 'new', 'deploy/tool.py': 'fresh'}
    assert findings({'rosy-x@.service': entry}, host, digests) == [('DRIFT', 'rosy-x@.service')] * 2 + [
        ('DRIFT', 'rosy-x@a.service')] * 2
    known = dict(entry, known_drift='waiting for the checkout move')
    assert {v for v, _ in findings({'rosy-x@.service': known}, host, digests)} == {'KNOWN'}
    host['paths']['rosy-x@a.service'] = '/home/u/.local/share/rosy/x/releases/abc'
    host['copies']['bin/tool.py'], host['files']['rosy-x@.service']['sha256'] = 'fresh', 'new'
    host['instances']['rosy-x@a.service']['dropins'] = ['ok.conf']
    assert findings({'rosy-x@.service': entry}, host, digests) == []
