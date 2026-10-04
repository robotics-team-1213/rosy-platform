"""Read-only candidate diagnostics; this API never grants dataset qualification."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
import review_dataset as target
from test_review_authority import current, digest, seal_bundle


def delivery(value, stamp=100):
    return {'schema': 'rosy.pinky-review-current-delivery/1', 'workspace_id': value['workspace_id'],
            'available': True, 'checked_at_unix': stamp, 'authority': copy.deepcopy(value)}


def test_pending_bundle_is_read_only_and_never_qualified(tmp_path):
    value = current(); root = tmp_path / 'bundle'; seal_bundle(root, value)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    calls = []
    def fetch():
        calls.append(True); return delivery(value)
    report = target.inspect_candidates(root, fetch_current=fetch, workspace_id='fixture', now=lambda: 100)
    assert len(calls) == 2
    assert report['training_dataset_qualified'] is False
    assert report['approved_masks'] == 0
    assert 'mask_not_approved' in report['frames'][0]['blockers']
    assert 'source_group_unknown' in report['frames'][0]['blockers']
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('stamp', [True, float('nan'), float('inf'), 9, 106])
def test_invalid_freshness_denied_before_bundle_read(stamp):
    with pytest.raises(ValueError):
        target.inspect_candidates('unused', fetch_current=lambda: delivery(current(), stamp),
                                  workspace_id='fixture', now=lambda: 100)


@pytest.mark.parametrize('field,bad', [('available', 1), ('schema', 'other'), ('workspace_id', 'wrong')])
def test_delivery_types_and_workspace(field, bad):
    envelope = delivery(current()); envelope[field] = bad
    with pytest.raises(ValueError):
        target.inspect_candidates('unused', fetch_current=lambda: envelope, workspace_id='fixture', now=lambda: 100)


def test_changed_authority_between_fetches_refuses_report(tmp_path):
    value = current(); root = tmp_path / 'bundle'; seal_bundle(root, value)
    other = copy.deepcopy(value); other['generation'] = 2; other = digest(other)
    snapshots = iter([delivery(value), delivery(other)])
    with pytest.raises(ValueError, match='changed'):
        target.inspect_candidates(root, fetch_current=lambda: next(snapshots), workspace_id='fixture', now=lambda: 100)


def test_capture_group_connects_sessions_and_exact_duplicate_images():
    rows = [dict(frame=0, source_session='part01', capture_group='shared', image_sha256='a', source_video_sha256='v', video_frame=1),
            dict(frame=1, source_session='part04', capture_group='shared', image_sha256='b', source_video_sha256='v', video_frame=2),
            dict(frame=2, source_session='other', capture_group='elsewhere', image_sha256='b', source_video_sha256=None, video_frame=None)]
    assert target.source_components(rows, {}) == [[0, 1, 2]]


def test_alternate_representation_hashes_connect_components():
    rows = [dict(frame=i, source_session=str(i), capture_group=str(i), image_sha256=str(i),
                 source_video_sha256=None, video_frame=None) for i in range(2)]
    assert target.source_components(rows, {0: ['same'], 1: ['same']}) == [[0, 1]]


@pytest.mark.parametrize('shape,dtype,value', [((2, 3, 3), 'uint8', 0), ((2, 3), 'uint16', 0),
                                              ((2, 3), 'uint8', 255), ((2, 3), 'uint8', 7)])
def test_bad_indexed_mask_blocks(shape, dtype, value):
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    ok, encoded = cv2.imencode('.png', np.full(shape, value, dtype=dtype)); assert ok
    assert target.mask_blockers(encoded.tobytes(), width=3, height=2, indices={0, 5})


def test_crosswalk_ignore_role_index_is_still_valid_class_pixel():
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    ok, encoded = cv2.imencode('.png', np.full((2, 3), 5, dtype='uint8')); assert ok
    assert target.mask_blockers(encoded.tobytes(), width=3, height=2, indices={0, 5}) == []

@pytest.mark.parametrize('age', [True, float('nan'), float('inf'), 0, 91])
def test_freshness_bound_is_strict(age):
    with pytest.raises(ValueError):
        target.inspect_candidates('unused', fetch_current=lambda: delivery(current()),
                                  workspace_id='fixture', authority_max_age_s=age, now=lambda: 100)


def test_older_previous_revision_refuses_current():
    with pytest.raises(ValueError, match='older'):
        target.inspect_candidates('unused', fetch_current=lambda: delivery(current()), workspace_id='fixture',
                                  previous_authority={'workspace_id': 'fixture', 'generation': 2,
                                                      'decision_sha256': 'a' * 64}, now=lambda: 100)


def test_eval_full_content_union_and_missing_source_group_remains_unknown(tmp_path):
    from dataset.build import content_sha
    folders = []
    for i in range(2):
        stage = tmp_path / ('eval' + str(i)) / 'staging'; stage.mkdir(parents=True)
        (stage / 'image.png').write_bytes(b'image' + bytes([i]))
        (stage / 'manifest.json').write_text(json.dumps({'purpose': 'eval', 'frames': [
            {'session': 'held' + str(i), 'image': 'image.png'}]}))
        final = stage.with_name(content_sha(stage)); stage.rename(final); folders.append(final)
    refs, sessions, groups, videos, hashes, complete = target._eval_inventory(folders)
    assert len(refs) == 2 and sessions == {'held0', 'held1'}
    assert len(hashes) == 2 and not groups and not videos and complete is False
    (folders[0] / 'image.png').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='content hash'):
        target._eval_inventory(folders)


@pytest.mark.parametrize('index', [True, 0.0, '0', 255])
def test_class_indices_cannot_be_coerced(index):
    pytest.importorskip('yaml')
    raw = json.dumps({'classes': [{'index': index, 'name': 'floor', 'role': 'background'}]}).encode()
    with pytest.raises(ValueError, match='strict class'):
        target._classes(raw, {})


def test_duplicate_class_indices_denied():
    raw = json.dumps({'classes': [{'index': 0, 'name': 'floor', 'role': 'background'},
                                 {'index': 0, 'name': 'lane', 'role': 'lane_marking'}]}).encode()
    with pytest.raises(ValueError, match='unique contiguous'):
        target._classes(raw, {})


def test_raw_yaml_hash_and_normalized_signature_are_distinct():
    from dataset.build import load_classes
    raw = b'classes:\n - {index: 0, name: floor, role: background}\n - {index: 1, name: crosswalk, role: ignore}\n'
    classes = load_classes('captured', require_color=False, source_bytes=raw)
    current = {'pixel_classes_sha256': hashlib.sha256(raw).hexdigest(),
               'classes_signature': hashlib.sha256(json.dumps(classes, sort_keys=True).encode()).hexdigest()}
    assert target._classes(raw, current) == {0, 1}
    current['classes_signature'] = current['pixel_classes_sha256']
    with pytest.raises(ValueError, match='signature'):
        target._classes(raw, current)

@pytest.mark.parametrize('suffix', ['.jpg', '.bmp'])
def test_grayscale_non_png_is_never_indexed_approval(suffix):
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    ok, encoded = cv2.imencode(suffix, np.zeros((2, 3), dtype='uint8')); assert ok
    assert target.mask_blockers(encoded.tobytes(), width=3, height=2, indices={0}) == ['mask_not_8bit_grayscale_png']


def test_primary_image_dimensions_are_decoded_from_captured_bytes():
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    ok, encoded = cv2.imencode('.jpg', np.zeros((2, 3, 3), dtype='uint8')); assert ok
    assert target.image_blockers(encoded.tobytes(), width=3, height=2) == []
    assert target.image_blockers(encoded.tobytes(), width=4, height=2) == ['image_dimensions_differ']


def test_empty_hashed_eval_inventory_cannot_establish_source_disjointness(tmp_path):
    from dataset.build import content_sha
    stage = tmp_path / 'eval' / 'stage'; stage.mkdir(parents=True)
    (stage / 'manifest.json').write_text(json.dumps({'purpose': 'eval', 'frames': [], 'labels': [{'session': 'held'}]}))
    final = stage.with_name(content_sha(stage)); stage.rename(final)
    inventory = target._eval_inventory([final])
    assert inventory[1] == {'held'} and inventory[-1] is False


def test_build_zero_approved_creates_nothing(tmp_path):
    from store import Store
    value = current(); root = tmp_path / 'bundle'; seal_bundle(root, value)
    store = Store(tmp_path / 'store'); scratch = tmp_path / 'scratch'
    report = target.build_dataset(root, fetch_current=lambda: delivery(value), workspace_id='fixture',
                                  eval_folders=(), source_proof_files=(), store=store, name='audit',
                                  staging_parent=scratch, now=lambda: 100)
    assert report['status'] == 'HOLD' and report['training_admission'] is False
    assert not scratch.exists() and not store.root.exists()


def test_whole_video_connects_adjacent_frames_even_different_group_aliases():
    rows = [dict(frame=i, source_session=str(i), capture_group=str(i), image_sha256=str(i),
                 source_video_sha256='v' * 64, video_frame=i) for i in range(2)]
    assert target.source_components(rows, {}) == [[0, 1]]


def build_fixture(tmp_path, shared_group=False):
    from test_review_authority import encoded, refs, reseal
    from dataset.build import load_classes, content_sha
    from store import Store
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    store = Store(tmp_path / 'store'); bundle = tmp_path / 'bundle'; bundle.mkdir()
    classes_raw = b'classes:\n - {index: 0, name: floor, role: background}\n - {index: 1, name: lane_line, role: lane_marking}\n'
    classes = load_classes('captured', require_color=False, source_bytes=classes_raw)
    class_sha = hashlib.sha256(classes_raw).hexdigest()
    signature = hashlib.sha256(json.dumps(classes, sort_keys=True).encode()).hexdigest()
    workspace = 'd' * 32; proofs = []; frames = []; sources = []; humans = []; app = []
    for i in range(3):
        pixels = np.full((16, 16, 3), 40 + i * 40, np.uint8)
        video_path = tmp_path / ('video' + str(i) + '.avi')
        writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*'FFV1'), 5, (16, 16))
        if not writer.isOpened(): pytest.skip('lossless FFV1 fixture codec unavailable')
        for number in range(3): writer.write(pixels + number)
        writer.release()
        video_sha = hashlib.sha256(video_path.read_bytes()).hexdigest()
        ok, image = cv2.imencode('.png', pixels); assert ok; image_raw = image.tobytes()
        image_sha = hashlib.sha256(image_raw).hexdigest()
        proof_path = tmp_path / ('proof' + str(i) + '.json')
        proof_path.write_text(json.dumps(dict(schema='rosy.pinky-review-source-proof/1', source_session='session' + str(i),
                                             capture_group='group' + str(0 if shared_group and i < 2 else i), video_path=str(video_path), video_sha256=video_sha)))
        proofs.append(proof_path)
        if i == 2:
            stage = store.evalsets_dir / 'held' / 'stage'; stage.mkdir(parents=True)
            (stage / 'image.png').write_bytes(image_raw)
            (stage / 'manifest.json').write_text(json.dumps(dict(purpose='eval', frames=[dict(
                session='session2', capture_group='group2', source_video_sha256=video_sha, video_frame=0, image='image.png')])))
            eval_root = stage.with_name(content_sha(stage)); stage.rename(eval_root)
            break
        source = dict(index=i, image=f'images/{i:06d}.png', image_sha256=image_sha, width=16, height=16,
                      source_session='session' + str(i), capture_group='group' + str(0 if shared_group else i), source_video_sha256=video_sha,
                      video=video_path.name, video_frame=0, fixed_eval_overlap=False, objects=[])
        review = dict(index=i, image_sha256=image_sha, boxes=[], review_status='approved', complete_frame_review=True)
        human = dict(review, video=source['video'], video_frame=0)
        ok, mask = cv2.imencode('.png', np.full((16, 16), 1, np.uint8)); assert ok
        mask_raw = mask.tobytes(); mask_sha = hashlib.sha256(mask_raw).hexdigest()
        approval = dict(image_sha256=image_sha, mask_sha256=mask_sha, mask_version=1, width=16, height=16,
                        classes_sha256=class_sha, classes_signature=signature, ignore_index=255,
                        complete_frame_review=True, background_reviewed=True)
        frame = dict(frame=i, review_uid=f'{workspace}:{i}', identity=f'video:{video_sha}:0', image_sha256=image_sha,
                     source_session=source['source_session'], capture_group=source['capture_group'], source_video_sha256=video_sha,
                     original_video_verified=False, video_frame=0, fixed_eval_overlap=False,
                     object_version=1, object_decision='approved', mask_version=1, mask_decision='approved', mask_sha256=mask_sha,
                     map_revision=None, map_pose=None, width=16, height=16, source_sha256=hashlib.sha256(encoded(source)).hexdigest(),
                     object_review_sha256=hashlib.sha256(encoded(human)).hexdigest(),
                     representations_sha256=hashlib.sha256(encoded([source])).hexdigest(), frame_excluded=False,
                     complete_frame_review=True, background_reviewed=True, pixel_approval=approval)
        frames.append(frame); sources.append(source); humans.append(human)
        app.append(dict(index=i, source=source, review=review, status='approved', version=1))
        for relative, raw in [(f'inputs/images/{i:06d}.png', image_raw), (f'pixel-masks/{i:06d}.png', mask_raw)]:
            path = bundle / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    authority = digest(dict(schema='rosy.pinky-review-decisions/1', workspace_id=workspace, generation=1,
                            map_reference_sha256=None, pixel_classes_sha256=class_sha, classes_signature=signature,
                            ignore_index=255, frames=frames))
    payloads = {'application-snapshot.json': encoded(app), 'inputs/source.jsonl': b''.join(encoded(s) for s in sources),
                'inputs/human.jsonl': b''.join(encoded(h) for h in humans),
                'representations.json': encoded({str(i): [s] for i, s in enumerate(sources)}),
                'pixel-classes.yaml': classes_raw,
                'pixel-reviews.jsonl': b''.join(encoded(dict(f, mask=f'pixel-masks/{f["frame"]:06d}.png',
                                                           classes_sha256=class_sha, training_dataset_qualified=False)) for f in frames),
                'pinky-review-receipt.json': encoded(dict(export_id='synthetic', authority=authority))}
    for name, raw in payloads.items(): (bundle / name).write_bytes(raw)
    legacy = dict(schema='rosy.object-review-return/1', files=refs(bundle),
                  source_sha256=hashlib.sha256(payloads['inputs/source.jsonl']).hexdigest(),
                  human_sha256=hashlib.sha256(payloads['inputs/human.jsonl']).hexdigest(),
                  groups=[dict(exported_indices=[0, 1])])
    raw = encoded(legacy); (bundle / 'manifest.json').write_bytes(raw)
    (bundle / 'COMPLETE').write_text(hashlib.sha256(raw).hexdigest())
    doc = dict(schema='rosy.pinky-review-export/2', export_id='synthetic', authority=authority,
               pixel_approved_frames=2, current_decisions_required=True, training_dataset_qualified=False,
               pixel_projection_verified=False, files=refs(bundle))
    reseal(bundle, doc)
    return dict(export_root=bundle, fetch_current=lambda: delivery(authority), workspace_id=workspace,
                eval_folders=[eval_root], gate_eval_refs=[dict(name='held', content_sha=eval_root.name)],
                source_proof_files=proofs, store=store, name='indexed',
                staging_parent=tmp_path / 'scratch', now=lambda: 100), authority


def test_indexed_build_roundtrip(tmp_path):
    from store import content_sha
    args, authority = build_fixture(tmp_path)
    result = target.build_dataset(**args)
    assert result['status'] == 'PUBLISHED_CONTENT_NOT_ADMITTED', result
    assert result['training_admission'] is False and result['training_dataset_qualified'] is False
    published = Path(result['dataset_path']); manifest = json.loads((published / 'manifest.json').read_bytes())
    assert content_sha(published) == result['dataset_revision']
    assert {f['split'] for f in manifest['frames']} == {'train', 'val'}
    for i, frame in enumerate(manifest['frames']):
        assert frame['session'] == authority['frames'][i]['source_session']
        assert (published / frame['image']).read_bytes() == (args['export_root'] / f'inputs/images/{i:06d}.png').read_bytes()
        assert (published / frame['mask']).read_bytes() == (args['export_root'] / f'pixel-masks/{i:06d}.png').read_bytes()
        source = manifest['sources'][i]
        assert source['annotation_origin'] == 'human_reviewed_pinky_indexed'
        assert source['producer_original_video_verified'] is False and source['independent_source_pixels_verified'] is True
    assert not list(published.rglob('READY'))
    repeated = target.build_dataset(**args)
    assert repeated['dataset_revision'] == result['dataset_revision']


@pytest.mark.parametrize('change', ['video', 'proof', 'omitted_eval', 'missing_proof'])
def test_source_or_eval_binding_blocker_never_publishes(tmp_path, change):
    args, _ = build_fixture(tmp_path)
    if change == 'video': (tmp_path / 'video0.avi').write_bytes(b'wrong video')
    if change == 'proof':
        path = args['source_proof_files'][0]; proof = json.loads(path.read_bytes()); proof['capture_group'] = 'wrong'
        path.write_text(json.dumps(proof))
    if change == 'omitted_eval': args['eval_folders'] = []
    if change == 'missing_proof': args['source_proof_files'] = args['source_proof_files'][1:]
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and result['training_admission'] is False
    assert not args['store'].datasets_dir.exists()


def test_postpublish_revocation(tmp_path):
    args, authority = build_fixture(tmp_path)
    next_authority = copy.deepcopy(authority); next_authority['generation'] = 2; next_authority = digest(next_authority)
    values = iter([delivery(authority), delivery(authority), delivery(next_authority)])
    args['fetch_current'] = lambda: next(values)
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and result['training_admission'] is False
    assert result['published_content_exists'] is True and Path(result['dataset_path']).is_dir()
    assert 'after immutable publication' in result['blockers'][0]
    assert not list(args['store'].root.rglob('READY'))


def test_one_capture_component_holds(tmp_path):
    args, _ = build_fixture(tmp_path, shared_group=True)
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and 'two disconnected' in result['blockers'][0]
    assert not args['store'].datasets_dir.exists()


def test_eval_missing_frame_identity_holds(tmp_path):
    from dataset.build import content_sha
    args, _ = build_fixture(tmp_path)
    root = args['eval_folders'][0]; doc = json.loads((root / 'manifest.json').read_bytes())
    doc['frames'][0].pop('video_frame'); (root / 'manifest.json').write_text(json.dumps(doc))
    new_root = root.with_name(content_sha(root)); root.rename(new_root)
    args['eval_folders'] = [new_root]
    args['gate_eval_refs'] = [dict(name='held', content_sha=new_root.name)]
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and 'inventory incomplete' in result['blockers'][0]
    assert not args['staging_parent'].exists() and not args['store'].datasets_dir.exists()


def test_gate_pinned_ref_cannot_be_omitted(tmp_path):
    args, _ = build_fixture(tmp_path)
    args['gate_eval_refs'] = [dict(name='held', content_sha='a' * 64)]
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and 'inventory incomplete' in result['blockers'][0]
    assert not args['store'].datasets_dir.exists()


@pytest.mark.parametrize('side_fields', [dict(sidecar_path='missing'), dict(sidecar_sha256='a' * 64),
                                      dict(sidecar_path='missing', sidecar_sha256=True)])
def test_sidecar_proof_pair_is_strict(tmp_path, side_fields):
    args, _ = build_fixture(tmp_path)
    (tmp_path / 'missing').write_bytes(b'sidecar bytes')
    path = args['source_proof_files'][0]; doc = json.loads(path.read_bytes()); doc.update(side_fields)
    path.write_text(json.dumps(doc))
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and not args['store'].datasets_dir.exists()


def test_decoded_source_pixels_are_exact(tmp_path):
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    args, _ = build_fixture(tmp_path); proofs, _ = target._capture_proofs(args['source_proof_files'])
    proof = next(iter(proofs.values()))
    ok, wrong = cv2.imencode('.png', np.full((16, 16, 3), 41, np.uint8)); assert ok
    with pytest.raises(ValueError, match='pixels differ'):
        target._video_pixels(proof, 0, wrong.tobytes(), tmp_path)
    ok, jpeg = cv2.imencode('.jpg', np.full((16, 16, 3), 40, np.uint8)); assert ok
    with pytest.raises(ValueError, match='JPEG conversion'):
        target._video_pixels(proof, 0, jpeg.tobytes(), tmp_path)


def test_source_changes_during_decode_holds(tmp_path, monkeypatch):
    args, _ = build_fixture(tmp_path); decode = target._verify_video_requests
    def changing(*params):
        result = decode(*params)
        (tmp_path / 'video0.avi').write_bytes(b'changed after immutable decode')
        return result
    monkeypatch.setattr(target, '_verify_video_requests', changing)
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and 'changed before publication' in result['blockers'][0]
    assert not args['store'].datasets_dir.exists()


def test_prepublication_revocation_creates_no_dataset(tmp_path):
    args, authority = build_fixture(tmp_path)
    changed = copy.deepcopy(authority); changed['generation'] = 2; changed = digest(changed)
    values = iter([delivery(authority), delivery(changed)])
    args['fetch_current'] = lambda: next(values)
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and 'before publication' in result['blockers'][0]
    assert not args['store'].datasets_dir.exists()


def test_video_decode_is_one_sequential_pass(tmp_path, monkeypatch):
    cv2 = pytest.importorskip('cv2')
    args, _ = build_fixture(tmp_path); proofs, _ = target._capture_proofs(args['source_proof_files'])
    proof = next(iter(proofs.values()))
    raw = (args['export_root'] / 'inputs/images/000000.png').read_bytes()
    original = cv2.VideoCapture; counts = dict(opens=0, reads=0)
    class Reader:
        def __init__(self, path):
            counts['opens'] += 1; self.reader = original(path)
        def read(self):
            counts['reads'] += 1; return self.reader.read()
        def release(self): self.reader.release()
    monkeypatch.setattr(cv2, 'VideoCapture', Reader)
    np = pytest.importorskip('numpy')
    ok, frame2 = cv2.imencode('.png', np.full((16, 16, 3), 42, np.uint8)); assert ok
    target._verify_video_requests([(proof, 0, raw), (proof, 2, frame2.tobytes()), (proof, 2, frame2.tobytes())], tmp_path)
    assert counts == dict(opens=1, reads=3)


def test_proof_path_traversal_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='traversal'):
        target._proof_path('../video.avi', tmp_path / 'proof.json')
    with pytest.raises(ValueError, match='traversal'):
        target._proof_path(str(tmp_path / '..' / 'video.avi'), tmp_path / 'proof.json')


def test_eval_whole_video_identity_blocks_other_frame(tmp_path):
    from dataset.build import content_sha
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    args, authority = build_fixture(tmp_path)
    root = args['eval_folders'][0]; doc = json.loads((root / 'manifest.json').read_bytes())
    doc['frames'][0]['source_video_sha256'] = authority['frames'][0]['source_video_sha256']
    doc['frames'][0]['video_frame'] = 2
    ok, pixels = cv2.imencode('.png', np.full((16, 16, 3), 42, np.uint8)); assert ok
    (root / 'image.png').write_bytes(pixels.tobytes()); (root / 'manifest.json').write_text(json.dumps(doc))
    new_root = root.with_name(content_sha(root)); root.rename(new_root)
    args['eval_folders'] = [new_root]; args['gate_eval_refs'] = [dict(name='held', content_sha=new_root.name)]
    path = args['source_proof_files'][2]; proof = json.loads(path.read_bytes())
    proof.update(video_path=str(tmp_path / 'video0.avi'), video_sha256=authority['frames'][0]['source_video_sha256'])
    path.write_text(json.dumps(proof))
    diagnostic = target.inspect_candidates(args['export_root'], fetch_current=args['fetch_current'],
        workspace_id=args['workspace_id'], eval_folders=args['eval_folders'], now=args['now'])
    assert 'fixed_eval_overlap' in diagnostic['frames'][0]['blockers']
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and 'overlaps fixed evaluation' in result['blockers'][0]
    assert not args['store'].datasets_dir.exists()


def test_windows_outside_scratch_root_holds(tmp_path):
    import os
    if os.name != 'nt': pytest.skip('Windows drive/root contract')
    args, _ = build_fixture(tmp_path)
    forbidden = Path('X:/pinky-build-forbidden-test')
    assert not forbidden.exists()
    args['staging_parent'] = forbidden
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and 'within X:/DevTemp' in result['blockers'][0]
    assert not forbidden.exists() and not args['store'].datasets_dir.exists()


def test_publish_then_raise_does_not_claim_rollback(tmp_path, monkeypatch):
    args, _ = build_fixture(tmp_path); put = args['store'].put_dataset; published = []
    def failing(src, name):
        path, sha = put(src, name); published.append(path)
        raise OSError('raised after immutable rename')
    monkeypatch.setattr(args['store'], 'put_dataset', failing)
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and result['training_admission'] is False
    assert published[0].is_dir() and 'raised after immutable rename' in result['blockers'][0]
    assert 'rollback' not in result and 'no_artifact' not in result


def test_windows_junction_staging_holds(tmp_path):
    import os
    import subprocess
    if os.name != 'nt': pytest.skip('Windows junction contract')
    args, _ = build_fixture(tmp_path)
    destination = tmp_path / 'target'; destination.mkdir()
    junction = tmp_path / 'junction'
    created = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(destination)], capture_output=True)
    if created.returncode: pytest.skip('host cannot create test junction')
    assert junction.is_junction()
    args['staging_parent'] = junction / 'scratch'
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and 'links refused' in result['blockers'][0]
    assert not (destination / 'scratch').exists() and not args['store'].datasets_dir.exists()


@pytest.mark.parametrize('invent_alias_identity', [False, True])
def test_duplicate_approved_source_frame_holds_before_staging(tmp_path, invent_alias_identity):
    from review_authority import validate_current
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    args, authority = build_fixture(tmp_path)
    proofs, _ = target._capture_proofs(args['source_proof_files'])
    original = authority['frames'][0]
    source_proof = proofs[(original['source_session'], original['capture_group'], original['source_video_sha256'])]
    raw = (args['export_root'] / 'inputs/images/000000.png').read_bytes()
    pixels = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    ok, alternate = cv2.imencode('.png', pixels, [cv2.IMWRITE_PNG_COMPRESSION, 9]); assert ok
    alternate_raw = alternate.tobytes(); assert alternate_raw != raw
    scratch = tmp_path / 'pixel-proof'; scratch.mkdir()
    target._video_pixels(source_proof, 0, raw, scratch)
    target._video_pixels(source_proof, 0, alternate_raw, scratch)
    # Preserve a third distinct source component and independent per-row decisions.
    third = copy.deepcopy(authority['frames'][1]); third.update(frame=2, review_uid=args['workspace_id'] + ':2')
    alias = copy.deepcopy(original)
    alias.update(frame=1, review_uid=args['workspace_id'] + ':1', source_session='operator-alias-session',
                 capture_group='operator-alias-group', image_sha256=hashlib.sha256(alternate_raw).hexdigest())
    ok, contradictory = cv2.imencode('.png', np.zeros((16, 16), np.uint8)); assert ok
    alias['mask_sha256'] = hashlib.sha256(contradictory.tobytes()).hexdigest()
    alias['pixel_approval'].update(image_sha256=alias['image_sha256'], mask_sha256=alias['mask_sha256'])
    if invent_alias_identity:
        alias['identity'] = 'legacy:1:' + alias['image_sha256']
    modified = copy.deepcopy(authority); modified['frames'] = [original, alias, third]; modified = digest(modified)
    expected = 'source identity binding differs' if invent_alias_identity else 'duplicate frame identity or UID'
    with pytest.raises(ValueError, match=expected): validate_current(modified)
    args['fetch_current'] = lambda: delivery(modified)
    result = target.build_dataset(**args)
    assert result['status'] == 'HOLD' and expected in result['blockers'][0]
    assert result['training_admission'] is False
    assert not args['staging_parent'].exists() and not args['store'].datasets_dir.exists()
