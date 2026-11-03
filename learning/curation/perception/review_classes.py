"""Explicit administrator class revisions; ordinary bind-once guards remain intact (D-973)."""
import hashlib
import json
import re
from pathlib import Path

import yaml

import build
import class_sets
import review_masks


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def binding(store, lane):
    if lane not in ('object', 'pixel'):
        raise ValueError('object or pixel class kind required')
    return class_sets.object_set(store) if lane == 'object' else review_masks.served_classes(store)


def impact(db, lane):
    table = 'frames' if lane == 'object' else 'masks'
    return db.execute(f"SELECT COUNT(*) FROM {table} WHERE status='approved'").fetchone()[0]


def snapshot(store, lane):
    with store.lock, store.connect() as db:
        value = binding(store, lane)
        return {'kind': lane, 'binding': value, 'expected_sha': digest(value),
                'approved_count': impact(db, lane), 'scope': 'workspace', 'roles': list(build.ROLES)}


def proposal(current, lane, rows):
    old = (current or {}).get('classes', [])
    if not isinstance(rows, list) or not len(old) <= len(rows) <= 255 or not rows:
        raise ValueError('existing classes must remain; at most 255 classes')
    allowed = {'index', 'name', 'display', 'color', 'hotkey'} | ({'role', 'semantic'} if lane == 'pixel' else set())
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) - allowed or not {'index', 'name', 'display', 'color'} <= set(row):
            raise ValueError('invalid class fields')
        if type(row['index']) is not int or not 0 <= row['index'] < 255:
            raise ValueError('class index must be 0..254; 255 is reserved')
        if not isinstance(row['name'], str) or not row['name'] or (i >= len(old) and not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', row['name'])):
            raise ValueError('canonical name must be lowercase letters, numbers and underscores')
        if not isinstance(row['display'], str) or not row['display'].strip() or len(row['display']) > 80:
            raise ValueError('display name must be 1..80 characters')
        if ('hotkey' in row and row['hotkey'] is not None and not isinstance(row['hotkey'], str)) or (lane == 'pixel' and not isinstance(row.get('role'), str)):
            raise ValueError('invalid class role or hotkey type')
        color = row['color']
        if color is not None and (not isinstance(color, list) or len(color) != 3 or
                any(type(v) is not int or not 0 <= v <= 255 for v in color)):
            raise ValueError('color requires RGB integers 0..255')
        if i < len(old) and any(row.get(key) != old[i].get(key) for key in ('index', 'name', 'role', 'semantic', 'hotkey')):
            raise ValueError('existing index, canonical name, role and semantic are immutable')
    if len({r['index'] for r in rows}) != len(rows) or len({r['name'] for r in rows}) != len(rows):
        raise ValueError('class indices and canonical names must be unique')
    colors = [tuple(r['color']) for r in rows if r['color'] is not None]
    if len(set(colors)) != len(colors):
        raise ValueError('class colors must be unique')
    if lane == 'object':
        if [r['index'] for r in rows] != list(range(len(rows))):
            raise ValueError('object indices must remain dense')
        value = class_sets._record([r['name'] for r in rows], 'detect', {'kind': 'admin_revision'},
            {r['name']: r['display'] for r in rows}, {r['name']: r['color'] for r in rows if r['color'] is not None})
        return value, value['sha256'] != current['sha256'], None
    raw = yaml.safe_dump({'classes': rows}, allow_unicode=True, sort_keys=True).encode()
    values = build.load_classes(Path('classes.yaml'), source_bytes=raw)
    for value, row in zip(values, rows):
        value['display'] = row['display']
    changed = current is None or review_masks.signature(values) != review_masks.signature(old)
    value = {'classes': values, 'sha256': review_masks.sha(raw) if changed else current['sha256'],
             'ignore_index': 255, 'classes_signature': review_masks.signature(values)}
    return value, changed, raw if changed else None


def revise(store, body, actor, conflict):
    if set(body) != {'kind', 'classes', 'expected_sha', 'expected_impact', 'confirm'} or body['confirm'] is not True:
        raise ValueError('explicit revision confirmation required')
    if not isinstance(body['expected_sha'], str) or type(body['expected_impact']) is not int or body['expected_impact'] < 0:
        raise ValueError('expected revision SHA and approval count required')
    lane = body['kind']
    with store.lock, store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = binding(store, lane)
        if digest(current) != body['expected_sha']:
            raise conflict('클래스가 바뀌었습니다. 다시 불러오세요.')
        value, changed, raw = proposal(current, lane, body['classes'])
        count = impact(db, lane) if changed else 0
        if body['expected_impact'] != count:
            raise conflict('재검수 대상 수가 바뀌었습니다. 적용 전 다시 확인하세요.')
        if raw:
            folder = store.state / 'pixel'
            folder.mkdir(exist_ok=True)
            path = folder / (value['sha256'] + '.yaml')
            if path.exists() and path.read_bytes() != raw:
                raise ValueError('class manifest hash collision')
            if not path.exists():
                path.write_bytes(raw)
        db.execute('INSERT INTO class_revisions(kind,old_binding,new_binding,actor,impact) VALUES (?,?,?,?,?)',
                   (lane, json.dumps(current), json.dumps(value), actor, count))
        key = 'object_class_set' if lane == 'object' else 'pixel_classes'
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(value)))
        if changed and lane == 'object':
            db.execute('INSERT OR IGNORE INTO object_draft_quarantine SELECT frame,sha256 FROM object_drafts')
            for row in db.execute('SELECT * FROM frames').fetchall():
                prior = json.loads(row['review'])
                # Snapshot every version: pending/excluded tabs must also reload the schema.
                prior['image_sha256'] = json.loads(row['source'])['image_sha256']
                db.execute('INSERT INTO events(frame,version,action,review) VALUES (?,?,?,?)',
                           (row['id'], row['version'], 'class_revision_snapshot', json.dumps(prior)))
                updated = dict(prior, review_status='pending_human', complete_frame_review=False, last_actor=actor) if row['status'] == 'approved' else prior
                status = 'pending' if row['status'] == 'approved' else row['status']
                raw_review = json.dumps(updated) if row['status'] == 'approved' else row['review']
                db.execute('UPDATE frames SET review=?,status=?,version=version+1 WHERE id=?', (raw_review, status, row['id']))
                db.execute('INSERT INTO events(frame,version,action,review) VALUES (?,?,?,?)',
                           (row['id'], row['version'] + 1, 'class_revision', json.dumps(updated)))
        elif changed:
            db.execute('UPDATE pixel_drafts SET withdrawn=1')
            for frame in db.execute('SELECT id FROM frames').fetchall():
                stored = db.execute('SELECT * FROM masks WHERE frame=?', (frame['id'],)).fetchone()
                row = dict(stored) if stored else dict(frame=frame['id'], version=0, status='pending',
                    path=None, sha256=None, complete=0, background=0, approval=None)
                previous = dict(row, actor=actor, classes=current, saved_version=row['version'] + 1)
                db.execute('INSERT INTO pixel_events(frame,version,action,review) VALUES (?,?,?,?)',
                           (row['frame'], row['version'] + 1, 'class_revision', json.dumps(previous)))
                approved = row['status'] == 'approved'
                db.execute('INSERT OR REPLACE INTO masks(frame,version,status,path,sha256,complete,background,approval) VALUES (?,?,?,?,?,?,?,?)',
                    (row['frame'], row['version'] + 1, 'pending' if approved else row['status'], row['path'], row['sha256'],
                     0 if approved else row['complete'], 0 if approved else row['background'], None if approved else row['approval']))
        db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
    return snapshot(store, lane)
