"""Offline, closed OMX collection sessions into inspected native LeRobot datasets."""
from __future__ import annotations

import argparse
from omx_output_paths import in_source_checkout
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_capture import ACTION, SCHEMA as CAPTURE_SCHEMA
from native_environment import ROLES, _events, _roles, seal_environment
from native_review import JOINTS, dataset_files, inspect_dataset, write_json

SCHEMA = 'rosy.omx-collection-session.v1'
MAX_TIME_NS = 2**63-1


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


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


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


def prepare(sessions, output, repo_id, *, completed_only=False, camera_references=None):
    """Produce a new, locally read-back dataset; leave all decisions unknown/exclude.

    ``camera_references`` (role -> reference JSON path) adds D-792 shadow checks as camera-setup.json."""
    records = [validate_session(path, completed_only=completed_only) for path in sessions]
    _require(bool(records), 'at least one session required')
    output = Path(output).absolute()
    _require(not output.exists() and not in_source_checkout(output), 'new output outside the source checkout required')
    for record in records:
        source = record['root']
        _require(not output.resolve().is_relative_to(source) and not source.is_relative_to(output.resolve()),
                 'output must be separate from every source')
    baseline = records[0]['manifest']
    keys = ('fps', 'task', 'rig_revision', 'calibration_revision', 'teacher_sha256', 'camera_shapes')
    _require(all(all(r['manifest'][k] == baseline[k] for k in keys) for r in records),
             'aggregate session configuration differs')
    _require(len({r['manifest']['session_id'] for r in records}) == len(records), 'duplicate session identity')
    records.sort(key=lambda r: r['manifest']['episodes'][0]['start_ns'])
    prior_end, prior_log, raw_logs = 0, 0, []
    episodes = []
    for record in records:
        attempts = record['manifest']['episodes']
        _require(attempts[0]['start_ns'] >= prior_end, 'aggregate session windows overlap')
        prior_end = attempts[-1]['end_ns']
        raw = record['blobs']['environment.jsonl']
        events = _events(raw.decode('utf-8'))
        _require(events[0]['recorded_ns'] > prior_log, 'aggregate environment clocks overlap')
        prior_log = events[-1]['recorded_ns']
        raw_logs.append(raw)
        episodes.extend((record, episode) for episode in record['selected'])
    windows = [dict(episode_index=i, **{k: e[k] for k in ('start_ns', 'end_ns', 'run_id', 'profile_sha256')})
               for i, (_, e) in enumerate(episodes)]
    # Validate combined log and selected windows before importing or writing LeRobot.
    raw_log = b''.join(raw_logs)
    seal_environment(raw_log, windows, {'validated': '0'*64}, rig_revision=baseline['rig_revision'],
                     calibration_revision=baseline['calibration_revision'])
    _require(importlib.metadata.version('lerobot') == '0.4.4', 'lerobot==0.4.4 required')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_DATASETS_OFFLINE'] = '1'
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    features = {key: dict(dtype='float32', shape=(6,), names=JOINTS[:])
                for key in ('observation.state', 'action')}
    features['source.capture_time_ns'] = dict(dtype='int64', shape=(1,), names=['fleet_host_unix_ns'])
    for source in ('joint', 'reference', *baseline['camera_shapes']):
        features[f'source.{source}_time_ns'] = dict(dtype='int64', shape=(1,), names=[source+'_source_unix_ns'])
    features.update({f'observation.images.{role}': dict(dtype='video', shape=tuple(shape),
                     names=['height', 'width', 'channels']) for role, shape in baseline['camera_shapes'].items()})
    dataset = LeRobotDataset.create(repo_id=repo_id, fps=baseline['fps'], root=output,
                                   robot_type='omx_follower', features=features, use_videos=True,
                                   video_backend='pyav', vcodec='h264', batch_encoding_size=1)
    try:
        for record, episode in episodes:
            for row in record['samples'][episode['episode_index']]:
                frame = {k: np.array(row[k], dtype=np.float32) for k in ('observation.state', 'action')}
                frame['source.capture_time_ns'] = np.array([row['time_ns']], dtype=np.int64)
                for source in ('joint', 'reference'):
                    frame[f'source.{source}_time_ns'] = np.array(
                        [_source_ns(row[source+'_source_stamp'])], dtype=np.int64)
                for role, shape in baseline['camera_shapes'].items():
                    frame[f'observation.images.{role}'] = np.frombuffer(
                        record['blobs'][row['images'][role]['path']], dtype=np.uint8).reshape(shape).copy()
                    frame[f'source.{role}_time_ns'] = np.array(
                        [_source_ns(row['images'][role]['source_stamp'])], dtype=np.int64)
                frame['task'] = baseline['task']
                dataset.add_frame(frame)
            dataset.save_episode(parallel_encoding=False)
    finally:
        dataset.finalize()
    files = dataset_files(output)
    capture = dict(schema=CAPTURE_SCHEMA, source_mode='scripted_teacher', action_semantics=ACTION,
                   body_units=baseline['body_units'], gripper_units=baseline['gripper_units'],
                   rig_revision=baseline['rig_revision'], calibration_revision=baseline['calibration_revision'],
                   teacher_sha256=baseline['teacher_sha256'], files=files,
                   episodes=[dict(episode_index=i, session_id=r['manifest']['session_id'], cycle_id=e['cycle_id'])
                             for i, (r, e) in enumerate(episodes)])
    environment = seal_environment(raw_log, windows, files, rig_revision=baseline['rig_revision'],
                                   calibration_revision=baseline['calibration_revision'])
    report = inspect_dataset(output, repo_id, body_units=baseline['body_units'],
                             rig_revision=baseline['rig_revision'],
                             calibration_revision=baseline['calibration_revision'],
                             source_mode='scripted_teacher', capture_provenance=capture,
                             environment_evidence=environment)
    _require(report['frame_count'] == sum(e['frames'] for _, e in episodes)
             and len(report['episodes']) == len(episodes), 'readback counts differ')
    for record in records:
        # Re-read source before writing the success receipt. Copies use validated original bytes.
        _require(_read_source(record['root'])[1] == record['blobs'], 'source changed during conversion')
    for i, record in enumerate(records):
        for relative, blob in record['blobs'].items():
            target = output / 'rosy_provenance' / f'session-{i:06d}' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
    receipt = dict(schema='rosy.omx-collection-intake.v1', reader_verified=True, uploaded=False,
                   completed_only=completed_only, fixture_only=False,
                   sessions=[dict(session_id=r['manifest']['session_id'], manifest_sha256=r['manifest_sha256'],
                                  manifest=r['manifest'], provenance_path=f'rosy_provenance/session-{i:06d}')
                             for i, r in enumerate(records)],
                   episodes=[dict(episode_index=i, session_id=r['manifest']['session_id'],
                                  attempt_index=e['episode_index'], cycle_id=e['cycle_id'])
                             for i, (r, e) in enumerate(episodes)])
    documents = [('capture.json', capture), ('environment.json', environment),
                 ('inspection.json', report), ('decisions.json', report['episodes'])]
    if camera_references:
        import camera_setup_intake
        references = {role: camera_setup_intake.load_reference(path) for role, path in camera_references.items()}
        documents.append(('camera-setup.json', camera_setup_intake.report(records, episodes, references)))
    for name, document in (*documents, ('intake-receipt.json', receipt)):
        write_json(output / name, document)
    return receipt


def camera_references(pairs):
    """``ROLE=PATH`` options as a role -> path map; one reference per role."""
    result = {}
    for pair in pairs:
        role, sep, path = pair.partition('=')
        _require(sep and role and path and role not in result, 'camera reference must be ROLE=PATH once per role')
        result[role] = Path(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('prepare')
    command.add_argument('sessions', nargs='+', type=Path)
    command.add_argument('--out', type=Path, required=True)
    command.add_argument('--repo-id', required=True)
    command.add_argument('--completed-only', action='store_true')
    command.add_argument('--camera-reference', action='append', default=[], metavar='ROLE=PATH',
                         help='D-792 camera setup reference JSON per camera role; adds shadow checks')
    args = parser.parse_args()
    try:
        prepare(args.sessions, args.out, args.repo_id, completed_only=args.completed_only,
                camera_references=camera_references(args.camera_reference))
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(f'Written: {args.out}; review required, no upload or device action performed.')


if __name__ == '__main__':
    main()
