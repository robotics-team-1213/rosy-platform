"""MCAP review imports keep source identity and never inherit video decisions."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcap_ros2")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
from review_app import ReviewStore, Conflict  # noqa: E402
import review_evidence  # noqa: E402
import review_ingest  # noqa: E402
import review_masks  # noqa: E402
import review_eval_bootstrap  # noqa: E402
from test_mcap_proof import _fixture  # noqa: E402
from mcap_proof import prove_frames  # noqa: E402
from test_review_cycle import CLASSES  # noqa: E402
from test_review_app import open_store  # noqa: E402


def _catalog(tmp_path):
    session, row = _fixture(tmp_path)
    proof = prove_frames(session, [row], tmp_path)
    folder = tmp_path / "catalog"
    folder.mkdir()
    classes = folder / "classes.yaml"
    classes.write_bytes(CLASSES)
    catalog = folder / "verified-inputs.jsonl"
    catalog.write_text(json.dumps({"source_kind": "mcap", "source_session": session.name,
                                   "capture_group": "heldout-group", "fixed_eval_overlap": True,
                                   "image": str(row["image"]),
                                   "image_sha256": hashlib.sha256(row["image"].read_bytes()).hexdigest(),
                                   "width": 6, "height": 4,
                                    "mcap": {"session_dir": str(session),
                                            "metadata_sha256": proof["metadata_sha256"],
                                            "bags": proof["bags"], "decoder": proof["decoder"],
                                            "frame": proof["frames"][0]}}) + "\n")
    return catalog, classes


def test_empty_eval_workspace_imports_only_proven_mcap_as_pending(tmp_path):
    store = ReviewStore(tmp_path / "eval-state", empty_eval=True)
    catalog, classes = _catalog(tmp_path)
    body = {"path": str(catalog), "classes": str(classes)}
    result = review_ingest.import_frames(store, body)
    assert result["added"] == 1
    frame = store.get(0)
    assert frame["status"] == "pending" and frame["source"]["source_kind"] == "mcap"
    assert frame["source"]["mcap"]["frame"]["header_stamp_ns"] == 1_000_000_123
    assert review_evidence.identity(frame["source"]).startswith("mcap:")
    assert review_ingest.import_frames(store, body)["added"] == 0
    assert len(store.list_frames()) == 1


def test_mcap_import_rejects_changed_bag_before_workspace_mutation(tmp_path):
    store = ReviewStore(tmp_path / "eval-state", empty_eval=True)
    catalog, classes = _catalog(tmp_path)
    source = tmp_path / "session" / "bag" / "bag_2.mcap"
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="bag hash"):
        review_ingest.import_frames(store, {"path": str(catalog), "classes": str(classes),
                                            "scratch": str(tmp_path)})
    assert store.list_frames() == []


def test_mcap_identity_never_links_same_pixels_to_video_workspace(tmp_path):
    (tmp_path / "video").mkdir()
    video_store = open_store(tmp_path / "video")
    catalog, classes = _catalog(tmp_path)
    with pytest.raises(ValueError, match="separate evaluation workspace"):
        review_ingest.import_frames(video_store, {"path": str(catalog), "classes": str(classes),
                                                  "scratch": str(tmp_path)})
    assert len(video_store.list_frames()) == 2


def test_mcap_ambiguous_log_time_requires_message_ordinal(tmp_path):
    session, row = _fixture(tmp_path, duplicate=True)
    with pytest.raises(ValueError, match="ambiguous"):
        prove_frames(session, [row], tmp_path)
    proof = prove_frames(session, [{**row, "message_ordinal": 0}], tmp_path)
    assert proof["frames"][0]["message_ordinal"] == 0


def test_mcap_import_refuses_auto_mask_draft(tmp_path):
    store = ReviewStore(tmp_path / "eval-state", empty_eval=True)
    catalog, classes = _catalog(tmp_path)
    row = json.loads(catalog.read_text())
    row["mask"] = {"indexed_png": "auto.png", "sha256": "0" * 64,
                   "classes_sha256": "0" * 64}
    catalog.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="empty pixel mask"):
        review_ingest.import_frames(store, {"path": str(catalog), "classes": str(classes)})
    assert store.list_frames() == []


def test_eval_workspace_can_approve_pixels_but_cannot_export_training(tmp_path):
    store = ReviewStore(tmp_path / "eval-state", empty_eval=True)
    catalog, classes = _catalog(tmp_path)
    review_ingest.import_frames(store, {"path": str(catalog), "classes": str(classes)})
    painted = review_masks.update(store, 0, {"version": 1, "action": "fill", "label": 0}, Conflict)
    approved = review_masks.update(store, 0, {"version": painted["version"],
                                               "action": "approve", "complete_frame_review": True,
                                               "background_reviewed": True}, Conflict)
    assert approved["status"] == "approved"
    assert review_evidence.validate_authority(review_evidence.decisions(store))
    with pytest.raises(ValueError, match="cannot export training"):
        store.prepare()


def test_eval_unknown_pixels_need_explicit_review_and_exact_count(tmp_path):
    store = ReviewStore(tmp_path / "eval-state", empty_eval=True)
    catalog, classes = _catalog(tmp_path)
    review_ingest.import_frames(store, {"path": str(catalog), "classes": str(classes)})
    with pytest.raises(ValueError, match="가림"):
        review_masks.update(store, 0, {"version": 1, "action": "approve",
                                       "complete_frame_review": True, "background_reviewed": True,
                                       "unknown_pixels_reviewed": True}, Conflict)
    painted = review_masks.update(store, 0, {"version": 1, "action": "fill", "label": 0}, Conflict)
    masked = review_masks.update(store, 0, {"version": painted["version"], "action": "paint",
                                             "label": 255, "radius": 1, "points": [[2, 2]]}, Conflict)
    body = {"version": masked["version"], "action": "approve",
            "complete_frame_review": True, "background_reviewed": True}
    with pytest.raises(ValueError, match="가림"):
        review_masks.update(store, 0, body, Conflict)
    approved = review_masks.update(store, 0, {**body, "unknown_pixels_reviewed": True}, Conflict)
    count = int((review_masks.pixels(store, approved) == 255).sum())
    assert count > 0
    assert approved["approval"]["reviewed_unknown_count"] == count
    current = review_evidence.decisions(store)
    assert review_evidence.validate_authority(current)
    current["frames"][0]["pixel_approval"]["reviewed_unknown_count"] = True
    current["decision_sha256"] = review_evidence.sha(review_evidence.encoded(
        {key: value for key, value in current.items() if key != "decision_sha256"}))
    with pytest.raises(ValueError, match="approval"):
        review_evidence.validate_authority(current)
    with pytest.raises(ValueError, match="cannot export training"):
        store.prepare()


def test_eval_bootstrap_reserves_before_import_and_replays_without_new_frames(tmp_path):
    catalog, classes = _catalog(tmp_path)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    kwargs = {'catalog_sha256': digest(catalog), 'classes_sha256': digest(classes)}
    root, state = tmp_path / 'store', tmp_path / 'eval-state'
    result = review_eval_bootstrap.start(root, state, catalog, classes, **kwargs)
    assert result['frames'] == result['added'] == 1
    from store import Store
    assert Store(root).eval_reservations() == {'session': 'heldout-group'}
    assert review_eval_bootstrap.start(root, state, catalog, classes, **kwargs)['added'] == 0
    assert ReviewStore(state).get(0)['status'] == 'pending'


def test_eval_readiness_requires_current_approved_mask_and_reproved_mcap(tmp_path):
    catalog, classes = _catalog(tmp_path)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    root, state = tmp_path / 'store', tmp_path / 'eval-state'
    review_eval_bootstrap.start(root, state, catalog, classes,
                                catalog_sha256=digest(catalog), classes_sha256=digest(classes))
    with pytest.raises(ValueError, match='approved'):
        review_eval_bootstrap.ready(root, state, tmp_path)
    review = ReviewStore(state)
    painted = review_masks.update(review, 0, {'version': 1, 'action': 'fill', 'label': 0}, Conflict)
    review_masks.update(review, 0, {'version': painted['version'], 'action': 'approve',
                                    'complete_frame_review': True, 'background_reviewed': True}, Conflict)
    result = review_eval_bootstrap.ready(root, state, tmp_path)
    assert result['frames'] == 1 and result['sessions'] == {'session': 'heldout-group'}
    class_file = state / 'pixel' / (digest(classes) + '.yaml')
    class_file.write_bytes(b'changed')
    with pytest.raises(ValueError, match='class file changed'):
        review_eval_bootstrap.ready(root, state, tmp_path)
    class_file.write_bytes(classes.read_bytes())
    source = review.get(0)['source']
    bag = Path(source['mcap']['session_dir']) / 'bag' / 'bag_2.mcap'
    bag.write_bytes(bag.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='bag hash'):
        review_eval_bootstrap.ready(root, state, tmp_path)


def test_human_eval_publication_is_immutable_and_keeps_reviewed_unknown(tmp_path):
    catalog, classes = _catalog(tmp_path)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    root, state = tmp_path / 'store', tmp_path / 'eval-state'
    review_eval_bootstrap.start(root, state, catalog, classes,
                                catalog_sha256=digest(catalog), classes_sha256=digest(classes))
    with pytest.raises(ValueError, match='approved'):
        review_eval_bootstrap.publish(root, state, 'heldout', tmp_path)
    assert not (root / 'evalsets').exists()
    review = ReviewStore(state)
    painted = review_masks.update(review, 0, {'version': 1, 'action': 'fill', 'label': 0}, Conflict)
    masked = review_masks.update(review, 0, {'version': painted['version'], 'action': 'paint',
                                             'label': 255, 'radius': 1, 'points': [[2, 2]]}, Conflict)
    review_masks.update(review, 0, {'version': masked['version'], 'action': 'approve',
                                    'complete_frame_review': True, 'background_reviewed': True,
                                    'unknown_pixels_reviewed': True}, Conflict)
    result = review_eval_bootstrap.publish(root, state, 'heldout', tmp_path)
    from dataset.build import read_eval_set
    folder = Path(result['path'])
    assert folder.parent.name == 'heldout-human'
    assert read_eval_set(folder)[1] == {'session'}
    manifest = json.loads((folder / 'manifest.json').read_text())
    row = manifest['frames'][0]
    assert row['sources'] == ['human_reviewed_eval'] and row['source_kind'] == 'mcap'
    assert row['reviewed_unknown_count'] > 0
    assert review_eval_bootstrap.publish(root, state, 'heldout', tmp_path)['path'] == str(folder)
    (folder / row['mask']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='immutable'):
        review_eval_bootstrap.publish(root, state, 'heldout', tmp_path)


def test_human_eval_mcap_companion_reproves_source_and_never_admits(tmp_path):
    catalog, classes = _catalog(tmp_path)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    root, state = tmp_path / 'store', tmp_path / 'eval-state'
    review_eval_bootstrap.start(root, state, catalog, classes,
                                catalog_sha256=digest(catalog), classes_sha256=digest(classes))
    review = ReviewStore(state)
    painted = review_masks.update(review, 0, {'version': 1, 'action': 'fill', 'label': 0}, Conflict)
    review_masks.update(review, 0, {'version': painted['version'], 'action': 'approve',
                                    'complete_frame_review': True, 'background_reviewed': True}, Conflict)
    eval_dir = Path(review_eval_bootstrap.publish(root, state, 'heldout', tmp_path)['path'])
    from review_eval_package import package_mcap_eval_companion
    from review_dataset import _eval_inventory, validate_eval_companions
    assert _eval_inventory([eval_dir])[-1] is True
    with pytest.raises(ValueError, match='all active'):
        validate_eval_companions([eval_dir], [])
    bundle = tmp_path / 'mcap-companion'
    package_mcap_eval_companion(eval_dir, bundle)
    captured = validate_eval_companions([eval_dir], [bundle])
    assert captured['training_admission'] is False
    assert captured['frames'][0]['source_kind'] == 'mcap'
    assert captured['frames'][0]['decoded_mcap_pixels_verified'] is True
    from test_review_dataset import companion_fixture
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    old_eval, old_bundle, _ = companion_fixture(legacy)
    mixed = validate_eval_companions([old_eval, eval_dir], [bundle, old_bundle])
    assert len(mixed['frames']) == 2 and 'eval_decoded_pixels_unverified' in mixed['blockers']
    receipt = json.loads((bundle / 'manifest.json').read_text())
    receipt['eval_ref']['content_sha'] = '0' * 64
    raw = json.dumps(receipt, sort_keys=True).encode()
    (bundle / 'manifest.json').write_bytes(raw)
    (bundle / 'COMPLETE').write_text(hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='unknown or duplicate'):
        validate_eval_companions([eval_dir], [bundle])
    receipt['eval_ref']['content_sha'] = eval_dir.name
    raw = json.dumps(receipt, sort_keys=True).encode()
    (bundle / 'manifest.json').write_bytes(raw)
    (bundle / 'COMPLETE').write_text(hashlib.sha256(raw).hexdigest())
    bag = Path(review.get(0)['source']['mcap']['session_dir']) / 'bag' / 'bag_2.mcap'
    bag.write_bytes(bag.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='bag hash'):
        validate_eval_companions([eval_dir], [bundle])


def test_training_builder_keeps_human_mcap_eval_disjoint_and_unadmitted(tmp_path, monkeypatch):
    from test_review_dataset import attach_build_companion, build_fixture
    from review_eval_package import package_mcap_eval_companion
    import review_dataset
    from review_dataset import build_dataset
    args, _ = build_fixture(tmp_path)
    attach_build_companion(args, tmp_path)
    catalog, classes = _catalog(tmp_path)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    state = tmp_path / 'eval-state'
    review_eval_bootstrap.start(args['store'].root, state, catalog, classes,
                                catalog_sha256=digest(catalog), classes_sha256=digest(classes))
    review = ReviewStore(state)
    painted = review_masks.update(review, 0, {'version': 1, 'action': 'fill', 'label': 0}, Conflict)
    review_masks.update(review, 0, {'version': painted['version'], 'action': 'approve',
                                    'complete_frame_review': True, 'background_reviewed': True}, Conflict)
    human = Path(review_eval_bootstrap.publish(args['store'].root, state, 'heldout', tmp_path)['path'])
    companion = tmp_path / 'human-companion'
    package_mcap_eval_companion(human, companion)
    args['eval_folders'].append(human)
    args['gate_eval_refs'].append({'name': human.parent.name, 'content_sha': human.name})
    denied = build_dataset(**args)
    assert denied['status'] == 'HOLD' and 'all active' in denied['blockers'][0]
    assert args['store'].datasets() == {}
    args['eval_companion_files'].append(companion)
    bag = Path(review.get(0)['source']['mcap']['session_dir']) / 'bag' / 'bag_2.mcap'
    original_bag = bag.read_bytes()
    original_verify = review_dataset._verify_video_requests
    def change_source(requests, scratch):
        original_verify(requests, scratch)
        bag.write_bytes(original_bag + b'changed')
    monkeypatch.setattr(review_dataset, '_verify_video_requests', change_source)
    denied = build_dataset(**args)
    assert denied['status'] == 'HOLD' and 'MCAP source changed' in denied['blockers'][0]
    assert args['store'].datasets() == {}
    bag.write_bytes(original_bag)
    monkeypatch.setattr(review_dataset, '_verify_video_requests', original_verify)
    result = build_dataset(**args)
    assert result['status'] == 'PUBLISHED_CONTENT_NOT_ADMITTED', result
    assert result['training_admission'] is False
    assert {r['name'] for r in json.loads((Path(result['dataset_path']) / 'manifest.json').read_text())['disjoint_from']} == {'held', 'heldout-human'}
