"""Return offline human reviews without resizing mixed-size original images.

Usage: review_return.py SOURCE.jsonl --human HUMAN.jsonl --images ROOT --out NEW_DIR
Inputs and image bytes are captured once; only explicit complete approvals export.
The final manifest/COMPLETE receipt records an export operation, not training approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import object_boxes as exporter  # noqa: E402


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _parse(data):
    result = {}
    for line in data.decode('utf-8-sig').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        index = row.get('index') if isinstance(row, dict) else None
        if type(index) is not int or index < 0 or index in result:
            raise ValueError('unique nonnegative integer index required')
        result[index] = row
    return result


def _jsonl(rows):
    return ''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in rows).encode('utf-8')


def receive_review(source_path, human_path, image_root, out, *, classes=exporter.OBJECT_CLASSES):
    """Freeze inputs, validate every reference, export size groups, then issue a receipt."""
    classes = tuple(classes)
    source_bytes, human_bytes = Path(source_path).read_bytes(), Path(human_path).read_bytes()
    source, human = _parse(source_bytes), _parse(human_bytes)
    root, out = Path(image_root).resolve(), Path(out)
    if out.exists():
        raise ValueError('new output directory required')
    if not source or set(human) - set(source):
        raise ValueError('nonempty source and matched human indices required')
    import cv2
    import numpy as np
    groups, captured = {}, {}
    for index, row in source.items():
        name = row.get('image')
        if (not isinstance(name, str) or Path(name).is_absolute() or Path(name).drive
                or '..' in Path(name).parts):
            raise ValueError('relative contained image path required')
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('image path escapes root')
        data = path.read_bytes()
        if _sha(data) != row.get('image_sha256'):
            raise ValueError('source image hash mismatch')
        decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None:
            raise ValueError('undecodable original image')
        size = (decoded.shape[1], decoded.shape[0])
        if (type(row.get('width')) is not int or type(row.get('height')) is not int
                or (row['width'], row['height']) != size):
            raise ValueError('source dimensions differ from actual image')
        suffix = path.suffix.lower()
        if suffix not in ('.jpg', '.jpeg', '.png'):
            raise ValueError('supported original image suffix required')
        candidates = row.get('objects', [])
        if not isinstance(candidates, list):
            raise ValueError('source objects must be an explicit list')
        for box in candidates:
            exporter._check_human_box(box)
            if box.get('label') not in classes + (None,):
                raise ValueError('unknown source object class')
            a = box['bbox_xyxy']
            if not (0 <= a[0] < a[2] <= size[0] and 0 <= a[1] < a[3] <= size[1]):
                raise ValueError('source object outside actual image')
        review = human.get(index)
        if review is not None:
            if review.get('image_sha256') != row['image_sha256']:
                raise ValueError('human image hash differs from bound source')
            if (review.get('review_status') not in ('pending', 'pending_human', 'approved')
                    or type(review.get('complete_frame_review')) is not bool
                    or not isinstance(review.get('boxes'), list)):
                raise ValueError('explicit review status, completion boolean and boxes required')
            for box in review['boxes']:
                exporter._check_human_box(box)
                if box.get('label') not in classes + (exporter.REJECT,):
                    raise ValueError('unknown object class')
                a = box['bbox_xyxy']
                if not (0 <= a[0] < a[2] <= size[0] and 0 <= a[1] < a[3] <= size[1]):
                    raise ValueError('review box outside actual image')
                if (box['label'] == 'traffic_light'
                        and box.get('signal_state', 'unknown') not in ('red', 'yellow', 'green', 'off', 'unknown')):
                    raise ValueError('unknown signal state')
        captured[index] = (data, suffix)
        groups.setdefault(size, []).append(index)
    # Nothing is written before every original and review reference passes validation.
    out.mkdir(parents=True, exist_ok=False)
    inputs = out / 'inputs'
    inputs.mkdir()
    (inputs / 'source.jsonl').write_bytes(source_bytes)
    (inputs / 'human.jsonl').write_bytes(human_bytes)
    snapshots = inputs / 'images'
    snapshots.mkdir()
    for index, (data, suffix) in captured.items():
        (snapshots / f'{index:06d}{suffix}').write_bytes(data)
    records = []
    for size, indices in sorted(groups.items()):
        group_id = f'{size[0]}x{size[1]}'
        group_inputs = inputs / group_id
        group_inputs.mkdir()
        # Rewrite only group-local image paths to verified snapshots; original inputs remain exact.
        subset = [dict(source[i], image=f'{i:06d}{captured[i][1]}') for i in indices]
        source_file, human_file = group_inputs / 'source.jsonl', group_inputs / 'human.jsonl'
        source_file.write_bytes(_jsonl(subset))
        human_file.write_bytes(_jsonl(human[i] for i in indices if i in human))
        destination = out / 'groups' / group_id
        exporter.main([str(source_file), '--human', str(human_file), '--images', str(snapshots),
                       '--out', str(destination), '--size', str(size[0]), str(size[1])], classes=classes)
        manifest = json.loads((destination / 'manifest.json').read_text(encoding='utf-8'))
        records.append({'path': f'groups/{group_id}', 'size_wh': list(size), 'source_indices': indices,
                        'exported_indices': manifest['exported_indices'], 'queued_indices': manifest['queued_indices']})
    files = [{'path': p.relative_to(out).as_posix(), 'sha256': _sha(p.read_bytes()),
              'bytes': p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
    result = {'schema': 'rosy.object-review-return/1', 'classes': list(classes),
              'source_sha256': _sha(source_bytes), 'human_sha256': _sha(human_bytes), 'groups': records,
              'exported_frames': sum(len(g['exported_indices']) for g in records),
              'queued_frames': sum(len(g['queued_indices']) for g in records),
              'reviewer_authentication': 'unverified', 'training_dataset_qualified': False,
              'signal_state': 'preserved in human JSONL; not represented by YOLO object class targets',
              'files': files}
    manifest_bytes = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    (out / 'manifest.json').write_bytes(manifest_bytes)
    (out / 'COMPLETE').write_text(_sha(manifest_bytes) + '\n', encoding='ascii')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--human', type=Path, required=True)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = receive_review(args.source, args.human, args.images, args.out)
    print(json.dumps({k: report[k] for k in ('exported_frames', 'queued_frames')}))
