"""Audit current GUI indexed-mask candidates without writes or qualification.

Injected fetch_current returns the existing current-delivery/1 transport receipt.
No receipt, approval, source declaration or this report grants training permission.
"""
import copy
import hashlib
import json
import math
import re
import struct
from pathlib import Path, PurePosixPath
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from review_authority import advance_revision, validate_current, verify_bundle


def _delivery(fetch, workspace, previous, max_age, now):
    receipt = fetch()
    if not isinstance(receipt, dict):
        raise ValueError('current authority delivery unavailable')
    stamp = receipt.get('checked_at_unix')
    if (receipt.get('schema') != 'rosy.pinky-review-current-delivery/1'
            or receipt.get('workspace_id') != workspace or receipt.get('available') is not True
            or type(stamp) not in (int, float) or not math.isfinite(stamp)
            or not -5 <= now() - stamp <= max_age):
        raise ValueError('current authority unavailable, expired or from another workspace')
    current = validate_current(receipt.get('authority'))
    revision = advance_revision(current, workspace_id=workspace, previous=previous)
    return current, revision


def source_components(rows, representation_hashes):
    """Connect sessions/groups and source identities; never synthesize a session."""
    parents = {r['frame']: r['frame'] for r in rows}
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]; i = parents[i]
        return i
    tokens = {}
    for row in rows:
        i = row['frame']
        keys = [('session', row.get('source_session')), ('group', row.get('capture_group')),
                ('image', row.get('image_sha256'))]
        if row.get('source_video_sha256') is not None and row.get('video_frame') is not None:
            keys.append(('video-frame', (row['source_video_sha256'], row['video_frame'])))
        keys.extend(('image', h) for h in representation_hashes.get(i, []))
        for kind, value in keys:
            if value is None:
                continue
            key = (kind, value)
            if key in tokens:
                parents[find(i)] = find(tokens[key])
            else:
                tokens[key] = i
    grouped = {}
    for i in sorted(parents):
        grouped.setdefault(find(i), []).append(i)
    return sorted(grouped.values(), key=lambda group: group[0])


def mask_blockers(raw, *, width, height, indices):
    import cv2
    import numpy as np
    if (len(raw) < 33 or raw[:8] != b'\x89PNG\r\n\x1a\n'
            or raw[8:16] != b'\x00\x00\x00\rIHDR' or raw[24:26] != b'\x08\x00'):
        return ['mask_not_8bit_grayscale_png']
    if struct.unpack('>II', raw[16:24]) != (width, height):
        return ['mask_dimensions_differ']
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 2 or image.dtype != np.uint8:
        return ['mask_not_2d_uint8_indexed']
    if image.shape != (height, width):
        return ['mask_dimensions_differ']
    values = set(int(v) for v in np.unique(image))
    blockers = []
    if values - (indices | {255}):
        blockers.append('mask_unknown_class_index')
    if 255 in values:
        blockers.append('mask_unreviewed_pixels')
    return blockers


def image_blockers(raw, *, width, height):
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        return ['image_unreadable']
    return [] if image.shape[:2] == (height, width) else ['image_dimensions_differ']


def _classes(raw, current):
    import yaml
    from dataset.build import load_classes
    doc = yaml.safe_load(raw)
    rows = doc.get('classes') if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError('classes missing')
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('index')) is not int
                or not 0 <= row['index'] < 255 or not isinstance(row.get('name'), str)
                or not row['name'] or not isinstance(row.get('role'), str)):
            raise ValueError('strict class index/name/role required')
        color = row.get('color')
        if color is not None and (not isinstance(color, list) or len(color) != 3
                                  or any(type(v) is not int or not 0 <= v <= 255 for v in color)):
            raise ValueError('strict class color required')
    indices = {r['index'] for r in rows}
    if len(indices) != len(rows) or indices != set(range(len(rows))):
        raise ValueError('unique contiguous class indices required')
    classes = load_classes('captured.yaml', require_color=False, source_bytes=raw)
    signature = hashlib.sha256(json.dumps(classes, sort_keys=True).encode()).hexdigest()
    if (hashlib.sha256(raw).hexdigest() != current.get('pixel_classes_sha256')
            or signature != current.get('classes_signature')):
        raise ValueError('class bytes or canonical signature differ')
    return indices


def _eval_inventory(folders):
    from dataset.build import read_eval_set
    refs, sessions, groups, videos, images = [], set(), set(), set(), set()
    complete = bool(folders)
    for folder in folders:
        root = Path(folder)
        if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
               for p in [root, *root.parents, *root.rglob('*')]):
            raise ValueError('eval links refused')
        ref, held, raw = read_eval_set(root, with_manifest=True)
        refs.append(ref); sessions.update(held)
        manifest = json.loads(raw)
        if not manifest.get('frames'):
            complete = False
        for row in manifest.get('frames', []):
            group, video, frame = (row.get(k) for k in ('capture_group', 'source_video_sha256', 'video_frame'))
            if (not isinstance(group, str) or not group.strip()
                    or not isinstance(video, str) or re.fullmatch('[0-9a-f]{64}', video) is None
                    or type(frame) is not int or frame < 0):
                complete = False
            else:
                groups.add(group); videos.add((video, frame))
            name = row.get('image')
            if not isinstance(name, str) or '\\' in name or ':' in name:
                raise ValueError('eval image path required')
            path = PurePosixPath(name)
            if path.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')):
                raise ValueError('unsafe eval image path')
            images.add(hashlib.sha256((root / name).read_bytes()).hexdigest())
        # Recheck full immutable content after image inventory extraction.
        if read_eval_set(root, with_manifest=True) != (ref, held, raw):
            raise ValueError('eval changed during audit')
    return refs, sessions, groups, videos, images, complete


def inspect_candidates(export_root, *, fetch_current, workspace_id,
                       authority_max_age_s=90, eval_folders=(), previous_authority=None,
                       now=time.time):
    """Return read-only diagnostic candidates; qualification is always false."""
    if (type(authority_max_age_s) not in (int, float) or not math.isfinite(authority_max_age_s)
            or not 0 < authority_max_age_s <= 90):
        raise ValueError('bounded authority freshness required')
    current, revision = _delivery(fetch_current, workspace_id, previous_authority, authority_max_age_s, now)
    verified = verify_bundle(export_root, current, workspace_id=workspace_id, capture_files=True)
    files = verified['captured_files']
    refs, sessions, groups, videos, eval_images, complete = _eval_inventory(tuple(eval_folders))
    indices = _classes(files['pixel-classes.yaml'], current) if 'pixel-classes.yaml' in files else set()
    masks = {row['frame']: row for row in (json.loads(line) for line in files['pixel-reviews.jsonl'].splitlines() if line.strip())}
    representations = {}
    if 'representations.json' in files:
        captured = json.loads(files['representations.json'])
        representations = {int(i): [r['image_sha256'] for r in entries]
                           for i, entries in captured.items()}
    image_bytes = {hashlib.sha256(raw).hexdigest(): raw for name, raw in files.items()
                   if name.startswith('inputs/images/')}
    components = source_components(current['frames'], representations)
    diagnostics = []
    for frame in current['frames']:
        blockers = []
        if frame['mask_decision'] != 'approved': blockers.append('mask_not_approved')
        if frame['object_decision'] == 'excluded' or frame.get('frame_excluded') is True: blockers.append('frame_excluded')
        if frame['source_session'] is None: blockers.append('source_session_unknown')
        if frame['capture_group'] is None: blockers.append('source_group_unknown')
        if frame['source_video_sha256'] is None: blockers.append('source_video_hash_unknown')
        if frame['video_frame'] is None: blockers.append('source_video_frame_unknown')
        if frame['original_video_verified'] is not True: blockers.append('original_video_unverified')
        if frame['fixed_eval_overlap'] is None: blockers.append('fixed_eval_overlap_unknown')
        if not complete: blockers.append('eval_source_group_inventory_incomplete')
        hashes = {frame['image_sha256'], *representations.get(frame['frame'], [])}
        if (frame['fixed_eval_overlap'] is True or frame['source_session'] in sessions
                or frame['capture_group'] in groups or hashes & eval_images
                or (frame['source_video_sha256'], frame['video_frame']) in videos):
            blockers.append('fixed_eval_overlap')
        mask = masks.get(frame['frame'])
        if mask:
            primary = image_bytes.get(frame['image_sha256'])
            if primary is None:
                blockers.append('primary_image_bytes_unavailable')
            else:
                blockers.extend(image_blockers(primary, width=frame['width'], height=frame['height']))
            if not indices: blockers.append('classes_unavailable')
            blockers.extend(mask_blockers(files[mask['mask']], width=frame['width'], height=frame['height'], indices=indices))
        diagnostics.append({'frame': frame['frame'], 'review_uid': frame['review_uid'],
                            'blockers': sorted(set(blockers)), 'training_dataset_qualified': False})
    by_frame = {row['frame']: row for row in diagnostics}
    for component in components:
        if any('fixed_eval_overlap' in by_frame[i]['blockers'] for i in component):
            for i in component:
                by_frame[i]['blockers'] = sorted(set(by_frame[i]['blockers']) | {'source_component_eval_overlap'})
    latest, _ = _delivery(fetch_current, workspace_id, revision, authority_max_age_s, now)
    if latest != current:
        raise ValueError('current authority changed during candidate audit')
    return {'training_dataset_qualified': False,
            'qualification_blockers': ['dataset_output_contract_not_implemented',
                                       'source_provenance_not_independently_verified'],
            'authority': revision,
            'approved_masks': len(masks), 'frames': diagnostics,
            'source_components': components, 'disjoint_from': refs}
