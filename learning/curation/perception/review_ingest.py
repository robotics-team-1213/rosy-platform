"""Validate/freeze additional image representations; imports never approve labels."""
import json
import os
import re
import stat
import threading
import zipfile
import zlib
from pathlib import Path

import cv2
import numpy as np
import yaml

import build
import class_sets
import edge_review
import review_evidence
import review_masks
from mcap_proof import prove_frames


OTHER_CLASS_SET = ('초안 마스크가 다른 클래스셋으로 만들어졌습니다 ({}). 초안은 같은 클래스셋의 것만 '
                   '가져올 수 있습니다. 초안 없이 가져오거나 초안과 같은 classes.yaml을 지정하세요.')


def bounded(path, limit=32 * 1024 * 1024):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError('input file exceeds local review limit')
    return path.read_bytes()


class _CatalogCapture:
    """One import's no-follow namespace and finite same-handle content captures."""
    def __init__(self, selected):
        self.selected = Path(selected)
        self.fds, self.bindings, self.directories = [], [], {}

    @staticmethod
    def signature(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def __enter__(self):
        if (os.name != 'posix' or any(not hasattr(os, flag) for flag in
                ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK')) or
                os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd or
                os.stat not in os.supports_follow_symlinks):
            raise ValueError('catalog-relative requires POSIX nofollow/dir_fd support')
        if not self.selected.is_absolute():
            raise ValueError('absolute catalog path required')
        try:
            self.base = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.fds.append(self.base)
            parent, leaf = self.parent(self.selected)
            info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                self.root = self.directory(parent, leaf)
                self.path = Path(os.path.abspath(self.selected))
                catalog_name = 'verified-inputs.jsonl'
            else:
                self.root, self.path, catalog_name = parent, Path(os.path.abspath(self.selected.parent)), leaf
            self.catalog = self.path / catalog_name
            self.raw = self.file(self.root, catalog_name, 32 * 1024**2)
            return self
        except BaseException as exc:
            self.close()
            if isinstance(exc, OSError):
                raise ValueError('catalog capture path must contain no links and be regular') from exc
            raise

    def close(self):
        for fd in reversed(self.fds):
            os.close(fd)
        self.fds.clear()

    def __exit__(self, *args):
        self.close()

    def directory(self, parent, name):
        key = (parent, name)
        if key not in self.directories:
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            self.fds.append(fd)
            info = os.fstat(fd)
            self.bindings.append((parent, name, self.signature(info), True))
            self.directories[key] = fd
        return self.directories[key]

    def parent(self, path):
        # Walk the original spelling, including '..', so no normalization hides links.
        parts = path.parts[1:]
        parent = self.base
        for component in parts[:-1]:
            parent = self.directory(parent, component)
        return parent, parts[-1] if parts else '.'

    @staticmethod
    def relative(reference):
        if (not isinstance(reference, str) or not reference or reference.startswith('/') or
                '\\' in reference or ':' in reference or any(ord(c) < 32 for c in reference) or
                any(part in ('', '.', '..') for part in reference.split('/'))):
            raise ValueError('portable relative catalog reference required')
        return reference.split('/')

    def file(self, parent, name, limit=None):
        fd = None
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('regular catalog reference file required')
            raw = None
            if limit is not None:
                if before.st_size > limit:
                    raise ValueError('input file exceeds local review limit')
                chunks, size = [], 0
                while size < limit + 1:
                    chunk = os.read(fd, min(1024**2, limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                raw = b''.join(chunks)
                if size > limit:
                    raise ValueError('input capture exceeds local review limit')
                if size != before.st_size:
                    raise ValueError('input capture size changed')
            if self.signature(os.fstat(fd)) != self.signature(before):
                raise ValueError('input capture metadata changed')
            self.bindings.append((parent, name, self.signature(before), False))
            return raw
        except OSError as exc:
            raise ValueError('catalog capture path must contain no links and be regular') from exc
        finally:
            if fd is not None:
                os.close(fd)

    def reference(self, reference, limit=None):
        parts = self.relative(reference)
        try:
            parent = self.root
            for name in parts[:-1]:
                parent = self.directory(parent, name)
            return self.file(parent, parts[-1], limit)
        except OSError as exc:
            raise ValueError('catalog reference path must contain no links') from exc

    def classes(self, explicit):
        if explicit:
            path = Path(explicit)
            if not path.is_absolute():
                path = Path.cwd() / path
            try:
                parent, leaf = self.parent(path)
                return self.file(parent, leaf, 1024**2)
            except OSError as exc:
                raise ValueError('class capture path must contain no links') from exc
        return self.file(self.root, 'classes.yaml', 1024**2)

    def adjacent_classes(self):
        try:
            os.stat('classes.yaml', dir_fd=self.root, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def verify(self):
        for parent, name, expected, directory in self.bindings:
            try:
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except OSError as exc:
                raise ValueError('catalog namespace binding changed') from exc
            actual = self.signature(info)
            if ((directory and (not stat.S_ISDIR(info.st_mode) or actual[:2] != expected[:2])) or
                    (not directory and (not stat.S_ISREG(info.st_mode) or actual != expected))):
                raise ValueError('catalog namespace binding changed')


def _png(raw):
    if (len(raw) < 33 or raw[:8] != b'\x89PNG\r\n\x1a\n' or
            raw[8:16] != b'\x00\x00\x00\rIHDR' or
            zlib.crc32(raw[12:29]) != int.from_bytes(raw[29:33], 'big')):
        raise ValueError('PNG signature and IHDR required for catalog-relative image')


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


def import_frames(store, body, upstream=None):
    """`upstream` maps image path to server-verified provider provenance; catalogs never declare it."""
    relative = body.get('catalog_relative', False)
    if type(relative) is not bool:
        raise ValueError('catalog_relative must be bool')
    if relative:
        with _CatalogCapture(body['path']) as capture:
            return _import_frames(store, body, upstream, capture)
    return _import_frames(store, body, upstream)


def _import_frames(store, body, upstream=None, capture=None):
    if capture:
        catalog, raw = capture.catalog, capture.raw
    else:
        root = Path(body['path']).resolve()
        catalog = root / 'verified-inputs.jsonl' if root.is_dir() else root
        raw = bounded(catalog)
    rows = [json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
    if not rows or len(rows) > 2000:
        raise ValueError('1..2000 original frame representations required')
    if capture and any(not isinstance(row, dict) for row in rows):
        raise ValueError('catalog rows must be objects')
    if capture and any(row.get('source_kind') == 'mcap' or 'mask' in row or row.get('objects')
                       for row in rows):
        raise ValueError('catalog-relative supports only draft-free PNG/video; unsupported mode')
    classes_path = body.get('classes')
    if not classes_path:
        draft = next((row.get('mask') for row in rows if row.get('mask')), None)
        if draft:
            classes_path = (str(Path(draft['zip']).parent / 'classes.yaml') if 'zip' in draft
                            else str(catalog.parent / 'classes.yaml'))
        elif not review_masks.classes(store) and (capture.adjacent_classes() if capture else
                                                  (catalog.parent / 'classes.yaml').is_file()):
            classes_path = str(catalog.parent / 'classes.yaml')   # first binding of a draft-free catalog
    binding = review_masks.classes(store)
    try:
        class_raw = ((capture.classes(body.get('classes')) if capture else
                      bounded(classes_path, 1024 * 1024)) if classes_path else None)
    except OSError as exc:
        raise ValueError(f'픽셀 클래스 파일을 읽을 수 없습니다: {classes_path}') from exc
    if class_raw:
        try:
            values = build.load_classes(Path(classes_path), source_bytes=class_raw)
            if capture:
                indices = [value['index'] for value in values]
                if len(set(indices)) != len(indices) or any(not 0 <= index < 255 for index in indices):
                    raise ValueError('unique pixel class indices in 0..254 required')
                for entry in yaml.safe_load(class_raw)['classes']:
                    if 'display' in entry and (not isinstance(entry['display'], str) or not entry['display']):
                        raise ValueError('pixel class display must be a non-empty string')
        except build.BuildError as exc:
            raise ValueError(f'픽셀 클래스 파일을 해석할 수 없습니다: {classes_path} ({exc})') from exc
        except (ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
            # A parser error quotes the offending line; the path is caller-chosen, so name only the line.
            mark = getattr(exc, 'problem_mark', None)
            where = f' ({mark.line + 1}번째 줄)' if mark else ''
            raise ValueError(f'픽셀 클래스 파일을 해석할 수 없습니다: {classes_path}{where}') from exc
        binding = {'classes': values, 'sha256': review_masks.sha(class_raw), 'ignore_index': 255}
        old = review_masks.classes(store)
        if old and old['sha256'] != binding['sha256']:
            raise ValueError('pixel classes differ from existing workspace')
    if not binding:
        raise ValueError('픽셀 검수에는 검증된 classes.yaml이 필요합니다. 클래스 파일 경로를 넣거나 '
                         '자료 폴더 옆에 classes.yaml을 두세요.')
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
        hf = upstream.get(row.get('image')) if upstream is not None else None
        if upstream is not None and (hf is None or row.get('source_kind')):
            raise ValueError('verified upstream provenance required')
        if hf:
            pass  # A provider still image has no capture video; the dataset build keeps it blocked.
        elif row.get('source_kind') == 'mcap':
            mcap = row.get('mcap')
        else:
            if type(row.get('video_frame')) is not int or row['video_frame'] < 0:
                raise ValueError('original video frame index required')
            if not re.fullmatch('[0-9a-f]{64}', row.get('source_video_sha256', '')):
                raise ValueError('declared source video SHA required')
        width, height = row['width'], row['height']
        if type(width) is not int or type(height) is not int:
            raise ValueError('integer image dimensions required')
        video = row.get('source_video')
        if capture:
            capture.relative(row['image'])
            if Path(row['image']).suffix.lower() != '.png':
                raise ValueError('PNG original required for catalog-relative import')
            capture.reference(video)  # Metadata only: no video bytes or independent proof.
            video = str(capture.path / video)
            data = capture.reference(row['image'], 32 * 1024**2)
            _png(data)
        else:
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
                    raise ValueError(OTHER_CLASS_SET.format('indexed draft classes hash differs'))
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
                    try:
                        mask = review_masks.from_color(draft, width, height, labelmap_raw, binding)
                    except build.BuildError as exc:   # only an unknown label means another class set
                        if 'is not in classes.yaml' not in str(exc):
                            raise
                        raise ValueError(OTHER_CLASS_SET.format(exc)) from exc
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
        if hf:
            normalized.update(source_kind='huggingface', upstream=hf)
        elif row.get('source_kind') == 'mcap':
            normalized.update(source_kind='mcap', mcap=mcap)
        else:
            try:
                normalized['source_session'] = edge_review.session(row.get('source_video', ''))
            except ValueError:
                pass  # Preserve historical identities; never invent authenticated capture stamps.
        normalized.update(video=video, width=width, height=height,
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
        if capture:
            capture.verify()
        if class_raw:
            # Another import may have bound classes during filesystem preflight.
            current = review_masks.classes(store)
            if current and current['sha256'] != binding['sha256']:
                raise ValueError('pixel classes differ from existing workspace')
            review_masks.bind_classes(store, class_raw)
        frozen = []
        for source, data, suffix, mask in checked:
            source['image'] = freeze_image(store, data, suffix)
            frozen.append((source, review_masks.freeze(store, mask) if mask else None))
        added, duplicates, aliases, draft_added, legacy_linked, queued, object_queued = [], 0, 0, 0, 0, 0, 0
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
                    for candidate in db.execute('SELECT id,source FROM frames') if not source.get('source_kind') else ():
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
                    if source['objects'] and existing['image_sha256'] != source['image_sha256']:
                        raise ValueError('object draft requires the exact reviewed image')
                    if mask is not None:
                        current = db.execute('SELECT sha256 FROM masks WHERE frame=?', (index,)).fetchone()
                        if not current or current['sha256'] != mask[1]:
                            queued += db.execute('INSERT OR IGNORE INTO pixel_drafts '
                                                 '(frame,sha256,path,catalog_sha256,origin) VALUES (?,?,?,?,?)',
                                                 (index, mask[1], mask[0], source['import_catalog_sha256'],
                                                  source.get('annotation_source'))).rowcount
                    if source['objects']:
                        boxes = json.dumps(source['objects'], sort_keys=True)
                        digest = review_masks.sha(boxes.encode())
                        object_queued += db.execute('INSERT OR IGNORE INTO object_drafts '
                                                    '(frame,sha256,boxes,origin,catalog_sha256) VALUES (?,?,?,?,?)',
                                                    (index, digest, boxes, source.get('annotation_source'),
                                                     source['import_catalog_sha256'])).rowcount
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
            if added or aliases or legacy_linked or queued or object_queued:
                db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
    return {'added': len(added), 'indices': added, 'duplicate_representations': duplicates,
            'new_representations': aliases, 'pixel_reviews_pending': draft_added,
            'draft_candidates_queued': queued,
            'object_draft_candidates_queued': object_queued,
            'legacy_primary_bindings': legacy_linked,
            'catalog_sha256': review_masks.sha(raw), 'original_video_verified': False}


def import_hf(store, job, files, registered_by):
    """A completed, re-verified HF import (`LearningImports.verified`) into the pending review queue."""
    binding = review_masks.classes(store)
    if not binding:
        raise ValueError('이 작업 공간에 픽셀 클래스셋이 없습니다. 클래스셋을 정한 작업 공간에서 검수로 보내세요.')
    for name, path in files.items():   # D-485: a declared class set must be this workspace's own
        base = name.rsplit('/', 1)[-1]
        if base == 'classes.yaml' and review_masks.sha(bounded(path, 1024 * 1024)) != binding['sha256']:
            raise ValueError(f'가져온 {name}이 이 작업 공간의 픽셀 클래스셋과 다릅니다.')
        if base == 'data.yaml' and (class_sets.from_data_yaml(bounded(path, 1024 * 1024), 'detect')['sha256']
                                    != class_sets.object_set(store)['sha256']):
            raise ValueError(f'가져온 {name}이 이 작업 공간의 객체 클래스셋과 다릅니다.')
    source = f"hf:{job['repo_type']}/{job['repo_id']}@{job['revision']}"
    rows, upstream = [], {}
    for entry in job['files']:
        if not entry['path'].lower().endswith(('.jpg', '.jpeg', '.png')):
            continue
        path = str(files[entry['path']])
        pixels = cv2.imdecode(np.frombuffer(bounded(path), np.uint8), cv2.IMREAD_COLOR)
        if pixels is None:
            raise ValueError(f"가져온 사진을 읽을 수 없습니다: {entry['path']}")
        rows.append({'image': path, 'image_sha256': entry['sha256'], 'width': pixels.shape[1],
                     'height': pixels.shape[0], 'source_session': source, 'capture_group': source})
        upstream[path] = {'provider': 'huggingface', 'repo_type': job['repo_type'], 'repo_id': job['repo_id'],
                          'revision': job['revision'], 'path': entry['path'], 'sha256': entry['sha256'],
                          'expected_sha256': entry['expected_sha256'], 'bytes': entry['bytes'],
                          'import_id': job['id'], 'media_revision': job.get('media_revision'),
                          'requester_id': job['requester_id'], 'registered_by': registered_by}
    if not rows:
        raise ValueError('가져온 자료에 검수할 JPEG/PNG 사진이 없습니다.')
    catalog = store.state / 'hf-imports' / (job['id'] + '.jsonl')
    catalog.parent.mkdir(exist_ok=True)
    temp = catalog.with_name(f'{catalog.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    temp.write_text('\n'.join(json.dumps(row, sort_keys=True) for row in rows), encoding='utf-8')
    os.replace(temp, catalog)  # a concurrent send must never read a half-written catalog
    return import_frames(store, {'path': str(catalog)}, upstream)
