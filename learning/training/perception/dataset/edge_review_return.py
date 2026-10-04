"""Bind explicitly reviewed CVAT masks to original edge PNGs without training.

edge_review_return.py PACK --human HUMAN.jsonl --cvat EXPORT_DIR
    --classes classes.yaml --exclude-eval FIXED_VERSION ... --out NEW_DIR

An approval binds index, image_sha256, mask path and mask_sha256 and requires
review_status=approved, complete_frame_review=true, background_reviewed=true.
Background approval means CVAT's default background was checked across the
whole frame. Unreviewed pixels must not be silently declared background.
The output is staged build.py input, not a qualified dataset or model READY.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

import build
from edge_review import bound, digest


def jsonl(raw):
    rows = {}
    for line in raw.decode('utf-8-sig').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        index = row.get('index')
        if type(index) is not int or index < 0 or index in rows:
            raise ValueError('unique nonnegative review index required')
        rows[index] = row
    return rows


def receive(pack, human, cvat, classes, evalsets, out):
    pack, cvat, out = Path(pack), Path(cvat), Path(out)
    if out.exists():
        raise ValueError('new output required')
    receipt_bytes = (pack / 'receipt.json').read_bytes()
    receipt = json.loads(receipt_bytes)
    if (pack / 'COMPLETE').read_text().strip() != digest(receipt_bytes):
        raise ValueError('review pack is incomplete')
    # Capture each verified reference once, so subsequent writes cannot swap it.
    captured = {}
    for item in receipt['files']:
        name = item['path']
        if name in captured:
            raise ValueError('duplicate receipt reference')
        raw = bound(pack, name).read_bytes()
        if len(raw) != item['bytes'] or digest(raw) != item['sha256']:
            raise ValueError('review pack reference changed')
        captured[name] = raw
    source = jsonl(captured['queue.jsonl'])
    human_bytes = Path(human).read_bytes()
    reviews = jsonl(human_bytes)
    if set(reviews) - set(source):
        raise ValueError('review index absent from source')
    fixed_sessions, fixed_hashes, refs = set(), set(), []
    for folder in evalsets:
        ref, sessions, fixed_manifest = build.read_eval_set(folder, with_manifest=True)
        refs.append(ref)
        fixed_sessions |= sessions
        fixed_hashes.add(digest(fixed_manifest))
    expected_fixed = {digest(data) for name, data in captured.items()
                      if name.startswith('eval-') and name.endswith('.json')}
    if not expected_fixed or not expected_fixed.issubset(fixed_hashes):
        raise ValueError('all original fixed evaluation versions must be supplied')
    classes_bytes = Path(classes).read_bytes()
    class_list = build.load_classes(classes, source_bytes=classes_bytes)
    # CVAT export directories place labelmap.txt at root or within SegmentationClass.
    labelmaps = sorted(cvat.rglob('labelmap.txt'))
    needs_masks = any(r.get('review_status') == 'approved' for r in reviews.values())
    if needs_masks and len(labelmaps) != 1:
        raise ValueError('exactly one CVAT labelmap required')
    labelmap_bytes = labelmaps[0].read_bytes() if needs_masks else b''
    lut = build.parse_labelmap(labelmaps[0], class_list, source_bytes=labelmap_bytes) if needs_masks else None
    approved, queued = [], []
    for index, row in source.items():
        review = reviews.get(index)
        if review is not None and review.get('image_sha256') != row['image_sha256']:
            raise ValueError('human approval references different image bytes')
        if review is None or review.get('review_status') != 'approved':
            queued.append(dict(row, review_status='pending_human'))
            continue
        if review.get('complete_frame_review') is not True or review.get('background_reviewed') is not True:
            raise ValueError('approval requires full frame and default-background review')
        if row['session'] in fixed_sessions or row['fixed_eval_overlap']:
            raise ValueError('approved frame overlaps fixed evaluation session')
        image = captured['images/' + row['image']]
        if digest(image) != row['image_sha256']:
            raise ValueError('source image binding differs')
        mask_path = bound(cvat, review['mask'])
        expected_name = f"{row['session']}__{row['frame_index']:08d}"
        if mask_path.suffix != '.png' or mask_path.stem != expected_name:
            raise ValueError('CVAT mask name must match original session and frame')
        mask = mask_path.read_bytes()
        if digest(mask) != review.get('mask_sha256'):
            raise ValueError('approved mask bytes differ')
        pixels = cv2.imdecode(np.frombuffer(mask, np.uint8), cv2.IMREAD_COLOR)
        original = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if pixels is None or original is None or pixels.shape != original.shape:
            raise ValueError('mask/original dimensions differ or image unreadable')
        build.colors_to_indices(pixels[..., ::-1], lut, mask_path.name)
        approved.append((row, review, image, mask))
    out.mkdir(parents=True)
    (out / 'inputs').mkdir()
    for name, raw in [('receipt.json', receipt_bytes), ('queue.jsonl', captured['queue.jsonl']),
                      ('human.jsonl', human_bytes), ('classes.yaml', classes_bytes)]:
        (out / 'inputs' / name).write_bytes(raw)
    (out / 'queued.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in queued), encoding='utf-8')
    sessions = {}
    if approved:
        (out / 'cvat/SegmentationClass').mkdir(parents=True)
        (out / 'cvat/labelmap.txt').write_bytes(labelmap_bytes)
    for row, review, image, mask in approved:
        directory = bound(out / 'frames', row['session'])
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{row['frame_index']:08d}.png"
        (directory / name).write_bytes(image)
        entry = dict(row, index=row['frame_index'], candidate_index=row['index'], image=name,
                     human_review=review, mask_sha256=digest(mask), labelmap_sha256=digest(labelmap_bytes),
                     classes_signature=digest(json.dumps(class_list, sort_keys=True).encode()))
        sessions.setdefault(row['session'], []).append(entry)
        (out / 'cvat/SegmentationClass' / f"{row['session']}__{row['frame_index']:08d}.png").write_bytes(mask)
    for session, frames in sessions.items():
        (out / 'frames' / session / 'frames.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in frames), encoding='utf-8')
        (out / 'frames' / session / 'session.json').write_text(json.dumps({
            'session': session, 'annotation_origin': 'human_reviewed_cvat',
            'source_receipt_sha256': digest(receipt_bytes), 'human_review_sha256': digest(human_bytes)}))
    result = {'schema': 'rosy.edge-mask-return/1', 'exported_frames': len(approved),
              'queued_frames': len(queued), 'training_dataset_qualified': False,
              'fixed_evaluation_sets': refs, 'frame_dirs': [f'frames/{s}' for s in sorted(sessions)],
              'files': [{'path': p.relative_to(out).as_posix(), 'sha256': digest(p.read_bytes()),
                         'bytes': p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]}
    raw = json.dumps(result, indent=2).encode()
    (out / 'manifest.json').write_bytes(raw)
    (out / 'COMPLETE').write_text(digest(raw) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pack', type=Path)
    parser.add_argument('--human', type=Path, required=True)
    parser.add_argument('--cvat', type=Path, required=True)
    parser.add_argument('--classes', type=Path, required=True)
    parser.add_argument('--exclude-eval', type=Path, action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = receive(args.pack, args.human, args.cvat, args.classes, args.exclude_eval, args.out)
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}))
