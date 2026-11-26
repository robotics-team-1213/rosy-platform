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


_OFFSET_JOINTS = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')


def _cal_side(path: Path, data: dict) -> str | None:
    if any(isinstance(v, dict) and isinstance(v.get('id'), int) and v['id'] >= 10 for v in data.values()):
        return 'follower'
    if any(isinstance(v, dict) and isinstance(v.get('id'), int) and 1 <= v['id'] <= 9 for v in data.values()):
        return 'leader'
    low = str(path).lower()
    if 'follower' in low:
        return 'follower'
    if 'leader' in low:
        return 'leader'
    return None


def _build_leader_follower_offset(calibrations, mounts, session, arm_id) -> dict | None:
    """Build structured leader/follower calibration, mount, and gripper offset summary for downstream training."""
    follower_docs, leader_docs = [], []
    for path in calibrations:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            continue
        side = _cal_side(path, data)
        if side == 'follower':
            follower_docs.append((path, data))
        elif side == 'leader':
            leader_docs.append((path, data))
    mount_docs = [(p, json.loads(p.read_text(encoding='utf-8'))) for p in mounts]
    for p, doc in mount_docs:
        if not isinstance(doc, dict):
            raise ValueError(f'mount file {p.name} must contain a JSON object')
    f_entry = next(((p, d) for p, d in follower_docs if any(j in d for j in _OFFSET_JOINTS)), None)
    l_entry = next(((p, d) for p, d in leader_docs if any(j in d for j in _OFFSET_JOINTS)), None)
    if not mount_docs and not (f_entry and l_entry):
        return None
    f_path, f_data = f_entry or (follower_docs[0] if follower_docs else (None, {}))
    l_path, l_data = l_entry or (leader_docs[0] if leader_docs else (None, {}))
    mount_map, floor_map, grip_map = {}, {}, None
    for _, doc in mount_docs:
        if isinstance(doc.get('mount'), dict):
            mount_map.update(doc['mount'])
        if isinstance(doc.get('follower_floor'), dict):
            floor_map.update(doc['follower_floor'])
        if isinstance(doc.get('gripper'), dict):
            grip_map = dict(doc['gripper'])
    joints = {}
    for joint in _OFFSET_JOINTS:
        fj = f_data.get(joint) if isinstance(f_data.get(joint), dict) else None
        lj = l_data.get(joint) if isinstance(l_data.get(joint), dict) else None
        if not fj and not lj and joint not in mount_map and joint not in floor_map and not (joint == 'gripper' and grip_map):
            continue
        row = {}
        for key, jdoc in (('follower', fj), ('leader', lj)):
            if jdoc:
                row[key] = {k: jdoc[k] for k in ('id', 'drive_mode', 'homing_offset', 'range_min', 'range_max') if k in jdoc}
        if fj and lj:
            for field, delta_key in (('homing_offset', 'homing_offset_delta'), ('range_min', 'range_min_delta'), ('range_max', 'range_max_delta')):
                if isinstance(fj.get(field), (int, float)) and isinstance(lj.get(field), (int, float)):
                    row[delta_key] = fj[field] - lj[field]
            if 'drive_mode' in fj and 'drive_mode' in lj:
                row['drive_mode_inverted'] = fj['drive_mode'] != lj['drive_mode']
        if joint != 'gripper':
            row['mount_offset_ticks'] = int(mount_map.get(joint, 0)) if isinstance(mount_map.get(joint, 0), (int, float)) else mount_map.get(joint, 0)
            if joint in floor_map:
                row['follower_floor_tick'] = floor_map[joint]
        elif grip_map:
            gm = dict(grip_map)
            lo, lc = gm.get('leader_open'), gm.get('leader_closed')
            fo, fc = gm.get('follower_open'), gm.get('follower_closed')
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lo, lc, fo, fc)) and lo != lc:
                gm['scale'] = round((fo - fc) / (lo - lc), 6)
                if fj and isinstance(fj.get('range_min'), (int, float)) and isinstance(fj.get('range_max'), (int, float)):
                    rmin, rmax = fj['range_min'], fj['range_max']
                    if rmax > rmin:
                        gm['follower_closed_norm'] = round((fc - rmin) / (rmax - rmin) * 100.0, 4)
                        gm['follower_open_norm'] = round((fo - rmin) / (rmax - rmin) * 100.0, 4)
            row['grip_map'] = gm
        joints[joint] = row
    out = {
        'schema': 'rosy.omx-leader-follower-offset.v1',
        'arm_id': arm_id,
        'follower_calibration': f_path.name if f_path else None,
        'leader_calibration': l_path.name if l_path else None,
        'mount_files': [p.name for p, _ in mount_docs],
        'mount': mount_map,
        'follower_floor': floor_map,
        'grip_map': grip_map,
        'joints': joints,
    }
    if isinstance(session.get('teleop_stage'), (int, float)) and not isinstance(session.get('teleop_stage'), bool):
        out['teleop_stage_deg_s'] = session['teleop_stage']
    return out


def seal(session_dir, name, collections, *, rig_revision, calibrations, mounts=()):
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', name):
        raise ValueError('collection name must be a safe basename')
    if not isinstance(rig_revision, str) or not rig_revision.strip() or rig_revision != rig_revision.strip():
        raise ValueError('explicit rig revision required')
    calibrations = [Path(path) for path in calibrations]
    names = [path.name for path in calibrations]
    if not calibrations or len(set(names)) != len(names) or not all(
            path.suffix == '.json' and path.is_file() and not path.is_symlink() for path in calibrations):
        raise ValueError('explicit distinct calibration json files required')
    mounts = [Path(path) for path in (mounts or ())]
    mount_names = [path.name for path in mounts]
    if len(set(mount_names)) != len(mount_names) or any(
            path.suffix != '.json' or not path.is_file() or path.is_symlink() for path in mounts):
        raise ValueError('explicit distinct mount json files required')
    if set(mount_names) & set(names) or 'leader_follower_offset.json' in (set(names) | set(mount_names)):
        raise ValueError('mount and calibration filenames must be distinct and reserve leader_follower_offset.json')
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
    if (session_dir / 'DO_NOT_TRAIN.txt').exists() or (dataset / 'DO_NOT_TRAIN.txt').exists():
        raise ValueError('DO_NOT_TRAIN recordings cannot be sealed')
    info = json.loads((dataset/'meta'/'info.json').read_text(encoding='utf-8'))
    if info.get('codebase_version') != 'v3.0' or info.get('robot_type') not in ('omx_follower', 'bi_omx_follower'):
        raise ValueError('native OMX LeRobot v3 dataset required')
    if int(info.get('total_episodes') or 0) < 1:
        raise ValueError('recording must contain at least 1 episode to seal')
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
        for path in mounts:
            shutil.copyfile(path, staging/'calibration'/path.name)
        arm_id = session.get('arm') if session.get('arm') in ('arm_a', 'arm_b', 'arm_s', 'arm_ab') else None
        if not arm_id:
            robot_cfg_pre = config.get('robot') if isinstance(config.get('robot'), dict) else {}
            if info['robot_type'] == 'bi_omx_follower':
                arm_id = 'arm_ab'
            elif str(robot_cfg_pre.get('id') or '').endswith(('_a', '_b', '_s')):
                arm_id = f"arm_{str(robot_cfg_pre['id'])[-1]}"
        offset_doc = _build_leader_follower_offset(calibrations, mounts, session, arm_id)
        if offset_doc is not None:
            (staging/'calibration'/'leader_follower_offset.json').write_text(
                json.dumps(offset_doc, indent=2, allow_nan=False) + '\n', encoding='utf-8')
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
        if arm_id:
            manifest['arm_id'] = arm_id
        if offset_doc is not None:
            manifest['calibration_offset'] = {
                'schema': 'rosy.omx-leader-follower-offset.v1',
                'file': 'calibration/leader_follower_offset.json',
                'sha256': files['calibration/leader_follower_offset.json'],
                'mount_files': [f'calibration/{p.name}' for p in mounts],
                'has_grip_map': bool(offset_doc.get('grip_map')),
                'has_mount_offset': bool(offset_doc.get('mount')),
            }
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
    parser.add_argument('--mount', action='append', default=[], type=Path)
    parser.add_argument('--collections', type=Path, default=Path.home()/'rosy-test'/'omx-collections')
    args = parser.parse_args()
    try:
        result = seal(args.session_dir, args.name, args.collections,
                      rig_revision=args.rig_revision, calibrations=args.calibration, mounts=args.mount)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    sys.stdout.write(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
