"""D-185 R8: the device hot-path measurement tool must parse /proc and report honestly.

The tool runs on the Pinky Pro Raspberry Pi, where these numbers are still HOLD.
Host tests cover the pure parts only: /proc parsing, CPU% arithmetic, process
matching against a fake /proc tree, the report schema and a tiny bench smoke.
A host run is never device evidence, and the report must say so.
"""
import json
import re

import pytest

from tools.device import hotpath_measure as hm

# Real /proc/<pid>/stat shape; the comm field holds a space and a ')' on purpose.
STAT = ('4242 (python3 a) b) S 1 4242 4242 0 -1 4194560 1234 0 0 0 '
        '350 150 0 0 20 0 3 0 98765 123456789 4321 18446744073709551615 '
        '1 1 0 0 0 0 0 16781312 16386 0 0 0 17 2 0 0 0 0 0')


def test_stat_parsing_reads_ticks_after_the_last_paren():
    stat = hm.parse_stat(STAT)
    assert stat == {'state': 'S', 'utime': 350, 'stime': 150, 'starttime': 98765}


def test_stat_parsing_rejects_garbage():
    with pytest.raises(ValueError):
        hm.parse_stat('not a stat line')


def test_cpu_percent_from_two_samples():
    prev = {'utime': 100, 'stime': 50}
    cur = {'utime': 250, 'stime': 100}
    # 200 ticks at 100 Hz over 2 s is one full core.
    assert hm.cpu_percent(prev, cur, 2., clk_tck=100) == pytest.approx(100.)
    assert hm.cpu_percent(prev, prev, 2., clk_tck=100) == 0.
    assert hm.cpu_percent(prev, cur, 0., clk_tck=100) is None


def test_psi_and_loadavg_parsing():
    psi = ('some avg10=3.25 avg60=1.10 avg300=0.40 total=123456\n'
           'full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')
    assert hm.parse_psi(psi) == 3.25
    assert hm.parse_psi('') is None
    assert hm.parse_psi('full avg10=1.0 avg60=0 avg300=0 total=0\n') is None
    assert hm.parse_loadavg('1.50 0.75 0.25 2/345 6789\n') == [1.5, .75, .25]


def test_rss_from_status():
    assert hm.parse_rss_kb('Name:\tpython3\nVmRSS:\t   52344 kB\nThreads:\t5\n') == 52344
    assert hm.parse_rss_kb('Name:\tkthreadd\n') is None


def fake_proc(tmp_path, procs):
    """procs: {pid: argv list}; each gets a cmdline, a stat and a status file."""
    for pid, argv in procs.items():
        entry = tmp_path / str(pid)
        entry.mkdir()
        (entry / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in argv) + b'\0')
        (entry / 'stat').write_text(STAT.replace('4242 (', f'{pid} (', 1))
        (entry / 'status').write_text('VmRSS:\t  1000 kB\n')
    (tmp_path / 'self').mkdir()  # non-numeric entries are skipped
    return tmp_path


def test_process_matching_by_entry_point_and_module(tmp_path):
    proc = fake_proc(tmp_path, {
        10: ['/usr/bin/python3', '/opt/rosy/install/control/lib/control/safety_node', '--ros-args'],
        11: ['/opt/rosy/install/control/lib/control/startup_calibration_node'],
        12: ['python3', '-m', 'control.goal_node'],
        13: ['/usr/bin/python3', '/opt/rosy/lib/control/web_node'],
        14: ['grep', 'safety_node'],  # a search for a node is not the node
        15: ['/usr/bin/python3', '/opt/rosy/lib/other/wander_node_helper'],
        16: [],  # kernel thread: empty cmdline
    })
    assert hm.find_processes(proc) == {
        10: 'safety_node', 11: 'startup_calibration_node', 12: 'goal_node', 13: 'web_node'}
    assert hm.find_processes(proc, names=('goal_node',)) == {12: 'goal_node'}


def test_node_names_match_the_installed_entry_points():
    setup = (hm.PKG / 'setup.py').read_text(encoding='utf-8')
    # Both ways: a node added to setup.py without NODE_NAMES would silently go unwatched.
    assert set(re.findall(r"'(\w+) = control\.\w+:main'", setup)) == set(hm.NODE_NAMES)


def test_watch_samples_fake_proc(tmp_path):
    proc = fake_proc(tmp_path, {20: ['/opt/rosy/lib/control/wander_node']})
    (tmp_path / 'loadavg').write_text('0.50 0.40 0.30 1/100 20\n')
    (tmp_path / 'pressure').mkdir()
    (tmp_path / 'pressure' / 'cpu').write_text('some avg10=1.50 avg60=0 avg300=0 total=1\n')
    ticks = iter(range(0, 1000, 50))

    def advance(_seconds):
        stat = proc / '20' / 'stat'
        stat.write_text(stat.read_text().replace(' 350 150 ', f' {350+next(ticks)} 150 ', 1))

    clock = iter(float(t) for t in range(0, 100, 2))
    samples = hm.watch(duration_s=4., interval_s=2., proc_root=proc,
                       sleep=advance, clock=lambda: next(clock), clk_tck=100)
    assert len(samples) == 2
    first = samples[0]
    assert first['load1'] == .5 and first['psi_some_avg10'] == 1.5
    assert first['processes'][0]['name'] == 'wander_node'
    assert first['processes'][0]['rss_kb'] == 1000
    assert first['processes'][0]['cpu_percent'] == pytest.approx(0.)  # +0 ticks in the first interval
    assert samples[1]['processes'][0]['cpu_percent'] == pytest.approx(25.)  # +50 ticks over 2 s


def test_report_schema_and_evidence_class(tmp_path):
    report = hm.build_report('bench', {'x': 1}, proc_root=tmp_path)
    assert report['schema_version'] == hm.SCHEMA_VERSION == 'rosy.control.hotpath_measure/1'
    assert set(report) >= {'schema_version', 'kind', 'created_utc', 'evidence', 'environment', 'bench'}
    env = report['environment']
    assert set(env) >= {'platform', 'machine', 'python', 'numpy', 'cpu_model', 'device_model'}
    # No device-tree model: never device evidence.
    assert report['evidence']['device'] is False
    assert 'not device evidence' in report['evidence']['statement']
    assert 'one full core' in report['units']['cpu_percent']
    json.dumps(report)

    (tmp_path / 'device-tree').mkdir()
    (tmp_path / 'device-tree' / 'model').write_bytes(b'Raspberry Pi 5 Model B Rev 1.0\0')
    (tmp_path / 'cpuinfo').write_text('processor\t: 0\nmodel name\t: Cortex-A76\n')
    report = hm.build_report('watch', [], proc_root=tmp_path)
    assert report['evidence']['device'] is True
    assert report['environment']['device_model'] == 'Raspberry Pi 5 Model B Rev 1.0'
    assert report['environment']['cpu_model'] == 'Cortex-A76'
    assert 'watch' in report


def test_summary_statistics():
    assert hm.summarize([3., 1., 2., 10.]) == {'n': 4, 'median_ms': 2.5, 'p90_ms': 10., 'max_ms': 10.}


def test_bench_smoke_returns_the_three_hot_paths():
    result = hm.bench(iterations=2, warmup=0)
    assert set(result) == {'wall_tracker_segments', 'scan_motion_match_motion', 'gridmap_inflate'}
    for row in result.values():
        assert row['n'] == 2 and row['max_ms'] >= row['median_ms'] >= 0.
        assert row['input']
    # Each synthetic input must take the real code path, not an early return.
    assert result['scan_motion_match_motion']['accepted'] is True
    assert result['wall_tracker_segments']['segments'] > 0
    assert result['gridmap_inflate']['grown'] is True
