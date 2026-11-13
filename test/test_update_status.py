"""update_status flags a channel that has stopped being healthy, not one that is briefly waiting."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_status', ROOT / 'tools/remote/update_status.py')
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)

NOW = 1_000_000.0
DAY = 86400


def git_repo(path, files):
    path.mkdir(parents=True, exist_ok=True)

    def git(*args):
        subprocess.run(['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                       check=True, capture_output=True)
    git('init', '-q')
    for name, data in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(data)
    git('add', '-A')
    git('commit', '-q', '-m', 'base')
    return git


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
    assert set(roles) == {'model', 'ai', 'site', 'omx'}
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
        'm@h': {'model'}, 'a@h': {'ai'}, 'site@h': {'site', 'omx'}}


def test_separate_control_hosts_are_probed_without_test_or_sim_enrollment():
    config = {'site_host': 'site@h', 'test_hosts': ['m@h', '  '], 'omx_hosts': ['arm@h', 'arm2@h']}
    assert status.roles(config) == {'site@h': {'site'}, 'arm@h': {'omx'}, 'arm2@h': {'omx'}}
    assert status.probe_targets(config) == ['m@h', 'site@h', 'arm@h', 'arm2@h']


@pytest.mark.parametrize('explicit, expected', [([], {'site'}), (['site@h'], {'site', 'omx'})])
def test_explicit_empty_or_colocated_omx_roles(explicit, expected):
    config = {'site_host': 'site@h', 'omx_hosts': explicit}
    assert status.roles(config) == {'site@h': expected}
    assert status.probe_targets(config) == ['site@h']


@pytest.mark.parametrize('config', [
    {'sim_hosts': ['a@h=unknown']}, {'sim_hosts': ['a@h=model', 'a@h=ai']},
    {'site_host': 'a@h', 'sim_hosts': ['a@h=ai']},
    {'sim_hosts': ['a@h=ai'], 'omx_hosts': ['a@h']},
    {'sim_hosts': 'a@h=ai'}, {'sim_hosts': [{}]},
    {'site_host': {}}, {'site_host': 'site@h extra'},
])
def test_ambiguous_or_malformed_roles_fail_closed(config):
    with pytest.raises(SystemExit):
        status.roles(config)


def test_service_role_composition_preserves_every_unit_and_rejects_conflicts():
    inventory = status.load_inventory()
    assert status.declared_units(inventory, {'site', 'omx'}) == {**inventory['site'], **inventory['omx']}
    with pytest.raises(SystemExit, match='conflict'):
        status.declared_units({'site': {'x': {'run': 'off'}}, 'omx': {'x': {'run': 'active'}}}, {'site', 'omx'})


def test_status_main_collects_an_independent_production_host(monkeypatch):
    config = {'site_host': 'site@h', 'omx_hosts': ['arm@h']}
    monkeypatch.setattr(status.lab_hosts, 'load', lambda: config)
    monkeypatch.setattr(status, 'load_inventory', lambda: {'site': {}, 'omx': {}})
    monkeypatch.setattr(status, 'ref_state', lambda *args: dict(
        ref='HEAD', verdict='ok', tip='a'*12, fetched_h=0, problem=None))
    monkeypatch.setattr(status, 'robot_cd_root', lambda: None)
    monkeypatch.setattr(status.sys, 'argv', ['update_status.py'])
    targets = []
    def run(argv, **kwargs):
        targets.append(argv[-2])
        return subprocess.CompletedProcess(argv, 0, stdout=b'gate open\n', stderr=b'')
    monkeypatch.setattr(status.subprocess, 'run', run)
    with pytest.raises(SystemExit) as ended:
        status.main()
    assert ended.value.code == 0
    assert targets == ['site@h', 'arm@h']


def test_images_outside_the_role_or_piling_up_are_reported():
    host = status.parse('\n'.join(['image rosy-site-fleet aaa', 'image rosy-site-fleet bbb', 'image <none> <none>',
                                   'image rosy-rollback-fleet workcell', 'image rosy-site-vision a',
                                   'image rosy-site-vision b', 'image rosy-site-vision c', 'image rosy-site-vision d']),
                        NOW, 6.0)
    found = status.audit_images({'rosy-site-fleet', 'rosy-site-vision'}, host)
    assert [(verdict, repository) for verdict, repository, _ in found] == [
        ('UNDECLARED', 'rosy-rollback-fleet'), ('DRIFT', 'rosy-site-vision')]


def test_manifest_declares_images_per_role_and_a_host_with_no_docker_passes():
    assert 'rosy-site-fleet' in status.declared_images({'site', 'omx'})
    assert 'rosy-site-fleet' not in status.declared_images({'model'})
    assert status.audit_images(set(), status.parse('gate open', NOW, 6.0)) == []


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


def test_ref_state_names_the_ref_and_ages_the_last_fetch_not_the_tip_commit(tmp_path):
    git = git_repo(tmp_path, {'a.txt': b'a'})
    state = status.ref_state(tmp_path, time.time(), 12)
    assert (state['ref'], state['verdict']) == ('HEAD', 'STALE-REF')
    git('update-ref', 'refs/remotes/origin/main', 'HEAD')
    reflog = tmp_path / '.git/logs/refs/remotes/origin/main'
    now = time.time()
    state = status.ref_state(tmp_path, now, 12)
    assert (state['ref'], state['verdict']) == ('origin/main', 'ok') and state['fetched_h'] < 1
    os.utime(reflog, (now - 20 * 3600, now - 20 * 3600))
    state = status.ref_state(tmp_path, now, 12)
    assert state['verdict'] == 'STALE-REF' and state['fetched_h'] == 20.0
    (tmp_path / '.git/FETCH_HEAD').write_text('')  # a later fetch that did not move origin/main
    assert status.ref_state(tmp_path, now, 12)['verdict'] == 'ok'
    assert status.ref_state(tmp_path / 'absent', now, 12)['verdict'] == 'STALE-REF'


def test_repo_digest_reads_only_the_named_ref(tmp_path):
    git = git_repo(tmp_path, {'f': b'old\r\n'})
    git('update-ref', 'refs/remotes/origin/main', 'HEAD')
    (tmp_path / 'f').write_bytes(b'new')
    (tmp_path / 'g').write_bytes(b'g')
    git('add', '-A')
    git('commit', '-q', '-m', 'unpublished')
    assert status.repo_digest('f', tmp_path, tmp_path) == hashlib.sha256(b'old\n').hexdigest()
    assert status.repo_digest('g', tmp_path, tmp_path) is None
    assert status.repo_digest('g', tmp_path, tmp_path, {tmp_path: 'HEAD'}) == hashlib.sha256(b'g').hexdigest()


def test_the_cam_stream_runs_the_auto_updated_code_with_its_private_config_left_in_place():
    unit = (ROOT / 'deploy/site/rosy-cam-stream.service').read_text(encoding='utf-8')
    start = next(line for line in unit.splitlines() if line.startswith('ExecStart='))
    assert '%h/.local/share/rosy/site-tools/current/deploy/site/rosy_cam_screen.py stream-start' in start
    assert '--config %h/.local/share/rosy/cam-screen/cam-screen.json' in start


@pytest.mark.parametrize('count', [1, 2, 3])
def test_selected_arms_replace_fixed_instances_and_ignore_extra_connected_devices(count):
    template = 'rosy-omx-observer@.service'
    host = observed()
    host['files'][template] = dict(enabled='enabled', active='template', sha256='x', dropins=[])
    host['topology'] = {'arms': {f'selected_{i}': {'configured': True, 'connected': True} for i in range(count)}}
    host['instances'] = {f'rosy-omx-observer@selected_{i}.service': dict(active='active', dropins=[]) for i in range(count)}
    declaration = {template: dict(run='active', channel='autoupdate', instances=['old_a', 'old_b'], instances_from='workcell-arms')}
    assert findings(declaration, host) == []
    host['instances']['rosy-omx-observer@connected_but_unselected.service'] = dict(active='active', dropins=[])
    assert findings(declaration, host) == [('UNEXPECTED', 'rosy-omx-observer@connected_but_unselected.service')]


def test_selected_arms_distinguish_disconnection_stopped_service_and_missing_config():
    template = 'rosy-omx-observer@.service'
    host = observed()
    host['files'][template] = dict(enabled='enabled', active='template', sha256='x', dropins=[])
    declaration = {template: dict(run='active', channel='autoupdate', instances_from='workcell-arms')}
    host['topology'] = {'arms': {'chosen': {'configured': True, 'connected': False}}}
    assert findings(declaration, host) == [('DISCONNECTED', 'rosy-omx-observer@chosen.service')]
    host['topology']['arms']['chosen']['connected'] = True
    assert findings(declaration, host) == [('DOWN', 'rosy-omx-observer@chosen.service')]
    host['topology'] = {'error': 'workcell selection unavailable'}
    assert findings(declaration, host) == [('CONFIGURATION', template)]


def test_observer_manifest_uses_selected_workcell_arms_without_a_fixed_count():
    entry = status.load_inventory()['omx']['rosy-omx-observer@.service']
    assert entry.get('instances_from') == 'workcell-arms'
    assert 'instances' not in entry


def test_chrony_with_no_usable_source_and_unresolved_names_fail_or_note():
    host = status.parse('chrony 0 2 pool.vanished,ntp.gone', NOW, 6.0)
    assert host['chrony'] == dict(usable=0, total=2, unresolved=['pool.vanished', 'ntp.gone'])
    assert [f[0] for f in status.clock_and_site(host, NOW)] == ['FAIL', 'note']
    assert status.clock_and_site(status.parse('chrony 1 3 -', NOW, 6.0), NOW) == []
    assert status.clock_and_site(status.parse('gate open', NOW, 6.0), NOW) == []  # no chrony report, no verdict


def _site(state):
    return status.clock_and_site(status.parse('sitestate ' + json.dumps(state), NOW, 6.0), NOW)


def test_site_hold_expiry_and_refused_last_run_are_reported():
    iso = lambda hours: datetime.fromtimestamp(NOW + hours * 3600, timezone.utc).isoformat()
    assert _site({'hold': {'reason': 'r', 'time': iso(-1), 'until': iso(23)}})[0][0] == 'HELD'
    expired = _site({'hold': {'reason': 'R migration', 'time': iso(-96), 'until': iso(-72)}})
    assert expired[0][0] == 'FAIL' and 'EXPIRED' in expired[0][2] and 'R migration' in expired[0][2]
    assert _site({'hold': {'reason': 'old', 'time': iso(-30)}})[0][0] == 'FAIL'  # legacy: set time + 24 h
    assert _site({'hold': {'reason': 'old', 'time': iso(-2)}})[0][0] == 'HELD'
    refused = _site({'last_run': {'result': 'refused', 'reason': 'fleet loaded image ID mismatch'}})
    assert refused[0][0] == 'FAIL' and 'image ID mismatch' in refused[0][2]
    assert _site({'last_run': {'result': 'idle'}}) == []


def test_retired_host_name_in_a_config_file_fails_with_the_path_only():
    host = status.parse('retired /etc/chrony/chrony.conf\nretired /home/r/.config/rosy/cal/receiver.json', NOW, 6.0)
    found = [f for f in status.clock_and_site(host, NOW) if f[1] == 'retired-name']
    assert [f[0] for f in found] == ['FAIL', 'FAIL'] and '/etc/chrony/chrony.conf' in found[0][2]
    assert not [f for f in status.clock_and_site(status.parse('gate open', NOW, 6.0), NOW) if f[1] == 'retired-name']


def test_retired_hostnames_list_the_vanished_tailnet_name_not_the_live_mdns_name():
    names = [n.lower() for n in status.retired_hostnames()]
    assert 'robttt-15z95n-gp7ql.tailb4b84d.ts.net' in names
    assert not [n for n in names if n.endswith('.local')]


def test_retired_name_probe_is_valid_bash_and_skips_backup_files():
    import subprocess
    assert subprocess.run(['bash', '-n'], input=status.PROBE.encode()).returncode == 0
    assert '*rosy-source-repair*' in status.PROBE and '*before-*' in status.PROBE


def test_failed_account_login_check_unit_fails_the_host():
    host = status.parse('failed rosy-site-account-login-check.service', NOW, 6.0)
    assert [f[:2] for f in status.clock_and_site(host, NOW)] == [('FAIL', 'account-login-check')]
    assert status.clock_and_site(status.parse('failed rosy-other.service', NOW, 6.0), NOW) == []


def _retired_scan(tmp_path, retired, *, sudo_works=False):
    """Run the probe's retired-name block alone against a fake HOME."""
    start, end = status.PROBE.index('# retired host names'), status.PROBE.index('D=docker')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / 'sudo').write_text('#!/bin/sh\nexit 1\n')
    (bin_dir / 'sudo').chmod(0o755)
    env = {**os.environ, 'HOME': str(tmp_path / 'home'), 'PATH': f'{bin_dir}:{os.environ["PATH"]}'}
    done = subprocess.run(['bash', '-c', f'RETIRED={retired!r}\n' + status.PROBE[start:end]],
                          capture_output=True, text=True, env=env, timeout=60)
    return [line for line in done.stdout.splitlines() if str(tmp_path) in line]


pytestmark_posix = pytest.mark.skipif(os.name == 'nt', reason='needs bash and POSIX modes')


@pytestmark_posix
def test_empty_retired_list_matches_nothing(tmp_path):
    receiver = tmp_path / 'home/.config/rosy/cal/receiver.json'
    receiver.parent.mkdir(parents=True)
    receiver.write_text('{"issuer": "https://anything.example.test"}')
    assert _retired_scan(tmp_path, '') == []
    assert _retired_scan(tmp_path, 'old-host.example.test') == []
    receiver.write_text('{"issuer": "https://OLD-HOST.example.test"}')
    assert _retired_scan(tmp_path, 'old-host.example.test') == [f'retired {receiver}']


@pytestmark_posix
def test_retired_scan_skips_symlinked_receivers_and_reports_unreadable_ones(tmp_path):
    base = tmp_path / 'home/.config/rosy'
    (base / 'a').mkdir(parents=True)
    real = tmp_path / 'real.json'
    real.write_text('old-host.example.test')
    (base / 'a/receiver.json').symlink_to(real)
    assert _retired_scan(tmp_path, 'old-host.example.test') == []
    (base / 'a/receiver.json').unlink()
    if os.getuid() != 0:
        locked = base / 'a/receiver.json'
        locked.write_text('old-host.example.test')
        locked.chmod(0)
        assert _retired_scan(tmp_path, 'old-host.example.test') == [f'retired-unreadable {locked}']


def test_probe_guards_the_retired_scan_and_names_missing_or_unreadable_site_state():
    assert 'if [ -n "$RETIRED" ]' in status.PROBE and 'set -f' in status.PROBE
    assert '-type f' in status.PROBE and '[ -L "$f" ] && continue' in status.PROBE
    assert 'sitestate missing' in status.PROBE and 'sitestate unreadable' in status.PROBE
    import subprocess
    assert subprocess.run(['bash', '-n'], input=status.PROBE.encode()).returncode == 0


def test_unreadable_retired_path_is_a_note_never_clean():
    found = status.clock_and_site(status.parse('retired-unreadable /etc/hosts', NOW, 6.0), NOW)
    assert found == [('note', 'retired-name', '/etc/hosts exists but could not be read; not checked')]


def test_retired_hostnames_must_be_full_hostnames(tmp_path):
    def load(*names):
        path = tmp_path / 'services.yaml'
        path.write_text('retired_hostnames:\n' + ''.join(f'  - {n}\n' for n in names))
        return status.retired_hostnames(path)
    assert load('old-host.example.test') == ['old-host.example.test']
    for bad in ('short', 'a.b', 'nodotbutlonghostname'):
        with pytest.raises(SystemExit):
            load('old-host.example.test', bad)


def test_malformed_probe_lines_become_findings_instead_of_raising():
    for line in ('chrony x y z', 'chrony 1', 'chrony 1 2.5 -'):
        found = status.clock_and_site(status.parse(line, NOW, 6.0), NOW)
        assert [f[:2] for f in found] == [('FAIL', 'chrony')], line
    for state in ('[]', '5', '"text"', 'null'):
        found = status.clock_and_site(status.parse('sitestate ' + state, NOW, 6.0), NOW)
        assert [f[:2] for f in found] == [('FAIL', 'site-autoupdate')], state
    for state in ({'hold': 'text'}, {'hold': ['x']}, {'last_run': 'text'}, {'last_run': [1]}):
        found = _site(state)
        assert [f[:2] for f in found] == [('FAIL', 'site-autoupdate')], state


def test_missing_site_state_is_a_note_on_a_site_host_and_unreadable_is_a_failure():
    missing = status.parse('sitestate missing', NOW, 6.0)
    assert [f[:2] for f in status.clock_and_site(missing, NOW, {'site'})] == [('note', 'site-autoupdate')]
    assert status.clock_and_site(missing, NOW, {'omx'}) == []
    assert status.clock_and_site(missing, NOW) == []
    unreadable = status.parse('sitestate unreadable', NOW, 6.0)
    assert [f[:2] for f in status.clock_and_site(unreadable, NOW, {'site'})] == [('FAIL', 'site-autoupdate')]
    assert [f[:2] for f in status.clock_and_site(status.parse('sitestate {bad', NOW, 6.0), NOW, {'site'})] == [('FAIL', 'site-autoupdate')]


def test_hold_until_rules_match_the_site_updater():
    naive = lambda hours: datetime.fromtimestamp(NOW + hours * 3600, timezone.utc).replace(tzinfo=None).isoformat()
    aware = lambda hours: datetime.fromtimestamp(NOW + hours * 3600, timezone.utc).isoformat()
    for until in (naive(23), 'garbage', 5, None, ''):
        found = _site({'hold': {'reason': 'r', 'time': aware(-1), 'until': until}})
        assert found[0][0] == 'FAIL' and 'EXPIRED' in found[0][2], until
    assert _site({'hold': {'reason': 'r', 'time': naive(-1)}})[0][0] == 'FAIL'  # naive set time: expired
    assert _site({'hold': {'reason': 'r', 'time': aware(-1)}})[0][0] == 'HELD'  # no until key: set time + 24 h
    epoch = _site({'hold': {'reason': 'r', 'time': '1970-01-01T00:00:00+00:00', 'until': aware(23)}})
    assert epoch[0][0] == 'HELD' and 'unknown age' not in epoch[0][2]
