"""Incremental pending import, independent masks and current export authority."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from contextlib import contextmanager

from test_review_app import open_store
from review_app import ReviewStore, Conflict
import review_evidence
import review_ingest
import review_masks


CLASSES = b'''classes:
- {index: 0, name: floor, role: background, color: [90, 90, 90]}
- {index: 1, name: lane_line, role: lane_marking, color: [255, 255, 255]}
- {index: 2, name: wall, role: wall, color: [220, 60, 60]}
- {index: 3, name: drivable, role: drivable, color: [60, 200, 60]}
- {index: 4, name: stop_line, role: stop_line, color: [250, 200, 0]}
- {index: 5, name: crosswalk, role: ignore, color: [0, 160, 255]}
'''


def catalog(tmp_path):
    folder = tmp_path / 'catalog'
    folder.mkdir()
    classes = folder / 'classes.yaml'
    classes.write_bytes(CLASSES)
    rows = []
    for suffix in ('.jpg', '.png'):
        raw = cv2.imencode(suffix, np.full((24, 32, 3), 100, dtype=np.uint8))[1].tobytes()
        image = folder / ('same-frame' + suffix)
        image.write_bytes(raw)
        rows.append({'image': str(image), 'image_sha256': hashlib.sha256(raw).hexdigest(),
                     'width': 32, 'height': 24, 'source_video_sha256': '1' * 64,
                     'source_video': 'teleop_bot_20260930T171014Z.mp4', 'video_frame': 9,
                     'source_session': 'declared-alias' + suffix, 'capture_group': 'group-1',
                     'fixed_eval_overlap': False, 'pixel_gt_approved': True})
    (folder / 'verified-inputs.jsonl').write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    return folder, classes, rows


def test_import_deduplicates_source_frames_and_preserves_all_old_reviews(tmp_path):
    store = open_store(tmp_path)
    before = store.list_frames()
    folder, classes, _ = catalog(tmp_path)
    result = review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    assert result['added'] == 1 and result['duplicate_representations'] == 1
    assert store.list_frames()[:2] == before
    assert store.get(2)['status'] == 'pending'
    assert review_masks.get(store, 2)['status'] == 'pending'
    assert np.all(review_masks.pixels(store, review_masks.get(store, 2)) == 255)
    current = review_evidence.decisions(store)
    assert review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})['added'] == 0
    assert review_evidence.decisions(store) == current
    assert ReviewStore(store.state).list_frames()[:2] == before


def test_invalid_import_never_changes_legacy_or_adds_partial_frames(tmp_path):
    store = open_store(tmp_path)
    before = store.list_frames()
    folder, classes, rows = catalog(tmp_path)
    Path(rows[-1]['image']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash'):
        review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    assert store.list_frames() == before


def test_exact_legacy_primary_binding_keeps_human_decision_and_original_bytes(tmp_path):
    store = open_store(tmp_path)
    folder, classes, rows = catalog(tmp_path)
    old = store.get(0)
    source = dict(old['source'], video='teleop_bot_20260930T171014Z.mp4', video_frame=9)
    with store.connect() as db:
        db.execute('UPDATE frames SET source=? WHERE id=0', (json.dumps(source),))
    raw = store.image(0).read_bytes()
    Path(rows[0]['image']).write_bytes(raw)
    rows[0]['image_sha256'] = hashlib.sha256(raw).hexdigest()
    (folder/'verified-inputs.jsonl').write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    result = review_ingest.import_frames(store, {'path':str(folder), 'classes':str(classes)})
    after = store.get(0)
    assert result['added'] == 0 and result['legacy_primary_bindings'] == 1
    assert len(store.list_frames()) == 2 and store.image(0).read_bytes() == raw
    assert (after['review'], after['status'], after['version']) == (old['review'], old['status'], old['version'])
    assert after['source']['legacy_source'] == source
    assert after['source']['image'] == source['image']
    assert after['source']['original_video_verified'] is False
    assert review_masks.get(store,0)['status'] == 'pending'
    current = review_evidence.decisions(store)
    assert current['frames'][0]['identity'] == 'video:' + '1'*64 + ':9'
    assert review_ingest.import_frames(store, {'path':str(folder), 'classes':str(classes)})['added'] == 0
    assert review_evidence.decisions(store) == current


def test_mask_requires_full_background_review_and_never_restores_object_approval(tmp_path):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    before = store.get(0)
    with pytest.raises(ValueError, match='미검수'):
        review_masks.update(store, 0, {'version':0, 'action':'approve',
                                      'complete_frame_review':True, 'background_reviewed':True}, Conflict)
    painted = review_masks.update(store, 0, {'version':0, 'action':'fill', 'label':0}, Conflict)
    with pytest.raises(ValueError, match='각각'):
        review_masks.update(store, 0, {'version':painted['version'], 'action':'approve',
                                      'complete_frame_review':True}, Conflict)
    approved = review_masks.update(store, 0, {'version':painted['version'], 'action':'approve',
                                            'complete_frame_review':True, 'background_reviewed':True}, Conflict)
    assert approved['status'] == 'approved'
    changed = review_masks.update(store, 0, {'version':approved['version'], 'action':'paint',
                                           'label':4, 'radius':2, 'points':[[8,9],[15,9]]}, Conflict)
    assert changed['status'] == 'pending'
    assert store.get(0) == before
    undo = review_masks.update(store, 0, {'version':changed['version'], 'action':'undo'}, Conflict)
    assert undo['status'] == 'pending' and np.all(review_masks.pixels(store, undo) == 0)
    with pytest.raises(Conflict):
        review_masks.update(store, 0, {'version':changed['version'], 'action':'fill', 'label':0}, Conflict)
    with pytest.raises(ValueError, match='제외'):
        review_masks.update(store, 1, {'version':0, 'action':'fill', 'label':0}, Conflict)


def test_old_complete_export_cannot_resurrect_excluded_or_changed_frame(tmp_path):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    mask = review_masks.update(store, 0, {'version':0, 'action':'fill', 'label':0}, Conflict)
    review_masks.update(store, 0, {'version':mask['version'], 'action':'approve',
                                 'complete_frame_review':True, 'background_reviewed':True}, Conflict)
    receipt = store.prepare()
    doc = review_evidence.verify_current(receipt['path'], review_evidence.decisions(store))
    assert doc['pixel_approved_frames'] == 1
    assert doc['authority']['frames'][1]['object_decision'] == 'excluded'
    store.update(0, {'version':1, 'action':'exclude'})
    with pytest.raises(ValueError, match='stale'):
        review_evidence.verify_current(receipt['path'], review_evidence.decisions(store))
    newer = store.prepare()
    assert review_evidence.verify_current(newer['path'], review_evidence.decisions(store))['pixel_approved_frames'] == 0
    target = Path(newer['path']) / 'application-snapshot.json'
    target.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='changed'):
        review_evidence.verify_current(newer['path'], review_evidence.decisions(store))


def test_snapshot_remains_coherent_when_second_store_commits_between_reads(tmp_path):
    store = open_store(tmp_path)
    actor = ReviewStore(store.state)
    with store.connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
    original = store.connect
    changed = []

    @contextmanager
    def interleaved():
        with original() as db:
            def trace(sql):
                if sql == 'SELECT * FROM masks' and not changed:
                    changed.append(True)
                    actor.update(0, {'version': 1, 'action': 'exclude'})
            db.set_trace_callback(trace)
            yield db
    store.connect = interleaved
    old = review_evidence.decisions(store)
    store.connect = original
    live = review_evidence.decisions(actor)
    assert changed and old['generation'] == 1 and live['generation'] == 2
    assert old['frames'][0]['object_decision'] == 'approved'
    assert live['frames'][0]['object_decision'] == 'excluded'


def test_export_uses_captured_revision_even_if_writer_changes_during_sealing(tmp_path, monkeypatch):
    store = open_store(tmp_path)
    actor = ReviewStore(store.state)
    original = review_evidence.seal_export
    def interleave(owner, out, receipt, captured):
        actor.update(0, {'version': 1, 'action': 'exclude'})
        return original(owner, out, receipt, captured)
    monkeypatch.setattr(review_evidence, 'seal_export', interleave)
    receipt = store.prepare()
    old = receipt['authority']
    assert review_evidence.verify_current(receipt['path'], old)['authority']['generation'] == 1
    with pytest.raises(ValueError, match='stale'):
        review_evidence.verify_current(receipt['path'], review_evidence.decisions(actor))


def test_resealed_bundle_cannot_hide_missing_sources_or_duplicate_paths(tmp_path):
    store = open_store(tmp_path)
    current = review_evidence.decisions(store)
    out = Path(store.prepare()['path'])
    contract = out / 'review-contract.json'
    original = json.loads(contract.read_bytes())
    def reseal(doc):
        raw = review_evidence.encoded(doc)
        contract.write_bytes(raw)
        (out / 'AUTHORITY_COMPLETE').write_text(review_evidence.sha(raw), encoding='ascii')
    doc = dict(original, files=original['files'] + [original['files'][0]])
    reseal(doc)
    with pytest.raises(ValueError, match='duplicate'):
        review_evidence.verify_current(out, current)
    doc = dict(original, files=[f for f in original['files'] if not f['path'].startswith('inputs/images/')])
    reseal(doc)
    with pytest.raises(ValueError, match='mandatory'):
        review_evidence.verify_current(out, current)
    reseal(original)
    invalid = dict(current, generation=True)
    with pytest.raises(ValueError, match='generation'):
        review_evidence.verify_current(out, invalid)
    invalid = dict(current, decision_sha256='0'*64)
    with pytest.raises(ValueError, match='digest'):
        review_evidence.verify_current(out, invalid)


def test_current_http_etag_detects_revocation_without_exporting_write_token(tmp_path):
    import threading
    import urllib.request
    import urllib.error
    from review_app import make_server
    store = open_store(tmp_path)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/api/decisions'
    try:
        with urllib.request.urlopen(url) as response:
            current, tag = json.load(response), response.headers['ETag']
        review_evidence.validate_authority(current)
        assert tag == '"' + current['decision_sha256'] + '"' and 'token' not in current
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(url, headers={'If-None-Match': tag}))
        assert error.value.code == 304
        store.update(0, {'version': 1, 'action': 'exclude'})
        with urllib.request.urlopen(urllib.request.Request(url, headers={'If-None-Match': tag})) as response:
            changed = json.load(response)
            assert response.status == 200 and response.headers['ETag'] != tag
        assert changed['frames'][0]['frame_excluded'] is True
        assert changed['generation'] == current['generation'] + 1
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_resealed_changed_object_box_cannot_pass_unchanged_live_content_binding(tmp_path):
    store = open_store(tmp_path)
    current = review_evidence.decisions(store)
    out = Path(store.prepare()['path'])
    frames = json.loads((out/'application-snapshot.json').read_bytes())
    frames[0]['review']['boxes'][0]['bbox_xyxy'][0] += 1
    (out/'application-snapshot.json').write_bytes(review_evidence.encoded(frames))
    (out/'inputs/human.jsonl').write_bytes(b''.join(review_evidence.encoded(review_evidence.human_review(f)) for f in frames))
    manifest = json.loads((out/'manifest.json').read_bytes())
    manifest['human_sha256'] = review_evidence.sha((out/'inputs/human.jsonl').read_bytes())
    for item in manifest['files']:
        raw = (out/item['path']).read_bytes()
        item.update(sha256=review_evidence.sha(raw), bytes=len(raw))
    raw = review_evidence.encoded(manifest)
    (out/'manifest.json').write_bytes(raw)
    (out/'COMPLETE').write_text(review_evidence.sha(raw), encoding='ascii')
    contract = json.loads((out/'review-contract.json').read_bytes())
    for item in contract['files']:
        raw = (out/item['path']).read_bytes()
        item.update(sha256=review_evidence.sha(raw), bytes=len(raw))
    raw = review_evidence.encoded(contract)
    (out/'review-contract.json').write_bytes(raw)
    (out/'AUTHORITY_COMPLETE').write_text(review_evidence.sha(raw), encoding='ascii')
    with pytest.raises(ValueError, match='frame snapshot differs'):
        review_evidence.verify_current(out, current)


@pytest.mark.parametrize('key,value',[('complete_frame_review',1),('width',32.0)])
def test_pixel_approval_rejects_equal_but_wrong_scalar_types(tmp_path,key,value):
    store = open_store(tmp_path)
    review_masks.bind_classes(store,CLASSES)
    review_masks.update(store,0,dict(version=0,action='fill',label=0),Conflict)
    review_masks.update(store,0,dict(version=1,action='approve',complete_frame_review=True,background_reviewed=True),Conflict)
    current = review_evidence.decisions(store)
    current['frames'][0]['pixel_approval'][key] = value
    del current['decision_sha256']
    current['decision_sha256'] = review_evidence.sha(review_evidence.encoded(current))
    with pytest.raises(ValueError,match='scalar type'):
        review_evidence.validate_authority(current)


def test_ignore_float_and_resealed_embedded_authority_fail_strict_validation(tmp_path):
    store = open_store(tmp_path)
    review_masks.bind_classes(store,CLASSES)
    current = review_evidence.decisions(store)
    invalid = dict(current, ignore_index=255.0)
    del invalid['decision_sha256']
    invalid['decision_sha256'] = review_evidence.sha(review_evidence.encoded(invalid))
    with pytest.raises(ValueError,match='ignore index'):
        review_evidence.validate_authority(invalid)
    out = Path(store.prepare()['path'])
    doc = json.loads((out/'review-contract.json').read_bytes())
    doc['authority']['frames'][0]['original_video_verified'] = 0
    raw = review_evidence.encoded(doc)
    (out/'review-contract.json').write_bytes(raw)
    (out/'AUTHORITY_COMPLETE').write_text(review_evidence.sha(raw),encoding='ascii')
    with pytest.raises(ValueError,match='digest'):
        review_evidence.verify_current(out,current)


@pytest.mark.parametrize('field',['frame_excluded','original_video_verified'])
@pytest.mark.parametrize('recompute_digest',[False,True])
def test_resealed_contract_authority_rejects_false_integer_alias(tmp_path,field,recompute_digest):
    store = open_store(tmp_path)
    review_masks.bind_classes(store,CLASSES)
    current = review_evidence.decisions(store)
    out = Path(store.prepare()['path'])
    doc = json.loads((out/'review-contract.json').read_bytes())
    assert doc['authority']['frames'][0][field] is False
    doc['authority']['frames'][0][field] = 0
    if recompute_digest:
        value = {k:v for k,v in doc['authority'].items() if k != 'decision_sha256'}
        doc['authority']['decision_sha256'] = review_evidence.sha(review_evidence.encoded(value))
    raw = review_evidence.encoded(doc)
    (out/'review-contract.json').write_bytes(raw)
    (out/'AUTHORITY_COMPLETE').write_text(review_evidence.sha(raw),encoding='ascii')
    with pytest.raises(ValueError):
        review_evidence.verify_current(out,current)


@pytest.mark.parametrize('field',['frame_excluded','original_video_verified'])
@pytest.mark.parametrize('recompute_digest',[False,True])
def test_resealed_receipt_authority_rejects_false_integer_alias(tmp_path,field,recompute_digest):
    store = open_store(tmp_path)
    current = review_evidence.decisions(store)
    out = Path(store.prepare()['path'])
    receipt = json.loads((out/'pinky-review-receipt.json').read_bytes())
    assert receipt['authority']['frames'][0][field] is False
    receipt['authority']['frames'][0][field] = 0
    if recompute_digest:
        authority = receipt['authority']
        del authority['decision_sha256']
        authority['decision_sha256'] = review_evidence.sha(review_evidence.encoded(authority))
    raw = review_evidence.encoded(receipt)
    (out/'pinky-review-receipt.json').write_bytes(raw)
    contract = json.loads((out/'review-contract.json').read_bytes())
    for item in contract['files']:
        if item['path']=='pinky-review-receipt.json':
            item.update(bytes=len(raw),sha256=review_evidence.sha(raw))
    raw = review_evidence.encoded(contract)
    (out/'review-contract.json').write_bytes(raw)
    (out/'AUTHORITY_COMPLETE').write_text(review_evidence.sha(raw),encoding='ascii')
    with pytest.raises(ValueError):
        review_evidence.verify_current(out,current)
