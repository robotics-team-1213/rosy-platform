"""Human-reviewed native OMX grasp segments; offline export, never transforms actions or uploads."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_review as native

SCHEMA = 'rosy.omx-native-segments.v1'
DEFAULT_FEATURES = {'timestamp', 'frame_index', 'episode_index', 'index', 'task_index'}


def digest(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def selection(report, segments):
    return dict(schema=SCHEMA, source_sha256=digest(report), segments=copy.deepcopy(segments))


def validate_selection(report, document, *, require_splits=True):
    """Frame ranges are half-open, and parent identity/grouping never changes on cropping."""
    if (not isinstance(document, dict) or set(document) != {'schema', 'source_sha256', 'segments'}
            or document['schema'] != SCHEMA or document['source_sha256'] != digest(report)):
        raise ValueError('segment source binding or schema differs')
    if report.get('source_mode') not in ('leader_native', 'scripted_teacher'):
        raise ValueError('segments require a declared native source')
    rows = document['segments']
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError('bounded segment list required')
    splits, groups, seen = {'train': [], 'eval': []}, {}, set()
    excluded = native.excluded_indexes(report)
    if any(isinstance(row, dict) and row.get('split') == 'test' for row in rows):
        splits['test'] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or type(row.get('episode_index')) is not int:
            raise ValueError('integer source episode_index required')
        episode = row['episode_index']
        if not 0 <= episode < len(report['episodes']):
            raise ValueError('unknown source episode')
        source = report['episodes'][episode]
        identity = ('episode_index', 'content_sha256', 'frames',
                    *(key for key in ('session_id', 'cycle_id') if key in source))
        required = {*identity, 'start_frame', 'end_frame', 'object', 'intervention',
                    'outcome', 'reviewer', 'reason', 'split'}
        if set(row) != required or any(row[key] != source[key] for key in identity):
            raise ValueError('segment identity differs from original episode')
        start, end = row['start_frame'], row['end_frame']
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= source['frames']:
            raise ValueError('invalid segment frame range')
        if (episode, start, end) in seen:
            raise ValueError('duplicate segment range')
        seen.add((episode, start, end))
        if row['outcome'] not in ('success', 'failure', 'unknown') or type(row['intervention']) is not bool:
            raise ValueError('explicit human outcome and boolean intervention required')
        if row['split'] not in (*splits, 'exclude'):
            raise ValueError('invalid segment split')
        for key in ('reviewer', 'reason', 'object'):
            if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 1000:
                raise ValueError(f'segment {key} required (1..1000 characters)')
        if row['split'] == 'exclude' or episode in excluded:
            continue
        if row['outcome'] != 'success' or row['intervention']:
            raise ValueError('included segments require human-confirmed success without intervention')
        for key in ('episode_index', 'content_sha256', 'session_id', 'cycle_id'):
            if key not in source:
                continue
            group = (key, source[key])
            if group in groups and groups[group] != row['split']:
                raise ValueError(f'parent {key} crosses segment splits')
            groups[group] = row['split']
        splits[row['split']].append(index)
    if require_splits and not all(splits.values()):
        raise ValueError('nonempty independent train and eval segment splits required')
    return splits


def parent_decisions(report, document):
    """Project split membership for parent environment coverage, preserving unknown parent outcomes."""
    rows = copy.deepcopy(report['episodes'])
    for row in rows:
        row['split'] = 'exclude'
    excluded = native.excluded_indexes(report)
    for segment in document['segments']:
        if segment['split'] != 'exclude' and segment['episode_index'] not in excluded:
            rows[segment['episode_index']]['split'] = segment['split']
    return rows


def validate_receipt(receipt):
    selected = validate_selection(receipt['source'], receipt['segment_selection'])
    if receipt.get('decisions') != parent_decisions(receipt['source'], receipt['segment_selection']):
        raise ValueError('parent coverage decisions differ from segment lineage')
    expected = {name: [dict(child_episode_index=i, segment_index=index,
                            **{key: receipt['segment_selection']['segments'][index][key]
                               for key in ('episode_index', 'content_sha256', 'start_frame', 'end_frame')})
                       for i, index in enumerate(indices)] for name, indices in selected.items()}
    if receipt.get('segment_lineage') != expected:
        raise ValueError('child episode lineage differs from original segment ranges')
    return selected


def copy_frame(row, features):
    result = {}
    for key in features:
        value = np.asarray(row[key])
        if key.startswith('observation.images.'):
            value = np.rint(value.transpose(1, 2, 0) * 255).astype(np.uint8)
        elif 'shape' in features[key]:
            # LeRobot readers squeeze singleton numeric features; writers require their declared shape.
            value = value.reshape(features[key]['shape'])
        result[key] = value.copy()
    result['task'] = row['task']
    return result


def verified_source(root, report):
    current = native.inspect_dataset(root, report['repo_id'], body_units=report['body_units'],
        rig_revision=report['rig_revision'], calibration_revision=report['calibration_revision'],
        source_mode=report['source_mode'], capture_provenance=report.get('capture_provenance'),
        environment_evidence=report.get('environment_evidence'), action_space=report.get('action_space'),
        camera_setup=report.get('camera_setup'))
    if current != report:
        raise ValueError('original source inspection changed')
    return native.load_dataset(root, report['repo_id'])


def frame_at(dataset, report, episode, frame):
    if (type(episode) is not int or type(frame) is not int
            or not 0 <= episode < len(report['episodes'])
            or not 0 <= frame < report['episodes'][episode]['frames']):
        raise ValueError('frame outside original episode')
    offset = sum(e['frames'] for e in report['episodes'][:episode])
    row = dataset[offset+frame]
    if native._integer(row['episode_index'], 'episode_index') != episode or native._integer(
            row['frame_index'], 'frame_index') != frame:
        raise ValueError('reader frame identity differs')
    return row


def export_segments(root, report, document, output):
    output = native._new_output(output, root)
    native.static_episodes(root, len(report['episodes']))
    splits = validate_selection(report, document)
    dataset = verified_source(root, report)
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    features = {key: value for key, value in dataset.meta.info['features'].items()
                if key not in DEFAULT_FEATURES}
    outputs, lineage = {}, {}
    for name, indices in splits.items():
        child = LeRobotDataset.create(repo_id=report['repo_id']+'_'+name, root=output/name,
            fps=dataset.meta.info['fps'], features=copy.deepcopy(features), robot_type=report['robot_type'],
            use_videos=True, video_backend='pyav', vcodec='h264', batch_encoding_size=1)
        try:
            for index in indices:
                segment = document['segments'][index]
                for frame in range(segment['start_frame'], segment['end_frame']):
                    row = frame_at(dataset, report, segment['episode_index'], frame)
                    child.add_frame(copy_frame(row, features))
                child.save_episode(parallel_encoding=False)
        finally:
            child.finalize()
        reader = native.load_dataset(output/name, report['repo_id']+'_'+name)
        verified = native.inspect_frames(reader.meta.info, (reader[i] for i in range(len(reader))))
        if len(verified['episodes']) != len(indices):
            raise ValueError('child episode count differs')
        offset = 0
        lineage[name] = []
        for child_index, index in enumerate(indices):
            segment = document['segments'][index]
            length = segment['end_frame']-segment['start_frame']
            if verified['episodes'][child_index]['frames'] != length:
                raise ValueError('child segment length differs')
            for step in range(length):
                original = frame_at(dataset, report, segment['episode_index'], segment['start_frame']+step)
                actual = reader[offset+step]
                if original['task'] != actual['task']:
                    raise ValueError('child task differs')
                for key in features:
                    expected, value = np.asarray(original[key]), np.asarray(actual[key])
                    if key.startswith('observation.images.'):
                        if expected.shape != value.shape or np.abs(expected-value).mean()*255 > 8:
                            raise ValueError('child image does not match original frame')
                    else:
                        np.testing.assert_array_equal(value, expected)
            lineage[name].append(dict(child_episode_index=child_index, segment_index=index,
                **{key: segment[key] for key in ('episode_index', 'content_sha256', 'start_frame', 'end_frame')}))
            offset += length
        outputs[name] = native.dataset_files(output/name)
    if native.dataset_files(root) != report['files']:
        raise ValueError('source bytes changed during segment export; no success receipt')
    decisions = parent_decisions(report, document)
    receipt = dict(source=report, decisions=decisions, splits=splits, outputs=outputs,
        segment_selection=document, segment_lineage=lineage,
        environment_coverage=native.split_coverage(native.validate_environment(report), decisions),
        environment_coverage_scope='original_parent_episodes', reader_verified=True, uploaded=False)
    validate_receipt(receipt)
    native.write_json(output/'split-receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--segments', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        export_segments(args.root, json.loads(args.report.read_text(encoding='utf-8')),
                        json.loads(args.segments.read_text(encoding='utf-8')), args.out)
    except (ValueError, OSError, ImportError, AssertionError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(f'Written: {args.out}; offline segments, no upload or device action.')


if __name__ == '__main__':
    main()
