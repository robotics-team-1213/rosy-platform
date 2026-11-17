"""Session, teacher trajectory, and sealed collection validation helpers for OMX collection intake."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_environment import ROLES, _events, _number, _roles, seal_environment
from native_review import inspect_frames, load_dataset

SCHEMA = 'rosy.omx-collection-session.v1'
MAX_TIME_NS = 2**63-1
TEACHER_FILE = 'teacher/trajectory.json'
TEACHER_SCHEMA = 'rosy.omx-replay-trajectory.v1'
REVISIONS = ('rig_revision', 'calibration_revision')


def _require(value, message):
    if not value:
        raise ValueError('collection: ' + message)


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('collection: nonfinite JSON constant ' + value)


def _json(raw):
    try:
        result = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('collection: invalid JSON') from exc
    _require(isinstance(result, dict), 'JSON object required')
    return result


def _source_ns(value):
    _require(_number(value) and 0 < value <= MAX_TIME_NS/1e9, 'source stamp outside int64 clock range')
    result = round(value*1e9)
    _require(0 < result <= MAX_TIME_NS, 'source stamp outside int64 clock range')
    return result


def _relative(value):
    _require(isinstance(value, str) and '\\' not in value and ':' not in value,
             'unsafe relative file path')
    path = PurePosixPath(value)
    _require(value == path.as_posix() and not path.is_absolute()
             and all(part not in ('', '.', '..') for part in path.parts), 'unsafe relative file path')
    return value


def _vector(value, *, normalized):
    _require(isinstance(value, list) and len(value) == 6 and all(_number(v) for v in value),
             'six finite numeric joint values required')
    if normalized:
        _require(all(-100 <= v <= 100 for v in value[:5]) and 0 <= value[5] <= 100,
                 'normalized joint value out of bounds')


def _teacher_and_ledger(manifest, blobs, completed_only):
    _require('teacher.json' in blobs and 'events.jsonl' in blobs, 'teacher and native event ledger required')
    _require('profile.json' in blobs, 'collection profile required')
    reach = _json(blobs['profile.json']).get('reach_tolerance_rad')
    _require(isinstance(reach, list) and len(reach) == 6 and all(_number(v) and 0 < v <= .2 for v in reach),
             'profile reach tolerance required')
    teacher = _json(blobs['teacher.json'])
    _require(teacher.get('schema') == 'rosy.omx-collection-teacher.v1', 'teacher schema differs')
    canonical = json.dumps(teacher, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    _require(hashlib.sha256(canonical).hexdigest() == manifest['teacher_sha256'], 'teacher digest differs')
    steps = teacher.get('steps')
    _require(isinstance(steps, list) and 0 < len(steps) <= 100, 'bounded teacher steps required')
    for step in steps:
        _require(isinstance(step, dict), 'teacher step object required')
        _vector(step.get('positions'), normalized=False)
        _require(_number(step.get('duration_s')) and step['duration_s'] > 0, 'teacher duration differs')
    raw = blobs['events.jsonl']
    _require(bool(raw) and raw.endswith(b'\n'), 'complete native event ledger required')
    events = [_json(line) for line in raw.splitlines()]
    stop = manifest.get('stop')
    _require(isinstance(stop, dict) and stop.get('hold_requested') is True
             and stop.get('terminal_observed') is True, 'confirmed owner HOLD and terminal required')
    _require(completed_only or 'error' not in manifest, 'session error requires explicit completed-only selection')
    return steps, events, reach


def _completed_attempt(episode, steps, events, reach):
    """An editable completion flag cannot replace byte-bound producer events."""
    cycle = episode['cycle_id']
    expected = [f'{cycle}-{ordinal}' for ordinal in range(len(steps))]
    selected = [event for event in events if event.get('cycle_id') == cycle
                or (isinstance(event.get('command_id'), str) and event['command_id'].startswith(cycle+'-'))]
    _require(episode['reason'] == '' and not any(e.get('kind') == 'ABORT' for e in selected),
             'completed attempt carries an abort or failure reason')
    _require(all(e.get('command_id') in expected for e in selected), 'unexpected command in completed cycle')
    prior_terminal = -1
    for command, step in zip(expected, steps):
        command_events = [(index, event) for index, event in enumerate(selected) if event.get('command_id') == command]
        kinds = {}
        for index, event in command_events:
            kinds.setdefault(event.get('kind'), []).append((index, event))
        required = ('INTENT', 'SUBMISSION', 'GOAL_ACCEPTED', 'TERMINAL_RESULT', 'TERMINAL', 'REACHED')
        _require(all(len(kinds.get(kind, [])) == 1 for kind in required),
                 'complete attempt requires one durable intent/submission/native goal/result/terminal/reach per step')
        indexed = [kinds[kind][0] for kind in required]
        positions = [index for index, _ in indexed]
        _require(positions == sorted(set(positions)) and positions[0] > prior_terminal,
                 'teacher command event order differs')
        prior_terminal = positions[-1]
        intent, submission, accepted, terminal, outer, reached = [event for _, event in indexed]
        errors, tolerance = reached.get('errors_rad'), reached.get('tolerance_rad')
        _require(tolerance == reach and isinstance(errors, list) and len(errors) == 6
                 and all(_number(e) and 0 <= e <= t for e, t in zip(errors, reach)),
                 'measured joints did not reach the teacher target')
        _require(intent.get('step') == step and isinstance(submission.get('decision'), dict)
                 and submission['decision'].get('accepted') is True, 'teacher intent or owner submission differs')
        _require(_text(accepted.get('goal_id')) and terminal.get('goal_id') == accepted['goal_id']
                 and type(terminal.get('status')) is int and terminal['status'] == 4
                 and type(terminal.get('result_code')) is int and terminal['result_code'] == 0,
                 'native goal/result does not establish command success')
        previous_sequence, previous_stamp = 0, -1.
        for _, event in command_events:
            if event.get('kind') in ('INTENT', 'SUBMISSION', 'TERMINAL', 'REACHED'):
                stamp = event.get('time_ns')
                _require(type(stamp) is int and episode['start_ns'] <= stamp < episode['end_ns'],
                         'outer command event outside episode window')
                continue
            _require(event.get('kind') in ('GOAL_ACCEPTED', 'RUNNING_FEEDBACK', 'TERMINAL_RESULT'),
                     'failed or unknown native event in completed command')
            sequence, stamp = event.get('sequence'), event.get('observed_at_monotonic_s')
            _require(type(sequence) is int and sequence > previous_sequence and _number(stamp)
                     and stamp >= 0 and stamp >= previous_stamp and event.get('goal_id') == accepted['goal_id'],
                     'native event sequence, clock or goal differs')
            previous_sequence, previous_stamp = sequence, stamp
        result = outer.get('result')
        _require(isinstance(result, dict) and result.get('succeeded') is True
                 and result.get('source') == 'native_follow_joint_trajectory',
                 'native outer terminal success required')


def _read_source(root):
    root = Path(root).absolute()
    _require(root.is_dir(), 'session directory required')
    for path in (root, *root.parents):
        _require(not path.is_symlink() and not (hasattr(path, 'is_junction') and path.is_junction()),
                 'session links are not accepted')
    blobs = {}
    for path in sorted(root.rglob('*')):
        _require(not path.is_symlink() and not (hasattr(path, 'is_junction') and path.is_junction())
                 and path.resolve().is_relative_to(root.resolve()), 'session links are not accepted')
        if path.is_file():
            _require(path.stat().st_nlink == 1, 'session hard links are not accepted')
            blobs[path.relative_to(root).as_posix()] = path.read_bytes()
        else:
            _require(path.is_dir(), 'special files are not accepted')
    _require('manifest.json' in blobs, 'closed session manifest required')
    return root.resolve(), blobs


def validate_session(root, *, completed_only=False, require_complete=True):
    """Validate every attempt and every raw byte before selecting complete episodes.

    require_complete=False lets a world-model builder read a session whose attempts all failed (D-782 §5).
    Behaviour-cloning intake keeps the default."""
    root, blobs = _read_source(root)
    manifest = _json(blobs['manifest.json'])
    _require(manifest.get('schema') == SCHEMA and manifest.get('state') == 'CLOSED'
             and manifest.get('mode') == 'hardware'
             and manifest.get('source_mode') == 'scripted_teacher', 'hardware collection schema/mode required')
    _require(all(_text(manifest.get(k)) for k in ('session_id', 'rig_revision', 'calibration_revision', 'task'))
             and _hash(manifest.get('teacher_sha256')), 'explicit identity, revisions and teacher required')
    _require(manifest.get('body_units') == 'normalized_-100_100'
             and manifest.get('gripper_units') == 'normalized_0_100', 'normalized units required')
    _require(type(manifest.get('fps')) is int and 0 < manifest['fps'], 'positive integer fps required')
    shapes = manifest.get('camera_shapes')
    _require(isinstance(shapes, dict) and len(shapes) == 2 and _roles(shapes) == set(ROLES),
             'both camera shapes required')
    for shape in shapes.values():
        _require(isinstance(shape, list) and len(shape) == 3 and shape[2] == 3
                 and all(type(n) is int and n > 0 for n in shape), 'positive HWC RGB shape required')
    files = manifest.get('files')
    _require(isinstance(files, dict) and files and 'manifest.json' not in files, 'raw file hash map required')
    for name, digest in files.items():
        _relative(name)
        _require(_hash(digest), 'invalid raw file hash')
    _require(set(files) == set(blobs) - {'manifest.json'}, 'raw file coverage differs')
    _require(all(hashlib.sha256(blobs[name]).hexdigest() == digest for name, digest in files.items()),
             'raw file hash differs')
    _require('environment.jsonl' in files, 'original environment log required')
    _events(blobs['environment.jsonl'].decode('utf-8'))
    steps, events, reach = _teacher_and_ledger(manifest, blobs, completed_only)
    attempts = manifest.get('episodes')
    _require(isinstance(attempts, list) and attempts, 'episode attempts required')
    selected, samples, windows, prior_end = [], {}, [], 0
    for index, episode in enumerate(attempts):
        _require(isinstance(episode, dict) and type(episode.get('episode_index')) is int
                 and episode['episode_index'] == index, 'attempt indexes must be contiguous')
        _require(type(episode.get('complete')) is bool and type(episode.get('frames')) is int
                 and episode['frames'] >= 0 and episode.get('outcome') == 'unknown'
                 and isinstance(episode.get('reason'), str), 'attempt completion/outcome differs')
        _require(_text(episode.get('cycle_id')) and _text(episode.get('run_id'))
                 and _hash(episode.get('profile_sha256')), 'attempt lineage required')
        start, end = episode.get('start_ns'), episode.get('end_ns')
        _require(type(start) is int and type(end) is int and 0 < start < end <= MAX_TIME_NS and start >= prior_end,
                 'invalid or overlapping attempt windows')
        prior_end = end
        path = _relative(episode.get('samples_path'))
        _require(path in files, 'missing samples file')
        raw = blobs[path]
        _require(not raw or raw.endswith(b'\n'), 'partial sample log')
        rows, previous = [], start-1
        for number, line in enumerate(raw.splitlines()):
            row = _json(line)
            stamp = row.get('time_ns')
            _require(type(row.get('frame_index')) is int and row['frame_index'] == number
                     and type(stamp) is int and start <= stamp < end and stamp > previous,
                     'sample sequence or host clock differs')
            previous = stamp
            for key in ('observation.state', 'action'):
                _vector(row.get(key), normalized=True)
            _vector(row.get('requested_target_rad'), normalized=False)
            _require(all(_number(row.get(k)) and row[k] > 0
                         for k in ('joint_source_stamp', 'reference_source_stamp')), 'source stamps required')
            for key in ('joint_source_stamp', 'reference_source_stamp'):
                _source_ns(row[key])
            images = row.get('images')
            _require(isinstance(images, dict) and set(images) == set(shapes), 'both sample cameras required')
            for role, shape in shapes.items():
                image = images[role]
                _require(isinstance(image, dict), 'image descriptor required')
                name = _relative(image.get('path'))
                _require(name in files and image.get('sha256') == files[name]
                         and type(image.get('width')) is int and image['width'] == shape[1]
                         and type(image.get('height')) is int and image['height'] == shape[0]
                         and len(blobs[name]) == math.prod(shape)
                         and _number(image.get('source_stamp')) and image['source_stamp'] > 0,
                         'raw image bytes, shape or source stamp differs')
                _source_ns(image['source_stamp'])
            rows.append(row)
        _require(len(rows) == episode['frames'], 'attempt frame count differs')
        _require(not episode['complete'] or len(rows) >= 2, 'complete attempt must contain at least two frames')
        samples[index] = rows
        windows.append({key: episode[key] for key in ('episode_index', 'start_ns', 'end_ns', 'run_id',
                                                     'profile_sha256')})
        if episode['complete']:
            _completed_attempt(episode, steps, events, reach)
            selected.append(episode)
        else:
            _require(completed_only, 'incomplete attempt requires explicit completed-only selection')
    seal_environment(blobs['environment.jsonl'], windows, files, rig_revision=manifest['rig_revision'],
                     calibration_revision=manifest['calibration_revision'])
    _require(bool(selected) or not require_complete, 'no complete episodes selected')
    return dict(root=root, manifest=manifest, blobs=blobs, samples=samples, selected=selected,
                manifest_sha256=hashlib.sha256(blobs['manifest.json']).hexdigest())


def _small_json(value, depth=1):
    """teacher.source is a lineage note, never a trajectory: containers nest at most 3 deep, lists <= 1000
    (a median teacher names its source episodes); the caller also caps the serialized size."""
    if isinstance(value, dict):
        return depth <= 3 and all(isinstance(k, str) and _small_json(v, depth+1) for k, v in value.items())
    if isinstance(value, list):
        return depth <= 3 and len(value) <= 1000 and all(_small_json(v, depth+1) for v in value)
    return value is None or type(value) in (str, int, bool) or _number(value)


def _sealed_teacher(root, manifest, actual):
    """record_session --replay: the sealed trajectory is the fixed teacher; A=episode 0, B=episode 1."""
    teacher = manifest.get('teacher')
    _require(isinstance(teacher, dict) and teacher.get('kind') == 'replay_trajectory'
             and teacher.get('file') == TEACHER_FILE and teacher.get('schema') == TEACHER_SCHEMA,
             'sealed replay_trajectory teacher required')
    _require(TEACHER_FILE in actual, 'sealed teacher trajectory missing')
    _require(_hash(manifest.get('teacher_sha256')) and manifest['teacher_sha256'] == actual[TEACHER_FILE],
             'teacher trajectory differs from its teacher_sha256')
    trajectory = _json((root/TEACHER_FILE).read_bytes())
    source = teacher.get('source')
    _require(trajectory.get('schema') == TEACHER_SCHEMA and trajectory.get('source') == source,
             'teacher trajectory differs from its manifest')
    _require(isinstance(source, dict) and _small_json(source)
             and len(json.dumps(source, allow_nan=False).encode('utf-8')) <= 16384, 'teacher source must be small JSON')
    segments = teacher.get('segments')
    _require(isinstance(segments, dict) and set(segments) == {'A', 'reset', 'B'} and all(
        isinstance(v, list) and len(v) == 2 and all(type(i) is int for i in v) for v in segments.values()),
        'teacher segments must be integer frame ranges')
    (a0, a1), (r0, r1), (b0, b1) = segments['A'], segments['reset'], segments['B']
    # B is its own taught return leg of A's length, after a reset hold of at least one frame.
    _require(a0 == 0 < a1 == r0 < r1 == b0 and b1 - b0 == a1 - a0, 'teacher segments must be contiguous A, reset, B')
    frames = trajectory.get('frames')
    _require(trajectory.get('segments') == segments and isinstance(frames, list) and len(frames) == b1,
             'teacher segments differ from the trajectory frames')
    replay = _json((root/'session.json').read_bytes()).get('replay')
    _require(isinstance(replay, dict) and replay.get('sha256') == manifest['teacher_sha256']
             and replay.get('segments') == segments, 'session replay differs from the sealed teacher')
    _require(manifest.get('total_episodes') == 2, 'a replay recording has exactly episodes A and B')


def _sealed_collection(root, operator=None):
    """Re-hash a record_seal.py collection; the manifest must cover every file exactly.

    A scripted_teacher seal may lack session_id and revisions (local-main record_seal): the folder
    name is the session and the operator names the revisions; sealed values must equal them.
    """
    root = Path(root).absolute()
    raw = (root/'manifest.json').read_bytes()
    manifest = json.loads(raw)
    _require(manifest.get('schema') == 'rosy.omx-collection-session.v1' and manifest.get('state') == 'CLOSED'
             and manifest.get('mode') == 'hardware'
             and manifest.get('source_mode') in ('leader_native', 'scripted_teacher'),
             'sealed leader or scripted_teacher collection required')
    actual = {}
    for path in sorted(root.rglob('*')):
        _require(not path.is_symlink() and (path.is_dir() or path.is_file()), 'links and special files refused')
        if path.is_file() and path != root/'manifest.json':
            with path.open('rb') as stream:
                actual[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    teacher = manifest['source_mode'] == 'scripted_teacher'
    if teacher:
        _sealed_teacher(root, manifest, actual)
    _require(actual == manifest.get('files'), 'collection bytes differ from its manifest')
    if teacher:
        _require(isinstance(operator, dict) and all(_text(operator.get(k)) for k in REVISIONS),
                 'a scripted_teacher intake needs the operator --rig-revision and --calibration-revision')
        manifest['session_id_origin'] = 'seal' if 'session_id' in manifest else 'folder'
        manifest.setdefault('session_id', root.name)
        manifest['revision_origin'] = {k: 'seal' if k in manifest else 'operator' for k in REVISIONS}
        for key in REVISIONS:
            _require(manifest.setdefault(key, operator[key]) == operator[key], f'sealed {key} differs from the operator value')
    else:
        _require(operator is None, 'operator revisions apply to scripted_teacher intakes only')
    if not teacher or manifest['revision_origin']['calibration_revision'] == 'seal':
        rows = sorted((k, v) for k, v in actual.items() if k.startswith('calibration/'))
        _require(bool(rows) and manifest.get('calibration_revision')
                 == hashlib.sha256(json.dumps(rows).encode('utf-8')).hexdigest(), 'calibration revision differs')
    for key in ('session_id', 'rig_revision'):
        _require(isinstance(manifest.get(key), str) and manifest[key].strip() == manifest[key] != '',
                 f'sealed {key} required')
    _require(manifest['session_id'] == root.name, 'collection name differs from its sealed session id')
    return manifest, hashlib.sha256(raw).hexdigest()


def _source_episodes(root, repo_id):
    dataset = load_dataset(root, repo_id)
    return inspect_frames(dataset.meta.info, (dataset[i] for i in range(len(dataset))))['episodes']
