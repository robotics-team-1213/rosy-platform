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


def test_bundle_exposes_only_verified_captured_bytes_when_requested(tmp_path):
    root = tmp_path / 'export'
    value = current()
    seal_bundle(root, value)
    expected = {p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob('*') if p.is_file()}
    ordinary = verify_bundle(root, value, workspace_id='fixture')
    assert 'captured_files' not in ordinary
    captured = verify_bundle(root, value, workspace_id='fixture', capture_files=True)
    assert captured['captured_files'] == expected
    assert {k: v for k, v in captured.items() if k != 'captured_files'} == ordinary
    (root / 'inputs/source.jsonl').write_bytes(b'changed after validation\n')
    assert captured['captured_files']['inputs/source.jsonl'] == expected['inputs/source.jsonl']
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, value, workspace_id='fixture', capture_files=True)


@pytest.mark.parametrize('flag', [0, 1, None, 'true'])
def test_capture_files_requires_explicit_bool(tmp_path, flag):
    root = tmp_path / 'export'
    value = current()
    seal_bundle(root, value)
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, value, workspace_id='fixture', capture_files=flag)


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



def rich_bundle(root):
    value = current(); value['workspace_id'] = 'c' * 32
    raw_image = b'synthetic image integrity fixture'
    image_sha = hashlib.sha256(raw_image).hexdigest()
    source = {'index': 0, 'image': 'images/000000.png', 'image_sha256': image_sha,
              'width': 2, 'height': 2, 'source_session': 'session', 'video': None,
              'video_frame': None, 'objects': []}
    review = {'index': 0, 'image_sha256': image_sha, 'boxes': [],
              'review_status': 'pending_human', 'complete_frame_review': False}
    human = dict(review, video=None, video_frame=None)
    row = value['frames'][0]
    row.update(review_uid=value['workspace_id'] + ':0', image_sha256=image_sha,
               identity='legacy:0:' + image_sha, width=2, height=2,
               source_sha256=hashlib.sha256(encoded(source)).hexdigest(),
               object_review_sha256=hashlib.sha256(encoded(human)).hexdigest(),
               representations_sha256=hashlib.sha256(encoded([source])).hexdigest(),
               frame_excluded=False, complete_frame_review=False,
               background_reviewed=False, pixel_approval=None)
    value.update(pixel_classes_sha256=None, classes_signature=None, ignore_index=None)
    value = digest(value); doc = seal_bundle(root, value)
    (root / 'application-snapshot.json').write_bytes(encoded([
        {'index': 0, 'source': source, 'review': review, 'status': 'pending', 'version': 1}]))
    (root / 'inputs/source.jsonl').write_bytes(encoded(source))
    (root / 'inputs/human.jsonl').write_bytes(encoded(human))
    (root / 'inputs/images').mkdir(); (root / 'inputs/images/000000.png').write_bytes(raw_image)
    (root / 'representations.json').write_bytes(encoded({'0': [source]}))
    (root / 'pinky-review-receipt.json').write_bytes(encoded({'authority': value, 'export_id': doc['export_id']}))
    refresh(root, doc)
    return value, doc


def refresh(root, doc):
    legacy = json.loads((root / 'manifest.json').read_bytes())
    legacy.update(source_sha256=hashlib.sha256((root / 'inputs/source.jsonl').read_bytes()).hexdigest(),
                  human_sha256=hashlib.sha256((root / 'inputs/human.jsonl').read_bytes()).hexdigest(),
                  groups=[{'exported_indices': [], 'queued_indices': [0]}])
    for ref in legacy['files']:
        raw = (root / ref['path']).read_bytes()
        ref.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    raw = encoded(legacy); (root / 'manifest.json').write_bytes(raw)
    (root / 'COMPLETE').write_text(hashlib.sha256(raw).hexdigest())
    doc['files'] = [r for r in refs(root) if r['path'] not in ('review-contract.json', 'AUTHORITY_COMPLETE')]
    reseal(root, doc)


def test_rich_content_positive_is_integrity_only(tmp_path):
    value, _ = rich_bundle(tmp_path / 'bundle')
    assert verify_bundle(tmp_path / 'bundle', value, workspace_id=value['workspace_id'])['training_dataset_qualified'] is False


@pytest.mark.parametrize('field,bad', [('width', True), ('height', 2.0),
    ('representations_sha256', 'x' * 64), ('source_sha256', None),
    ('object_review_sha256', True), ('frame_excluded', True),
    ('complete_frame_review', 1), ('background_reviewed', 0), ('pixel_approval', {})])
def test_rich_current_type_and_binding_reseal_refused(tmp_path, field, bad):
    value, _ = rich_bundle(tmp_path / 'bundle'); value['frames'][0][field] = bad
    with pytest.raises(ReviewAuthorityError):
        validate_current(digest(value))


def test_partial_rich_schema_cannot_silently_fall_back_to_legacy():
    value = current(); value['frames'][0]['width'] = 2
    with pytest.raises(ReviewAuthorityError):
        validate_current(digest(value))


@pytest.mark.parametrize('field,bad', [('ignore_index', 255.0), ('classes_signature', None)])
def test_class_binding_reseal_refused(tmp_path, field, bad):
    value, _ = rich_bundle(tmp_path / 'bundle')
    value.update(pixel_classes_sha256='d' * 64, classes_signature='e' * 64, ignore_index=255)
    value[field] = bad
    with pytest.raises(ReviewAuthorityError):
        validate_current(digest(value))


@pytest.mark.parametrize('field,bad', [('width', 2.0), ('complete_frame_review', 1), ('ignore_index', 255.0)])
def test_exact_nested_pixel_approval_types_refused(tmp_path, field, bad):
    value, _ = rich_bundle(tmp_path / 'bundle')
    value.update(pixel_classes_sha256='d' * 64, classes_signature='e' * 64, ignore_index=255)
    row = value['frames'][0]; row.update(mask_decision='approved', mask_version=1,
        mask_sha256='f' * 64, complete_frame_review=True, background_reviewed=True)
    row['pixel_approval'] = dict(image_sha256=row['image_sha256'], mask_sha256=row['mask_sha256'],
        mask_version=1, width=2, height=2, classes_sha256='d' * 64, classes_signature='e' * 64,
        ignore_index=255, complete_frame_review=True, background_reviewed=True)
    row['pixel_approval'][field] = bad
    with pytest.raises(ReviewAuthorityError):
        validate_current(digest(value))


@pytest.mark.parametrize('target', ['human', 'source', 'review', 'representations', 'receipt', 'image'])
def test_rich_resealed_payload_change_refused(tmp_path, target):
    root = tmp_path / 'bundle'; value, doc = rich_bundle(root)
    if target in ('source', 'review'):
        app = json.loads((root / 'application-snapshot.json').read_bytes())
        if target == 'source':
            app[0]['source']['objects'] = [{'label': None, 'bbox_xyxy': [0, 0, 1, 1]}]
            (root / 'inputs/source.jsonl').write_bytes(encoded(app[0]['source']))
        else:
            app[0]['review']['boxes'] = [{'label': 'wall', 'bbox_xyxy': [0, 0, 1, 1]}]
            (root / 'inputs/human.jsonl').write_bytes(encoded(dict(app[0]['review'], video=None, video_frame=None)))
        (root / 'application-snapshot.json').write_bytes(encoded(app))
    elif target == 'human':
        human = json.loads((root / 'inputs/human.jsonl').read_bytes())
        human['boxes'] = [{'label': 'wall', 'bbox_xyxy': [0, 0, 1, 1]}]
        (root / 'inputs/human.jsonl').write_bytes(encoded(human))
    elif target == 'representations':
        (root / 'representations.json').write_bytes(encoded({'0': []}))
    elif target == 'receipt':
        (root / 'pinky-review-receipt.json').write_bytes(encoded({'authority': value, 'export_id': 'wrong'}))
    else:
        (root / 'inputs/images/000000.png').write_bytes(b'changed image')
    refresh(root, doc)
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, value, workspace_id=value['workspace_id'])



def approved_rich_mask(root):
    import zlib
    value, doc = rich_bundle(root)
    classes = [{'index': 0, 'name': 'floor', 'role': 'background', 'color': [0, 0, 0]}]
    class_raw = json.dumps({'classes': classes}).encode()
    def chunk(kind, raw):
        return len(raw).to_bytes(4, 'big') + kind + raw + (zlib.crc32(kind + raw) & 0xffffffff).to_bytes(4, 'big')
    mask_raw = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', b'\x00\x00\x00\x02' * 2 + b'\x08\x00\x00\x00\x00')
                + chunk(b'IDAT', zlib.compress(b'\x00' * 6)) + chunk(b'IEND', b''))
    value.update(pixel_classes_sha256=hashlib.sha256(class_raw).hexdigest(),
                 classes_signature=hashlib.sha256(json.dumps(classes, sort_keys=True).encode()).hexdigest(), ignore_index=255)
    row = value['frames'][0]; row.update(mask_decision='approved', mask_version=1,
        mask_sha256=hashlib.sha256(mask_raw).hexdigest(), complete_frame_review=True, background_reviewed=True)
    row['pixel_approval'] = {key: row[key] for key in ('image_sha256', 'mask_sha256', 'mask_version', 'width', 'height',
                                                     'complete_frame_review', 'background_reviewed')}
    row['pixel_approval'].update(classes_sha256=value['pixel_classes_sha256'],
                                classes_signature=value['classes_signature'], ignore_index=255)
    value = digest(value); doc['authority'] = value; doc['pixel_approved_frames'] = 1
    (root / 'pixel-classes.yaml').write_bytes(class_raw)
    (root / 'pixel-masks').mkdir(); (root / 'pixel-masks/000000.png').write_bytes(mask_raw)
    (root / 'pixel-reviews.jsonl').write_bytes(encoded(dict(row, mask='pixel-masks/000000.png',
        classes_sha256=value['pixel_classes_sha256'], training_dataset_qualified=False)))
    (root / 'pinky-review-receipt.json').write_bytes(encoded({'authority': value, 'export_id': doc['export_id']}))
    refresh(root, doc)
    return value, doc


def test_rich_exact_pixel_binding_is_still_unqualified(tmp_path):
    root = tmp_path / 'bundle'; value, doc = approved_rich_mask(root)
    result = verify_bundle(root, value, workspace_id=value['workspace_id'])
    assert result['contract']['pixel_approved_frames'] == 1
    assert result['training_dataset_qualified'] is False


def test_whole_frame_exclusion_cannot_export_historical_approved_mask(tmp_path):
    root = tmp_path / 'bundle'; value, doc = approved_rich_mask(root)
    row = value['frames'][0]; row.update(frame_excluded=True, object_decision='excluded')
    value = digest(value); doc['authority'] = value
    app = json.loads((root / 'application-snapshot.json').read_bytes()); app[0]['status'] = 'excluded'
    (root / 'application-snapshot.json').write_bytes(encoded(app))
    (root / 'pinky-review-receipt.json').write_bytes(encoded({'authority': value, 'export_id': doc['export_id']}))
    refresh(root, doc)
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, value, workspace_id=value['workspace_id'])
    (root / 'pixel-reviews.jsonl').write_bytes(b''); doc['pixel_approved_frames'] = 0; refresh(root, doc)
    assert verify_bundle(root, value, workspace_id=value['workspace_id'])['training_dataset_qualified'] is False


def test_rich_class_and_embedded_authority_cannot_use_numeric_alias(tmp_path):
    root = tmp_path / 'bundle'; value, doc = approved_rich_mask(root)
    doc['authority'] = copy.deepcopy(value); doc['authority']['frames'][0]['frame_excluded'] = 0
    reseal(root, doc)
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, value, workspace_id=value['workspace_id'])
    doc['authority'] = value
    (root / 'pixel-classes.yaml').write_bytes(b'changed classes')
    refresh(root, doc)
    with pytest.raises(ReviewAuthorityError):
        verify_bundle(root, value, workspace_id=value['workspace_id'])
