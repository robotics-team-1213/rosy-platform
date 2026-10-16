"""Offline, closed OMX collection sessions into inspected native LeRobot datasets."""
from __future__ import annotations

import argparse
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
from native_environment import _events, seal_environment
from native_review import JOINTS, dataset_files, inspect_dataset, write_json

SCHEMA = 'rosy.omx-collection-session.v1'


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


def validate_session(root, *, completed_only=False):
    """Validate every attempt and every raw byte before selecting complete episodes."""
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
    _require(isinstance(shapes, dict) and set(shapes) == {'top', 'front'}, 'both camera shapes required')
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
        _require(type(start) is int and type(end) is int and 0 < start < end and start >= prior_end,
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
            rows.append(row)
        _require(len(rows) == episode['frames'], 'attempt frame count differs')
        _require(not episode['complete'] or bool(rows), 'complete attempt must contain frames')
        samples[index] = rows
        windows.append({key: episode[key] for key in ('episode_index', 'start_ns', 'end_ns', 'run_id',
                                                     'profile_sha256')})
        if episode['complete']:
            selected.append(episode)
        else:
            _require(completed_only, 'incomplete attempt requires explicit completed-only selection')
    seal_environment(blobs['environment.jsonl'], windows, files, rig_revision=manifest['rig_revision'],
                     calibration_revision=manifest['calibration_revision'])
    _require(bool(selected), 'no complete episodes selected')
    return dict(root=root, manifest=manifest, blobs=blobs, samples=samples, selected=selected,
                manifest_sha256=hashlib.sha256(blobs['manifest.json']).hexdigest())


def prepare(sessions, output, repo_id, *, completed_only=False):
    """Produce a new, locally read-back dataset; leave all decisions unknown/exclude."""
    records = [validate_session(path, completed_only=completed_only) for path in sessions]
    _require(bool(records), 'at least one session required')
    output = Path(output).absolute()
    _require(not output.exists() and output.drive.upper() != 'F:', 'new output outside source drive required')
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
    features.update({f'observation.images.{role}': dict(dtype='video', shape=tuple(shape),
                     names=['height', 'width', 'channels']) for role, shape in baseline['camera_shapes'].items()})
    dataset = LeRobotDataset.create(repo_id=repo_id, fps=baseline['fps'], root=output,
                                   robot_type='omx_follower', features=features, use_videos=True,
                                   video_backend='pyav', vcodec='h264', batch_encoding_size=1)
    try:
        for record, episode in episodes:
            for row in record['samples'][episode['episode_index']]:
                frame = {k: np.array(row[k], dtype=np.float32) for k in ('observation.state', 'action')}
                for role, shape in baseline['camera_shapes'].items():
                    frame[f'observation.images.{role}'] = np.frombuffer(
                        record['blobs'][row['images'][role]['path']], dtype=np.uint8).reshape(shape).copy()
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
    for name, document in (('capture.json', capture), ('environment.json', environment),
                           ('inspection.json', report), ('decisions.json', report['episodes']),
                           ('intake-receipt.json', receipt)):
        write_json(output / name, document)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('prepare')
    command.add_argument('sessions', nargs='+', type=Path)
    command.add_argument('--out', type=Path, required=True)
    command.add_argument('--repo-id', required=True)
    command.add_argument('--completed-only', action='store_true')
    args = parser.parse_args()
    try:
        prepare(args.sessions, args.out, args.repo_id, completed_only=args.completed_only)
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(f'Written: {args.out}; review required, no upload or device action performed.')


if __name__ == '__main__':
    main()
