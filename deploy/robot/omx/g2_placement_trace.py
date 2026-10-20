"""Passive bounded movement evidence; no predicate, admission or motion authority."""
from collections import deque
from datetime import datetime
import json
import math
from pathlib import Path
import socket
import sqlite3
import threading
import time
import uuid

from g2_ports import write_json

SCHEMA = 'rosy.g2-placement-trace/1'
POSE_KEYS = ('x_m', 'y_m', 'z_m', 'roll_rad', 'pitch_rad', 'yaw_rad')


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e11:
        raise ValueError('bounded finite diagnostic number required')
    return float(value)


def pose(value):
    return {key: number(value[key]) for key in POSE_KEYS}


def identifier(value):
    if type(value) is not str or len(value) != 36 or str(uuid.UUID(value)) != value:
        raise ValueError('canonical diagnostic UUID required')
    return value


class PlacementTrace:
    def __init__(self):
        self.models = {}
        self.diagnostic_failure_count = 0

    def watch(self, *, model, action_id, attempt_id, baseline, baseline_observed_at, confirmation_seen_at):
        action_id, attempt_id = identifier(action_id), identifier(attempt_id)
        if model != 'cell_' + action_id:
            raise ValueError('trace model differs from confirmed action')
        binding = dict(action_id=action_id, attempt_id=attempt_id, baseline=pose(baseline),
                       baseline_observed_at=number(baseline_observed_at),
                       confirmation_seen_at=number(confirmation_seen_at))
        existing = self.models.get(model)
        if existing is not None:
            if any(existing[key] != value for key, value in binding.items()):
                raise ValueError('confirmed trace baseline cannot be replaced')
            return
        if len(self.models) >= 16:
            raise ValueError('confirmed trace model limit reached')
        self.models[model] = dict(binding, registered_at=time.time(), before=deque(maxlen=3),
                                  first_crossing=None, after=[], last_steady=None)

    def observe(self, model, measured, *, wall, steady, sim_clock):
        record = self.models.get(model)
        if record is None or len(record['after']) >= 3:
            return
        measured = pose(measured)
        baseline = record['baseline']
        distance = math.dist([measured[key] for key in POSE_KEYS[:3]], [baseline[key] for key in POSE_KEYS[:3]])
        angular = max(abs(math.atan2(math.sin(measured[key]-baseline[key]),
                                     math.cos(measured[key]-baseline[key]))) for key in POSE_KEYS[3:])
        sample = dict(observed_at=number(wall), steady_at=number(steady),
                      sim_clock=None if sim_clock is None else number(sim_clock), pose=measured,
                      translation_m=distance, max_euler_delta_rad=angular)
        if record['first_crossing'] is None and (distance > .002 or angular > math.radians(2)):
            record['first_crossing'] = sample
            record['last_steady'] = steady
            return
        if record['last_steady'] is not None and steady-record['last_steady'] < .05:
            return
        record['last_steady'] = steady
        (record['before'] if record['first_crossing'] is None else record['after']).append(sample)

    def snapshot(self):
        models = {model: {key: list(value) if key in ('before', 'after') else value
                          for key, value in record.items() if key != 'last_steady'}
                  for model, record in self.models.items()}
        result = dict(schema=SCHEMA, diagnostic_only=True, snapshot_atomic=False,
                      diagnostic_failure_count=self.diagnostic_failure_count,
                      movement_trigger=dict(translation_m=.002, max_euler_delta_rad=math.radians(2)), models=models)
        if len(json.dumps(result, allow_nan=False).encode()) > 60000:
            raise ValueError('trace exceeds bounded IPC payload')
        return result


def exchange(run, request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(.5)
        connection.connect(str(Path(run)/'observer.sock'))
        connection.sendall(json.dumps(request, allow_nan=False).encode()+b'\n')
        with connection.makefile('rb') as stream:
            raw = stream.readline(65537)
    if len(raw) > 65536:
        raise ValueError('placement trace exceeds observer frame bound')
    result = json.loads(raw)
    if result.get('ok') is not True:
        raise RuntimeError('passive placement trace request failed')
    return result


def register_confirmed(job, run, request, *, registered=None):
    for step in job['steps']:
        if step['status'] != 'GOAL_CONFIRMED':
            continue
        action_id, attempt_id = identifier(step['action_id']), identifier(step['attempt_id'])
        if registered is not None and action_id in registered:
            continue
        saved = json.loads((Path(run)/'placements'/(action_id+'.json')).read_text())
        evidence = saved['evidence']
        if (saved['mission_id'] != job['mission_id'] or evidence['action_id'] != action_id
                or evidence['attempt_id'] != attempt_id or evidence['step_index'] != step['step_index']
                or evidence['model_id'] != 'cell_'+action_id):
            raise ValueError('trace baseline differs from confirmed saved goal evidence')
        request(dict(operation='watch_placement', model=evidence['model_id'], action_id=action_id,
                     attempt_id=attempt_id, baseline=evidence['model_pose_base'],
                     baseline_observed_at=evidence['observed_at'], confirmation_seen_at=time.time()))
        if registered is not None:
            registered.add(action_id)


class TraceRegistration:
    def __init__(self, run):
        self.run, self.registered, self.disabled = Path(run), set(), False
        self.failure = None

    def observe(self, job, request):
        if self.disabled:
            return
        try:
            register_confirmed(job, self.run, request, registered=self.registered)
        except Exception as error:
            self.disabled = True
            self.failure = dict(error_type=type(error).__name__[:80], diagnostic_only=True)


def correlations(run):
    """Recorded wall times are correlation evidence, never proof of contact identity."""
    database = Path(run)/'owner.sqlite3'
    if not database.exists():
        return []
    result = []
    with sqlite3.connect('file:'+str(database)+'?mode=ro', uri=True, timeout=.1) as db:
        rows = db.execute("SELECT action_id,event_type,detail_json,created_at FROM omx_action_events "
                          "WHERE event_type IN ('ACTION_PHASE_SUBMISSION_STARTED','ACTION_PHASE_TERMINAL_RESULT') "
                          "ORDER BY event_id LIMIT 128")
        for action, kind, detail, stamp in rows:
            detail = json.loads(detail)
            result.append(dict(action_id=identifier(action), event_type=kind,
                               phase_id=detail.get('phase_id'), recorded_wall=datetime.fromisoformat(stamp).timestamp()))
    return result


def _persist_trace(run, request, registration_failure):
    try:
        result = (request or (lambda value: exchange(run, value)))(dict(operation='placement_trace'))['trace']
        result['registration_failure'] = registration_failure
        result['phase_correlations'] = correlations(run)
        result['aid_correlations'] = []
        for path in sorted((Path(run)/'aid').glob('*.json'))[:32]:
            value = json.loads(path.read_text())
            result['aid_correlations'].append({key: value.get(key) for key in
                ('action_id', 'attempt_id', 'command', 'confirmed', 'elapsed_s')})
            result['aid_correlations'][-1]['receipt_file_mtime_wall'] = path.stat().st_mtime
        result['collection'] = 'COLLECTED'
        write_json(Path(run)/'placement-trace.json', result)
        return True
    except Exception as error:
        try:
            failure = dict(schema=SCHEMA, collection='FAILED', error_type=type(error).__name__[:80])
            if registration_failure is not None:
                failure['registration_failure'] = registration_failure
            write_json(Path(run)/'placement-trace.json', failure)
        except Exception:
            pass
        return False


def persist_trace(run, request=None, *, timeout=1., registration_failure=None):
    """A stalled diagnostic transport or disk cannot delay control cleanup indefinitely."""
    completed = []
    def collect():
        completed.append(_persist_trace(run, request, registration_failure))
    worker = threading.Thread(target=collect, name='g2-placement-evidence', daemon=True)
    worker.start()
    worker.join(min(max(number(timeout), 0.), 1.))
    return bool(completed and completed[0])
