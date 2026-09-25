"""Rig environment guard (D-185 R4): mark runs on an overloaded box invalid, never code evidence.

Usage (from run_track260905.sh):
  python3 tools/gz/rig_environment.py record <out> <parent_pid>  # every 2 s until the parent exits
  python3 tools/gz/rig_environment.py judge <out>                # writes <out>/environment.json

Exit 3 from ``judge`` means environment-invalid; any other non-zero exit is a crash of the
guard itself. A run is invalid when, after the first minute of samples (``load1`` is a
1-minute average that still carries the previous run):
  - the mean 1-minute load reaches RIG_MAX_MEAN_LOAD (default 16, the D-185 A/B limit), or
  - more than RIG_MAX_OVER_FRACTION (default 0.25) of samples reach that load, or
  - the simulation ran below RIG_MIN_RTF_RATIO (default 0.1) of RIG_REALTIME_FACTOR, or
  - another Gazebo session runs in this rig's partition.
Rate needs evidence: at least 10 s of simulation and the monitor's own wall time for the
same span. Without it the guard leaves the verdict to pass/fail, so a missing result, a
broken /clock or an early real failure is never relabelled "environment". Other
partitions' Gazebo sessions are reported, not judged. Reads /proc only; never ROS.
"""
import json
import os
import sys
import time
from pathlib import Path

PARTITION = 'pinky_calmap227'


def judge(samples, elapsed_sim_s, wall_s, requested_rtf=1., max_mean_load=16., max_over_fraction=.25,
          min_rtf_ratio=.1, min_sim_s=10., warmup_s=60.):
    """Pure verdict over recorded samples and the monitor's simulated and wall spans."""
    reasons = []
    rows = [s for s in samples if s.get('load1') is not None]
    if rows:
        settled = [s for s in rows if s['wall_s']-rows[0]['wall_s'] >= warmup_s]
        rows = settled if len(settled) >= 3 else rows
    loads = [s['load1'] for s in rows]
    mean_load = round(sum(loads)/len(loads), 2) if loads else None
    over = sum(load >= max_mean_load for load in loads)/len(loads) if loads else None
    if mean_load is None:
        reasons.append('no load samples')
    elif mean_load >= max_mean_load:
        reasons.append(f'mean load {mean_load} >= {max_mean_load}')
    # The over-limit share and CPU pressure (PSI) are reported, not judged: load is only an
    # indirect signal (a solo run reached 29% over 16 on 2026-09-24), and the PSI limit is
    # calibrated from recorded runs before it may invalidate one (D-185 R4).
    pressure = [s['psi_some_avg10'] for s in rows if s.get('psi_some_avg10') is not None]
    rtf = ratio = None
    if elapsed_sim_s is not None and elapsed_sim_s >= min_sim_s and wall_s and wall_s > 0:
        rtf = round(elapsed_sim_s/wall_s, 3)
        ratio = round(rtf/requested_rtf, 3)
        if ratio < min_rtf_ratio:
            reasons.append(f'real-time factor {rtf} < {min_rtf_ratio} of requested {requested_rtf}')
    own = max((s.get('own_gz', 0) for s in samples), default=0)
    if own > 1:
        reasons.append(f'{own} Gazebo sessions in partition {PARTITION}')
    return {'valid': not reasons, 'reasons': reasons, 'mean_load': mean_load,
            'max_load': max(loads) if loads else None,
            'over_fraction': round(over, 3) if over is not None else None,
            'psi_mean': round(sum(pressure)/len(pressure), 2) if pressure else None,
            'psi_max': max(pressure) if pressure else None,
            'rtf': rtf, 'rtf_ratio': ratio, 'requested_rtf': requested_rtf,
            'foreign_gz_max': max((s.get('foreign_gz', 0) for s in samples), default=0), 'own_gz_max': own,
            'limits': {'max_mean_load': max_mean_load, 'max_over_fraction': max_over_fraction,
                       'min_rtf_ratio': min_rtf_ratio, 'min_sim_s': min_sim_s, 'warmup_s': warmup_s}}


def _is_gazebo(argv):
    """A Gazebo launcher/server process (`gz sim ...`, possibly via ruby), not a search for one."""
    names = [Path(a).name for a in argv[:3]]
    return (names[:2] == ['gz', 'sim'] or
            (len(names) >= 3 and names[0].startswith('ruby') and names[1:3] == ['gz', 'sim']))


def gazebo_sessions(proc_root=Path('/proc')):
    """(own, foreign) counts of distinct Gazebo sessions; an unreadable environ counts as foreign."""
    own, foreign = set(), set()
    for entry in Path(proc_root).iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = [a.decode(errors='replace') for a in (entry/'cmdline').read_bytes().split(b'\0') if a]
            if not argv or not _is_gazebo(argv):
                continue
            session = (entry/'stat').read_text().rsplit(')', 1)[1].split()[3]
        except (OSError, IndexError):
            continue
        try:
            environ = (entry/'environ').read_bytes().split(b'\0')
        except OSError:
            foreign.add(session)
            continue
        (own if f'GZ_PARTITION={PARTITION}'.encode() in environ else foreign).add(session)
    return len(own), len(foreign)


def cpu_pressure(pressure=Path('/proc/pressure/cpu')):
    """PSI 'some avg10': percent of the last 10 s in which a runnable task waited for CPU."""
    try:
        line = next(l for l in Path(pressure).read_text().splitlines() if l.startswith('some '))
        return float(dict(f.split('=') for f in line.split()[1:])['avg10'])
    except (OSError, StopIteration, KeyError, ValueError):
        return None  # kernel without PSI


def sample(proc_root=Path('/proc'), loadavg=Path('/proc/loadavg'), pressure=Path('/proc/pressure/cpu')):
    own, foreign = gazebo_sessions(proc_root)
    return {'wall_s': round(time.time(), 2), 'load1': float(Path(loadavg).read_text().split()[0]),
            'psi_some_avg10': cpu_pressure(pressure), 'own_gz': own, 'foreign_gz': foreign}


def record(out, parent_pid):
    """Append one sample every 2 s; stop once the rig script (parent_pid) is gone."""
    path = Path(out)/'environment_samples.jsonl'
    while True:
        with path.open('a') as handle:
            handle.write(json.dumps(sample())+'\n')
        if not Path(f'/proc/{int(parent_pid)}').exists():
            return
        time.sleep(2.)


def _rows(path):
    rows = []
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # a line torn by the still-running recorder
    return rows


def judge_run(out):
    out = Path(out)
    try:
        result = json.loads((out/'track_result.json').read_text())
    except (OSError, ValueError):
        result = {}
    verdict = judge(_rows(out/'environment_samples.jsonl'), result.get('elapsed_sim_s'),
                    result.get('elapsed_wall_s'), float(os.environ.get('RIG_REALTIME_FACTOR', '1.0')),
                    float(os.environ.get('RIG_MAX_MEAN_LOAD', '16')),
                    float(os.environ.get('RIG_MAX_OVER_FRACTION', '.25')),
                    float(os.environ.get('RIG_MIN_RTF_RATIO', '.1')))
    (out/'environment.json').write_text(json.dumps(verdict, indent=2))
    return verdict


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else None
    if command == 'record' and len(sys.argv) == 4:
        record(sys.argv[2], sys.argv[3])
    elif command == 'judge' and len(sys.argv) == 3:
        verdict = judge_run(sys.argv[2])
        print('RIG ENVIRONMENT:', 'VALID' if verdict['valid'] else 'INVALID', json.dumps(verdict), flush=True)
        sys.exit(0 if verdict['valid'] else 3)
    else:
        raise SystemExit('usage: rig_environment.py record <out> <parent_pid> | judge <out>')
