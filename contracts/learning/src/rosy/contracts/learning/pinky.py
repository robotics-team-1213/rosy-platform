"""Pinky recording and converted sidecar semantics; no actuator/task certification."""
from datetime import datetime
import json
import math
from pathlib import Path, PurePosixPath

from .artifacts import validate_episode


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Pinky recording nonempty identifier required')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _member(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or PurePosixPath(name).name != name or name in ('.', '..')):
        raise ValueError('Pinky recording local filename required')
    return name


def _validate_recording(metadata, raw):
    """Validate preserved conversion/session files and clock-aware command sidecar."""
    metadata, raw = Path(metadata).resolve(), Path(raw).resolve()
    doc = json.loads(metadata.read_text(encoding='utf-8'))
    if doc.get('schema') != 'rosy.teleop.video/1':
        raise ValueError('Pinky recording metadata required')
    session = json.loads((raw / 'session.json').read_text(encoding='utf-8'))
    if session != doc.get('session') or session.get('schema') != 'rosy.recording.session/1':
        raise ValueError('Pinky original session binding differs')
    for field in ('device', 'reason'):
        _text(session.get(field))
    for field in ('camera_profile_revision', 'model_revision', 'task_id'):
        if session.get(field) is not None:
            _text(session[field])
    try:
        start, end = [datetime.fromisoformat(session[key]) for key in ('started_at', 'ended_at')]
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError('Pinky completed session timestamps required') from error
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError('Pinky completed session timestamps required')
    source = doc['source']; _text(source.get('session'))
    topics = session.get('topics')
    if not isinstance(topics, list) or 'cmd_vel' not in topics or not any(
            topic in topics for topic in ('camera/front', 'camera/front/compressed')):
        raise ValueError('Pinky camera and CORE command topics required')
    bags = sorted((raw / 'bag').glob('*.mcap'))
    if not bags or sum(path.stat().st_size for path in bags) != source.get('bag_bytes'):
        raise ValueError('Pinky raw bag byte closure differs')
    video = metadata.parent / _member(doc['video']['file'])
    if not video.is_file() or video.stat().st_size != doc['video']['bytes']:
        raise ValueError('Pinky video byte count differs')
    sidecar = metadata.parent / _member(doc['sidecar']['file'])
    rows = [json.loads(line) for line in sidecar.read_text(encoding='utf-8').splitlines()]
    if not rows or type(doc['video']['frames']) is not int or len(rows) != doc['video']['frames']:
        raise ValueError('Pinky sidecar frame count differs')
    if any(type(doc['video'].get(key)) is not int or not 1 <= doc['video'][key] <= 16384
           for key in ('width', 'height')):
        raise ValueError('Pinky video dimensions required')
    if not _number(doc['video'].get('fps')) or doc['video']['fps'] <= 0:
        raise ValueError('Pinky positive video fps required')
    gap = doc['sidecar']['max_gap_s']
    if not _number(gap) or gap <= 0:
        raise ValueError('Pinky positive sidecar lookback required')
    previous_stamp = previous_log = None
    commands = 0
    for index, row in enumerate(rows):
        if type(row.get('index')) is not int or row['index'] != index:
            raise ValueError('Pinky frame index differs')
        stamp, log = row.get('stamp_ns'), row.get('log_ns')
        if any(type(value) is not int or value < 0 for value in (stamp, log)):
            raise ValueError('Pinky source clocks required')
        if ((previous_stamp is not None and stamp <= previous_stamp)
                or (previous_log is not None and log < previous_log)):
            raise ValueError('Pinky source clocks not advancing')
        if not _number(row.get('t')) or abs(row['t'] * 1e9 - stamp) > 1000:
            raise ValueError('Pinky capture timestamp differs')
        if not isinstance(row.get('side'), dict) or not isinstance(row.get('dt'), dict):
            raise ValueError('Pinky sidecar side/dt required')
        if set(row['side']) != set(row['dt']):
            raise ValueError('Pinky side/dt topic binding differs')
        for topic, payload in row['side'].items():
            delta = row['dt'][topic]
            if payload is None:
                if delta is not None:
                    raise ValueError('Pinky absent observation has nonnull dt')
                continue
            if not isinstance(payload, dict) or not _number(delta):
                raise ValueError('Pinky side observation/dt required')
            if topic in ('line/observation', 'perception/learned/shadow'):
                source_stamp = payload.get('stamp_ns')
                if (type(source_stamp) is not int or abs(source_stamp - stamp) > 1000
                        or log + delta * 1e9 < stamp - 50_000 or delta > .50005
                        or (topic == 'line/observation' and payload.get('source') != 'CAMERA_LINE')):
                    raise ValueError('Pinky stamped evidence clock/source differs')
            elif not -gap - .00005 <= delta <= 0:
                raise ValueError('Pinky future or stale command/observation dt')
        command, dt = row['side'].get('cmd_vel'), row['dt'].get('cmd_vel')
        if command is None:
            if dt is not None:
                raise ValueError('Pinky absent command has nonnull dt')
        else:
            if (not isinstance(command, dict) or set(command) != {'linear', 'angular'}
                    or not all(_number(value) for value in command.values())):
                raise ValueError('Pinky finite m/s rad/s command required')
            # Original conversion rounds dt to 4 decimals: up to 50 us ambiguity.
            if not _number(dt) or not -gap - .00005 <= dt <= 0:
                raise ValueError('Pinky future or stale command dt')
            commands += 1
        previous_stamp, previous_log = stamp, log
    if not commands:
        raise ValueError('Pinky recording has no observed CORE commands')
    if doc.get('scan') is not None:
        if not (metadata.parent / _member(doc['scan']['file'])).is_file():
            raise ValueError('Pinky declared scan sidecar missing')
    return {'metadata': doc, 'session': session, 'rows': rows, 'commands': commands}


def validate_recording(metadata, raw):
    try:
        return _validate_recording(metadata, raw)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
        raise ValueError('malformed Pinky recording') from error


def validate_profile(doc, *, root):
    value = validate_episode(doc, root=root)
    if value['profile'] != 'pinky_recording_session_v1':
        raise ValueError('Pinky Episode profile required')
    root = Path(root).resolve()
    refs = {ref['path']: ref for ref in value['sources']}
    candidates = []
    for name in refs:
        if Path(name).suffix == '.json':
            original = json.loads((root / name).read_text(encoding='utf-8'))
            if isinstance(original, dict) and original.get('schema') == 'rosy.teleop.video/1':
                candidates.append(name)
    if len(candidates) != 1:
        raise ValueError('Pinky recording metadata required')
    metadata = root / candidates[0]
    checked = validate_recording(metadata, root / 'source/raw')
    original, session = checked['metadata'], checked['session']
    expected = {'episode_id': original['source']['session'], 'device': session['device'],
                'robot_type': 'pinky_pro', 'task': session['reason'], 'status': 'complete', 'skill': None}
    if any(value[key] != item for key, item in expected.items()):
        raise ValueError('Pinky Episode metadata binding differs')
    revisions = {'model': session.get('model_revision'), 'camera_profile': session.get('camera_profile_revision'),
                 'policy': None, 'calibration': None}
    if (value['revisions'] != revisions or value['outcome'] != {
            'task': 'unknown', 'action': 'unknown', 'judge': 'unknown', 'evidence': []}
            or value['correlations'] != {'action_ids': [], 'attempt_ids': []}):
        raise ValueError('Pinky historical unknown/outcome binding differs')
    binding_path = 'source/binding.json'
    if binding_path not in refs:
        raise ValueError('Pinky explicit environment/clock binding required')
    binding = json.loads((root / binding_path).read_text(encoding='utf-8'))
    if binding != {'schema': 'rosy.pinky-episode-binding/1',
                   'environment': value['environment'], 'clock_domain': value['clock_domain']}:
        raise ValueError('Pinky environment/clock binding differs')
    for stream, path in (('observation', metadata.parent / original['sidecar']['file']),
                         ('action', metadata.parent / original['sidecar']['file']),
                         ('events', root / 'source/raw/session.json')):
        name = path.relative_to(root).as_posix()
        if name not in refs or value['streams'][stream] != refs[name]:
            raise ValueError('Pinky Episode stream binding differs')
    for path in [metadata.parent / original['video']['file'], *(root / 'source/raw').rglob('*')]:
        if path.is_file() and path.relative_to(root).as_posix() not in refs:
            raise ValueError('Pinky original file absent from Episode sources')
    if original.get('scan') and (metadata.parent / original['scan']['file']).relative_to(root).as_posix() not in refs:
        raise ValueError('Pinky scan absent from Episode sources')
    return checked
