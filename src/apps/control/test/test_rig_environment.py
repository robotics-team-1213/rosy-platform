"""D-185 R4: a rig run on an overloaded box is environment-invalid, never code evidence.

2026-09-23/24: peer Gazebo sessions pushed the 8-core WSL box to load 25-30. Idle nodes
then waited ~340 ms for the CPU, and one run's simulation ran at 0.01x. Such runs
failed or passed for reasons unrelated to the code under test. The guard must never
turn a real failure into "environment" either (review 2026-09-24): without rate
evidence it leaves the pass/fail verdict alone.
"""
import json
from pathlib import Path

from tools.gz import rig_environment
from tools.gz.rig_environment import judge, judge_run, sample
from tools.gz.run_calibration_spaces import outcome

ROOT = Path(__file__).resolve().parents[1]


def samples(loads, foreign=0, own=1, step=10.):
    return [{'wall_s': 100.+step*i, 'load1': load, 'foreign_gz': foreign, 'own_gz': own}
            for i, load in enumerate(loads)]


def test_quiet_box_and_normal_speed_is_valid():
    verdict = judge(samples([6., 9., 12.]), elapsed_sim_s=60., wall_s=150.)
    assert verdict['valid'] is True and verdict['reasons'] == []
    assert verdict['rtf'] == .4 and verdict['rtf_ratio'] == .4


def test_first_minute_of_load_is_ignored_when_later_samples_exist():
    # load1 is a 1-minute average: its first minute still carries the previous run.
    verdict = judge(samples([30.]*6+[8.]*6), elapsed_sim_s=60., wall_s=150.)
    assert verdict['valid'] is True and verdict['mean_load'] == 8.


def test_mean_load_at_or_over_the_limit_is_invalid():
    verdict = judge(samples([14., 18., 16.], step=40.), elapsed_sim_s=60., wall_s=150.)
    assert verdict['valid'] is False and verdict['reasons'] == ['mean load 16.0 >= 16.0']  # too few settled samples: all count


def test_the_share_of_overloaded_samples_is_reported_not_judged():
    # 2026-09-24: a solo run with no foreign Gazebo still spent 29% of samples at load >= 16;
    # load is an indirect signal, so only its mean judges until PSI thresholds are calibrated.
    verdict = judge(samples([30.]*6+[4.]*8, step=40.), elapsed_sim_s=60., wall_s=150.)  # 4/12 settled over
    assert verdict['valid'] is True and verdict['over_fraction'] == .333


def test_cpu_pressure_is_reported():
    rows = samples([8.]*8, step=20.)  # the first minute (3 samples) is warm-up
    for row, psi in zip(rows, (50., 50., 10., 20., 30., 40., 50., 60.)):
        row['psi_some_avg10'] = psi
    verdict = judge(rows, elapsed_sim_s=60., wall_s=150.)
    assert verdict['valid'] is True and verdict['psi_mean'] == 40. and verdict['psi_max'] == 60.


def test_a_stalled_simulation_is_invalid_relative_to_the_requested_rate():
    assert judge(samples([8.]), elapsed_sim_s=12., wall_s=605.)['reasons'] == ['real-time factor 0.02 < 0.1 of requested 1.0']
    slow = judge(samples([8.]), elapsed_sim_s=30., wall_s=1000., requested_rtf=.2)
    assert slow['rtf_ratio'] == .15 and slow['valid'] is True


def test_no_rate_evidence_never_invalidates_a_run():
    # A missing result, a broken /clock or an early real failure stays a pass/fail matter.
    for elapsed, wall in ((None, 150.), (0., 150.), (2., 25.), (60., None)):
        verdict = judge(samples([8.]), elapsed_sim_s=elapsed, wall_s=wall)
        assert verdict['valid'] is True and verdict['rtf'] is None, (elapsed, wall)


def test_a_second_gazebo_in_our_partition_is_invalid():
    verdict = judge(samples([8.], own=2), elapsed_sim_s=60., wall_s=150.)
    assert verdict['reasons'] == ['2 Gazebo sessions in partition pinky_calmap227']


def test_limits_are_configurable_and_foreign_gazebo_is_only_reported():
    verdict = judge(samples([20., 20.], foreign=2, step=40.), elapsed_sim_s=60., wall_s=150., max_mean_load=24.)
    assert verdict['valid'] is True and verdict['foreign_gz_max'] == 2


def test_missing_load_evidence_is_invalid_not_silently_valid():
    assert judge([], elapsed_sim_s=60., wall_s=150.)['reasons'] == ['no load samples']


def test_judge_run_uses_the_monitor_wall_time_and_tolerates_a_torn_line(tmp_path, monkeypatch):
    lines = [json.dumps(s) for s in samples([6., 7., 8.])]
    (tmp_path/'environment_samples.jsonl').write_text('\n'.join(lines)+'\n{"wall_s": 13')
    (tmp_path/'track_result.json').write_text(json.dumps({'elapsed_sim_s': 60., 'elapsed_wall_s': 100.}))
    monkeypatch.setenv('RIG_REALTIME_FACTOR', '1.0')
    verdict = judge_run(tmp_path)
    assert verdict['valid'] is True and verdict['rtf'] == .6
    assert json.loads((tmp_path/'environment.json').read_text()) == verdict


def test_judge_run_without_a_result_leaves_the_verdict_to_pass_fail(tmp_path):
    (tmp_path/'environment_samples.jsonl').write_text(json.dumps(samples([6.])[0])+'\n')
    assert judge_run(tmp_path)['valid'] is True


def test_limits_come_from_the_environment(tmp_path, monkeypatch):
    (tmp_path/'environment_samples.jsonl').write_text(json.dumps(samples([10.])[0])+'\n')
    monkeypatch.setenv('RIG_MAX_MEAN_LOAD', '8')
    assert judge_run(tmp_path)['reasons'] == ['mean load 10.0 >= 8.0']


def fake_process(proc, pid, argv, environ=None, sid=None):
    folder = proc/str(pid)
    folder.mkdir(parents=True)
    (folder/'cmdline').write_bytes(b'\0'.join(a.encode() for a in argv)+b'\0')
    if environ is not None:
        (folder/'environ').write_bytes(b'\0'.join(e.encode() for e in environ)+b'\0')
    (folder/'stat').write_text(f'{pid} (x) S 1 1 {sid or pid} 0 0')


def test_sample_counts_gazebo_sessions_by_partition(tmp_path):
    proc = tmp_path/'proc'
    fake_process(proc, 10, ['ruby', '/usr/bin/gz', 'sim', '-s'], ['GZ_PARTITION=pinky_calmap227'], sid=10)
    fake_process(proc, 11, ['ruby', '/usr/bin/gz', 'sim', '-r', 'world.sdf'], ['GZ_PARTITION=fleet57'], sid=11)
    fake_process(proc, 12, ['ruby', '/usr/bin/gz', 'sim', '-g'], ['GZ_PARTITION=fleet57'], sid=11)  # GUI fork, same session
    fake_process(proc, 13, ['gz', 'sim', '-s'], ['GZ_PARTITION=pinky_calmap2270'], sid=13)  # prefix is another partition
    fake_process(proc, 14, ['pgrep', '-f', 'gz sim'], [], sid=14)  # a search, not a server
    fake_process(proc, 15, ['ruby', '/usr/bin/gz', 'sim'], None, sid=15)  # environ unreadable: unknown, so foreign
    fake_process(proc, 16, [], [], sid=16)  # zombie
    (tmp_path/'loadavg').write_text('16.13 12.00 9.00 3/900 1234\n')
    (tmp_path/'cpu').write_text('some avg10=2.96 avg60=18.43 avg300=25.37 total=9176039654\n'
                                'full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')
    row = sample(proc_root=proc, loadavg=tmp_path/'loadavg', pressure=tmp_path/'cpu')
    assert row['load1'] == 16.13 and row['own_gz'] == 1 and row['foreign_gz'] == 3
    assert row['psi_some_avg10'] == 2.96
    assert sample(proc_root=proc, loadavg=tmp_path/'loadavg', pressure=tmp_path/'absent')['psi_some_avg10'] is None


def test_record_stops_when_its_parent_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(rig_environment.time, 'sleep', lambda s: None)
    monkeypatch.setattr(rig_environment, 'sample', lambda **kwargs: {'wall_s': 1., 'load1': 1.})
    rig_environment.record(tmp_path, parent_pid=2**22+7)  # a pid that does not exist: returns at once
    assert len((tmp_path/'environment_samples.jsonl').read_text().splitlines()) == 1


def test_rig_script_wiring():
    script = (ROOT/'tools/gz/run_track260905.sh').read_text()
    start, gz = script.index('rig_start=$(date'), script.index('setsid gz sim')
    recorder = next(line for line in script.splitlines() if 'rig_environment.py record' in line)
    wait = script.index('wait "${pids[$monitor_index]}"')
    judge_call, verdict = script.index('rig_environment.py judge'), script.index("print('RIG VERDICT: PASS'")
    assert start < gz and '8>&-' in recorder and '9>&-' in recorder and recorder.rstrip().endswith('pids+=($!)')
    assert '"$$"' in recorder  # the recorder exits with this script
    assert wait < judge_call < verdict
    # An invalid run still reports its pass/fail, marked as not counted, and exits 3.
    assert 'RIG_ENVIRONMENT_INVALID' in script and 'RIG VERDICT (environment-invalid, not counted)' in script
    assert "'environment.json'" in script and "'.jsonl'" in script  # unlinked and archived per run


def test_matrix_runner_does_not_count_environment_invalid_runs():
    assert outcome(3, False) == 'environment_invalid'
    assert outcome(4, False) == 'lock_busy'
    assert outcome(0, True) == 'pass' and outcome(1, False) == 'fail' and outcome(0, False) == 'fail'
    names = (ROOT/'tools/gz/run_calibration_spaces.py').read_text()
    assert "'environment.json'" in names
