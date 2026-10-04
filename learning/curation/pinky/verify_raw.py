"""Recompute camera/side/scan bindings from MCAP; reports confer no runtime authority."""
import argparse
import bisect
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'learning/registry/policy'))
from dataset_store import closure
from raw_messages import clean, load_tables
from rosy.contracts.learning.pinky import validate_profile

STAMPED = ('line/observation', 'perception/learned/shadow')


def selected(series, row, gap, topic):
    if topic in STAMPED:
        hits = []
        for log, payload in series:
            stamp = payload.get('stamp') if isinstance(payload, dict) else None
            if (type(stamp) not in (int, float) or not math.isfinite(stamp)
                    or (topic == 'line/observation' and payload.get('source') != 'CAMERA_LINE')):
                continue
            stamp = int(round(stamp * 1e9))
            if abs(stamp - row['stamp_ns']) <= 1000 and row['stamp_ns'] <= log <= row['log_ns'] + 500_000_000:
                hits.append((log, {**payload, 'stamp_ns': stamp}))
        return min(hits, key=lambda item: item[0]) if hits else None
    index = bisect.bisect_right([item[0] for item in series], row['log_ns']) - 1
    return None if index < 0 or row['log_ns'] - series[index][0] > int(gap * 1e9) else series[index]


def compare_rows(rows, tables, gap):
    camera = tables.get('camera', [])
    if len(camera) != len(rows):
        raise ValueError('raw camera frame count differs')
    counts = {name: 0 for name in tables if name != 'camera'}
    for index, row in enumerate(rows):
        log, image = camera[index]
        if row['log_ns'] != log or row['stamp_ns'] != image['stamp_ns']:
            raise ValueError(f'raw camera clock binding differs at frame {index}')
        if set(row['side']) != set(counts) or set(row['dt']) != set(counts):
            raise ValueError('raw side topic set differs')
        for topic in counts:
            hit = selected(tables[topic], row, gap, topic)
            expected = None if hit is None else hit[1]
            if topic == 'scan' and expected is not None:
                expected = {'stamp_ns': expected['stamp_ns']}
            delta = None if hit is None else round((hit[0] - row['log_ns']) / 1e9, 4)
            actual = row['side'][topic]
            if topic == 'odom' and isinstance(actual, dict) and isinstance(expected, dict):
                same = set(actual) == set(expected) and actual['x'] == expected['x'] and actual['y'] == expected['y']
                same = same and math.isclose(actual['yaw'], expected['yaw'], rel_tol=0, abs_tol=1e-12)
            elif topic in STAMPED or topic == 'teleop/intent':
                same = json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(
                    clean(expected), sort_keys=True, allow_nan=False)
            else:
                same = actual == clean(expected)
            if not same or row['dt'][topic] != delta:
                raise ValueError(f'raw {topic} value/dt differs at frame {index}')
            counts[topic] += hit is not None
    return counts


def compare_scan(path, rows, series, gap, declared):
    import numpy as np
    beams = max(len(item['ranges']) for _, item in series)
    with np.load(path, allow_pickle=False) as arrays:
        if (arrays['ranges'].shape != (len(rows), beams) or arrays['ranges'].dtype != np.float16
                or arrays['scan_stamp_ns'].shape != (len(rows),) or arrays['scan_stamp_ns'].dtype != np.int64
                or arrays['dt'].shape != (len(rows),) or arrays['dt'].dtype != np.float32):
            raise ValueError('raw scan shape/dtype differs')
        for key in ('angle_min', 'angle_max', 'angle_increment', 'range_min', 'range_max'):
            value = series[0][1][key]
            if any(scan[key] != value for _, scan in series):
                raise ValueError('raw scan geometry changed during recording')
            if declared[key] != value or arrays[key].shape != () or arrays[key] != np.float32(value):
                raise ValueError('raw scan geometry differs')
        if declared['beams'] != beams:
            raise ValueError('raw scan beam count differs')
        for index, row in enumerate(rows):
            hit = selected(series, row, gap, 'scan')
            expected = np.full(beams, np.nan, np.float16)
            stamp, dt = 0, np.float32(np.nan)
            if hit:
                values = hit[1]['ranges']; expected[:len(values)] = values
                stamp = hit[1]['stamp_ns']; dt = np.float32((hit[0] - row['log_ns']) / 1e9)
            if (not np.array_equal(arrays['ranges'][index], expected, equal_nan=True)
                    or arrays['scan_stamp_ns'][index] != stamp
                    or not np.array_equal(arrays['dt'][index], dt, equal_nan=True)):
                raise ValueError(f'raw scan payload differs at frame {index}')


def video_frames(path, expected, width, height):
    import cv2
    capture = cv2.VideoCapture(str(path)); count = 0
    try:
        if not capture.isOpened():
            raise ValueError('raw-linked video cannot be decoded')
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame.shape[:2] != (height, width):
                raise ValueError('raw-linked video dimensions differ')
            count += 1
    finally:
        capture.release()
    if count != expected:
        raise ValueError('raw-linked video decoded frame count differs')
    return count


def verify(root):
    root = Path(root).resolve()
    dataset = closure(root)
    episode = json.loads((root / 'episode.json').read_text())
    checked = validate_profile(episode, root=root)
    if dataset['episodes'] != [episode['revision']]:
        raise ValueError('single raw verification Episode required')
    tables, details = load_tables(root / 'source/raw')
    metadata, rows = checked['metadata'], checked['rows']
    size = metadata['video']
    if (details['skipped_frames'] != metadata['source'].get('skipped_frames')
            or any((item['width'], item['height']) != (size['width'], size['height'])
                   for _, item in tables.get('camera', []))):
        raise ValueError('raw camera dimensions/skipped count differs')
    actual_counts = {('camera/front' if name == 'camera' else name): len(items) for name, items in tables.items()}
    if actual_counts != metadata['source']['topics']:
        raise ValueError('raw source topic counts differ')
    counts = compare_rows(rows, tables, metadata['sidecar']['max_gap_s'])
    if metadata.get('scan'):
        compare_scan(root / 'source/video' / metadata['scan']['file'], rows, tables['scan'],
                     metadata['sidecar']['max_gap_s'], metadata['scan'])
    elif 'scan' in tables:
        raise ValueError('raw scan omitted from conversion')
    decoded = video_frames(root / 'source/video' / size['file'], len(rows), size['width'], size['height'])
    after = closure(root)
    if after != dataset:
        raise ValueError('raw verification inputs changed')
    code = [Path(__file__), Path(__file__).with_name('raw_messages.py')]
    return {'schema': 'rosy.pinky-raw-verification/1', 'dataset_revision': dataset['revision'],
            'episode_revision': episode['revision'], 'verdict': 'pass', 'frames': len(rows),
            'matched_side_frames': counts, 'decoded_video_frames': decoded, **details,
            'tool_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in code},
            'packages': {name: importlib.metadata.version(name) for name in (
                'mcap', 'mcap-ros2-support', 'numpy', 'opencv-python-headless', 'lz4', 'zstandard')},
            'episode_context': {key: episode[key] for key in (
                'device', 'robot_type', 'environment', 'clock_domain', 'revisions', 'streams', 'outcome')},
            'pixel_provenance': 'unverified', 'motion_derivation': 'unverified', 'task_outcome': 'unknown'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path); parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if (args.out.exists() or args.out.resolve().drive.upper() == 'F:'
            or args.out.resolve().is_relative_to(args.root.resolve())):
        raise ValueError('new verification report outside source drive required')
    result = verify(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
