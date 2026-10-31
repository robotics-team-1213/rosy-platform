"""Placement must respect ADMIT's host-wide exclusive jobs and waiting priority."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'remote'))
import host_probe
import remote_pytest as runner

pytestmark = pytest.mark.skipif(os.name != 'posix' or not shutil.which('bash'),
                                reason='the actual PROBE shell requires POSIX bash')


def measured(tmp_path, marker=None, live=True):
    jobs = tmp_path / 'rosy-jobs'
    jobs.mkdir(parents=True)
    pid = 4242 if live else 4243
    if marker == 'wait':
        (jobs / 'fixture.alone-wait').write_text(f'{pid}\n')
    elif marker:
        (jobs / 'fixture.lock').write_text(f'{pid} {marker} 2 3\n')
    # Liveness is confined to this shell fixture; no signal or real job marker is used.
    script = 'kill() { [ "$1" = -0 ] && [ "$2" = 4242 ]; }\n' + host_probe.PROBE
    script = script.replace('J=~/rosy-jobs', f'J={shlex.quote(str(jobs))}')
    script = script.replace('/usr/bin/python3', shlex.quote(sys.executable))
    result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, check=True,
                            env={**os.environ, 'HOME': str(tmp_path)})
    probe = host_probe.parse_probe(result.stdout)
    assert probe is not None
    # Give placement fixed ample hardware capacity, independently of the test PC's load.
    probe.update(nproc=24, load1=0, avail_gb=32, total_gb=32, sim=True,
                 disk_free_gb=100, disk_use=1)
    return probe, jobs


@pytest.mark.parametrize('marker,live,blocked', [
    ('alone', True, True), ('wait', True, True),
    ('alone', False, False), ('wait', False, False),
    ('pytest', True, False), ('browser', True, False), ('sim', True, False),
    (None, True, False),
])
def test_probe_places_pytest_only_when_admit_allows_nonexclusive_work(tmp_path, marker, live, blocked):
    probe, jobs = measured(tmp_path, marker, live)
    assert probe['pytest'] is True, 'exclusive admission must not erase Python capability'
    chosen, notes = runner.place('pytest', ['fixture'], [probe])
    assert chosen == ([] if blocked else ['fixture']), notes
    if blocked:
        assert 'alone' in notes[0].lower() and 'floor' not in notes[0].lower()
    # Exclusive pytest admission must not change SIM capability or its existing policy.
    assert runner.place('sim', ['fixture'], [probe])[0] == ['fixture']
    if marker == 'wait':
        assert (jobs / 'fixture.alone-wait').exists(), 'PROBE must not broaden waiter pruning'


@pytest.mark.parametrize('marker', ['alone', 'wait'])
def test_exclusive_host_never_reenters_through_pytest_floor_fallback(tmp_path, monkeypatch, marker):
    probe, _ = measured(tmp_path, marker)
    monkeypatch.setattr(runner, 'probe', lambda host: probe)
    monkeypatch.setattr(runner, 'SITES', set())
    assert runner.placed_hosts('pytest', hosts=['fixture']) == []


def test_idle_alternative_wins_over_more_free_capacity_on_exclusive_host(tmp_path):
    blocked, _ = measured(tmp_path / 'blocked', 'alone')
    available, _ = measured(tmp_path / 'available')
    available.update(nproc=12, avail_gb=12, total_gb=16)
    chosen, _ = runner.place('pytest', ['blocked', 'available'], [blocked, available])
    assert chosen == ['available']


@pytest.mark.parametrize('python,capable', [('0', False), ('1', True)])
def test_legacy_probe_python_capability_does_not_imply_exclusive_admission(python, capable):
    probe = host_probe.parse_probe(f'ROSYPROBE 8 0 16777216 33554432 {python} 1 0 0 0 0 0 0')
    assert probe['pytest'] is capable
    assert probe['sim'] is True
    assert probe.get('pytest_blocked') is False
