"""D-464 sealed evaluation extraction-lineage evidence, never admission.

This module owns only companion capture/correlation. The indexed dataset owner
supplies its stable byte reader and retains publication and PNG pixel proof.
"""
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath


def _capture_video_companions(eval_folders, companion_files, *, read_bytes):
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
        raw = read_bytes(root / 'manifest.json'); seal = read_bytes(root / 'COMPLETE')
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
        eval_bytes = {relative(name): read_bytes(eval_root / name) for name in doc['eval_files']}
        require(all(sha(data) == doc['eval_files'][name] for name, data in eval_bytes.items()), 'eval changed during capture')
        resources = doc['resources']; require(isinstance(resources, dict), 'resource inventory required')
        payloads = {}
        for name, digest in resources.items():
            relative(name); require(name not in ('manifest.json', 'COMPLETE'), 'reserved resource')
            data = read_bytes(root / name)
            require(isinstance(digest, str) and sha(data) == digest, 'resource digest differs')
            payloads[name] = data
        require(set(file_hashes(root)) == {'manifest.json', 'COMPLETE', *resources}, 'bundle path set differs')
        def resource(name):
            require(isinstance(name, str) and name in payloads, 'resource reference missing')
            return payloads[name]
        eval_doc = parse(eval_raw); sources = {}
        require(eval_doc.get('builder') == 'build.py --auto-labels (D-379)', 'D-379 extraction builder required')
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
            # D-379 copies frames/{selected-index}.jpg and masks/conf bearing
            # that same selected label index. This is not a video-frame guess:
            # the original ordinal is still independently joined through t.
            session = row['session']; selected = row['sample_index']
            require(re.fullmatch(r'[A-Za-z0-9_.-]+', session) is not None, 'canonical session path required')
            for kind, directory, suffix in [('image', 'images', 'jpg'), ('mask', 'masks', 'png'), ('conf', 'conf', 'png')]:
                require(expected_rows[identity].get(kind) == f'{directory}/{session}/{session}__{selected:06d}.{suffix}',
                        'eval image/extraction selected label index differs')
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
        require(all(read_bytes(path) == data for path, data in bindings.items()), 'captured artifacts changed')
        require(file_hashes(eval_root) == doc['eval_files'] and set(file_hashes(root)) == {'manifest.json', 'COMPLETE', *resources}, 'inventory changed')
        observed.update(bindings)
        captured[sha(raw)] = {'manifest.json': raw, 'COMPLETE': seal, **payloads}
    require(seen == set(expected), 'all active eval companions required')
    return dict(training_admission=False, training_dataset_qualified=False, frames=frames,
                blockers=sorted(blockers), observed=observed, captured_files=captured)


def _capture_mcap_companions(eval_folders, companion_files, *, read_bytes):
    """Re-prove human evaluation pixels from the original pinned MCAP bytes."""
    import os
    import tempfile

    import cv2
    import numpy as np

    from dataset.build import load_classes, read_eval_set
    from dataset.mcap_proof import prove_frames
    from dataset.review_evidence import encoded, identity, sha, validate_authority
    from store import file_hashes

    def require(ok, why):
        if not ok:
            raise ValueError('eval companion: ' + why)

    def parse(raw):
        def pairs(items):
            out = {}
            for key, value in items:
                require(key not in out, 'duplicate JSON field')
                out[key] = value
            return out
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: require(False, 'finite JSON required'))

    expected = {}
    for folder in eval_folders:
        root = Path(folder).absolute()
        ref, _, raw = read_eval_set(root, with_manifest=True)
        require((ref['name'], ref['content_sha']) not in expected, 'duplicate evaluation ref')
        expected[(ref['name'], ref['content_sha'])] = (root, raw)
    require(bool(expected), 'MCAP evaluation inventory empty')
    observed, captured, frames, source_hashes, seen = {}, {}, [], {}, set()
    for folder in companion_files:
        root = Path(folder).absolute()
        require(not any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
                        for p in (root, *root.parents, *root.rglob('*'))), 'bundle links refused')
        raw, seal = read_bytes(root / 'manifest.json'), read_bytes(root / 'COMPLETE')
        require(seal.decode('ascii').strip() == sha(raw), 'seal differs')
        doc = parse(raw)
        require(isinstance(doc, dict) and set(doc) == {'schema', 'eval_ref', 'eval_manifest_sha256', 'eval_files'}
                and doc['schema'] == 'rosy.pinky-fixed-eval-mcap-companion/1', 'MCAP companion schema required')
        ref = doc['eval_ref']
        require(isinstance(ref, dict) and set(ref) == {'name', 'content_sha'}, 'exact eval ref required')
        key = (ref['name'], ref['content_sha'])
        require(key in expected and key not in seen, 'unknown or duplicate eval version')
        seen.add(key)
        eval_root, eval_raw = expected[key]
        require(sha(eval_raw) == doc['eval_manifest_sha256'], 'eval manifest differs')
        inventory = file_hashes(eval_root)
        require(doc['eval_files'] == inventory and set(file_hashes(root)) == {'manifest.json', 'COMPLETE'},
                'full eval or bundle inventory differs')
        eval_files = {name: read_bytes(eval_root / name) for name in inventory}
        require(all(sha(value) == inventory[name] for name, value in eval_files.items()),
                'eval changed during capture')
        eval_doc = parse(eval_raw)
        require(eval_doc.get('builder') == 'review_eval_bootstrap.py --publish (D-475)'
                and eval_doc.get('ignore_index') == 255 and eval_doc.get('trusted_sources') == ['human_reviewed_eval'],
                'human MCAP evaluation contract required')
        authority = parse(eval_files['authority.json'])
        validate_authority(authority)
        require(authority['decision_sha256'] == eval_doc.get('authority_sha256'), 'authority digest differs')
        require(sha(eval_files['pixel-classes.yaml']) == eval_doc.get('classes_sha256')
                == authority['pixel_classes_sha256'], 'class bytes differ')
        normalized = load_classes(Path('classes.yaml'), source_bytes=eval_files['pixel-classes.yaml'])
        require(normalized == eval_doc['classes']
                and sha(json.dumps(normalized, sort_keys=True).encode()) == authority['classes_signature'],
                'class identity differs')
        classes = {c['index'] for c in eval_doc['classes']}
        require(len(classes) == len(eval_doc['classes']) and 255 not in classes, 'class indices invalid')
        rows = eval_doc.get('frames')
        require(isinstance(rows, list) and rows and len(rows) == len(authority['frames']),
                'full approved frame coverage required')
        groups = {}
        identities = set()
        for row, approval in zip(rows, authority['frames']):
            require(isinstance(row, dict) and row.get('source_kind') == 'mcap'
                    and row.get('sources') == ['human_reviewed_eval']
                    and row.get('split') == 'eval' and row.get('frame') == approval['frame']
                    and row.get('identity') == approval['identity']
                    and row.get('session') == approval['source_session']
                    and row.get('capture_group') == approval['capture_group']
                    and row.get('mask_sha256') == approval['mask_sha256']
                    and row.get('image_sha256') == approval['image_sha256']
                    and row.get('mask_version') == approval['mask_version']
                    and approval['mask_decision'] == 'approved' and approval['object_decision'] != 'excluded'
                    and row.get('approval_sha256') == sha(encoded(approval['pixel_approval'])),
                    'frame approval differs')
            require(row['identity'] not in identities, 'duplicate MCAP frame identity')
            identities.add(row['identity'])
            image_raw, mask_raw = eval_files[row['image']], eval_files[row['mask']]
            require(sha(image_raw) == row['image_sha256'] and sha(mask_raw) == row['mask_sha256'],
                    'approved image or mask bytes differ')
            mask = cv2.imdecode(np.frombuffer(mask_raw, np.uint8), cv2.IMREAD_UNCHANGED)
            unknown = row.get('reviewed_unknown_count')
            require(mask is not None and mask.dtype == np.uint8
                    and mask.shape == (approval['height'], approval['width'])
                    and type(unknown) is int and 0 <= unknown < mask.size
                    and int(np.count_nonzero(mask == 255)) == unknown
                    and unknown == approval['pixel_approval'].get('reviewed_unknown_count', 0)
                    and np.isin(mask, list(classes | {255})).all(), 'approved mask pixels differ')
            mcap = row.get('mcap')
            require(isinstance(mcap, dict) and isinstance(mcap.get('frame'), dict)
                    and isinstance(mcap.get('session_dir'), str)
                    and isinstance(mcap.get('bags'), list)
                    and sum(b.get('name') == mcap['frame'].get('bag') for b in mcap['bags']
                            if isinstance(b, dict)) == 1, 'MCAP source required')
            require(row['identity'] == identity({'source_kind': 'mcap', 'mcap': mcap})
                    and mcap['frame'].get('width') == approval['width']
                    and mcap['frame'].get('height') == approval['height'],
                    'MCAP frame identity or dimensions differ')
            session = Path(mcap['session_dir'])
            require(session.is_absolute() and session.name == row['session'], 'MCAP source session differs')
            require(not any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
                            for p in (session, *session.parents)), 'MCAP source links refused')
            groups.setdefault(session, []).append((row, {'image': str(eval_root / row['image']), **mcap['frame']}))
        scratch = Path('X:/DevTemp') if os.name == 'nt' else Path(tempfile.gettempdir())
        for session, entries in groups.items():
            first = entries[0][0]['mcap']
            require(all(row['mcap']['metadata_sha256'] == first['metadata_sha256']
                        and row['mcap']['bags'] == first['bags'] for row, _ in entries),
                    'MCAP session inventory differs')
            proof = prove_frames(session, [selector for _, selector in entries], scratch, expected=first)
            require(proof['decoder'] == first['decoder'], 'MCAP decoder differs')
            source_hashes[session / 'bag' / 'metadata.yaml'] = first['metadata_sha256']
            for bag in first['bags']:
                source_hashes[session / 'bag' / bag['name']] = bag['sha256']
            for (row, _), proven in zip(entries, proof['frames']):
                require(proven == row['mcap']['frame'], 'MCAP decoded frame differs')
                frames.append({'session': row['session'], 'image': row['image'],
                               'capture_group': row['capture_group'], 'source_kind': 'mcap',
                               'decoded_mcap_pixels_verified': True, 'eval_ref': ref,
                               'mcap': proven})
        bindings = {root / 'manifest.json': raw, root / 'COMPLETE': seal,
                    **{eval_root / name: data for name, data in eval_files.items()}}
        require(all(read_bytes(path) == data for path, data in bindings.items())
                and file_hashes(eval_root) == inventory, 'captured evaluation changed')
        observed.update(bindings)
        captured[sha(raw)] = {'manifest.json': raw, 'COMPLETE': seal}
    require(seen == set(expected), 'all active eval companions required')
    return {'training_admission': False, 'training_dataset_qualified': False,
            'frames': frames, 'blockers': [], 'observed': observed,
            'captured_files': captured, 'source_hashes': source_hashes}


def capture_eval_companions(eval_folders, companion_files, *, read_bytes):
    """Keep D-379 semantics; dispatch human MCAP evals to independent proof."""
    from dataset.build import read_eval_set

    human, video = [], []
    for folder in eval_folders:
        _, _, raw = read_eval_set(folder, with_manifest=True)
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            raise ValueError('eval companion: evaluation manifest object required')
        (human if doc.get('builder') == 'review_eval_bootstrap.py --publish (D-475)'
         else video).append(folder)
    mcap_files, video_files = [], []
    for folder in companion_files:
        raw = read_bytes(Path(folder) / 'manifest.json')
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            raise ValueError('eval companion: companion manifest object required')
        (mcap_files if doc.get('schema') == 'rosy.pinky-fixed-eval-mcap-companion/1'
         else video_files).append(folder)
    if not human:
        return _capture_video_companions(eval_folders, companion_files, read_bytes=read_bytes)
    parts = []
    if video or video_files:
        parts.append(_capture_video_companions(video, video_files, read_bytes=read_bytes))
    parts.append(_capture_mcap_companions(human, mcap_files, read_bytes=read_bytes))
    merged = {'training_admission': False, 'training_dataset_qualified': False,
              'frames': [], 'blockers': [], 'observed': {}, 'captured_files': {}, 'source_hashes': {}}
    for part in parts:
        merged['frames'].extend(part['frames'])
        merged['blockers'].extend(part['blockers'])
        for field in ('observed', 'captured_files', 'source_hashes'):
            for key, value in part.get(field, {}).items():
                if key in merged[field]:
                    raise ValueError('eval companion: duplicate captured artifact')
                merged[field][key] = value
    merged['blockers'] = sorted(set(merged['blockers']))
    return merged

