"""D-763 SIM check probe (Fleet API on the live 2-robot Gazebo rig). Writes every request/response.

Checks: A lane trip + work read (slice 2/4), B refusals while a trip is open (slice 1 trip_refusal),
S7: a two-step trip job through the product route (D-763 slice 7, branch feat/fleet-job-trip-steps).
"""
import json, os, time, urllib.request, urllib.error
from pathlib import Path

OUT = Path(os.environ['D763_OUT'])
TOKEN = os.environ['MAP_DRIVE_FLEET_TOKEN']
FLEET, CORE = 'http://127.0.0.1:31353', {'rosy_01': 'http://127.0.0.1:31351', 'rosy_02': 'http://127.0.0.1:31352'}
LOG = (OUT / 'api-log.jsonl').open('a', buffering=1)
RESULT = {}
T0 = time.monotonic()


def call(url, method='GET', body=None, token=TOKEN, headers=None, tag=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            code, value = r.status, json.load(r)
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            value = json.load(e)
        except Exception:
            value = {'raw': 'unparsable'}
    except Exception as e:
        code, value = 0, {'error': type(e).__name__, 'message': str(e)[:200]}
    LOG.write(json.dumps(dict(t=round(time.monotonic() - T0, 2), wall=time.time(), tag=tag, method=method,
                              url=url, body=body, status=code, response=value)) + '\n')
    return code, value


def fleet(path, method='GET', body=None, tag=None, **kw):
    return call(FLEET + '/api/fleet/' + path, method, body, tag=tag, **kw)


def harness(path, method='POST', body=None, tag=None):
    return call(FLEET + '/api/_d763_harness/' + path, method, body, tag=tag)


def core(ns, path, method='GET', body=None, token='rosy-dev-operator', tag=None):
    return call(CORE[ns] + '/api/v1/' + path, method, body, token=token, tag=tag)


def record(name, ok, **evidence):
    RESULT[name] = dict(pass_=bool(ok), **evidence)
    (OUT / 'probe-result.json').write_text(json.dumps(RESULT, indent=2, default=str))
    print(name, 'PASS' if ok else 'FAIL', flush=True)


def wait_trip(trip_id, budget_s, tag, on_tick=None):
    """Poll the trip and the work read; return (last trip view, every distinct work trip row seen)."""
    rows, last, deadline = {}, None, time.monotonic() + budget_s
    while time.monotonic() < deadline:
        _, last = fleet(f'trips/{trip_id}', tag=tag)
        _, work = fleet('work', tag=tag + ':work')
        for row in (work or {}).get('rows', []):
            if row.get('source') == 'trip' and row.get('source_id') == trip_id:
                key = json.dumps([row.get('status'), row.get('visible_state'), row.get('wait')], sort_keys=True)
                rows.setdefault(key, dict(first_t=round(time.monotonic() - T0, 1), row=row))
        core('rosy_02', 'line-follow', tag=tag + ':core-lf')
        if on_tick:
            on_tick(last)
        if (last or {}).get('state') in ('arrived', 'canceled', 'stopped', 'failed'):
            break
        time.sleep(1.0)
    return last, list(rows.values())


def plan(robot, to, via=(), tag='plan'):
    code, p = fleet(f'robots/{robot}/trip', 'POST', {'to': to, 'via': list(via), 'repeat': False, 'speed_cap': .08}, tag=tag)
    return code, p


try:
    # ---- readiness -------------------------------------------------------------------------
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        poses = [fleet(f'robots/{ns}/map-pose', tag='ready')[1] for ns in CORE]
        if all((p or {}).get('state') == 'LOCALIZED' for p in poses):
            break
        time.sleep(2)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        cams = [core(ns, 'vision/front/status', tag='ready-camera')[1] for ns in CORE]
        if all((c or {}).get('available') is True for c in cams):
            break
        time.sleep(2)
    time.sleep(30)  # warm-up like the lap probe (it spins 50 s before its trip)
    core('rosy_02', 'line-follow', tag='ready-core-lf')
    record('ready_localized', all((p or {}).get('state') == 'LOCALIZED' for p in poses), poses=poses)
    _, active = fleet('site-map/active', tag='site-map')
    places = [p.get('id') for p in ((active or {}).get('map') or active or {}).get('places', [])] if isinstance(active, dict) else []
    (OUT / 'site-map-active.json').write_text(json.dumps(active, indent=2))
    code, work0 = fleet('work', tag='work-baseline')
    record('work_read_kinds', code == 200 and 'trip' in (work0.get('kinds') or []), status=code, kinds=work0.get('kinds'),
           sources=dict(tasks=work0.get('tasks_available'), missions=work0.get('missions_available'),
                        cell_jobs=work0.get('cell_jobs_available')))


    fleet('traffic/signals/sig_ring', 'POST', {'verb': 'cycle'}, tag='signal-cycle')
    _, control = fleet('dispatch-control', tag='dispatch-control')
    code, rearm = fleet('dispatch/rearm', 'POST', {'expected_generation': control.get('generation')}, tag='rearm')
    record('S7_rearm', code == 200, status=code, reply=rearm)
    code, made = fleet('trip-jobs', 'POST', {'robot_id': 'rosy_02', 'steps': [{'to': 'SW'}, {'to': 'SE'}]}, tag='S7-create')
    job = (made or {}).get('job') or {}
    record('S7_create', code == 200 and job.get('status') == 'READY', status=code, reply=made)
    mid, timeline, trips, last_key = job.get('mission_id'), [], {}, None
    deadline = time.monotonic() + 420
    while mid and time.monotonic() < deadline:
        _, work = fleet('work', tag='S7-poll:work')
        row = next((r for r in (work or {}).get('rows', []) if r.get('source_id') == mid), None) or {}
        _, listed = fleet('trips', tag='S7-poll:trips')
        for view in (listed or {}).get('trips', listed if isinstance(listed, list) else []):
            if isinstance(view, dict) and view.get('robot_id') == 'rosy_02':
                trips[view['trip_id']] = {k: view.get(k) for k in ('state', 'reason', 'segment_index', 'pose', 'lease', 'detail', 'started_by')}
        _, lf = core('rosy_02', 'line-follow', tag='S7-poll:core-lf')
        _, st = core('rosy_02', 'robot/state', tag='S7-poll:core-state')
        key = json.dumps([row.get('status'), row.get('reason'), sorted((t, v['state']) for t, v in trips.items())])
        if key != last_key:
            timeline.append(dict(t=round(time.monotonic() - T0, 1), job=row, trips={t: (v['state'], v['reason']) for t, v in trips.items()},
                                 core_mode=(st or {}).get('mode'), core_lease=(st or {}).get('trip_lease'),
                                 core_line={k: (lf or {}).get(k) for k in ('state', 'reason', 'mode', 'junction')}))
            last_key = key
        (OUT / 'S7-timeline.json').write_text(json.dumps(dict(timeline=timeline, trips=trips), indent=2, default=str))
        if row.get('status') in ('GOAL_CONFIRMED', 'HOLD'):
            break
        time.sleep(1.0)
    ended = [v for v in trips.values() if v['state'] == 'arrived']
    record('S7_two_steps_drive_and_arrive', len(ended) >= 2 and timeline and timeline[-1]['job'].get('status') == 'GOAL_CONFIRMED',
           final=timeline[-1] if timeline else None, trips=trips)
    _, st = core('rosy_02', 'robot/state', tag='S7-after')
    record('S7_lease_released', (st or {}).get('trip_lease') is None, core_trip_lease=(st or {}).get('trip_lease'))
finally:
    for ns in CORE:
        core(ns, 'line-follow/mode', 'PUT', {'mode': 'OFF'}, tag='cleanup-off')
    LOG.close()
