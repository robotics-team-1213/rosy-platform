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
import os
import stat
import tempfile
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
                ('video', row.get('source_video_sha256')),
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
                or frame['source_video_sha256'] in {sha for sha, _ in videos}):
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


def _stable_bytes(path):
    path = Path(path).absolute()
    for part in [path, *path.parents]:
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('source proof links refused')
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('regular source proof artifact required')
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('source proof artifact changed while captured')
    return raw


def _proof_path(value, proof):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('source proof artifact path required')
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('source proof path traversal refused')
    if not path.is_absolute():
        if '..' in path.parts:
            raise ValueError('source proof path traversal refused')
        path = proof.parent / path
    return path.absolute()


def _capture_proofs(paths):
    proofs, observed = {}, {}
    for value in paths:
        path = Path(value).absolute(); raw = _stable_bytes(path); observed[path] = raw
        doc = json.loads(raw)
        if not isinstance(doc, dict) or doc.get('schema') != 'rosy.pinky-review-source-proof/1':
            raise ValueError('source proof schema required')
        for name in ('source_session', 'capture_group'):
            if not isinstance(doc.get(name), str) or not doc[name].strip():
                raise ValueError('source proof session/group required')
        if not isinstance(doc.get('video_sha256'), str) or re.fullmatch('[0-9a-f]{64}', doc['video_sha256']) is None:
            raise ValueError('source proof video digest required')
        video_path = _proof_path(doc.get('video_path'), path)
        video = _stable_bytes(video_path); observed[video_path] = video
        if hashlib.sha256(video).hexdigest() != doc['video_sha256']:
            raise ValueError('source proof actual video hash differs')
        side_fields = {'sidecar_path', 'sidecar_sha256'} & set(doc)
        if side_fields:
            if side_fields != {'sidecar_path', 'sidecar_sha256'}:
                raise ValueError('source proof sidecar pair required')
            side_path = _proof_path(doc['sidecar_path'], path)
            side = _stable_bytes(side_path); observed[side_path] = side
            if (not isinstance(doc['sidecar_sha256'], str)
                    or re.fullmatch('[0-9a-f]{64}', doc['sidecar_sha256']) is None
                    or hashlib.sha256(side).hexdigest() != doc['sidecar_sha256']):
                raise ValueError('source proof actual sidecar hash differs')
        key = (doc['source_session'], doc['capture_group'], doc['video_sha256'])
        if key in proofs:
            raise ValueError('duplicate source proof binding')
        proofs[key] = {'record': doc, 'bytes': raw, 'sha256': hashlib.sha256(raw).hexdigest(), 'video': video,
                       'suffix': video_path.suffix}
    return proofs, observed


def validate_eval_companions(eval_folders, companion_files):
    """Capture sealed evaluation lineage; never grant pixel proof or admission.

    The internal bundle contains manifest.json, COMPLETE and every resource
    named by its exact inventory. External snapshot paths are not this contract.
    """
    from store import file_hashes
    from dataset.build import read_eval_set
    def require(condition, message):
        if not condition:
            raise ValueError('eval companion: ' + message)
    def parse(raw):
        def pairs(rows):
            result = {}
            for key, value in rows:
                require(key not in result, 'duplicate JSON field')
                result[key] = value
            return result
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: require(False, 'finite JSON required'))
    def relative(name):
        require(isinstance(name, str) and name and '\\' not in name and ':' not in name
                and all(p not in ('', '.', '..') for p in name.split('/'))
                and not PurePosixPath(name).is_absolute(), 'relative artifact path required')
        return name
    def sha(raw):
        return hashlib.sha256(raw).hexdigest()
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    folders = tuple(Path(p).absolute() for p in eval_folders)
    roots = set(folders)
    require(len(roots) == len(folders), 'duplicate evaluation folder')
    require(bool(roots), 'evaluation inventory empty')
    expected = {}
    for root in roots:
        ref, _, raw = read_eval_set(root, with_manifest=True)
        require((ref['name'], ref['content_sha']) not in expected, 'duplicate evaluation ref')
        expected[(ref['name'], ref['content_sha'])] = (root, raw)
    observed, captured, frames, blockers, seen = {}, {}, [], set(), set()
    for value in companion_files:
        root = Path(value).absolute()
        raw = _stable_bytes(root / 'manifest.json'); seal = _stable_bytes(root / 'COMPLETE')
        require(seal.decode('ascii').strip() == sha(raw), 'seal differs')
        doc = parse(raw)
        require(isinstance(doc, dict) and set(doc) == {'schema', 'eval_ref', 'eval_manifest_sha256',
                'eval_files', 'resources', 'sources', 'frames'}
                and doc['schema'] == 'rosy.pinky-fixed-eval-companion/1', 'schema fields required')
        ref = doc['eval_ref']
        require(isinstance(ref, dict) and set(ref) == {'name', 'content_sha'}
                and text(ref['name']) and text(ref['content_sha']), 'exact eval ref required')
        key = (ref['name'], ref['content_sha'])
        require(key in expected and key not in seen, 'unknown or duplicate eval version')
        seen.add(key); eval_root, eval_raw = expected[key]
        require(sha(eval_raw) == doc['eval_manifest_sha256'], 'eval manifest differs')
        require(doc['eval_files'] == file_hashes(eval_root), 'full eval inventory differs')
        eval_bytes = {relative(name): _stable_bytes(eval_root / name) for name in doc['eval_files']}
        require(all(sha(data) == doc['eval_files'][name] for name, data in eval_bytes.items()), 'eval changed during capture')
        resources = doc['resources']; require(isinstance(resources, dict), 'resource inventory required')
        payloads = {}
        for name, digest in resources.items():
            relative(name); require(name not in ('manifest.json', 'COMPLETE'), 'reserved resource')
            data = _stable_bytes(root / name)
            require(isinstance(digest, str) and sha(data) == digest, 'resource digest differs')
            payloads[name] = data
        require(set(file_hashes(root)) == {'manifest.json', 'COMPLETE', *resources}, 'bundle path set differs')
        def resource(name):
            require(isinstance(name, str) and name in payloads, 'resource reference missing')
            return payloads[name]
        eval_doc = parse(eval_raw); sources = {}
        require(isinstance(doc['sources'], list) and doc['sources'], 'original sources required')
        for source in doc['sources']:
            require(isinstance(source, dict) and set(source) == {'session', 'labels', 'meta', 'video', 'sidecar', 'pts', 'labels_digest'}
                    and text(source['session']) and source['session'] not in sources, 'source fields required')
            session = source['session']
            labels = [parse(line) for line in resource(source['labels']).splitlines() if line.strip()]
            require(labels and all(isinstance(r, dict) and type(r.get('index')) is int and r['index'] >= 0
                    and type(r.get('t')) in (int, float) and math.isfinite(r['t']) and r.get('session') == session for r in labels), 'canonical label rows required')
            require(len({r['index'] for r in labels}) == len(labels), 'duplicate label index')
            canonical = ''.join(json.dumps(r, sort_keys=True, allow_nan=False) + '\n' for r in sorted(labels, key=lambda r: r['index'])).encode()
            matches = [r for r in eval_doc.get('labels', []) if r.get('session') == session]
            require(len(matches) == 1 and sha(canonical) == source['labels_digest'] == matches[0].get('labels_digest'), 'full canonical label digest differs')
            meta = parse(resource(source['meta']))
            require(isinstance(meta, dict) and isinstance(meta.get('source'), dict)
                and meta.get('session') == session and meta['source'].get('sha256') == {
                'video': sha(resource(source['video'])), 'sidecar': sha(resource(source['sidecar']))}, 'original meta source hashes differ')
            side = [parse(line) for line in resource(source['sidecar']).splitlines() if line.strip()]
            require(side and all(isinstance(r, dict) and type(r.get('index')) is int and r['index'] == i
                    and type(r.get('t')) in (int, float) and math.isfinite(r['t']) for i, r in enumerate(side)), 'explicit sequential sidecar index required')
            pts = parse(resource(source['pts']))
            require(isinstance(pts, list) and len(pts) == len(side) and all(isinstance(r, dict)
                    and type(r.get('video_frame')) is int and r['video_frame'] == i
                    and type(r.get('pts')) is int and text(r.get('time_base')) for i, r in enumerate(pts)), 'exact ordinal PTS inventory required')
            sources[session] = (source, {r['index']: r for r in labels}, side)
        expected_rows = {(r['session'], r['image']): r for r in eval_doc['frames']}
        require(len(expected_rows) == len(eval_doc['frames']) and expected_rows, 'unique eval frame identity required')
        row_keys = set(); require(isinstance(doc['frames'], list), 'frame bindings required')
        for row in doc['frames']:
            require(isinstance(row, dict) and set(row) == {'session', 'image', 'sample_index', 'video_frame', 'capture_group',
                'group_basis', 'decoded_video_pixels_verified', 'extraction'}, 'frame fields required')
            identity = (row['session'], row['image'])
            require(identity in expected_rows and identity not in row_keys and row['session'] in sources, 'exact unique eval frame required')
            row_keys.add(identity); source, labels, side = sources[row['session']]
            require(type(row['sample_index']) is int and row['sample_index'] in labels and type(row['video_frame']) is int
                    and 0 <= row['video_frame'] < len(side), 'exact selected index and original ordinal required')
            label = labels[row['sample_index']]
            matches = [i for i, sample in enumerate(side) if sample['t'] == label['t']]
            require(matches == [row['video_frame']], 'unique exact timestamp ordinal required')
            require(row['decoded_video_pixels_verified'] is False, 'lineage cannot assert decoded pixels')
            require((row['capture_group'] is None and row['group_basis'] is None) or
                    (text(row['capture_group']) and row['group_basis'] == 'operator_collection_assertion'), 'explicit group assertion required')
            if row['capture_group'] is None: blockers.add('eval_group_assertion_unknown')
            blockers.add('eval_decoded_pixels_unverified')
            extraction = row['extraction']; require(isinstance(extraction, dict) and set(extraction) == {'image', 'mask', 'conf'}, 'all extraction bytes required')
            for kind in extraction:
                name = expected_rows[identity].get(kind)
                require(name in eval_bytes and resource(extraction[kind]) == eval_bytes[name], 'original extraction bytes differ')
            frames.append(dict(row, source_video_sha256=sha(resource(source['video'])), eval_ref=ref))
        require(row_keys == set(expected_rows), 'full eval row coverage required')
        require(set(sources) == {key[0] for key in expected_rows}, 'source session coverage differs')
        bindings = {root / 'manifest.json': raw, root / 'COMPLETE': seal,
                    **{root / name: data for name, data in payloads.items()},
                    **{eval_root / name: data for name, data in eval_bytes.items()}}
        require(all(_stable_bytes(path) == data for path, data in bindings.items()), 'captured artifacts changed')
        require(file_hashes(eval_root) == doc['eval_files'] and set(file_hashes(root)) == {'manifest.json', 'COMPLETE', *resources}, 'inventory changed')
        observed.update(bindings)
        captured[sha(raw)] = {'manifest.json': raw, 'COMPLETE': seal, **payloads}
    require(seen == set(expected), 'all active eval companions required')
    return dict(training_admission=False, training_dataset_qualified=False, frames=frames,
                blockers=sorted(blockers), observed=observed, captured_files=captured)


def _verify_video_requests(requests, scratch):
    """One sequential decode per video; retain only the current decoded frame."""
    import cv2
    import numpy as np
    grouped = {}
    for proof, index, raw in requests:
        if type(index) is not int or index < 0:
            raise ValueError('source proof exact video frame required')
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('source pixel proof requires original PNG; JPEG conversion unverified')
        digest = proof['record']['video_sha256']
        group = grouped.setdefault(digest, dict(proof=proof, frames={}))
        group['frames'].setdefault(index, []).append(raw)
    for digest, group in grouped.items():
        proof, targets = group['proof'], group['frames']
        path = scratch / ('source-' + digest + proof['suffix'])
        path.write_bytes(proof['video'])
        reader = cv2.VideoCapture(str(path))
        try:
            for index in range(max(targets) + 1):
                ok, pixels = reader.read()
                if not ok:
                    raise ValueError('source video frame unavailable')
                for raw in targets.get(index, []):
                    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
                    if image is None or image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
                        raise ValueError('source PNG pixel layout not proven')
                    if pixels.shape != image.shape or not np.array_equal(pixels, image):
                        raise ValueError('source decoded frame pixels differ from approved PNG')
        finally:
            reader.release()


def _video_pixels(proof, index, image_bytes, scratch):
    _verify_video_requests([(proof, index, image_bytes)], scratch)


def _active_eval(store, folders, gate_eval_refs):
    supplied = {Path(p).absolute() for p in folders}
    inventory = store.evalsets()
    required = {store.evalset_path(name, sha).absolute() for name, versions in inventory.items() for sha in versions}
    if not gate_eval_refs:
        raise ValueError('configured gate eval refs required')
    pinned = set()
    for ref in gate_eval_refs:
        if not isinstance(ref, dict) or set(ref) != {'name', 'content_sha'}:
            raise ValueError('exact gate eval ref required')
        pinned.add(store.evalset_path(ref['name'], ref['content_sha']).absolute())
    if not pinned <= required or not required or supplied != required:
        raise ValueError('all store eval versions must be supplied; active inventory incomplete')
    return inventory


def build_dataset(export_root, *, fetch_current, workspace_id, eval_folders,
                  source_proof_files, store, name, staging_parent, gate_eval_refs=(),
                  authority_max_age_s=90, previous_authority=None, now=time.time,
                  eval_companion_files=()):
    """Publish verified bytes only; always return training_admission=False.

    Publication is immutable content storage, never authorization to train.
    Group/session metadata is a configured operator collection assertion.
    """
    published = None
    result = {'status': 'HOLD', 'training_admission': False, 'training_dataset_qualified': False}
    try:
        if (type(authority_max_age_s) not in (int, float) or not math.isfinite(authority_max_age_s)
                or not 0 < authority_max_age_s <= 90):
            raise ValueError('bounded authority freshness required')
        current, revision = _delivery(fetch_current, workspace_id, previous_authority, authority_max_age_s, now)
        verified = verify_bundle(export_root, current, workspace_id=workspace_id, capture_files=True)
        files = verified['captured_files']
        masks = [json.loads(line) for line in files['pixel-reviews.jsonl'].splitlines() if line.strip()]
        if not masks:
            latest, _ = _delivery(fetch_current, workspace_id, revision, authority_max_age_s, now)
            if latest != current:
                raise ValueError('current authority changed during build audit')
            return dict(result, blockers=['no_approved_masks'], authority=revision)
        folders = tuple(eval_folders)
        inventory = _active_eval(store, folders, gate_eval_refs)
        refs, sessions, groups, videos, eval_images, complete = _eval_inventory(folders)
        eval_inventory = (list(refs), set(sessions), set(groups), set(videos), set(eval_images), complete)
        companions = (validate_eval_companions(folders, eval_companion_files)
                      if eval_companion_files else None)
        if not complete:
            raise ValueError('eval source group/video/frame inventory incomplete')
        proofs, observed = _capture_proofs(source_proof_files)
        if companions is not None:
            observed.update(companions['observed'])
            # Additional lineage can exclude candidates, never replace the
            # manifest's group fields or original PNG pixel-proof requirement.
            for row in companions['frames']:
                sessions.add(row['session'])
                videos.add((row['source_video_sha256'], row['video_frame']))
                if row['capture_group'] is not None:
                    groups.add(row['capture_group'])
        eval_captured = {}
        for folder in folders:
            root = Path(folder).absolute()
            snapshot = {p.relative_to(root).as_posix(): _stable_bytes(p) for p in sorted(root.rglob('*')) if p.is_file()}
            lines = [relative + '\0' + hashlib.sha256(raw).hexdigest() + '\n' for relative, raw in snapshot.items()]
            if hashlib.sha256(''.join(sorted(lines)).encode()).hexdigest() != root.name:
                raise ValueError('eval changed during immutable byte capture')
            eval_captured[root] = snapshot
            observed.update({root / relative: raw for relative, raw in snapshot.items()})
        indices = _classes(files['pixel-classes.yaml'], current)
        representations = json.loads(files['representations.json'])
        hashes = {int(i): [r['image_sha256'] for r in rows] for i, rows in representations.items()}
        components = source_components(current['frames'], hashes)
        selected = {m['frame']: m for m in masks}
        image_bytes = {hashlib.sha256(raw).hexdigest(): raw for key, raw in files.items() if key.startswith('inputs/images/')}
        by_frame = {r['frame']: r for r in current['frames']}
        eligible_components = []
        for component in components:
            approved = [i for i in component if i in selected]
            if not approved:
                continue
            for i in component:
                frame = by_frame[i]
                if (frame['source_session'] is None or frame['capture_group'] is None
                        or frame['source_video_sha256'] is None or frame['video_frame'] is None
                        or frame['fixed_eval_overlap'] is None):
                    raise ValueError('source component provenance UNKNOWN')
                images = {frame['image_sha256'], *hashes.get(i, [])}
                if (frame['fixed_eval_overlap'] is True or frame['source_session'] in sessions
                        or frame['capture_group'] in groups or images & eval_images
                        or frame['source_video_sha256'] in {sha for sha, _ in videos}):
                    raise ValueError('source component overlaps fixed evaluation')
            eligible_components.append(component)
        if len(eligible_components) < 2:
            raise ValueError('at least two disconnected source components required')
        scratch_parent = Path(staging_parent).absolute()
        if os.name == 'nt' and scratch_parent.drive.upper() != 'X:':
            raise ValueError('scratch staging must be on X:')
        if any(part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction())
               for part in [scratch_parent, *scratch_parent.parents]):
            raise ValueError('scratch staging links refused')
        scratch_parent = scratch_parent.resolve()
        if os.name == 'nt' and not scratch_parent.is_relative_to(Path('X:/DevTemp').resolve()):
            raise ValueError('scratch staging must remain within X:/DevTemp')
        scratch_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='indexed-dataset-', dir=scratch_parent) as temp:
            scratch = Path(temp); dataset = scratch / 'dataset'
            # Eval frames need the same independent original video proof as candidates.
            eval_provenance = []
            video_requests = []
            for folder in folders:
                snapshot = eval_captured[Path(folder).absolute()]
                manifest = json.loads(snapshot['manifest.json'])
                for frame in manifest['frames']:
                    key = (frame['session'], frame['capture_group'], frame['source_video_sha256'])
                    if key not in proofs:
                        raise ValueError('eval original source proof unavailable')
                    raw = snapshot[frame['image']]
                    video_requests.append((proofs[key], frame['video_frame'], raw))
                    eval_provenance.append(dict(eval_revision=Path(folder).name, session=frame['session'],
                                                capture_group=frame['capture_group'], video_sha256=frame['source_video_sha256'],
                                                video_frame=frame['video_frame'], image_sha256=hashlib.sha256(raw).hexdigest(),
                                                source_proof_sha256=proofs[key]['sha256']))
            for i, mask in selected.items():
                frame = by_frame[i]
                proof_key = (frame['source_session'], frame['capture_group'], frame['source_video_sha256'])
                if proof_key not in proofs:
                    raise ValueError('approved original source proof unavailable')
                mask_errors = mask_blockers(files[mask['mask']], width=frame['width'], height=frame['height'], indices=indices)
                if mask_errors:
                    raise ValueError('approved mask integrity: ' + ','.join(mask_errors))
                video_requests.append((proofs[proof_key], frame['video_frame'], image_bytes[frame['image_sha256']]))
            _verify_video_requests(video_requests, scratch)
            from dataset.build import assign_splits, load_classes
            component_keys = {tuple(component): hashlib.sha256(json.dumps(sorted({(by_frame[i]['source_session'], by_frame[i]['capture_group'], by_frame[i]['source_video_sha256']) for i in component})).encode()).hexdigest()
                              for component in eligible_components}
            splits = assign_splits(component_keys.values())
            entries, sources = [], []
            dataset.mkdir()
            for component in eligible_components:
                component_key = component_keys[tuple(component)]
                for i in component:
                    if i not in selected:
                        continue
                    frame, mask = by_frame[i], selected[i]
                    proof_key = (frame['source_session'], frame['capture_group'], frame['source_video_sha256'])
                    if proof_key not in proofs:
                        raise ValueError('approved original source proof unavailable')
                    proof = proofs[proof_key]; image_raw = image_bytes[frame['image_sha256']]; mask_raw = files[mask['mask']]
                    image_name, mask_name = f'images/{i:06d}.png', f'masks/{i:06d}.png'
                    for relative, raw in [(image_name, image_raw), (mask_name, mask_raw)]:
                        path = dataset / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
                    proof_name = 'evidence/source-proofs/' + proof['sha256'] + '.json'
                    path = dataset / proof_name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(proof['bytes'])
                    entries.append(dict(image=image_name, mask=mask_name, session=frame['source_session'],
                                        split=splits[component_key], source_component=component_key))
                    sources.append(dict(annotation_origin='human_reviewed_pinky_indexed', session=frame['source_session'],
                                        capture_group=frame['capture_group'], group_basis='operator_collection_assertion',
                                        source_video_sha256=frame['source_video_sha256'], video_frame=frame['video_frame'],
                                        producer_original_video_verified=frame['original_video_verified'],
                                        independent_source_pixels_verified=True, source_proof=proof_name,
                                        source_proof_sha256=proof['sha256'], approval=copy.deepcopy(frame),
                                        export_contract_sha256=verified['contract_sha'], authority=revision,
                                        image_sha256=frame['image_sha256'], mask_sha256=frame['mask_sha256'],
                                        classes_sha256=current['pixel_classes_sha256'], classes_signature=current['classes_signature']))
            evidence = dataset / 'evidence'; evidence.mkdir(exist_ok=True)
            if companions is not None:
                for digest, payloads in companions['captured_files'].items():
                    for relative, raw in payloads.items():
                        path = evidence / 'eval-companions' / digest / relative
                        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            for proof in proofs.values():
                path = evidence / 'source-proofs' / (proof['sha256'] + '.json')
                path.parent.mkdir(exist_ok=True); path.write_bytes(proof['bytes'])
            for root, snapshot in eval_captured.items():
                (evidence / ('eval-' + root.name + '.json')).write_bytes(snapshot['manifest.json'])
            (evidence / 'eval-provenance.json').write_text(json.dumps(eval_provenance, sort_keys=True), encoding='utf-8')
            for relative in ['pixel-classes.yaml', 'pixel-reviews.jsonl', 'review-contract.json', 'AUTHORITY_COMPLETE']:
                (evidence / relative).write_bytes(files[relative])
            (evidence / 'current-decisions.json').write_text(json.dumps(current, sort_keys=True), encoding='utf-8')
            manifest = dict(schema='rosy.perception.dataset/1', builder='review_dataset.py (D-464)',
                            classes=load_classes('captured', require_color=False, source_bytes=files['pixel-classes.yaml']),
                            frames=entries, sources=sources, ignore_index=255, disjoint_from=refs)
            (dataset / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding='utf-8')
            latest, _ = _delivery(fetch_current, workspace_id, revision, authority_max_age_s, now)
            if latest != current:
                raise ValueError('current authority changed before publication')
            if _active_eval(store, folders, gate_eval_refs) != inventory or _eval_inventory(folders) != eval_inventory:
                raise ValueError('eval inventory changed before publication')
            if any(_stable_bytes(path) != raw for path, raw in observed.items()):
                raise ValueError('source proof artifacts changed before publication')
            published, sha = store.put_dataset(dataset, name)
            result.update(dataset_path=str(published), dataset_revision=sha, authority=revision, frames=len(entries))
            from store import content_sha
            if content_sha(published) != sha:
                raise ValueError('published immutable content hash differs')
            latest, _ = _delivery(fetch_current, workspace_id, revision, authority_max_age_s, now)
            if latest != current:
                raise ValueError('current authority changed after immutable publication')
            if _active_eval(store, folders, gate_eval_refs) != inventory or _eval_inventory(folders) != eval_inventory:
                raise ValueError('eval changed after immutable publication')
            if any(_stable_bytes(path) != raw for path, raw in observed.items()):
                raise ValueError('source proofs changed after immutable publication')
            result.update(status='PUBLISHED_CONTENT_NOT_ADMITTED', build_integrity_verified=True,
                          blockers=['trainer_fresh_authority_admission_required'])
            return result
    except (ValueError, OSError, KeyError, TypeError) as error:
        result['blockers'] = [str(error)]
        if published is not None:
            result['published_content_exists'] = True
        return result
