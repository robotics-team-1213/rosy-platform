"""Validate/freeze additional image representations; imports never approve labels."""
import json
import re
import zipfile
from pathlib import Path

import cv2
import numpy as np

import build
import edge_review
import review_evidence
import review_masks
from mcap_proof import prove_frames


def bounded(path, limit=32 * 1024 * 1024):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError('input file exceeds local review limit')
    return path.read_bytes()


def image(raw, digest, width, height):
    if review_masks.sha(raw) != digest:
        raise ValueError('source image hash differs')
    pixels = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if pixels is None or pixels.shape[:2] != (height, width):
        raise ValueError('source image dimensions differ')
    if not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise ValueError('bounded image dimensions required')


def freeze_image(store, raw, suffix):
    if suffix.lower() not in ('.jpg', '.jpeg', '.png'):
        raise ValueError('JPEG/PNG original required')
    folder = store.state / 'originals'
    folder.mkdir(exist_ok=True)
    file = folder / (review_masks.sha(raw) + suffix.lower())
    if not file.exists():
        file.write_bytes(raw)
    elif file.read_bytes() != raw:
        raise ValueError('original hash collision')
    return file.relative_to(store.state).as_posix()


def import_frames(store, body):
    root = Path(body['path']).resolve()
    catalog = root / 'verified-inputs.jsonl' if root.is_dir() else root
    raw = bounded(catalog)
    rows = [json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
    if not rows or len(rows) > 2000:
        raise ValueError('1..2000 original frame representations required')
    classes_path = body.get('classes')
    if not classes_path:
        draft = next((row.get('mask') for row in rows if row.get('mask')), None)
        if draft:
            classes_path = (str(Path(draft['zip']).parent / 'classes.yaml') if 'zip' in draft
                            else str(catalog.parent / 'classes.yaml'))
    binding = review_masks.classes(store)
    class_raw = bounded(classes_path, 1024 * 1024) if classes_path else None
    if class_raw:
        values = build.load_classes(Path(classes_path), source_bytes=class_raw)
        binding = {'classes': values, 'sha256': review_masks.sha(class_raw), 'ignore_index': 255}
        old = review_masks.classes(store)
        if old and old['sha256'] != binding['sha256']:
            raise ValueError('pixel classes differ from existing workspace')
    if not binding:
        raise ValueError('verified classes.yaml required for pixel review')
    mcap_groups = {}
    with store.connect() as db:
        kind = db.execute("SELECT value FROM metadata WHERE key='workspace_kind'").fetchone()
    for row in rows:
        if row.get('source_kind') == 'mcap':
            if not kind or kind[0] != 'evaluation':
                raise ValueError('MCAP evaluation requires a separate evaluation workspace')
            if row.get('mask'):
                raise ValueError('MCAP evaluation starts with an empty pixel mask')
            mcap = row.get('mcap')
            if not isinstance(mcap, dict) or not isinstance(mcap.get('frame'), dict):
                raise ValueError('MCAP source proof required')
            session = Path(mcap['session_dir'])
            if session.name != row.get('source_session'):
                raise ValueError('MCAP source session differs')
            frame = mcap['frame']
            selector = {key: frame[key] for key in
                        ('topic', 'log_ns', 'bag', 'channel_id', 'message_ordinal', 'header_stamp_ns')}
            mcap_groups.setdefault(session, []).append((row, mcap, {**selector, 'image': row['image']}))
        elif kind and kind[0] == 'evaluation':
            raise ValueError('evaluation workspace accepts only MCAP sources')
    for session, group in mcap_groups.items():
        first = group[0][1]
        if any(mcap['metadata_sha256'] != first['metadata_sha256'] or
               mcap['bags'] != first['bags'] for _, mcap, _ in group):
            raise ValueError('MCAP bag inventory differs within catalog')
        verified = prove_frames(session, [selector for _, _, selector in group],
                                body.get('scratch', store.state), expected=first)
        for (_, mcap, _), frame in zip(group, verified['frames']):
            if frame != mcap['frame'] or verified['decoder'] != mcap.get('decoder'):
                raise ValueError('MCAP source proof differs')
    checked = []
    for row in rows:
        if not all(isinstance(row.get(k), str) and row[k].strip() for k in ('source_session', 'capture_group')):
            raise ValueError('source_session and capture_group required')
        if row.get('source_kind') == 'mcap':
            mcap = row.get('mcap')
        else:
            if type(row.get('video_frame')) is not int or row['video_frame'] < 0:
                raise ValueError('original video frame index required')
            if not re.fullmatch('[0-9a-f]{64}', row.get('source_video_sha256', '')):
                raise ValueError('declared source video SHA required')
        width, height = row['width'], row['height']
        if type(width) is not int or type(height) is not int:
            raise ValueError('integer image dimensions required')
        data = bounded(row['image'])
        image(data, row['image_sha256'], width, height)
        objects = row.get('objects', [])
        if not isinstance(objects, list) or len(objects) > 100:
            raise ValueError('at most 100 object draft boxes required')
        for box in objects:
            store.validate_boxes({'width': width, 'height': height}, [box],
                                 classes=store.object_classes())
        mask, labelmap_sha = None, None
        if row.get('mask'):
            ref = row['mask']
            if not isinstance(ref, dict) or not re.fullmatch('[0-9a-f]{64}', ref.get('sha256', '')):
                raise ValueError('draft mask digest required')
            if set(ref) == {'indexed_png', 'sha256', 'classes_sha256'}:
                if ref['classes_sha256'] != binding['sha256']:
                    raise ValueError('indexed draft classes hash differs')
                draft = bounded(edge_review.bound(catalog.parent, ref['indexed_png']))
                if review_masks.sha(draft) != ref['sha256']:
                    raise ValueError('draft mask hash differs')
                mask = review_masks.from_indexed(draft, width, height, binding)
            elif set(ref) == {'zip', 'entry', 'sha256'}:
                with zipfile.ZipFile(ref['zip']) as archive:
                    entry = archive.getinfo(ref['entry'])
                    if entry.file_size > 32 * 1024 * 1024:
                        raise ValueError('bounded draft mask required')
                    draft = archive.read(entry)
                    if review_masks.sha(draft) != ref['sha256']:
                        raise ValueError('draft mask hash differs')
                    labelmap_raw = archive.read('labelmap.txt')
                    labelmap_sha = review_masks.sha(labelmap_raw)
                    mask = review_masks.from_color(draft, width, height, labelmap_raw, binding)
            else:
                raise ValueError('draft mask reference must be indexed PNG or color ZIP')
            indexed = cv2.imdecode(np.frombuffer(mask, np.uint8), cv2.IMREAD_UNCHANGED)
            review_masks.require_inside_lane_boundaries(indexed, binding)
        normalized = {key: row.get(key) for key in
                      ('source_session', 'capture_group', 'source_video_sha256', 'video_frame',
                       'video_time_s', 'timestamp_basis', 'collection', 'dataset_memberships_snapshot')}
        for key in ('annotation_source', 'annotation_note'):
            if row.get(key):
                if not isinstance(row[key], str) or len(row[key]) > 100:
                    raise ValueError(f'bounded {key} required')
                normalized[key] = row[key]
        normalized['source_session_declared'] = row['source_session']
        if row.get('source_kind') == 'mcap':
            normalized.update(source_kind='mcap', mcap=mcap)
        else:
            try:
                normalized['source_session'] = edge_review.session(row.get('source_video', ''))
            except ValueError:
                pass  # Preserve historical identities; never invent authenticated capture stamps.
        normalized.update(video=row.get('source_video'), width=width, height=height,
                          image_sha256=row['image_sha256'], objects=objects,
                          original_video_verified=False, map_revision=None, map_pose=None,
                          fixed_eval_overlap=row.get('fixed_eval_overlap') is True,
                          review_status='pending_human', complete_frame_review=False,
                          import_catalog_sha256=review_masks.sha(raw),
                          draft_labelmap_sha256=labelmap_sha,
                          original_source_path=row['image'])
        checked.append((normalized, data, Path(row['image']).suffix, mask))
    # No frame/decision mutation until every image, draft and class reference passes.
    with store.lock:
        if class_raw:
            review_masks.bind_classes(store, class_raw)
        frozen = []
        for source, data, suffix, mask in checked:
            source['image'] = freeze_image(store, data, suffix)
            frozen.append((source, review_masks.freeze(store, mask) if mask else None))
        added, duplicates, aliases, draft_added, legacy_linked, queued = [], 0, 0, 0, 0, 0
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            next_id = db.execute('SELECT COALESCE(MAX(id),-1)+1 FROM frames').fetchone()[0]
            for source, mask in frozen:
                key = review_evidence.identity(source)
                found = db.execute('SELECT frame FROM frame_keys WHERE identity=?', (key,)).fetchone()
                if not found:
                    # Link only an exact primary image plus the same declared video/frame.
                    # Never match by pixels alone across captures or replace human decisions.
                    matches = []
                    for candidate in db.execute('SELECT id,source FROM frames') if source.get('source_kind') != 'mcap' else ():
                        old = json.loads(candidate['source'])
                        if (not old.get('source_video_sha256') and
                                old['image_sha256'] == source['image_sha256'] and
                                Path(old.get('video') or '').name == Path(source.get('video') or '').name and
                                old.get('video_frame') == source['video_frame']):
                            matches.append((candidate['id'], old))
                    if len(matches) > 1:
                        raise ValueError('ambiguous existing legacy primary image binding')
                    if matches:
                        index, old = matches[0]
                        enriched = dict(old, legacy_source=old)
                        for field in ('source_session', 'capture_group', 'source_video_sha256',
                                      'original_video_verified', 'fixed_eval_overlap', 'map_revision',
                                      'map_pose', 'source_session_declared', 'import_catalog_sha256',
                                      'original_source_path', 'dataset_memberships_snapshot'):
                            enriched[field] = source.get(field)
                        db.execute('UPDATE frames SET source=? WHERE id=?', (json.dumps(enriched), index))
                        db.execute('UPDATE frame_keys SET identity=? WHERE frame=?', (key, index))
                        found = (index,)
                        legacy_linked += 1
                if found:
                    index = found[0]
                    previous = db.execute('SELECT source FROM frames WHERE id=?', (index,)).fetchone()
                    existing = json.loads(previous[0])
                    if (existing['width'], existing['height']) != (source['width'], source['height']):
                        raise ValueError('same source frame has conflicting dimensions')
                    if (existing.get('capture_group'), existing.get('source_session')) != (source['capture_group'], source['source_session']):
                        raise ValueError('same source frame has conflicting session identity')
                    if mask is not None:
                        current = db.execute('SELECT sha256 FROM masks WHERE frame=?', (index,)).fetchone()
                        if not current or current['sha256'] != mask[1]:
                            queued += db.execute('INSERT OR IGNORE INTO pixel_drafts '
                                                 '(frame,sha256,path,catalog_sha256,origin) VALUES (?,?,?,?,?)',
                                                 (index, mask[1], mask[0], source['import_catalog_sha256'],
                                                  source.get('annotation_source'))).rowcount
                    duplicates += 1
                else:
                    index = next_id
                    next_id += 1
                    source['index'] = index
                    review = {'index': index, 'image_sha256': source['image_sha256'], 'boxes': [],
                              'video': source.get('video'), 'video_frame': source.get('video_frame'),
                              'review_status': 'pending_human', 'complete_frame_review': False,
                              'review_origin': 'pinky_web_additional_import'}
                    db.execute('INSERT INTO frames VALUES (?,?,?,?,1)',
                               (index, json.dumps(source), json.dumps(review), 'pending'))
                    db.execute('INSERT INTO frame_keys VALUES (?,?)', (key, index))
                    db.execute('INSERT INTO events(frame,action,version,review) VALUES (?,?,?,?)',
                               (index, 'additional_import', 1, json.dumps(review)))
                    added.append(index)
                cursor = db.execute('INSERT OR IGNORE INTO representations VALUES (?,?,?)',
                                    (index, source['image_sha256'], json.dumps(source)))
                aliases += cursor.rowcount
                # A later alternate representation never overwrites any pixel review.
                if not found:
                    if mask is None:
                        mask = review_masks.freeze(store, review_masks.encode(
                            np.full((source['height'], source['width']), 255, dtype=np.uint8)))
                    db.execute('INSERT INTO masks(frame,version,status,path,sha256) VALUES (?,1,?,?,?)',
                               (index, 'pending', *mask))
                    draft_added += 1
            if added or aliases or legacy_linked or queued:
                db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
    return {'added': len(added), 'indices': added, 'duplicate_representations': duplicates,
            'new_representations': aliases, 'pixel_reviews_pending': draft_added,
            'draft_candidates_queued': queued,
            'legacy_primary_bindings': legacy_linked,
            'catalog_sha256': review_masks.sha(raw), 'original_video_verified': False}
