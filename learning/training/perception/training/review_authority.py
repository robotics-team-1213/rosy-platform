"""Verify sealed GUI evidence against caller-supplied current decisions.

The caller pins the workspace, fetches current decisions and enforces freshness.
These helpers provide integrity/revision checks, never human truth or qualification.
"""
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


class ReviewAuthorityError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ReviewAuthorityError(message)


def _encoded(value):
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ReviewAuthorityError('finite JSON decision data required') from exc


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _seal(raw, digest):
    return raw in {digest.encode('ascii'), (digest + '\n').encode('ascii'), (digest + '\r\n').encode('ascii')}


def _hex(value, nullable=False):
    return (nullable and value is None) or (isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None)


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 2**63 - 1


def _text(value, nullable=False):
    return (nullable and value is None) or (isinstance(value, str) and bool(value.strip()) and len(value) <= 4096)


def validate_current(current):
    """Validate/recompute the complete current snapshot; return a detached copy."""
    _require(isinstance(current, dict), 'current decisions unavailable')
    value = copy.deepcopy(current)
    _require(value.get('schema') == 'rosy.pinky-review-decisions/1', 'current schema differs')
    workspace = value.get('workspace_id')
    _require(_text(workspace) and workspace == workspace.strip(), 'workspace identity required')
    _require(_integer(value.get('generation'), 1), 'bounded integer generation required')
    _require(_hex(value.get('decision_sha256')), 'decision digest required')
    raw = {k: v for k, v in value.items() if k != 'decision_sha256'}
    _require(_sha(_encoded(raw)) == value['decision_sha256'], 'decision digest differs')
    _require('map_reference_sha256' in value and _hex(value['map_reference_sha256'], True), 'map reference hash invalid')
    if 'pixel_classes_sha256' in value:
        _require(_hex(value['pixel_classes_sha256'], True), 'pixel classes hash invalid')
    frames = value.get('frames')
    _require(isinstance(frames, list) and len(frames) <= 100000, 'complete bounded frame list required')
    seen = [set(), set(), set()]
    for row in frames:
        _require(isinstance(row, dict), 'frame object required')
        _require(_integer(row.get('frame')), 'integer frame required')
        _require(row.get('review_uid') == f'{workspace}:{row["frame"]}', 'review UID binding differs')
        _require(_text(row.get('identity')), 'source identity required')
        for values, key in zip(seen, ('frame', 'review_uid', 'identity')):
            _require(row[key] not in values, 'duplicate frame identity or UID')
            values.add(row[key])
        _require(_hex(row.get('image_sha256')), 'image hash invalid')
        for key in ('source_session', 'capture_group', 'map_revision'):
            _require(key in row and _text(row[key], True), f'{key} invalid')
        _require('map_pose' in row and (row['map_pose'] is None or isinstance(row['map_pose'], dict)), 'map pose invalid')
        _require('source_video_sha256' in row and _hex(row['source_video_sha256'], True), 'video hash invalid')
        _require(type(row.get('original_video_verified')) is bool, 'video verification boolean required')
        _require('video_frame' in row and (row['video_frame'] is None or _integer(row['video_frame'])), 'video frame invalid')
        _require('fixed_eval_overlap' in row and (row['fixed_eval_overlap'] is None or type(row['fixed_eval_overlap']) is bool), 'eval overlap invalid')
        if row['source_video_sha256'] is not None and row['video_frame'] is not None:
            expected = f'video:{row["source_video_sha256"]}:{row["video_frame"]}'
        elif row['identity'].startswith('legacy:'):
            expected = f'legacy:{row["frame"]}:{row["image_sha256"]}'
        else:
            expected = f'image:{row["source_session"]}:{row["video_frame"]}:{row["image_sha256"]}'
        _require(row['identity'] == expected, 'source identity binding differs')
        if row['original_video_verified']:
            _require(row['source_video_sha256'] is not None and row['video_frame'] is not None, 'verified video binding missing')
        for key in ('object_version', 'mask_version'):
            _require(_integer(row.get(key)), f'{key} invalid')
        _require(row.get('object_decision') in ('pending', 'approved', 'excluded'), 'object decision invalid')
        _require(row.get('mask_decision') in ('pending', 'approved', 'excluded'), 'mask decision invalid')
        _require('mask_sha256' in row and _hex(row['mask_sha256'], True), 'mask hash invalid')
        if row['mask_decision'] == 'approved':
            _require(row['mask_sha256'] is not None and row['mask_version'] > 0, 'approved mask binding missing')
    return value


def advance_revision(current, *, workspace_id, previous=None):
    """Check a pinned authority; caller persists only after verified fetch/delivery."""
    value = validate_current(current)
    _require(_text(workspace_id) and value['workspace_id'] == workspace_id, 'unknown workspace authority')
    result = {k: value[k] for k in ('workspace_id', 'generation', 'decision_sha256')}
    if previous is not None:
        _require(isinstance(previous, dict) and set(previous) == set(result), 'invalid previous authority state')
        _require(previous['workspace_id'] == workspace_id and _integer(previous['generation'], 1)
                 and _hex(previous['decision_sha256']), 'invalid previous authority state')
        _require(result['generation'] >= previous['generation'], 'older authority revision refused')
        if result['generation'] == previous['generation']:
            _require(result['decision_sha256'] == previous['decision_sha256'], 'same generation authority conflict')
    return result


def _name(name):
    _require(isinstance(name, str) and 0 < len(name) <= 4096 and '\\' not in name
             and ':' not in name and '\x00' not in name, 'safe relative path required')
    path = PurePosixPath(name)
    _require(not path.is_absolute() and all(p not in ('', '.', '..') for p in name.split('/'))
             and path.as_posix() == name, 'canonical relative path required')
    return name


def _no_links(path):
    for part in [path, *path.parents]:
        _require(not part.is_symlink() and not (hasattr(part, 'is_junction') and part.is_junction()), 'symlink or junction component refused')


def _read(root, name):
    path = root / _name(name)
    _no_links(path)
    try:
        before = path.lstat()
        _require(stat.S_ISREG(before.st_mode), 'regular referenced file required')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            _require(stat.S_ISREG(opened.st_mode) and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), 'reference changed while opening')
            raw = stream.read()
        _no_links(path)
        after = path.lstat()
        _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                 (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'reference changed while reading')
        return raw
    except OSError as exc:
        raise ReviewAuthorityError('referenced file unavailable') from exc


def _json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ReviewAuthorityError('nonfinite JSON')))
    except (ValueError, UnicodeError) as exc:
        raise ReviewAuthorityError('invalid evidence JSON') from exc


def _references(doc):
    _require(isinstance(doc, dict) and isinstance(doc.get('files'), list), 'file inventory required')
    result, seen = {}, set()
    for ref in doc['files']:
        _require(isinstance(ref, dict) and set(ref) == {'path', 'bytes', 'sha256'}, 'exact file reference required')
        name = _name(ref['path'])
        _require(name.casefold() not in seen, 'duplicate file path')
        _require(_integer(ref['bytes']) and _hex(ref['sha256']), 'file hash and byte count required')
        seen.add(name.casefold()); result[name] = ref
    return result


def _paths(root):
    paths, folded = set(), set()
    for path in root.rglob('*'):
        _no_links(path)
        _require(path.is_dir() or stat.S_ISREG(path.lstat().st_mode), 'special bundle entry refused')
        if path.is_file():
            name = _name(path.relative_to(root).as_posix())
            _require(name.casefold() not in folded, 'colliding bundle paths')
            folded.add(name.casefold()); paths.add(name)
    return paths


def verify_bundle(export_root, current, *, workspace_id):
    """Verify both seals and exact current equality; never qualify the dataset."""
    value = validate_current(current)
    advance_revision(value, workspace_id=workspace_id)
    root = Path(os.path.abspath(export_root))
    _no_links(root)
    _require(root.is_dir(), 'bundle directory unavailable')
    captured = {}
    def read(name):
        if name not in captured:
            captured[name] = _read(root, name)
        return captured[name]
    raw = read('review-contract.json')
    _require(_seal(read('AUTHORITY_COMPLETE'), _sha(raw)), 'authority seal differs')
    doc = _json(raw)
    _require(isinstance(doc, dict) and doc.get('schema') == 'rosy.pinky-review-export/2', 'export schema differs')
    _require(_text(doc.get('export_id')), 'export identity missing')
    authority = validate_current(doc.get('authority'))
    _require(_encoded(authority) == _encoded(value), 'export differs from current decisions')
    _require(doc.get('current_decisions_required') is True and doc.get('training_dataset_qualified') is False
             and doc.get('pixel_projection_verified') is False, 'evidence scope differs')
    refs = _references(doc)
    mandatory = {'manifest.json', 'COMPLETE', 'application-snapshot.json', 'pixel-reviews.jsonl',
                 'inputs/source.jsonl', 'inputs/human.jsonl', 'pinky-review-receipt.json'}
    _require(mandatory <= set(refs), 'mandatory evidence absent from inventory')
    _require(not {'review-contract.json', 'AUTHORITY_COMPLETE'} & set(refs), 'self-referential authority inventory')
    for name, ref in refs.items():
        payload = read(name)
        _require(len(payload) == ref['bytes'] and _sha(payload) == ref['sha256'], 'referenced bytes differ')
    legacy_raw = read('manifest.json')
    _require(_seal(read('COMPLETE'), _sha(legacy_raw)), 'legacy seal differs')
    legacy = _json(legacy_raw)
    _require(isinstance(legacy, dict) and legacy.get('schema') == 'rosy.object-review-return/1', 'legacy manifest schema differs')
    for name, ref in _references(legacy).items():
        _require(name in refs and refs[name] == ref, 'legacy and authority inventories differ')
    rows = _json(read('application-snapshot.json'))
    _require(isinstance(rows, list) and len(rows) == len(value['frames']), 'complete application snapshot required')
    app = {}
    for row in rows:
        _require(isinstance(row, dict) and _integer(row.get('index')) and row['index'] not in app, 'unique application frame required')
        app[row['index']] = row
    for frame in value['frames']:
        row = app.get(frame['frame'])
        _require(row is not None and type(row.get('version')) is int and row['version'] == frame['object_version']
                 and row.get('status') == frame['object_decision'] and isinstance(row.get('source'), dict)
                 and row['source'].get('image_sha256') == frame['image_sha256'], 'application decision binding differs')
    if value.get('pixel_classes_sha256') is not None:
        _require('pixel-classes.yaml' in refs and refs['pixel-classes.yaml']['sha256'] == value['pixel_classes_sha256'], 'current pixel class binding differs')
    masks = [_json(line) for line in read('pixel-reviews.jsonl').splitlines() if line.strip()]
    approved = {r['frame']: r for r in value['frames'] if r['mask_decision'] == 'approved' and r['object_decision'] != 'excluded'}
    _require(_integer(doc.get('pixel_approved_frames')) and doc['pixel_approved_frames'] == len(masks) == len(approved), 'approved mask count differs')
    seen = set()
    for mask in masks:
        _require(isinstance(mask, dict) and _integer(mask.get('frame')) and mask['frame'] in approved
                 and mask['frame'] not in seen, 'unique current approved mask required')
        frame = approved[mask['frame']]; seen.add(mask['frame'])
        _require(set(frame) <= set(mask) and _encoded({k: mask[k] for k in frame}) == _encoded(frame), 'mask decision binding differs')
        name = _name(mask.get('mask'))
        _require(name in refs and refs[name]['sha256'] == frame['mask_sha256'], 'exported PNG hash differs from approved mask')
        _require('pixel-classes.yaml' in refs and mask.get('classes_sha256') == refs['pixel-classes.yaml']['sha256'], 'mask class binding differs')
        _require(mask.get('complete_frame_review') is True and mask.get('background_reviewed') is True
                 and mask.get('training_dataset_qualified') is False, 'explicit mask completion required')
    expected = set(refs) | {'review-contract.json', 'AUTHORITY_COMPLETE'}
    _require(_paths(root) == expected, 'bundle path set differs from sealed inventory')
    for name, payload in captured.items():
        _require(_read(root, name) == payload, 'bundle changed during validation')
    _require(_paths(root) == expected, 'bundle changed during validation')
    return {'contract': doc, 'contract_sha': _sha(raw), 'files': sorted(expected), 'training_dataset_qualified': False}
