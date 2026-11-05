"""Applied human-point SAM provenance, separate from requested or previewed jobs."""
import json
import re
import hashlib
from pathlib import Path


def reference(db, index, digest, label, points, image_sha256, classes_sha256):
    # Equal mask bytes retain the first draft origin; jobs retain every human prompt.
    jobs = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_ai_jobs'").fetchone()
    records = (db.execute('SELECT document FROM review_ai_jobs WHERE frame=? ORDER BY rowid DESC', (index,)) if jobs else
               db.execute('SELECT origin FROM pixel_drafts WHERE frame=? AND sha256=?', (index, digest)))
    for row in records:
        try:
            record = json.loads(row[0])
        except (TypeError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        actor = record.get('actor' if jobs else 'requested_by')
        job_id = record.get('id' if jobs else 'job_id')
        prompt = {'label': record.get('label'), 'points': record.get('points')} if jobs else record.get('sam_prompt')
        checkpoint = record.get('sam_checkpoint_sha256')
        if (record.get('action') == 'sam_points' and record.get('model') == 'sam3'
                and prompt == {'label': label, 'points': points}
                and isinstance(actor, str) and 1 <= len(actor) <= 256
                and isinstance(job_id, str) and re.fullmatch('[0-9a-f]{32}', job_id)
                and isinstance(checkpoint, str) and re.fullmatch('[0-9a-f]{64}', checkpoint)
                and record.get('model_digest') == checkpoint
                and (not jobs or (record.get('state') == 'succeeded' and record.get('frame') == index
                     and record.get('image_sha256') == image_sha256 and record.get('classes_sha256') == classes_sha256
                     and isinstance(record.get('result'), dict)
                     and record['result'].get('selection_sha256') == digest
                     and record['result'].get('candidate_sha256') == digest))):
            return {'selection_sha256': digest, 'job_id': job_id, 'requested_by': actor,
                    'label': label, 'points': points, 'model': 'sam3', 'model_digest': checkpoint,
                    'sam_checkpoint_sha256': checkpoint, 'image_sha256': image_sha256,
                    'classes_sha256': classes_sha256}
    return None


def class_history(db, state, original, current):
    hashes = [current]
    for row in db.execute("SELECT old_binding,new_binding FROM class_revisions WHERE kind='pixel' ORDER BY id DESC"):
        old, new = json.loads(row['old_binding']), json.loads(row['new_binding'])
        if new and old and new['sha256'] == hashes[-1] and old['sha256'] != new['sha256']:
            hashes.append(old['sha256'])
        if hashes[-1] == original:
            break
    if hashes[-1] != original:
        raise ValueError('SAM class revision history is incomplete')
    documents = []
    for digest in reversed(hashes):
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('invalid SAM class revision hash')
        path = (Path(state) / 'pixel' / (digest + '.yaml')).resolve()
        if not path.is_relative_to(Path(state).resolve()):
            raise ValueError('SAM class revision outside workspace')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('SAM class revision file hash differs')
        documents.append(raw.decode('utf-8'))
    return documents


def validate_class_history(documents, original, current, limit):
    import build
    import yaml
    import review_classes
    if (not isinstance(documents, list) or not 2 <= len(documents) <= limit + 1
            or any(not isinstance(raw, str) or len(raw) > 1024 * 1024 for raw in documents)):
        raise ValueError('invalid SAM class revision proof')
    hashes = [hashlib.sha256(raw.encode('utf-8')).hexdigest() for raw in documents]
    if hashes[0] != original or hashes[-1] != current:
        raise ValueError('SAM class revision hash differs')
    previous = build.load_classes(Path('classes.yaml'), source_bytes=documents[0].encode('utf-8'))
    previous_sha = hashes[0]
    for digest, raw in zip(hashes[1:], documents[1:]):
        classes = build.load_classes(Path('classes.yaml'), source_bytes=raw.encode('utf-8'))
        rows = []
        for value, source in zip(classes, yaml.safe_load(raw)['classes']):
            row = dict(value, display=source.get('display', value['name']))
            if 'hotkey' in source:
                row['hotkey'] = source['hotkey']
            rows.append(row)
        # D-973 owns immutable index/name/role/semantic/hotkey and allowed additions.
        review_classes.proposal({'classes': previous, 'sha256': previous_sha}, 'pixel', rows)
        previous, previous_sha = classes, digest


def capture(db, masks, state, classes_sha256):
    """Keep actual application history, including uses later undone or painted over."""
    records = {}
    for row in db.execute("SELECT frame,version,review FROM pixel_events WHERE action='sample' ORDER BY frame,version,id"):
        detail = json.loads(row['review'])
        if 'sam_assistance' not in detail:
            continue
        use = detail['sam_assistance']
        if (not isinstance(use, dict) or use.get('applied_version') != row['version']
                or detail.get('saved_version') != row['version']
                or row['frame'] not in masks or row['version'] > masks[row['frame']]['version']):
            raise ValueError('SAM assistance event version differs')
        if use['classes_sha256'] != classes_sha256:
            use['class_history'] = class_history(db, state, use['classes_sha256'], classes_sha256)
        records.setdefault(row['frame'], []).append(use)
    return records


def validate(records, frame, classes_sha256):
    fields = {'selection_sha256', 'job_id', 'requested_by', 'label', 'points', 'model', 'model_digest',
              'sam_checkpoint_sha256', 'image_sha256', 'classes_sha256', 'applied_version', 'applied_mask_sha256'}
    if not isinstance(records, list) or len(records) > frame['mask_version']:
        raise ValueError('invalid SAM assistance history')
    previous = 0
    for use in records:
        if not isinstance(use, dict) or set(use) - {'class_history'} != fields:
            raise ValueError('invalid SAM assistance reference')
        points, version = use['points'], use['applied_version']
        if (type(version) is not int or not previous < version <= frame['mask_version']
                or type(use['label']) is not int or not 0 <= use['label'] < 255
                or use['model'] != 'sam3' or use['model_digest'] != use['sam_checkpoint_sha256']
                or not isinstance(use['job_id'], str) or not re.fullmatch('[0-9a-f]{32}', use['job_id'])
                or not isinstance(use['requested_by'], str) or not 1 <= len(use['requested_by']) <= 256
                or any(not isinstance(use[key], str) or not re.fullmatch('[0-9a-f]{64}', use[key]) for key in
                       ('selection_sha256', 'model_digest', 'sam_checkpoint_sha256', 'image_sha256',
                        'classes_sha256', 'applied_mask_sha256'))
                or use['image_sha256'] != frame['image_sha256']
                or not isinstance(points, list) or not 1 <= len(points) <= 16
                or any(not isinstance(point, list) or len(point) != 2 or any(type(v) is not int for v in point)
                       or not 0 <= point[0] < frame['width'] or not 0 <= point[1] < frame['height'] for point in points)):
            raise ValueError('invalid SAM assistance binding')
        if use['classes_sha256'] != classes_sha256 or 'class_history' in use:
            validate_class_history(use.get('class_history'), use['classes_sha256'], classes_sha256, frame['mask_version'])
        previous = version
    return records
