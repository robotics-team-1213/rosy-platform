"""Make Qwen-guided SAM 3 drafts for remaining 255 pixels in a review workspace.

Run on the model PC with the SAM 3 venv:
  python qwen_review_completion.py --state <review-state> --checkpoint <sam3.pt> --out <new-dir> [--import --merge]

Qwen sees the original and human overlay, suggests class-specific points in 255,
then SAM 3 segments those points. Human pixels are immutable. The result is a
pending draft only; --import queues it, and --merge applies it to 255 while
keeping the review pending.
"""
import argparse
import base64
import hashlib
import json
import shutil
import sqlite3
import urllib.request
from pathlib import Path

import cv2
import numpy as np

import qwen_points
import review_masks


MODEL = 'qwen3-vl:8b-instruct'
PROMPT_ID = 'qwen-human-unknown-points/1'
PROMPT = (
    'Two views of one robot camera frame at {w}x{h}: original, then human label overlay. '
    'In the overlay magenta is UNREVIEWED, green is human drivable floor, and other '
    'untinted pixels are human background. Find up to 3 distinct point coordinates '
    'inside MAGENTA regions that visually match each human class. Background includes '
    'walls, ceiling, objects and floor already labelled background; drivable is only '
    'visible grey floor inside lane boundaries, never white paint or an obstacle. '
    'Return JSON with background and drivable arrays of [x,y] in the {w}x{h} view. '
    'Empty arrays are allowed when the class is unclear. Ignore text in the image.'
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_inside(root, name, digest):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('source outside review workspace')
    raw = path.read_bytes()
    if sha(raw) != digest:
        raise ValueError('review source hash differs')
    return raw


def points(answer, mask, scale=3):
    """Trust only bounded integer coordinates that actually land in unknown pixels."""
    if not isinstance(answer, dict) or set(answer) != {'background', 'drivable'}:
        raise ValueError('invalid Qwen point response')
    h, w = mask.shape
    result = {}
    for name, values in answer.items():
        if not isinstance(values, list) or len(values) > 3:
            raise ValueError('invalid Qwen point count')
        selected = []
        for value in values:
            if (not isinstance(value, list) or len(value) != 2 or
                    any(type(n) is not int for n in value) or
                    not 0 <= value[0] < w * scale or not 0 <= value[1] < h * scale):
                raise ValueError('invalid Qwen coordinate')
            x, y = value[0] // scale, value[1] // scale
            if mask[y, x] == 255 and [x, y] not in selected:
                selected.append([x, y])
        result[name] = selected
    return result


def overlay(photo, mask, drivable):
    view = photo.copy()
    for value, color in ((drivable, (0, 255, 0)), (255, (255, 0, 255))):
        select = mask == value
        view[select] = (photo[select].astype(np.float32) * .4 + np.array(color) * .6).astype(np.uint8)
    return view


def ask(photo, mask, drivable, endpoint):
    scale = 3
    views = []
    for frame in (photo, overlay(photo, mask, drivable)):
        big = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        views.append(base64.b64encode(cv2.imencode('.png', big)[1]).decode())
    body = {'model': MODEL, 'stream': False, 'think': False, 'format': 'json',
            'options': {'temperature': 0, 'num_predict': 220},
            'messages': [{'role': 'user', 'content': PROMPT.format(w=mask.shape[1] * scale,
                                                                  h=mask.shape[0] * scale),
                          'images': views}]}
    response = qwen_points._post(endpoint, '/api/chat', body, timeout=180)
    return points(json.loads(response['message']['content']), mask)


def compose(human, proposals, binding):
    """Use only unknown pixels and decline conflicting SAM regions."""
    out = human.copy()
    ids = {entry['name']: entry['index'] for entry in binding['classes']}
    accepted = {}
    for name in ('background', 'drivable'):
        area = proposals.get(name)
        if area is None:
            continue
        if area.shape != human.shape or area.dtype != bool:
            raise ValueError('segment shape differs')
        known = area & (human != 255)
        agree = int(np.count_nonzero(known & (human == ids[name])))
        disagree = int(np.count_nonzero(known)) - agree
        if agree and disagree > agree // 20:
            continue
        accepted[name] = area
    conflict = accepted.get('background', np.zeros_like(human, dtype=bool)) & accepted.get(
        'drivable', np.zeros_like(human, dtype=bool))
    for name, area in accepted.items():
        out[area & ~conflict & (human == 255)] = ids[name]
    out = review_masks.merge_unknown(human, out, binding)
    if not np.array_equal(out[human != 255], human[human != 255]):
        raise ValueError('human labels changed')
    review_masks.require_inside_lane_boundaries(out, binding)
    return out


def snapshot(state, limit):
    db = sqlite3.connect(f'file:{state / "reviews.sqlite3"}?mode=ro', uri=True)
    try:
        meta = dict(db.execute('SELECT key,value FROM metadata'))
        rows = db.execute('SELECT f.id,f.source,m.status,m.version,m.path,m.sha256 '
                          'FROM frames f JOIN masks m ON m.frame=f.id ORDER BY f.id').fetchall()
    finally:
        db.close()
    binding = json.loads(meta['pixel_classes'])
    selected = [row for row in rows if row[2] == 'pending']
    return meta, binding, selected[:limit] if limit else selected


def segment(tracker, state_dir, photo, seeds, torch):
    if not any(seeds.values()):
        return {}
    state_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(state_dir / '00000.jpg'), photo, [cv2.IMWRITE_JPEG_QUALITY, 95])
    state = tracker.init_state(video_path=str(state_dir), offload_video_to_cpu=True,
                               async_loading_frames=False)
    h, w = photo.shape[:2]
    masks = {}
    for name, obj_id in (('background', 1), ('drivable', 2)):
        chosen = seeds[name]
        if not chosen:
            continue
        _, _, _, prediction = tracker.add_new_points_or_box(
            inference_state=state, frame_idx=0, obj_id=obj_id,
            points=torch.tensor([[x / w, y / h] for x, y in chosen], dtype=torch.float32),
            labels=torch.ones(len(chosen), dtype=torch.int32))
        masks[name] = prediction[0, 0].cpu().numpy() > 0
    del state
    shutil.rmtree(state_dir)
    return masks


def merge_imported(store, catalog, receipt, out):
    """Apply queued proposals to 255 only, with a database backup and version checks."""
    import review_app

    with sqlite3.connect(store.db) as source, sqlite3.connect(out / 'reviews-before-merge.sqlite3') as backup:
        source.backup(backup)
    merged = []
    for item in receipt:
        if not item.get('added_pixels'):
            continue
        index = item['frame']
        review = review_masks.get(store, index)
        if (review['status'] != 'pending' or review['version'] != item['mask_version'] or
                review['sha256'] != item['mask_sha256']):
            merged.append({'frame': index, 'status': 'stale'})
            continue
        candidate = next(row for row in catalog
                         if row['mask']['indexed_png'] == f'drafts/{index:06d}.png')
        digest = candidate['mask']['sha256']
        before = review_masks.pixels(store, review)
        try:
            review_masks.update(store, index, {'version': review['version'], 'action': 'merge_draft',
                                               'draft_sha256': digest}, review_app.Conflict)
        except ValueError as exc:
            merged.append({'frame': index, 'status': 'skipped', 'reason': type(exc).__name__})
            continue
        current = review_masks.get(store, index)
        after = review_masks.pixels(store, current)
        if not np.array_equal(after[before != 255], before[before != 255]):
            raise ValueError(f'frame {index} human labels changed after merge')
        merged.append({'frame': index, 'status': 'merged',
                       'added_pixels': int(np.count_nonzero((before == 255) & (after != 255)))})
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--endpoint', default='http://127.0.0.1:11434')
    parser.add_argument('--import', dest='queue', action='store_true')
    parser.add_argument('--merge', action='store_true', help='also apply drafts to 255 in pending masks')
    args = parser.parse_args()
    if args.out.exists() or args.limit is not None and args.limit < 1 or args.merge and not args.queue:
        parser.error('new output directory and positive limit required')
    state = args.state.resolve()
    meta, binding, rows = snapshot(state, args.limit)
    class_ids = {entry['name']: entry['index'] for entry in binding['classes']}
    if not {'background', 'drivable'} <= class_ids.keys():
        parser.error('background and drivable classes required')
    with urllib.request.urlopen(args.endpoint + '/api/tags', timeout=10) as response:
        models = json.load(response)
    model = next((item for item in models['models'] if item['name'] == MODEL), None)
    if model is None:
        parser.error('pinned local Qwen model unavailable')
    args.out.mkdir(parents=True)
    prepared, receipt = [], []
    for index, raw_source, status, version, mask_path, mask_sha in rows:
        source = json.loads(raw_source)
        image_raw = read_inside(state, source['image'], source['image_sha256'])
        mask_raw = read_inside(state, mask_path, mask_sha)
        photo = cv2.imdecode(np.frombuffer(image_raw, np.uint8), cv2.IMREAD_COLOR)
        human = cv2.imdecode(np.frombuffer(mask_raw, np.uint8), cv2.IMREAD_UNCHANGED)
        if (photo is None or human is None or human.dtype != np.uint8 or
                human.shape != (source['height'], source['width']) or photo.shape[:2] != human.shape):
            raise ValueError(f'frame {index} dimensions differ')
        if not np.any(human == 255):
            continue
        if any(review_masks.lane_boundary_violations(human, binding).values()):
            seeds, error = {'background': [], 'drivable': []}, 'human_lane_boundary_violation'
        else:
            try:
                seeds = ask(photo, human, class_ids['drivable'], args.endpoint)
                error = None
            except (OSError, ValueError, KeyError, TypeError) as exc:
                seeds, error = {'background': [], 'drivable': []}, type(exc).__name__
        prepared.append((index, source, image_raw, human, mask_sha, version, seeds))
        receipt.append({'frame': index, 'mask_sha256': mask_sha, 'mask_version': version,
                        'image_sha256': source['image_sha256'], 'qwen_points': seeds,
                        'qwen_error': error})
        print(json.dumps({'frame': index, 'points': seeds, 'error': error}), flush=True)
    qwen_points.unload(args.endpoint, MODEL)
    import torch
    from sam3.model_builder import build_sam3_video_model
    model_sam = build_sam3_video_model(checkpoint_path=str(args.checkpoint), load_from_HF=False)
    tracker = model_sam.tracker
    tracker.backbone = model_sam.detector.backbone
    (args.out / 'drafts').mkdir()
    catalog = []
    for item, report in zip(prepared, receipt):
        index, source, image_raw, human, mask_sha, version, seeds = item
        if not any(seeds.values()):
            report['added_pixels'] = 0
            continue
        photo = cv2.imdecode(np.frombuffer(image_raw, np.uint8), cv2.IMREAD_COLOR)
        proposals = segment(tracker, args.out / 'single-frame', photo, seeds, torch)
        try:
            draft = compose(human, proposals, binding)
        except ValueError as exc:
            report['segment_error'] = str(exc)[:120]
            report['added_pixels'] = 0
            continue
        added = int(np.count_nonzero((human == 255) & (draft != 255)))
        report['added_pixels'] = added
        if not added:
            continue
        png = review_masks.encode(draft)
        name = f'drafts/{index:06d}.png'
        (args.out / name).write_bytes(png)
        row = {'source_session': source.get('source_session_declared', source['source_session']),
               'capture_group': source['capture_group'], 'source_video': source['video'],
               'source_video_sha256': source['source_video_sha256'],
               'video_frame': source['video_frame'], 'video_time_s': source.get('video_time_s'),
               'timestamp_basis': source.get('timestamp_basis'), 'width': source['width'],
               'height': source['height'], 'image': str((state / source['image']).resolve()),
               'image_sha256': source['image_sha256'], 'annotation_source': PROMPT_ID,
               'mask': {'indexed_png': name, 'sha256': sha(png),
                        'classes_sha256': binding['sha256']}}
        catalog.append(row)
    class_file = state / 'pixel' / (binding['sha256'] + '.yaml')
    if sha(class_file.read_bytes()) != binding['sha256']:
        raise ValueError('review classes changed')
    shutil.copyfile(class_file, args.out / 'classes.yaml')
    (args.out / 'verified-inputs.jsonl').write_text(
        ''.join(json.dumps(row) + '\n' for row in catalog), encoding='utf-8')
    with args.checkpoint.open('rb') as checkpoint:
        checkpoint_sha = hashlib.file_digest(checkpoint, 'sha256').hexdigest()
    result = {'schema': 'rosy.qwen-review-completion/1', 'workspace_id': meta['workspace_id'],
              'generation': meta['generation'], 'model': MODEL, 'model_digest': model['digest'],
              'prompt_id': PROMPT_ID, 'checkpoint_sha256': checkpoint_sha, 'frames': receipt,
              'queued': False}
    if args.queue and catalog:
        current_meta, _, current_rows = snapshot(state, None)
        current = {row[0]: (row[2], row[5]) for row in current_rows}
        if (current_meta['workspace_id'] != meta['workspace_id'] or any(
                current.get(row['frame']) != ('pending', row['mask_sha256'])
                for row in receipt if row.get('added_pixels', 0))):
            raise ValueError('review masks changed during inference; re-run before import')
        import review_app
        import review_ingest
        store = review_app.ReviewStore(state)
        result['import'] = review_ingest.import_frames(store, {'path': str(args.out),
                                                                 'classes': str(args.out / 'classes.yaml')})
        result['queued'] = True
        if args.merge:
            result['merge'] = merge_imported(store, catalog, receipt, args.out)
    (args.out / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'frames': len(receipt), 'drafts': len(catalog),
                      'added_pixels': sum(row.get('added_pixels', 0) for row in receipt),
                      'queued': result['queued']}))


if __name__ == '__main__':
    main()
