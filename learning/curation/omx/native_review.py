"""Offline native OMX dataset inspection and reviewed episode splits; no robot or upload."""
import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from omx_output_paths import in_source_checkout
from native_capture import bind_capture, check_capture_groups
from native_environment import bind_environment, seal_environment, split_coverage, validate_environment

JOINTS = ['shoulder_pan.pos', 'shoulder_lift.pos', 'elbow_flex.pos',
          'wrist_flex.pos', 'wrist_roll.pos', 'gripper.pos']
OBJECT_RESULTS = ('moved_as_intended', 'grasp_missed', 'dropped', 'displaced', 'untouched', 'unknown')


def _integer(value, name):
    array = np.asarray(value)
    if array.size != 1 or array.dtype.kind not in 'iu':
        raise ValueError(f'{name} must be an integer')
    return int(array.item())


def inspect_frames(info, frames):
    if info.get('robot_type') != 'omx_follower' or info.get('codebase_version') != 'v3.0':
        raise ValueError('expected native omx_follower LeRobot v3 data, not ROSY SIM')
    features = info.get('features', {})
    for key in ('action', 'observation.state'):
        if features.get(key, {}).get('names') != JOINTS or tuple(features[key].get('shape', ())) != (6,):
            raise ValueError('native OMX joint order and six position features are required')
    cameras = {key: value for key, value in features.items() if key.startswith('observation.images.')}
    if not cameras:
        raise ValueError('camera observations are required')
    fps = info.get('fps')
    if type(fps) not in (int, float) or not math.isfinite(fps) or fps <= 0:
        raise ValueError('fps must be finite and positive')
    episodes, digest, count, previous_time = [], None, 0, None
    for row in frames:
        episode = _integer(row.get('episode_index'), 'episode_index')
        frame = _integer(row.get('frame_index'), 'frame_index')
        if not episodes or episode != episodes[-1]['episode_index']:
            if episode != len(episodes) or frame != 0:
                raise ValueError('episode order or first frame index differs')
            if episodes:
                episodes[-1]['content_sha256'] = digest.hexdigest()
            episodes.append(dict(episode_index=episode, frames=0, outcome='unknown',
                                 object_result='unknown', split='exclude', reviewer='', reason=''))
            digest, previous_time = hashlib.sha256(), None
        if frame != episodes[-1]['frames']:
            raise ValueError('missing or duplicate frame index')
        stamp_array = np.asarray(row.get('timestamp'))
        if stamp_array.size != 1:
            raise ValueError('one timestamp per frame is required')
        stamp = float(stamp_array.item())
        if not math.isfinite(stamp) or abs(stamp - frame / fps) > 1e-3 or (
                previous_time is not None and stamp <= previous_time):
            raise ValueError('invalid or nonmonotonic episode timestamp')
        previous_time = stamp
        for key in ('action', 'observation.state', *sorted(cameras)):
            if key not in row:
                raise ValueError(f'missing {key}')
            value = np.asarray(row[key], dtype='<f4')
            if not np.isfinite(value).all():
                raise ValueError(f'nonfinite {key}')
            shape = (6,)
            if key in cameras:
                declared = cameras[key].get('shape', [])
                if len(declared) != 3 or declared[2] != 3:
                    raise ValueError('RGB camera metadata must declare HWC')
                shape = (3, declared[0], declared[1])
                if value.size and (value.min() < 0 or value.max() > 1):
                    raise ValueError('reader RGB must be normalized to [0, 1]')
            if value.shape != shape:
                raise ValueError(f'{key} shape differs from metadata')
            digest.update(key.encode() + value.tobytes())
        task = row.get('task')
        if not isinstance(task, str) or not task.strip():
            raise ValueError('task text is required')
        digest.update(json.dumps([frame, task], ensure_ascii=False).encode())
        episodes[-1]['frames'] += 1
        count += 1
    if not episodes or count != info.get('total_frames') or len(episodes) != info.get('total_episodes'):
        raise ValueError('incomplete dataset: frame/episode counts differ')
    episodes[-1]['content_sha256'] = digest.hexdigest()
    return dict(robot_type='omx_follower', lerobot_version='0.4.4', frame_count=count,
                joint_names=JOINTS[:], camera_keys=sorted(cameras), episodes=episodes)


def reviewed_splits(report, decisions):
    if report.get('source_mode') == 'unverified_native':
        raise ValueError('capture source must be explicitly declared before training')
    if not isinstance(decisions, list) or len(decisions) != len(report['episodes']):
        raise ValueError('review must cover every episode exactly once')
    splits, content_splits = {'train': [], 'eval': []}, {}
    if any(decision.get('split') == 'test' for decision in decisions):
        splits['test'] = []
    for source, decision in zip(report['episodes'], decisions):
        keys = ('episode_index', 'content_sha256', 'frames',
                *(key for key in ('session_id', 'cycle_id') if key in source))
        if any(source[key] != decision.get(key) for key in keys):
            raise ValueError('review identity differs from inspected source')
        split = decision.get('split')
        if split not in (*splits, 'exclude'):
            raise ValueError('split must be train, eval, test or exclude')
        if decision.get('outcome') not in ('success', 'failure', 'unknown'):
            raise ValueError('outcome must be success, failure or unknown')
        # Human-observed object effect, kept for action-outcome (world model) labels; not a split rule.
        if decision.get('object_result', 'unknown') not in OBJECT_RESULTS:
            raise ValueError('object_result must be one of ' + ', '.join(OBJECT_RESULTS))
        if split == 'exclude':
            continue
        if decision['outcome'] != 'success':
            raise ValueError('included demonstrations require operator-confirmed success')
        if any(not isinstance(decision.get(key), str) or not decision[key].strip()
               for key in ('reviewer', 'reason')):
            raise ValueError('included demonstrations need reviewer and reason')
        fingerprint = source['content_sha256']
        if fingerprint in content_splits and content_splits[fingerprint] != split:
            raise ValueError('duplicate episode content crosses train/eval splits')
        content_splits[fingerprint] = split
        splits[split].append(source['episode_index'])
    if not all(splits.values()):
        raise ValueError('nonempty independent train and eval splits are required')
    check_capture_groups(report['episodes'], decisions)
    if 'files' in report:
        validate_environment(report)
    return splits


def dataset_files(root):
    root = Path(root)
    files = {}
    for folder in ('meta', 'data', 'videos'):
        for path in sorted((root / folder).rglob('*')):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('dataset links are not accepted')
            if path.is_file() and path.suffix in ('.json', '.parquet', '.mp4'):
                with path.open('rb') as stream:
                    files[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    if 'meta/info.json' not in files or not any(p.startswith('data/') for p in files):
        raise ValueError('local dataset metadata and data files are required')
    return files


def load_dataset(root, repo_id):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_DATASETS_OFFLINE'] = '1'
    from huggingface_hub import constants
    if not constants.HF_HUB_OFFLINE:
        raise ValueError('use a fresh process with HF_HUB_OFFLINE=1')
    if importlib.metadata.version('lerobot') != '0.4.4':
        raise ValueError('native inspection requires lerobot==0.4.4')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    return LeRobotDataset(repo_id=repo_id, root=Path(root), video_backend='pyav', download_videos=False)


def inspect_dataset(root, repo_id, *, body_units, rig_revision, calibration_revision,
                    source_mode=None, capture_provenance=None, environment_evidence=None):
    root = Path(root).resolve()
    if body_units not in ('degrees', 'normalized_-100_100') or not all(
            isinstance(value, str) and value.strip() for value in (rig_revision, calibration_revision)):
        raise ValueError('explicit units, rig and calibration revisions are required')
    before = dataset_files(root)
    dataset = load_dataset(root, repo_id)
    report = inspect_frames(dataset.meta.info, (dataset[i] for i in range(len(dataset))))
    if dataset_files(root) != before:
        raise ValueError('dataset changed during inspection')
    report.update(repo_id=repo_id, files=before, body_units=body_units, gripper_units='normalized_0_100',
                  rig_revision=rig_revision, calibration_revision=calibration_revision,
                  reader_verified=True)
    report.update(bind_capture(report['episodes'], before, source_mode=source_mode,
                               body_units=body_units, rig_revision=rig_revision,
                               calibration_revision=calibration_revision, provenance=capture_provenance))
    report['environment_summary'] = bind_environment(
        report['episodes'], before, rig_revision=rig_revision,
        calibration_revision=calibration_revision, evidence=environment_evidence)
    if environment_evidence is not None:
        report['environment_evidence'] = copy.deepcopy(environment_evidence)
    return report


def _new_output(path, source):
    path, source = Path(path).resolve(), Path(source).resolve()
    if in_source_checkout(path) or path == source or path.is_relative_to(source) or source.is_relative_to(path):
        raise ValueError('output must be separate from source and outside the source checkout')
    if path.exists():
        raise ValueError('output already exists')
    return path


def write_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def split_reviewed(root, report, decisions, output):
    output = _new_output(output, root)
    current = inspect_dataset(root, report['repo_id'], body_units=report['body_units'],
                              rig_revision=report['rig_revision'],
                              calibration_revision=report['calibration_revision'],
                              source_mode=report['source_mode'] if report['source_mode'] != 'unverified_native' else None,
                              capture_provenance=report.get('capture_provenance'),
                              environment_evidence=report.get('environment_evidence'))
    current = copy.deepcopy(current)
    current.setdefault('environment_summary', validate_environment(current))
    expected = copy.deepcopy(report)
    if 'environment_summary' not in expected and expected.get('environment_evidence') is None:
        expected['environment_summary'] = validate_environment(expected)
    if current != expected:
        raise ValueError('inspection report no longer matches source')
    splits = reviewed_splits(current, decisions)
    from lerobot.datasets.dataset_tools import split_dataset
    dataset = load_dataset(root, report['repo_id'])
    produced = split_dataset(dataset, splits, output_dir=output)
    for name, child in produced.items():
        # Upstream split_dataset does not preserve the source video backend.
        child = load_dataset(output / name, child.repo_id)
        inspect_frames(child.meta.info, (child[i] for i in range(len(child))))
    if dataset_files(root) != report['files']:
        raise ValueError('source dataset changed during splitting; no success receipt written')
    write_json(output / 'split-receipt.json', dict(source=current, decisions=decisions, splits=splits,
                                                 outputs={name: dataset_files(output / name) for name in produced},
                                                 environment_coverage=split_coverage(
                                                     validate_environment(current), decisions),
                                                 reader_verified=True, uploaded=False))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inspect = commands.add_parser('inspect')
    inspect.add_argument('root', type=Path)
    inspect.add_argument('--repo-id', required=True)
    inspect.add_argument('--body-units', choices=('degrees', 'normalized_-100_100'), required=True)
    inspect.add_argument('--rig-revision', required=True)
    inspect.add_argument('--calibration-revision', required=True)
    inspect.add_argument('--source-mode', choices=('leader_native', 'scripted_teacher'))
    inspect.add_argument('--capture-provenance', type=Path,
                         help='byte-bound scripted teacher capture manifest; not device acceptance')
    inspect.add_argument('--environment-evidence', type=Path,
                         help='sealed original environment log and host-clock episode windows')
    inspect.add_argument('--out', type=Path, required=True)
    split = commands.add_parser('split')
    split.add_argument('root', type=Path)
    split.add_argument('--report', type=Path, required=True)
    split.add_argument('--decisions', type=Path, required=True)
    split.add_argument('--out', type=Path, required=True)
    seal = commands.add_parser('seal-environment', help='bind closed log and recorder-declared episode windows')
    seal.add_argument('root', type=Path)
    seal.add_argument('--log', type=Path, required=True)
    seal.add_argument('--windows', type=Path, required=True)
    seal.add_argument('--rig-revision', required=True)
    seal.add_argument('--calibration-revision', required=True)
    seal.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'seal-environment':
            output = _new_output(args.out, args.root)
            before = dataset_files(args.root)
            evidence = seal_environment(args.log.read_bytes(), json.loads(args.windows.read_text(encoding='utf-8')),
                                        before, rig_revision=args.rig_revision,
                                        calibration_revision=args.calibration_revision)
            if dataset_files(args.root) != before:
                raise ValueError('environment: dataset changed during sealing')
            write_json(output / 'environment.json', evidence)
        elif args.command == 'inspect':
            output = _new_output(args.out, args.root)
            report = inspect_dataset(args.root, args.repo_id, body_units=args.body_units,
                                     rig_revision=args.rig_revision, calibration_revision=args.calibration_revision,
                                     source_mode=args.source_mode,
                                     capture_provenance=json.loads(args.capture_provenance.read_text(encoding='utf-8'))
                                     if args.capture_provenance else None,
                                     environment_evidence=json.loads(args.environment_evidence.read_text(encoding='utf-8'))
                                     if args.environment_evidence else None)
            write_json(output / 'inspection.json', report)
            write_json(output / 'decisions.json', report['episodes'])
        else:
            split_reviewed(args.root, json.loads(args.report.read_text(encoding='utf-8')),
                           json.loads(args.decisions.read_text(encoding='utf-8')), args.out)
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(f'Written: {args.out}; no upload or device action performed.')


if __name__ == '__main__':
    main()
