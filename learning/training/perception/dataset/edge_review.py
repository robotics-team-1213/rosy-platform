"""Prepare verified, unlabelled edge candidates for private human review.

edge_review.py <candidate-dir> --videos <original-video-dir>
    --dataset-manifest <manifest>... --eval-manifest <manifest>... --out <new-dir>

This creates an original-PNG gallery, CVAT image zip and provenance queue only.
It never creates masks, training datasets, model READY markers or approvals.
Session overlap is conservative even if the source video bytes have changed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import zipfile
from pathlib import Path, PureWindowsPath


def digest(data):
    return hashlib.sha256(data).hexdigest()


def bound(root, name):
    if not isinstance(name, str) or '\\' in name or PureWindowsPath(name).drive:
        raise ValueError('invalid relative path')
    path = (root / name).resolve()
    if Path(name).is_absolute() or '..' in Path(name).parts or not path.is_relative_to(root.resolve()):
        raise ValueError('path escapes source root')
    return path


def session(video):
    match = re.fullmatch(r'teleop_([^/\\]+)_(\d{8}T\d{6}Z)\.mp4', video)
    if not match:
        raise ValueError('source video has no canonical session identity')
    return match[2] + '_' + match[1]


def prepare(root, videos, datasets, evalsets, out):
    import cv2
    import numpy as np
    root, videos, out = Path(root), Path(videos), Path(out)
    if out.exists():
        raise ValueError('output already exists')
    snapshots = []
    memberships, heldout = {}, set()
    for kind, paths in [('dataset', datasets), ('eval', evalsets)]:
        for index, path in enumerate(paths):
            data = Path(path).read_bytes()
            document = json.loads(data)
            frames = document['frames']
            if not frames:
                raise ValueError('empty comparison manifest')
            for frame in frames:
                identity = frame['session']
                memberships.setdefault(identity, set()).add((kind, digest(data), frame['split']))
                if kind == 'eval':
                    heldout.add(identity)
            snapshots.append((f'{kind}-{index}.json', data))
    raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if manifest.get('schema') != 'rosy.edge-candidate-review/1':
        raise ValueError('unsupported edge manifest')
    sources = {}
    for source in manifest['sources']:
        video = source['video']
        if video in sources:
            raise ValueError('duplicate source video')
        sources[video] = source
        session(video)
        for item in [dict(name=video, sha256=source['sha256']), *source.get('sidecars', [])]:
            if digest(bound(videos, item['name']).read_bytes()) != item['sha256']:
                raise ValueError('original source hash mismatch')
    rows, images, seen, frame_keys = [], [], set(), set()
    for index, candidate in enumerate(manifest['images']):
        name = candidate['image']
        if name in seen:
            raise ValueError('duplicate candidate image')
        seen.add(name)
        video = candidate['source_video']
        if video not in sources:
            raise ValueError('unknown source video')
        data = bound(root, name).read_bytes()
        if digest(data) != candidate['image_sha256']:
            raise ValueError('candidate file hash mismatch')
        pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if pixels is None or digest(pixels.tobytes()) != candidate['decoded_bgr_sha256']:
            raise ValueError('candidate decoded hash mismatch')
        identity = session(video)
        frame_index = candidate['frame_index']
        if type(frame_index) is not int or frame_index < 0:
            raise ValueError('invalid frame index')
        frame_key = (identity, frame_index)
        if frame_key in frame_keys:
            raise ValueError('duplicate source frame / CVAT name')
        frame_keys.add(frame_key)
        overlap = [{'kind': k, 'manifest_sha256': h, 'split': s}
                   for k, h, s in sorted(memberships.get(identity, set()))]
        row = dict(candidate, index=index, session=identity,
                   source_video_sha256=sources[video]['sha256'],
                   width=pixels.shape[1], height=pixels.shape[0],
                   dataset_memberships=overlap, fixed_eval_overlap=identity in heldout,
                   eligible_new_holdout=False, label_status='unlabelled',
                   review_status='pending_human', annotation_origin='none',
                   disposition='quarantine_eval_overlap' if identity in heldout else 'pending_human',
                   lowlight_improvement_deferred='dark_candidate' in candidate.get('candidate_tags', []))
        rows.append(row)
        images.append((name, data))
    # All inputs pass before creating the output. COMPLETE is written last.
    out.mkdir(parents=True)
    for name, data in [('source-manifest.json', raw), *snapshots]:
        (out / name).write_bytes(data)
    with zipfile.ZipFile(out / 'cvat-images.zip', 'w', compression=zipfile.ZIP_STORED) as archive:
        for row, (name, data) in zip(rows, images):
            archive.writestr(f"{row['session']}__{row['frame_index']:08d}.png", data)
            target = bound(out / 'images', name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    (out / 'queue.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    cards = []
    for row, (_, data) in zip(rows, images):
        caption = html.escape(f"{row['index']} | {row['session']} | frame {row['frame_index']} | "
                              f"{row['disposition']} | known dataset entries {len(row['dataset_memberships'])} | "
                              f"video seconds {row.get('video_time_s')} | hints {row.get('candidate_tags', [])}")
        cards.append('<figure><img loading="lazy" src="data:image/png;base64,'
                     + base64.b64encode(data).decode() + '"><figcaption>' + caption + '</figcaption></figure>')
    page = ('<!doctype html><meta charset="utf-8"><title>ROSY edge review</title>'
            '<style>body{font:16px system-ui;margin:24px}main{display:grid;grid-template-columns:'
            'repeat(auto-fit,minmax(300px,1fr))}figure{margin:12px}img{width:100%}figcaption{overflow-wrap:anywhere}</style>'
            f'<h1>{len(rows)}장 후보 검수</h1><p>자동 태그는 정답이 아닙니다. 횡단보도·벽 경계·원형 경계·가림을 확인하세요. '
            '이 페이지는 마스크 편집기가 아닙니다. CVAT에서 원본 PNG에 라벨링해야 합니다. '
            '어두운 장면 개선은 후속 ADR 범위이며 현재 새 홀드아웃으로 승인된 세션은 없습니다.</p><main>'
            + ''.join(cards) + '</main>')
    (out / 'review.html').write_text(page, encoding='utf-8')
    result = {'schema': 'rosy.edge-review-intake/1', 'source_manifest_sha256': digest(raw),
              'images_verified': len(rows), 'source_videos_verified': len(sources),
              'known_dataset_overlap_images': sum(bool(r['dataset_memberships']) for r in rows),
              'fixed_eval_overlap_images': sum(r['fixed_eval_overlap'] for r in rows),
              'human_approved_frames': 0, 'training_dataset_qualified': False,
              'new_live_footage': False, 'new_holdout_qualified': False,
              'files': [{'path': str(p.relative_to(out)).replace('\\', '/'), 'sha256': digest(p.read_bytes()),
                         'bytes': p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]}
    receipt = json.dumps(result, indent=2).encode()
    (out / 'receipt.json').write_bytes(receipt)
    (out / 'COMPLETE').write_text(digest(receipt) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--videos', type=Path, required=True)
    parser.add_argument('--dataset-manifest', type=Path, action='append', required=True)
    parser.add_argument('--eval-manifest', type=Path, action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.root, args.videos, args.dataset_manifest, args.eval_manifest, args.out)
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}))
