"""Conservatively clip model drivable drafts outside visible lane edges.

Run on the model PC before review import. Removed pixels become 255 (unknown),
never background or an approved label. The output is a new pending catalog.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import build
import edge_review
import review_masks


def clip_drivable(mask, *, left, right, drivable):
    result = mask.copy()
    removed = 0
    for row in result:
        left_edges = np.flatnonzero(row == left)
        right_edges = np.flatnonzero(row == right)
        for outside in (row[:left_edges.min()] if left_edges.size else row[:0],
                        row[right_edges.max() + 1:] if right_edges.size else row[:0]):
            count = outside == drivable
            removed += int(count.sum())
            outside[count] = 255
    return result, removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--classes', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('new output directory required')
    raw = args.catalog.read_bytes()
    rows = [json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
    if not 1 <= len(rows) <= 200:
        parser.error('1..200 model drafts required')
    class_raw = args.classes.read_bytes()
    binding = {'classes': build.load_classes(args.classes, source_bytes=class_raw),
               'sha256': hashlib.sha256(class_raw).hexdigest()}
    names = {item['name']: item['index'] for item in binding['classes']}
    if not {'lane_left', 'lane_right', 'drivable'} <= names.keys():
        parser.error('v13 left/right lane and drivable classes required')
    prepared = []
    for index, row in enumerate(rows):
        ref = row['mask']
        if ref['classes_sha256'] != binding['sha256']:
            raise ValueError(f'frame {index}: pixel classes differ')
        path = edge_review.bound(args.catalog.parent, ref['indexed_png'])
        data = path.read_bytes()
        if len(data) > 32 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != ref['sha256']:
            raise ValueError(f'frame {index}: mask hash or size differs')
        valid = review_masks.from_indexed(data, row['width'], row['height'], binding)
        mask = cv2.imdecode(np.frombuffer(valid, np.uint8), cv2.IMREAD_UNCHANGED)
        clipped, count = clip_drivable(mask, left=names['lane_left'], right=names['lane_right'],
                                       drivable=names['drivable'])
        review_masks.require_inside_lane_boundaries(clipped, binding)
        prepared.append((row, review_masks.encode(clipped), count))
    args.out.mkdir(parents=True)
    (args.out / 'drafts').mkdir()
    (args.out / 'classes.yaml').write_bytes(class_raw)
    output, audit = [], []
    for index, (row, data, count) in enumerate(prepared):
        name = f'drafts/{index:06d}.png'
        (args.out / name).write_bytes(data)
        next_row = dict(row, mask={'indexed_png': name, 'sha256': hashlib.sha256(data).hexdigest(),
                                   'classes_sha256': binding['sha256']},
                        annotation_source='sam3_road_visible_lane_clip',
                        annotation_note='차선 밖 주행영역은 255 미검수; 사람 검수 전 후보')
        output.append(next_row)
        audit.append({'image_sha256': row['image_sha256'], 'drivable_removed_to_255': count})
    encoded = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in output).encode()
    (args.out / 'verified-inputs.jsonl').write_bytes(encoded)
    (args.out / 'receipt.json').write_text(json.dumps({
        'schema': 'rosy.visible-lane-clipped-draft/1', 'approval': False, 'frames': len(output),
        'removed_to_255': sum(row['drivable_removed_to_255'] for row in audit),
        'source_catalog_sha256': hashlib.sha256(raw).hexdigest(),
        'catalog_sha256': hashlib.sha256(encoded).hexdigest(), 'audit': audit}, indent=2) + '\n')


if __name__ == '__main__':
    main()
