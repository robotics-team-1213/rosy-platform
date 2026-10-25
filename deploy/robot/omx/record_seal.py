#!/usr/bin/env python3
"""Seal one finished native recording (leader or scripted teacher) as a closed collection for the model-PC transfer.

Runs on the site PC after record_session.py, from no robot or camera access:

    python record_seal.py --session-dir <dir where record_session.py ran> --name <new collection name>         --rig-revision <bench layout name> --calibration <follower/leader calibration json> ...

It accepts only a safe, non-teleop recording that exited 0 without interruption. It copies the
LeRobot dataset, session.json and the recording config into ~/rosy-test/omx-collections/<name>/
and writes the manifest last. The operator names the rig revision and the calibration files used;
nothing is inferred. The collection name is the session id and episode i is cycle `<name>-ep<i>`
(D-848), so the model PC can keep one recording in one train/eval split.
tools/remote/omx_collection_transfer.py then moves it to the model PC.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time


def _hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _hashes(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or (path.exists() and not (path.is_file() or path.is_dir())):
            raise ValueError('links and special files are not accepted in a recording')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = _hash(path)
    return result


def calibration_revision(files):
    """One digest over the copied calibration files; the model-PC intake recomputes it."""
    rows = sorted((k, v) for k, v in files.items() if k.startswith('calibration/'))
    return hashlib.sha256(json.dumps(rows).encode('utf-8')).hexdigest()


def seal(session_dir, name, collections, *, rig_revision, calibrations):
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', name):
        raise ValueError('collection name must be a safe basename')
    if not isinstance(rig_revision, str) or not rig_revision.strip() or rig_revision != rig_revision.strip():
        raise ValueError('explicit rig revision required')
    calibrations = [Path(path) for path in calibrations]
    names = [path.name for path in calibrations]
    if not calibrations or len(set(names)) != len(names) or not all(
            path.suffix == '.json' and path.is_file() and not path.is_symlink() for path in calibrations):
        raise ValueError('explicit distinct calibration json files required')
    session_dir = Path(session_dir)
    session = json.loads((session_dir/'session.json').read_text(encoding='utf-8'))
    if (session.get('safe_end') is not True or session.get('teleop_only') is not False
            or session.get('exit_code') != 0 or session.get('interrupted')):
        raise ValueError('only a safe, completed, non-teleop recording can be sealed')
    source_mode = session.get('source_mode', 'leader_native')
    teacher_path = None
    if source_mode == 'scripted_teacher':  # record_session --replay: the trajectory is the teacher
        replay = session.get('replay') or {}
        if not (isinstance(replay.get('sha256'), str) and replay.get('path')):
            raise ValueError('a scripted_teacher recording needs its replay path and sha256')
        teacher_path = Path(replay['path'])
        if not teacher_path.is_file() or teacher_path.is_symlink() or _hash(teacher_path) != replay['sha256']:
            raise ValueError('the replay trajectory is missing or differs from the one recorded')
    elif source_mode != 'leader_native':
        raise ValueError('only leader_native or scripted_teacher recordings can be sealed')
    config_path = Path(session['config'])
    if not config_path.is_absolute():
        config_path = session_dir/config_path
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    dataset = Path(config['dataset']['root'])
    info = json.loads((dataset/'meta'/'info.json').read_text(encoding='utf-8'))
    if info.get('codebase_version') != 'v3.0' or info.get('robot_type') not in ('omx_follower', 'bi_omx_follower'):
        raise ValueError('native OMX LeRobot v3 dataset required')
    before = _hashes(dataset)
    collections = Path(collections)
    target = collections/name
    staging = collections/f'.{name}.sealing'
    if target.exists() or staging.exists():
        raise ValueError('collection exists; choose a new name')
    collections.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        shutil.copytree(dataset, staging/'dataset')
        shutil.copyfile(session_dir/'session.json', staging/'session.json')
        shutil.copyfile(config_path, staging/'record-config.json')
        (staging/'calibration').mkdir()
        for path in calibrations:
            shutil.copyfile(path, staging/'calibration'/path.name)
        if teacher_path is not None:
            (staging/'teacher').mkdir()
            shutil.copyfile(teacher_path, staging/'teacher'/'trajectory.json')
        if _hashes(dataset) != before:
            raise ValueError('dataset changed while sealing')
        files = _hashes(staging)
        if {k.removeprefix('dataset/'): v for k, v in files.items() if k.startswith('dataset/')} != before:
            raise ValueError('copied dataset differs from the recording')
        manifest = dict(schema='rosy.omx-collection-session.v1', state='CLOSED', mode='hardware',
                        source_mode=source_mode, robot_type=info['robot_type'],
                        total_episodes=info.get('total_episodes'), sealed_ns=time.time_ns(),
                        session_id=name, rig_revision=rig_revision,
                        calibration_revision=calibration_revision(files), files=files)
        if teacher_path is not None:
            trajectory = json.loads((staging/'teacher'/'trajectory.json').read_text(encoding='utf-8'))
            manifest.update(teacher_sha256=files['teacher/trajectory.json'], teacher=dict(
                kind='replay_trajectory', file='teacher/trajectory.json', schema=trajectory.get('schema'),
                segments=session['replay'].get('segments'), source=trajectory.get('source')))
        with (staging/'manifest.json').open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)  # the recording itself is never touched
        raise
    return dict(collection=str(target), file_count=len(files), robot_type=info['robot_type'],
                total_episodes=info.get('total_episodes'))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--session-dir', required=True, type=Path)
    parser.add_argument('--name', required=True)
    parser.add_argument('--rig-revision', required=True)
    parser.add_argument('--calibration', action='append', required=True, type=Path)
    parser.add_argument('--collections', type=Path, default=Path.home()/'rosy-test'/'omx-collections')
    args = parser.parse_args()
    try:
        result = seal(args.session_dir, args.name, args.collections,
                      rig_revision=args.rig_revision, calibrations=args.calibration)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    sys.stdout.write(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
