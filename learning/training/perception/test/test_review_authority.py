import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
from review_authority import ReviewAuthorityError, advance_revision, validate_current, verify_bundle


def encoded(doc):
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode()


def digest(doc):
    value = copy.deepcopy(doc); value.pop('decision_sha256', None)
    value['decision_sha256'] = hashlib.sha256(encoded(value)).hexdigest()
    return value


def current():
    return digest({'schema': 'rosy.pinky-review-decisions/1', 'workspace_id': 'fixture',
        'generation': 1, 'map_reference_sha256': None, 'frames': [{
        'frame': 0, 'review_uid': 'fixture:0', 'identity': 'legacy:0:' + 'a' * 64,
        'image_sha256': 'a' * 64, 'source_session': 'session', 'capture_group': None,
        'source_video_sha256': None, 'original_video_verified': False, 'video_frame': None,
        'fixed_eval_overlap': None, 'object_version': 1, 'object_decision': 'pending',
        'mask_version': 0, 'mask_decision': 'pending', 'mask_sha256': None,
        'map_revision': None, 'map_pose': None}]})


def seal_bundle(root, value):
    root.mkdir()
    app = [{'index': 0, 'version': 1, 'status': 'pending',
            'source': {'image_sha256': 'a' * 64}, 'boxes': []}]
    for name, raw in {'application-snapshot.json': encoded(app), 'pixel-reviews.jsonl': b'',
                      'inputs/source.jsonl': b'{}\n', 'inputs/human.jsonl': b'',
                      'pinky-review-receipt.json': b'{}\n'}.items():
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    legacy = {'schema': 'rosy.object-review-return/1', 'files': refs(root)}
    raw = encoded(legacy); (root / 'manifest.json').write_bytes(raw)
    (root / 'COMPLETE').write_text(hashlib.sha256(raw).hexdigest() + '\n')
    doc = {'schema': 'rosy.pinky-review-export/2', 'export_id': 'fixture-export',
           'authority': value, 'pixel_approved_frames': 0, 'current_decisions_required': True,
           'latest_decisions_endpoint': '/api/decisions', 'training_dataset_qualified': False,
           'pixel_projection_verified': False, 'files': refs(root)}
    reseal(root, doc)
    return doc


def refs(root):
    return [{'path': p.relative_to(root).as_posix(), 'bytes': len(p.read_bytes()),
             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(root.rglob('*')) if p.is_file()]


def reseal(root, doc):
    raw = encoded(doc); (root / 'review-contract.json').write_bytes(raw)
    (root / 'AUTHORITY_COMPLETE').write_text(hashlib.sha256(raw).hexdigest() + '\n')


def test_current_digest_is_recomputed_and_input_is_not_mutated():
    value = current(); before = copy.deepcopy(value)
    assert validate_current(value) == value
    assert value == before
    value['generation'] = 2
    with pytest.raises(ReviewAuthorityError):
        validate_current(value)


@pytest.mark.parametrize('field,value', [('generation', True), ('workspace_id', ''), ('schema', 'other')])
def test_current_required_types_fail_even_when_resealed(field, value):
    doc = current(); doc[field] = value
    with pytest.raises(ReviewAuthorityError):
        validate_current(digest(doc))


@pytest.mark.parametrize('field,value', [('frame', True), ('object_version', -1),
    ('original_video_verified', 1), ('image_sha256', 'x' * 64), ('object_decision', 'maybe')])
def test_frame_types_and_statuses_fail_even_when_resealed(field, value):
    doc = current(); doc['frames'][0][field] = value
    with pytest.raises(ReviewAuthorityError):
        validate_current(digest(doc))


def test_duplicate_identity_and_uid_refused():
    doc = current(); doc['frames'].append(copy.deepcopy(doc['frames'][0]))
    with pytest.raises(ReviewAuthorityError):
        validate_current(digest(doc))


def test_revision_pin_monotonicity_and_same_generation_conflict():
    doc = current(); state = advance_revision(doc, workspace_id='fixture')
    assert advance_revision(doc, workspace_id='fixture', previous=state) == state
    newer = copy.deepcopy(doc); newer['generation'] = 2; newer = digest(newer)
    state2 = advance_revision(newer, workspace_id='fixture', previous=state)
    with pytest.raises(ReviewAuthorityError):
        advance_revision(doc, workspace_id='fixture', previous=state2)
    conflict = copy.deepcopy(doc); conflict['frames'][0]['object_decision'] = 'excluded'
    with pytest.raises(ReviewAuthorityError):
        advance_revision(digest(conflict), workspace_id='fixture', previous=state)
    with pytest.raises(ReviewAuthorityError):
        advance_revision(doc, workspace_id='unknown')
    with pytest.raises(ReviewAuthorityError):
        advance_revision(None, workspace_id='fixture', previous=state)


def test_bundle_valid_integrity_does_not_qualify_training(tmp_path):
    value = current(); doc = seal_bundle(tmp_path / 'bundle', value)
    result = verify_bundle(tmp_path / 'bundle', value, workspace_id='fixture')
    assert result['contract'] == doc
    assert result['training_dataset_qualified'] is False
    assert set(result['files']) == {r['path'] for r in doc['files']} | {'review-contract.json', 'AUTHORITY_COMPLETE'}


@pytest.mark.parametrize('name', ['COMPLETE', 'AUTHORITY_COMPLETE', 'application-snapshot.json', 'pixel-reviews.jsonl'])
def test_missing_bundle_file_refused(tmp_path, name):
    root = tmp_path / 'bundle'; seal_bundle(root, current()); (root / name).unlink()
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, current(), workspace_id='fixture')


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'inputs\\escape', 'inputs/../escape', 'C:drive'])
def test_path_escape_resealed_refused(tmp_path, name):
    root = tmp_path / 'bundle'; doc = seal_bundle(root, current())
    doc['files'][0]['path'] = name; reseal(root, doc)
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, current(), workspace_id='fixture')


def test_duplicate_reference_extra_file_and_stale_current_refused(tmp_path):
    root = tmp_path / 'bundle'; doc = seal_bundle(root, current())
    doc['files'].append(copy.deepcopy(doc['files'][0])); reseal(root, doc)
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, current(), workspace_id='fixture')
    doc['files'].pop(); reseal(root, doc)
    (root / 'unsealed').write_bytes(b'new')
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, current(), workspace_id='fixture')
    (root / 'unsealed').unlink()
    changed = current(); changed['generation'] = 2
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, digest(changed), workspace_id='fixture')


def test_symlink_component_refused_even_when_target_is_inside_bundle(tmp_path):
    root = tmp_path / 'bundle'; doc = seal_bundle(root, current())
    (root / 'real').mkdir(); (root / 'real/file').write_bytes(b'data')
    try:
        (root / 'alias').symlink_to(root / 'real', target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation unavailable')
    doc['files'].append({'path': 'alias/file', 'bytes': 4, 'sha256': hashlib.sha256(b'data').hexdigest()})
    reseal(root, doc)
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, current(), workspace_id='fixture')



def test_unicode_digest_and_duplicate_json_keys(tmp_path):
    value = current(); value['workspace_id'] = '??'; value['frames'][0]['review_uid'] = '??:0'
    assert validate_current(digest(value))['workspace_id'] == '??'
    root = tmp_path / 'bundle'; doc = seal_bundle(root, current())
    raw = encoded(doc).replace(b'"export_id": "fixture-export"', b'"export_id": "wrong", "export_id": "fixture-export"')
    (root / 'review-contract.json').write_bytes(raw)
    (root / 'AUTHORITY_COMPLETE').write_bytes(hashlib.sha256(raw).hexdigest().encode())
    with pytest.raises(ReviewAuthorityError, match='JSON'):
        verify_bundle(root, current(), workspace_id='fixture')


def test_legacy_seal_cannot_be_overridden_by_authority_reseal(tmp_path):
    root = tmp_path / 'bundle'; doc = seal_bundle(root, current())
    (root / 'manifest.json').write_bytes(b'{}')
    for ref in doc['files']:
        if ref['path'] == 'manifest.json':
            ref.update(bytes=2, sha256=hashlib.sha256(b'{}').hexdigest())
    reseal(root, doc)
    with pytest.raises(ReviewAuthorityError, match='legacy seal'):
        verify_bundle(root, current(), workspace_id='fixture')


def test_resealed_application_snapshot_cannot_change_current_decision(tmp_path):
    root = tmp_path / 'bundle'; doc = seal_bundle(root, current())
    app = json.loads((root / 'application-snapshot.json').read_bytes())
    app[0]['status'] = 'approved'
    raw = encoded(app); (root / 'application-snapshot.json').write_bytes(raw)
    # Reseal both inventories; the current authority still binds pending.
    legacy = json.loads((root / 'manifest.json').read_bytes())
    for ref in legacy['files']:
        if ref['path'] == 'application-snapshot.json':
            ref.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    legacy_raw = encoded(legacy); (root / 'manifest.json').write_bytes(legacy_raw)
    (root / 'COMPLETE').write_text(hashlib.sha256(legacy_raw).hexdigest())
    doc['files'] = refs(root)
    doc['files'] = [r for r in doc['files'] if r['path'] not in ('review-contract.json', 'AUTHORITY_COMPLETE')]
    reseal(root, doc)
    with pytest.raises(ReviewAuthorityError, match='application decision'):
        verify_bundle(root, current(), workspace_id='fixture')


def test_mutation_during_verification_refused(tmp_path, monkeypatch):
    import review_authority
    root = tmp_path / 'bundle'; seal_bundle(root, current())
    original = review_authority._read
    count = 0
    def mutating(root, name):
        nonlocal count
        result = original(root, name)
        if name == 'inputs/human.jsonl':
            count += 1
            if count == 1:
                (root / name).write_bytes(b'changed after read')
        return result
    monkeypatch.setattr(review_authority, '_read', mutating)
    with pytest.raises(ReviewAuthorityError, match='changed'):
        verify_bundle(root, current(), workspace_id='fixture')


def test_approved_mask_hash_cannot_point_to_different_exported_bytes(tmp_path):
    value = current(); value['frames'][0].update(mask_version=1, mask_decision='approved', mask_sha256='b' * 64)
    value = digest(value)
    root = tmp_path / 'bundle'; doc = seal_bundle(root, value)
    (root / 'pixel-masks').mkdir(); (root / 'pixel-masks/000000.png').write_bytes(b'synthetic mask bytes')
    (root / 'pixel-classes.yaml').write_bytes(b'classes: []')
    mask = dict(value['frames'][0], mask='pixel-masks/000000.png', classes_sha256=hashlib.sha256(b'classes: []').hexdigest(),
                complete_frame_review=True, background_reviewed=True, training_dataset_qualified=False)
    (root / 'pixel-reviews.jsonl').write_bytes(encoded(mask))
    legacy = json.loads((root / 'manifest.json').read_bytes())
    for ref in legacy['files']:
        raw = (root / ref['path']).read_bytes()
        ref.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    raw = encoded(legacy); (root / 'manifest.json').write_bytes(raw)
    (root / 'COMPLETE').write_text(hashlib.sha256(raw).hexdigest())
    doc.update(pixel_approved_frames=1, files=[r for r in refs(root) if r['path'] not in ('review-contract.json', 'AUTHORITY_COMPLETE')])
    reseal(root, doc)
    with pytest.raises(ReviewAuthorityError, match='PNG hash'):
        verify_bundle(root, value, workspace_id='fixture')
