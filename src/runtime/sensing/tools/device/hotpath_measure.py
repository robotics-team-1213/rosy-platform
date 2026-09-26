#!/usr/bin/env python3
"""D-185 R8: measure control hot paths and node CPU on the Pinky Pro Raspberry Pi.

Two subcommands, each writing one JSON report (schema ``rosy.control.hotpath_measure/1``):

``bench``  times the three device-relevant hot paths on synthetic inputs shaped like
           the equivalence tests (median, p90, max in ms):
           - ``control.sensing.wall_tracker._segments`` on a 720-ray wall scan
             (test_wall_tracker_equivalence.scan);
           - ``control.sensing.scan_motion.match_motion`` on two 180-point box-room
             clouds, the current one rotated by 10 deg (test_registration_endpoints);
           - ``control.planning.gridmap.OccupancyMap.inflate`` on a 200x200 map with
             walls, r_cells=5 (test_inflate_equivalence map size).
``watch``  samples running control node processes (matched by installed entry-point
           name or ``-m control.<node>``): CPU% from /proc/<pid>/stat utime+stime
           deltas, VmRSS, loadavg and PSI ``/proc/pressure/cpu`` some avg10.

A report is device evidence only when it was produced on the device: ``evidence.device``
is true only if /proc/device-tree/model names a Raspberry Pi. Host runs (x86, WSL,
Windows) are never device evidence, whatever their numbers.

Device procedure (Pinky Pro, Raspberry Pi OS; HOLD as of 2026-09-24, no Pi run yet)
--------------------------------------------------------------------------------
1. Get the code onto the Pi. Either
   a. checkout: ``git clone``/``git fetch`` the Rosy OS repo on the Pi and check out the
      revision under test (e.g. before and after an R1-R3 change). Running the tool from
      the checkout measures that checkout's ``control`` package; or
   b. installed: ``scp src/runtime/sensing/tools/device/hotpath_measure.py pinky@<pi>:/tmp/``
      and ``source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash``
      so the deployed ``control`` package is imported. ``environment.control_source``
      in the report records which one was used.
   numpy must be importable (it is on the device image).
2. Bench, with the robot stack stopped so nothing competes for the CPU (about 1-2 min):
       cd "<checkout>/src/runtime/sensing"
       python3 tools/device/hotpath_measure.py bench --iterations 50 --label <revision> \\
           --out ~/rosy-measure/bench-$(date +%Y%m%dT%H%M%S).json
3. Watch, with the stack running as in the scenario to measure (e.g. startup
   calibration, then wander/goal with the web dashboard open). It runs for about
   --duration seconds (default 600 s, one sample every 2 s):
       python3 tools/device/hotpath_measure.py watch --duration 600 --interval 2 \\
           --label <scenario> --out ~/rosy-measure/watch-$(date +%Y%m%dT%H%M%S).json
   ``--names`` restricts the matched nodes (default: every control entry point).
4. Copy ``~/rosy-measure/*.json`` back and cite it in the D-185 R8 record. Without --out
   the report goes to stdout. Record the scenario next to the numbers; a watch run is
   only comparable to one of the same scenario and duration.
"""
import argparse
import json
import math
import os
import platform
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

SCHEMA_VERSION = 'rosy.control.hotpath_measure/1'
_HERE = Path(__file__).resolve()
#: src/runtime/sensing when run from a checkout; a lone copied file has no package root.
PKG = _HERE.parents[2] if len(_HERE.parents) > 2 else _HERE.parent

#: console_scripts in setup.py (every control node entry point).
NODE_NAMES = (
    'control_node', 'safety_node', 'wander_node', 'calib_node', 'startup_calibration_node',
    'camera_detect_node', 'ir_adc_node', 'line_observer_node', 'road_observer_node',
    'obstacle_observer_node', 'watch_node', 'goal_node', 'localization_node', 'web_node',
    'dock_observer_node',
)


# ---------------------------------------------------------------- /proc parsing

def parse_stat(text):
    """Fields of /proc/<pid>/stat after the comm, which may itself hold spaces and ')'."""
    try:
        fields = text.rsplit(')', 1)[1].split()
        return {'state': fields[0], 'utime': int(fields[11]), 'stime': int(fields[12]),
                'starttime': int(fields[19])}
    except (IndexError, ValueError) as error:
        raise ValueError(f'unparseable stat: {text[:60]!r}') from error


def cpu_percent(prev, cur, dt_s, clk_tck):
    """Percent of one core used between two stat samples; None without elapsed time."""
    if dt_s <= 0:
        return None
    ticks = (cur['utime']+cur['stime'])-(prev['utime']+prev['stime'])
    return 100.*ticks/clk_tck/dt_s


def parse_psi(text):
    """PSI 'some avg10': percent of the last 10 s a runnable task waited for a CPU."""
    for line in text.splitlines():
        if line.startswith('some '):
            try:
                return float(dict(f.split('=', 1) for f in line.split()[1:])['avg10'])
            except (KeyError, ValueError):
                return None
    return None


def parse_loadavg(text):
    return [float(v) for v in text.split()[:3]]


def parse_rss_kb(text):
    for line in text.splitlines():
        if line.startswith('VmRSS:'):
            return int(line.split()[1])
    return None


def _node_name(argv, names):
    """The control node an argv runs, or None. A search (grep safety_node) is not a node."""
    if not argv:
        return None
    for i, arg in enumerate(argv[:-1]):
        if arg == '-m' and argv[i+1].startswith('control.'):
            name = argv[i+1].split('.', 1)[1]
            return name if name in names else None
    candidates = [Path(argv[0]).name]
    if candidates[0].startswith('python') and len(argv) > 1:
        candidates.append(Path(argv[1]).name)
    return next((c for c in candidates if c in names), None)


def find_processes(proc_root=Path('/proc'), names=NODE_NAMES):
    """{pid: node name} of running control nodes, excluding this tool."""
    found = {}
    for entry in Path(proc_root).iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            argv = [a.decode(errors='replace') for a in (entry/'cmdline').read_bytes().split(b'\0') if a]
        except OSError:
            continue  # exited while scanning
        name = _node_name(argv, names)
        if name:
            found[int(entry.name)] = name
    return found


def _read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def _snapshot(proc_root, names):
    procs = {}
    for pid, name in find_processes(proc_root, names).items():
        stat = _read(Path(proc_root)/str(pid)/'stat')
        if stat is None:
            continue
        try:
            parsed = parse_stat(stat)
        except ValueError:
            continue
        status = _read(Path(proc_root)/str(pid)/'status') or ''
        procs[pid] = dict(parsed, name=name, rss_kb=parse_rss_kb(status))
    loadavg = _read(Path(proc_root)/'loadavg')
    pressure = _read(Path(proc_root)/'pressure'/'cpu')
    return {'procs': procs, 'load': parse_loadavg(loadavg) if loadavg else None,
            'psi': parse_psi(pressure) if pressure else None}


def watch(duration_s=600., interval_s=2., proc_root=Path('/proc'), names=NODE_NAMES,
          sleep=time.sleep, clock=time.monotonic, clk_tck=None):
    """One sample per interval; CPU% is against the previous sample of the same process.

    A process that restarted (new starttime) or appeared mid-run has cpu_percent None
    for its first sample instead of a bogus delta.
    """
    if clk_tck is None:
        clk_tck = os.sysconf('SC_CLK_TCK')
    start = prev_t = clock()
    prev = _snapshot(proc_root, names)
    samples = []
    while True:
        sleep(interval_s)
        t = clock()
        cur = _snapshot(proc_root, names)
        rows = []
        for pid, p in sorted(cur['procs'].items()):
            before = prev['procs'].get(pid)
            same = before is not None and before['starttime'] == p['starttime']
            cpu = cpu_percent(before, p, t-prev_t, clk_tck) if same else None
            rows.append({'pid': pid, 'name': p['name'], 'state': p['state'],
                         'cpu_percent': None if cpu is None else round(cpu, 2), 'rss_kb': p['rss_kb']})
        load = cur['load'] or [None]*3
        samples.append({'t_s': round(t-start, 3), 'load1': load[0], 'load5': load[1], 'load15': load[2],
                        'psi_some_avg10': cur['psi'], 'processes': rows})
        prev, prev_t = cur, t
        if t-start >= duration_s-1e-9:
            return samples


def watch_summary(samples):
    """Per node name: median and max CPU%, max RSS over the run."""
    by_name = {}
    for sample in samples:
        for row in sample['processes']:
            by_name.setdefault(row['name'], []).append(row)
    out = {}
    for name, rows in sorted(by_name.items()):
        cpu = [r['cpu_percent'] for r in rows if r['cpu_percent'] is not None]
        rss = [r['rss_kb'] for r in rows if r['rss_kb'] is not None]
        out[name] = {'samples': len(rows), 'cpu_percent_median': statistics.median(cpu) if cpu else None,
                     'cpu_percent_max': max(cpu) if cpu else None, 'rss_kb_max': max(rss) if rss else None}
    return out


# ---------------------------------------------------------------- bench

def summarize(times_ms):
    """median, nearest-rank p90 and max of a list of durations in ms."""
    ordered = sorted(times_ms)
    return {'n': len(ordered), 'median_ms': statistics.median(ordered),
            'p90_ms': ordered[math.ceil(.9*len(ordered))-1], 'max_ms': ordered[-1]}


def wall_scan(front=.4, side=.6, nose=0., noise=.0005, seed=0, n=720):
    """Same geometry as test_wall_tracker_equivalence.scan: a box around the robot."""
    rng = random.Random(seed)
    ranges = []
    for i in range(n):
        a = -math.pi+i*math.tau/n+nose
        dx, dy = math.cos(a), math.sin(a)
        t = min(front/dx if dx > 1e-9 else 1e9, side/abs(dy) if abs(dy) > 1e-9 else 1e9,
                2./abs(dx) if dx < -1e-9 else 1e9)
        ranges.append(round(t+rng.gauss(0., noise), 3))
    return SimpleNamespace(ranges=ranges, angle_min=-math.pi, angle_increment=math.tau/n,
                           range_min=.05, range_max=12.)


def box_cloud(n=180, yaw=0.):
    """n endpoint points of the same box room, seen from a base rotated by yaw."""
    import numpy as np
    s = wall_scan(n=n, noise=0.)
    angles = s.angle_min+np.arange(n)*s.angle_increment
    ranges = np.asarray(s.ranges)
    points = np.column_stack((ranges*np.cos(angles), ranges*np.sin(angles)))
    c, si = math.cos(yaw), math.sin(yaw)
    return points@np.array([[c, -si], [si, c]])  # as test_registration_endpoints builds `current`


def wall_map(size=200):
    """size x size free map, 5 cm cells, with border and maze-like inner walls."""
    from control.planning.gridmap import OccupancyMap
    m = OccupancyMap(size, size, .05, (0., 0.), fill=0)
    for k in range(size):
        for c, r in ((k, 0), (k, size-1), (0, k), (size-1, k)):
            m.set_cell(c, r, 100)
    for x in range(40, size-1, 40):
        for k in range(size//4, size):
            m.set_cell(x, k if x % 80 else size-1-k, 100)
    return m


def _time(call, iterations, warmup):
    for _ in range(warmup):
        call()
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        call()
        times.append((time.perf_counter()-t0)*1000.)
    return summarize(times)


def bench(iterations=50, warmup=3):
    from control.planning.gridmap import OccupancyMap  # noqa: F401  (import cost outside timing)
    from control.sensing.scan_motion import match_motion
    from control.sensing.wall_tracker import _segments

    scan = wall_scan()
    ref, cur = box_cloud(), box_cloud(yaw=math.radians(10.))
    grid = wall_map()
    result = {
        'wall_tracker_segments': dict(
            _time(lambda: _segments(scan, 0.), iterations, warmup),
            input='720-ray box scan front 0.4 side 0.6 m, noise 0.5 mm, nose 0, no compensation',
            segments=len(_segments(scan, 0.))),
        'scan_motion_match_motion': dict(
            _time(lambda: match_motion(ref, cur, math.radians(10.)), iterations, warmup),
            input='two 180-point box-room clouds, current rotated 10 deg, yaw hint 10 deg',
            accepted=match_motion(ref, cur, math.radians(10.)) is not None),
        'gridmap_inflate': dict(
            _time(lambda: grid.inflate(5.), iterations, warmup),
            input='200x200 map at 0.05 m, border + inner walls, r_cells 5',
            grown=grid.inflate(5.).data != grid.data),
    }
    return result


# ---------------------------------------------------------------- report

def _cpu_model(text):
    fields = {}
    for line in (text or '').splitlines():
        key, sep, value = line.partition(':')
        if sep:
            fields.setdefault(key.strip(), value.strip())
    for key in ('model name', 'Hardware', 'Model', 'CPU part'):
        if fields.get(key):
            return fields[key]
    return None


def environment(proc_root=Path('/proc')):
    try:
        import numpy
        numpy_version = numpy.__version__
    except ImportError:
        numpy_version = None
    model = None
    try:
        model = (Path(proc_root)/'device-tree'/'model').read_bytes().rstrip(b'\0').decode(errors='replace') or None
    except OSError:
        pass
    control = sys.modules.get('control')
    return {'platform': platform.platform(), 'machine': platform.machine(), 'python': platform.python_version(),
            'numpy': numpy_version, 'cpu_model': _cpu_model(_read(Path(proc_root)/'cpuinfo')),
            'cpu_count': os.cpu_count(), 'device_model': model,
            'control_source': getattr(control, '__file__', None) and str(Path(control.__file__).parent)}


def build_report(kind, payload, proc_root=Path('/proc'), label=None, argv=None):
    env = environment(proc_root)
    device = bool(env['device_model'] and 'Raspberry Pi' in env['device_model'])
    statement = ('DEVICE: produced on a Raspberry Pi (' + env['device_model'] + '); device evidence for that '
                 'unit only' if device else
                 'HOST: not device evidence. Only a run on the Pinky Pro Raspberry Pi counts for D-185 R8.')
    report = {'schema_version': SCHEMA_VERSION, 'kind': kind, 'label': label,
              'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'argv': argv, 'evidence': {'device': device, 'statement': statement}, 'environment': env,
              'units': {'cpu_percent': 'percent of one full core (100 = one core busy); see environment.cpu_count',
                        'timings': 'milliseconds of wall time per call'},
              kind: payload}
    if kind == 'watch':
        report['watch_summary'] = watch_summary(payload)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='kind', required=True)
    b = sub.add_parser('bench', help='time the three hot paths')
    b.add_argument('--iterations', type=int, default=50)
    b.add_argument('--warmup', type=int, default=3)
    w = sub.add_parser('watch', help='sample running control node processes')
    w.add_argument('--duration', type=float, default=600.)
    w.add_argument('--interval', type=float, default=2.)
    w.add_argument('--names', nargs='+', default=list(NODE_NAMES))
    for p in (b, w):
        p.add_argument('--label', help='revision or scenario, stored in the report')
        p.add_argument('--out', help='JSON report path (default: stdout)')
    args = parser.parse_args(argv)
    if args.kind == 'bench':
        payload = bench(args.iterations, args.warmup)
    else:
        payload = watch(args.duration, args.interval, names=tuple(args.names))
    text = json.dumps(build_report(args.kind, payload, label=args.label,
                                   argv=sys.argv[1:] if argv is None else list(argv)), indent=2)
    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text+'\n', encoding='utf-8')
        print(out)
    else:
        print(text)
    return 0


if __name__ == '__main__':
    # Run from a checkout, measure that checkout's control package; a lone copied file
    # falls back to the installed (sourced) package.
    if (PKG/'control'/'__init__.py').is_file():
        sys.path.insert(0, str(PKG))
    sys.exit(main())
