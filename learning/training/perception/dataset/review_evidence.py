"""Current-decision authority and verified nominal CAD references (no projection)."""
import hashlib
import json
import uuid
import re
import stat
from pathlib import Path

import yaml

import review_masks


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def human_review(frame):
    """Export provenance without modifying the stored operator decision."""
    return dict(frame['review'], video=frame['source'].get('video'),
                video_frame=frame['source'].get('video_frame'))


def configure(store):
    with store.connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS frame_keys (
            identity TEXT PRIMARY KEY, frame INTEGER NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS representations (
            frame INTEGER, image_sha256 TEXT, provenance TEXT,
            PRIMARY KEY(frame,image_sha256));
            CREATE TABLE IF NOT EXISTS object_drafts (
            frame INTEGER NOT NULL, sha256 TEXT NOT NULL, boxes TEXT NOT NULL,
            origin TEXT, catalog_sha256 TEXT NOT NULL,
            PRIMARY KEY(frame,sha256));''')
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('workspace_id',?)", (uuid.uuid4().hex,))
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('generation','1')")
        for row in db.execute('SELECT id,source FROM frames').fetchall():
            source = json.loads(row['source'])
            key = identity(source, legacy=row['id'])
            db.execute('INSERT OR IGNORE INTO frame_keys VALUES (?,?)', (key, row['id']))
            db.execute('INSERT OR IGNORE INTO representations VALUES (?,?,?)',
                       (row['id'], source['image_sha256'], json.dumps(source)))


def identity(row, legacy=None):
    if row.get('source_kind') == 'mcap':
        frame = row['mcap']['frame']
        bag = next(b for b in row['mcap']['bags'] if b['name'] == frame['bag'])
        return (f'mcap:{bag["sha256"]}:{frame["topic"]}:{frame["log_ns"]}:'
                f'{frame["channel_id"]}:{frame["message_ordinal"]}')
    digest = row.get('source_video_sha256')
    index = row.get('video_frame')
    if isinstance(digest, str) and len(digest) == 64 and type(index) is int and index >= 0:
        return f'video:{digest}:{index}'
    if legacy is not None:
        return f'legacy:{legacy}:{row["image_sha256"]}'
    # Without a declared video identity do not merge equal pixels across sessions.
    return f'image:{row["source_session"]}:{row.get("video_frame")}:{row["image_sha256"]}'


def metadata(store, key):
    with store.connect() as db:
        row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return row[0] if row else None


def snapshot(store):
    """One SQLite read transaction, including writers in other store instances."""
    with store.connect() as db:
        db.execute('BEGIN')
        meta = dict(db.execute('SELECT key,value FROM metadata').fetchall())
        frames = [store.decoded(r) for r in db.execute('SELECT * FROM frames ORDER BY id')]
        masks = {r['frame']: dict(r) for r in db.execute('SELECT * FROM masks')}
        representations = {}
        for r in db.execute('SELECT * FROM representations ORDER BY frame,image_sha256'):
            representations.setdefault(r['frame'], []).append(json.loads(r['provenance']))
    binding = json.loads(meta['pixel_classes']) if meta.get('pixel_classes') else None
    if binding:
        binding['classes_signature'] = review_masks.signature(binding['classes'])
    workspace = meta['workspace_id']
    rows = []
    for frame in frames:
            source = frame['source']
            mask = masks.get(frame['index'], {'version': 0, 'status': 'pending', 'sha256': None})
            approval = json.loads(mask['approval']) if mask.get('approval') else None
            rows.append({'frame': frame['index'], 'review_uid': f'{workspace}:{frame["index"]}',
                         'identity': identity(source, legacy=frame['index']),
                         'image_sha256': source['image_sha256'],
                         'source_sha256': sha(encoded(source)),
                         'object_review_sha256': sha(encoded(human_review(frame))),
                         'width': source['width'], 'height': source['height'],
                         'representations_sha256': sha(encoded(representations.get(frame['index'], []))),
                         'source_session': source.get('source_session'),
                         'capture_group': source.get('capture_group'),
                         'source_video_sha256': source.get('source_video_sha256'),
                         'original_video_verified': source.get('original_video_verified', False),
                         'video_frame': source.get('video_frame'),
                         'fixed_eval_overlap': source.get('fixed_eval_overlap'),
                         'object_version': frame['version'], 'object_decision': frame['status'],
                         'frame_excluded': frame['status'] == 'excluded',
                         'mask_version': mask['version'], 'mask_decision': mask['status'],
                         'mask_sha256': mask['sha256'],
                         'complete_frame_review': bool(mask.get('complete', 0)),
                         'background_reviewed': bool(mask.get('background', 0)),
                         'pixel_approval': approval,
                         'map_revision': source.get('map_revision'), 'map_pose': source.get('map_pose')})
    value = {'schema': 'rosy.pinky-review-decisions/1', 'workspace_id': workspace,
             'generation': int(meta['generation']), 'frames': rows,
             'pixel_classes_sha256': (binding or {}).get('sha256'),
             'classes_signature': (binding or {}).get('classes_signature'),
             'ignore_index': (binding or {}).get('ignore_index'),
             'map_reference_sha256': meta.get('cad_reference_sha256')}
    value['decision_sha256'] = sha(encoded(value))
    return {'authority': value, 'frames': frames, 'masks': masks, 'classes': binding,
            'representations': representations,
            'cad': json.loads(meta['cad_reference']) if meta.get('cad_reference') else None}


def decisions(store):
    return snapshot(store)['authority']


def register_map(store, path):
    raw = Path(path).read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('bounded CAD evidence required')
    doc = json.loads(raw)
    files = doc.get('verified_files') or list(doc.get('files', {}).values())
    if not isinstance(files, list) or len(files) != 6:
        raise ValueError('six verified CAD/graph/Nav2 references required')
    captured = {}
    for item in files:
        data = Path(item['path']).read_bytes()
        if len(data) != item['bytes'] or sha(data) != item['sha256']:
            raise ValueError('CAD reference hash or size differs')
        captured[Path(item['path']).name] = data
    graph = yaml.safe_load(captured['lane_graph.yaml'])
    if graph.get('source_sha256') != doc['cad_source_sha256']:
        raise ValueError('CAD/graph source binding differs')
    if not any(sha(data) == doc['cad_source_sha256'] for data in captured.values()):
        raise ValueError('CAD source is absent')
    value = {'map_id': doc['map_id'], 'cad_source_sha256': doc['cad_source_sha256'],
             'files': files, 'files_verified': True, 'pixel_projection_verified': False,
             'recording_revision_binding': 'unverified', 'pose_calibration_binding': 'unverified',
             'nodes_m': graph.get('nodes', {}),
             'unobserved_training_classes': ['stop_line', 'crosswalk'],
             'crosswalk_stop_line_existing_train_val_pixels': 0,
             'training_coverage_basis': 'historical learning catalog snapshot, 2026-10-04; not a live measurement or new-frame coverage',
             'warning': '공칭 CAD 참고입니다. 촬영 지도 revision·동기화 자세·카메라 보정은 미검증이며 사람 정답이 아닙니다.'}
    frozen = encoded(value)
    folder = store.state / 'cad'
    folder.mkdir(exist_ok=True)
    (folder / (sha(frozen) + '.json')).write_bytes(frozen)
    with store.lock, store.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('cad_reference',?)", (frozen.decode(),))
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('cad_reference_sha256',?)", (sha(frozen),))
        db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
    return value


def map_reference(store):
    raw = metadata(store, 'cad_reference')
    return json.loads(raw) if raw else None


def seal_export(store, out, receipt, captured):
    authority = captured['authority']
    masks = []
    for row in authority['frames']:
        if row['object_decision'] == 'excluded' or row['mask_decision'] != 'approved':
            continue
        mask = dict(captured['masks'][row['frame']], width=row['width'], height=row['height'])
        review_masks.pixels(store, mask)  # Validate the indexed dimensions/hash without re-encoding.
        raw = (store.state / mask['path']).read_bytes()
        if sha(raw) != row['mask_sha256'] or not row['pixel_approval']:
            raise ValueError('approved pixel binding missing or changed; re-review required')
        target = out / 'pixel-masks' / f'{row["frame"]:06d}.png'
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(raw)
        masks.append(dict(row, mask=target.relative_to(out).as_posix(),
                          classes_sha256=captured['classes']['sha256'],
                          complete_frame_review=True, background_reviewed=True,
                          training_dataset_qualified=False))
    binding = captured['classes']
    if binding:
        raw = (store.state / 'pixel' / (binding['sha256'] + '.yaml')).read_bytes()
        if sha(raw) != binding['sha256']:
            raise ValueError('pixel class file changed')
        (out / 'pixel-classes.yaml').write_bytes(raw)
    (out / 'pixel-reviews.jsonl').write_bytes(b''.join(encoded(row) for row in masks))
    (out / 'application-snapshot.json').write_bytes(encoded(captured['frames']))
    (out / 'representations.json').write_bytes(encoded(captured['representations']))
    cad = captured['cad']
    if cad:
        (out / 'cad-reference.json').write_bytes(encoded(cad))
    import class_sets  # lazy: verify_current consumers stay free of the dataset exporter
    # Outside `authority` on purpose: adding it there would change decision_sha256 of
    # every existing workspace at an unchanged generation (consumers treat that as a conflict).
    contract = {'schema': 'rosy.pinky-review-export/2', 'export_id': receipt['export_id'],
                'authority': authority, 'pixel_approved_frames': len(masks),
                'object_class_set_sha256': class_sets.object_set(store)['sha256'],
                'current_decisions_required': True,
                'latest_decisions_endpoint': '/api/decisions',
                'training_dataset_qualified': False, 'pixel_projection_verified': False,
                'files': [{'path': p.relative_to(out).as_posix(), 'bytes': p.stat().st_size,
                           'sha256': sha(p.read_bytes())} for p in sorted(out.rglob('*')) if p.is_file()]}
    raw = encoded(contract)
    (out / 'review-contract.json').write_bytes(raw)
    (out / 'AUTHORITY_COMPLETE').write_text(sha(raw) + '\n', encoding='ascii')
    return contract


def valid_digest(value, nullable=False):
    return (nullable and value is None) or (isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None)


def validate_authority(current):
    """Structural validity is separate from the consumer's live-fetch freshness."""
    if not isinstance(current, dict) or current.get('schema') != 'rosy.pinky-review-decisions/1':
        raise ValueError('invalid current authority schema')
    workspace, generation = current.get('workspace_id'), current.get('generation')
    if (not isinstance(workspace, str) or not re.fullmatch('[a-f0-9]{32}', workspace)
            or type(generation) is not int or not 1 <= generation <= 2**63-1):
        raise ValueError('invalid workspace or authority generation')
    value = {k: v for k, v in current.items() if k != 'decision_sha256'}
    if not valid_digest(current.get('decision_sha256')) or sha(encoded(value)) != current['decision_sha256']:
        raise ValueError('invalid current decision digest')
    for key in ('pixel_classes_sha256', 'classes_signature', 'map_reference_sha256'):
        if key not in current or not valid_digest(current[key], nullable=True):
            raise ValueError('invalid authority class/map binding')
    if ((current['pixel_classes_sha256'] is None) != (current['classes_signature'] is None)
            or (current['pixel_classes_sha256'] is not None and
                (type(current.get('ignore_index')) is not int or current['ignore_index'] != 255))
            or (current['pixel_classes_sha256'] is None and current.get('ignore_index') is not None)):
        raise ValueError('invalid class signature or ignore index')
    rows = current.get('frames')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100000:
        raise ValueError('bounded authority frames required')
    ids, identities = set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid authority frame')
        index = row.get('frame')
        if (type(index) is not int or index < 0 or index in ids
                or row.get('review_uid') != f'{workspace}:{index}'
                or not isinstance(row.get('identity'), str) or not row['identity']
                or row['identity'] in identities):
            raise ValueError('duplicate or invalid frame identity')
        ids.add(index)
        identities.add(row['identity'])
        for key, low, high in (('width', 1, 4096), ('height', 1, 4096),
                               ('object_version', 1, 2**63-1), ('mask_version', 0, 2**63-1)):
            if type(row.get(key)) is not int or not low <= row[key] <= high:
                raise ValueError('invalid frame dimensions or revision')
        for key in ('object_decision', 'mask_decision'):
            if row.get(key) not in ('pending', 'approved', 'excluded'):
                raise ValueError('invalid authority decision')
        if type(row.get('frame_excluded')) is not bool or row['frame_excluded'] != (row['object_decision'] == 'excluded'):
            raise ValueError('invalid whole-frame exclusion tombstone')
        for key in ('image_sha256', 'representations_sha256', 'source_sha256', 'object_review_sha256'):
            if not valid_digest(row.get(key)):
                raise ValueError('invalid frame image or representation digest')
        if not valid_digest(row.get('mask_sha256'), nullable=True):
            raise ValueError('invalid mask digest')
        for key in ('complete_frame_review', 'background_reviewed', 'original_video_verified'):
            if type(row.get(key)) is not bool:
                raise ValueError('invalid frame review flag')
        if ((row.get('fixed_eval_overlap') is not None and type(row['fixed_eval_overlap']) is not bool)
                or not valid_digest(row.get('source_video_sha256'), nullable=True)
                or (row.get('video_frame') is not None and
                    (type(row['video_frame']) is not int or row['video_frame'] < 0))):
            raise ValueError('invalid video/evaluation binding')
        for key in ('source_session', 'capture_group', 'map_revision'):
            if row.get(key) is not None and (not isinstance(row[key], str) or not row[key]):
                raise ValueError('invalid source metadata')
        if row.get('map_pose') is not None and not isinstance(row['map_pose'], dict):
            raise ValueError('invalid map pose')
        if row['mask_decision'] == 'approved':
            expected = {'image_sha256': row['image_sha256'], 'mask_sha256': row['mask_sha256'],
                        'mask_version': row['mask_version'], 'width': row['width'], 'height': row['height'],
                        'classes_sha256': current['pixel_classes_sha256'],
                        'classes_signature': current['classes_signature'], 'ignore_index': 255,
                        'complete_frame_review': True, 'background_reviewed': True}
            approval = row.get('pixel_approval')
            reviewed_unknown = isinstance(approval, dict) and approval.get('unknown_pixels_reviewed') is True
            if reviewed_unknown:
                count = approval.get('reviewed_unknown_count')
                if (not row.get('fixed_eval_overlap') or not row['identity'].startswith('mcap:')
                        or type(count) is not int or not 0 < count < row['width'] * row['height']):
                    raise ValueError('invalid reviewed unknown approval')
                expected.update(unknown_pixels_reviewed=True, reviewed_unknown_count=count)
            if (not row['complete_frame_review'] or not row['background_reviewed']
                    or approval != expected
                    or (row.get('fixed_eval_overlap') and not row['identity'].startswith('mcap:'))
                    or not row['mask_sha256'] or not current['pixel_classes_sha256']):
                raise ValueError('invalid exact pixel approval binding')
            for key in ('mask_version', 'width', 'height', 'ignore_index'):
                if type(approval.get(key)) is not int:
                    raise ValueError('invalid exact pixel approval scalar type')
            for key in ('complete_frame_review', 'background_reviewed'):
                if approval.get(key) is not True:
                    raise ValueError('invalid exact pixel approval scalar type')
        elif row.get('pixel_approval') is not None:
            raise ValueError('pending or excluded mask cannot retain approval')
    return current


def safe_file(root, name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/'))):
        raise ValueError('invalid export reference')
    path = root
    for part in name.split('/'):
        path = path / part
        if path.is_symlink():
            raise ValueError('symlink export reference')
    if not stat.S_ISREG(path.stat().st_mode) or not path.resolve().is_relative_to(root):
        raise ValueError('non-regular export reference')
    return path


def verify_current(export, current):
    """Caller must fetch configured live authority, pin workspace, and enforce monotonicity.

    Supplying a saved historical current cannot establish freshness with this helper.
    """
    validate_authority(current)
    base = Path(export).absolute()
    if any(p.is_symlink() for p in (base, *base.parents)):
        raise ValueError('symlink export root')
    root = base.resolve()
    raw = safe_file(root, 'review-contract.json').read_bytes()
    if safe_file(root, 'AUTHORITY_COMPLETE').read_text().strip() != sha(raw):
        raise ValueError('incomplete review authority')
    doc = json.loads(raw)
    validate_authority(doc.get('authority'))
    if doc.get('schema') != 'rosy.pinky-review-export/2' or encoded(doc['authority']) != encoded(current):
        raise ValueError('stale review export; latest decisions required')
    if (doc.get('current_decisions_required') is not True or doc.get('training_dataset_qualified') is not False
            or doc.get('pixel_projection_verified') is not False):
        raise ValueError('invalid review qualification boundary')
    files = doc.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('sealed files required')
    payload = {}
    for item in files:
        name = item.get('path')
        if name in payload or name in ('review-contract.json', 'AUTHORITY_COMPLETE'):
            raise ValueError('duplicate or circular export reference')
        path = safe_file(root, name)
        data = path.read_bytes()
        if (type(item.get('bytes')) is not int or not valid_digest(item.get('sha256'))
                or len(data) != item['bytes'] or sha(data) != item['sha256']):
            raise ValueError('review export file changed')
        payload[name] = data
    mandatory = {'manifest.json', 'COMPLETE', 'pinky-review-receipt.json',
                 'inputs/source.jsonl', 'inputs/human.jsonl', 'application-snapshot.json',
                 'representations.json', 'pixel-reviews.jsonl'}
    if current['pixel_classes_sha256']:
        mandatory.add('pixel-classes.yaml')
    if current['map_reference_sha256']:
        mandatory.add('cad-reference.json')
    if not mandatory <= payload.keys():
        raise ValueError('mandatory sealed file missing')
    if payload['COMPLETE'].decode().strip() != sha(payload['manifest.json']):
        raise ValueError('legacy object seal differs')
    manifest = json.loads(payload['manifest.json'])
    for item in manifest['files']:
        if (item['path'] not in payload or sha(payload[item['path']]) != item['sha256']
                or len(payload[item['path']]) != item['bytes']):
            raise ValueError('mandatory legacy source file missing or differs')
    if (sha(payload['inputs/source.jsonl']) != manifest['source_sha256']
            or sha(payload['inputs/human.jsonl']) != manifest['human_sha256']):
        raise ValueError('object source binding differs')
    receipt = json.loads(payload['pinky-review-receipt.json'])
    validate_authority(receipt.get('authority'))
    if encoded(receipt['authority']) != encoded(current) or receipt.get('export_id') != doc.get('export_id'):
        raise ValueError('receipt authority differs')
    frames = json.loads(payload['application-snapshot.json'])
    sources = [json.loads(line) for line in payload['inputs/source.jsonl'].splitlines() if line]
    if len(frames) != len(current['frames']) or sources != [f['source'] for f in frames]:
        raise ValueError('application/source snapshot differs')
    human = [json.loads(line) for line in payload['inputs/human.jsonl'].splitlines() if line]
    expected_human = [human_review(f) for f in frames if not any(b.get('label') is None for b in f['review']['boxes'])]
    if human != expected_human:
        raise ValueError('human object content differs from snapshot')
    representations = json.loads(payload['representations.json'])
    for frame, row in zip(frames, current['frames']):
        source = frame['source']
        if (frame['index'] != row['frame'] or frame['version'] != row['object_version']
                or frame['status'] != row['object_decision'] or source['image_sha256'] != row['image_sha256']
                or source['width'] != row['width'] or source['height'] != row['height']
                or sha(encoded(source)) != row['source_sha256']
                or sha(encoded(human_review(frame))) != row['object_review_sha256']
                or identity(source, legacy=frame['index']) != row['identity']
                or sha(encoded(representations.get(str(row['frame']), []))) != row['representations_sha256']):
            raise ValueError('frame snapshot differs from authority')
        suffix = Path(source['image']).suffix.lower()
        name = f'inputs/images/{row["frame"]:06d}{suffix}'
        if name not in payload or sha(payload[name]) != row['image_sha256']:
            raise ValueError('mandatory approved image/source missing or differs')
    approved_objects = {r['frame'] for r in current['frames'] if r['object_decision'] == 'approved'}
    exported_objects = [i for group in manifest['groups'] for i in group['exported_indices']]
    if len(exported_objects) != len(approved_objects) or set(exported_objects) != approved_objects:
        raise ValueError('object approved count/decisions differ')
    if current['pixel_classes_sha256']:
        import build
        class_raw = payload['pixel-classes.yaml']
        normalized = build.load_classes(Path('classes.yaml'), source_bytes=class_raw)
        if (sha(class_raw) != current['pixel_classes_sha256']
                or sha(json.dumps(normalized, sort_keys=True).encode()) != current['classes_signature']):
            raise ValueError('classes payload differs from authority')
    if current['map_reference_sha256'] and sha(payload['cad-reference.json']) != current['map_reference_sha256']:
        raise ValueError('CAD reference differs from authority')
    approved_masks = [r for r in current['frames'] if r['mask_decision'] == 'approved' and r['object_decision'] != 'excluded']
    reviews = [json.loads(line) for line in payload['pixel-reviews.jsonl'].splitlines() if line]
    if type(doc.get('pixel_approved_frames')) is not int or len(reviews) != len(approved_masks) or len(reviews) != doc['pixel_approved_frames']:
        raise ValueError('pixel approved count differs')
    for review, row in zip(reviews, approved_masks):
        name = f'pixel-masks/{row["frame"]:06d}.png'
        if (any(review.get(k) != v for k, v in row.items()) or review.get('mask') != name
                or name not in payload or sha(payload[name]) != row['mask_sha256']
                or review.get('classes_sha256') != current['pixel_classes_sha256']):
            raise ValueError('pixel payload differs from exact approval')
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(payload[name], np.uint8), cv2.IMREAD_UNCHANGED)
        unknown = row['pixel_approval'].get('reviewed_unknown_count', 0)
        if (image is None or image.dtype != np.uint8 or image.shape != (row['height'], row['width'])
                or int(np.count_nonzero(image == 255)) != unknown
                or not np.isin(image, [c['index'] for c in normalized] + ([255] if unknown else [])).all()):
            raise ValueError('approved indexed mask payload invalid')
    return doc
