"""D-666 immutable replay bindings; synthetic approvals are not human acceptance."""
import json
from dataclasses import asdict
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
for holder in ("learning/registry/perception", "learning/curation/perception",
               "learning/evaluation/perception", "middleware/perception", "operations/world/src"):
    sys.path.insert(0, str(ROOT / holder))

import store
import review_evidence as review
import review_masks
import road_fitness_replay as replay
from test_road_fitness import CLASSES, _labels, _replay_model, _snapshots


def seal(folder):
    digest = store.content_sha(folder)
    target = folder.parent / digest
    folder.rename(target)
    return target


def dataset(root, name, semantic, mask, image_raw):
    folder = root / "evalsets" / name / "stage"
    folder.mkdir(parents=True)
    classes = [dict(c, color=[i * 20, 0, 0]) for i, c in enumerate(CLASSES)]
    classes[2]["semantic"] = semantic
    classes_raw = yaml.safe_dump({"classes": classes}).encode()
    (folder / "pixel-classes.yaml").write_bytes(classes_raw)
    (folder / "image.jpg").write_bytes(image_raw)
    cv2.imwrite(str(folder / "mask.png"), mask)
    image_sha, mask_sha = review.sha(image_raw), review.sha((folder / "mask.png").read_bytes())
    row = {"frame": 0, "review_uid": "a" * 32 + ":0", "identity": "mcap:eval-s:0",
           "width": 12, "height": 12, "object_version": 1, "mask_version": 1,
           "object_decision": "pending", "mask_decision": "approved", "frame_excluded": False,
           "image_sha256": image_sha, "mask_sha256": mask_sha,
           "representations_sha256": "b" * 64, "source_sha256": "c" * 64,
           "object_review_sha256": "d" * 64, "complete_frame_review": True, "background_reviewed": True,
           "original_video_verified": False, "source_video_sha256": None, "video_frame": None,
           "fixed_eval_overlap": True, "source_session": "eval-s", "capture_group": "eval-g",
           "map_revision": None, "map_pose": None}
    signature = review_masks.signature(classes)
    row["pixel_approval"] = {"image_sha256": image_sha, "mask_sha256": mask_sha, "mask_version": 1,
                             "width": 12, "height": 12, "classes_sha256": review.sha(classes_raw),
                             "classes_signature": signature, "ignore_index": 255,
                             "complete_frame_review": True, "background_reviewed": True}
    authority = {"schema": "rosy.pinky-review-decisions/1", "workspace_id": "a" * 32, "generation": 1,
                 "pixel_classes_sha256": review.sha(classes_raw), "classes_signature": signature,
                 "map_reference_sha256": None, "ignore_index": 255, "frames": [row]}
    authority["decision_sha256"] = review.sha(review.encoded(authority))
    review.validate_authority(authority)
    (folder / "authority.json").write_bytes(review.encoded(authority))
    frame = {"frame": 0, "identity": row["identity"], "session": "eval-s", "capture_group": "eval-g",
             "split": "eval", "image": "image.jpg", "mask": "mask.png", "image_sha256": image_sha,
             "mask_sha256": mask_sha, "mask_version": 1,
             "approval_sha256": review.sha(review.encoded(row["pixel_approval"])), "reviewed_unknown_count": 0}
    manifest = {"schema": "rosy.perception.dataset/1", "purpose": "eval", "ignore_index": 255,
                "classes": classes, "frames": [frame], "authority_sha256": authority["decision_sha256"],
                "classes_sha256": review.sha(classes_raw)}
    (folder / "manifest.json").write_bytes(review.encoded(manifest))
    return seal(folder)


def bundle(tmp_path, monkeypatch):
    root = tmp_path / "store"
    _, encoded = cv2.imencode(".jpg", np.zeros((12, 12, 3), np.uint8))
    road = dataset(root, "road", "road_surface/1", _labels().astype(np.uint8), encoded.tobytes())
    region_mask = _labels().astype(np.uint8)
    region_mask[:, 7:] = 0
    region = dataset(root, "region", "current_road_region/1", region_mask, encoded.tobytes())
    store.Store(root).reserve_eval_source("eval-s", "eval-g")
    train = root / "datasets" / "train" / "stage"
    train.mkdir(parents=True)
    _, train_image = cv2.imencode(".jpg", np.full((12, 12, 3), 40, np.uint8))
    (train / "image.jpg").write_bytes(train_image.tobytes())
    (train / "manifest.json").write_bytes(review.encoded({"classes": CLASSES,
        "frames": [{"session": "train-s", "capture_group": "train-g", "image": "image.jpg"}]}))
    train = seal(train)
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    model = _replay_model(model_dir)
    raw = json.loads((model_dir / "model_manifest.json").read_text())
    raw["dataset"] = {"repo": "store:train", "revision": train.name}
    (model_dir / "model_manifest.json").write_text(json.dumps(raw))
    from control.sensing.perception.learned.manifest import load_manifest
    model.manifest = load_manifest(model_dir)
    monkeypatch.setattr(replay.LaneSegModel, "open", lambda folder: model)
    image, anchor = _snapshots()
    def snapshot(value):
        row = asdict(value)
        row["received_at"] = value.received_at.isoformat()
        row["validity"] = value.validity.value
        row["evidence_refs"] = list(value.evidence_refs)
        return row
    inputs = tmp_path / "inputs" / "stage"
    inputs.mkdir(parents=True)
    doc = {"schema": "rosy.perception.region-inputs/1", "model_revision": model.model_revision,
           "road_eval_sha256": road.name, "region_eval_sha256": region.name,
           "preprocessing_sha256": review.sha(review.encoded(raw["input"])),
           "training_refs": [f"train@{train.name}"], "frames": [{"identity": "mcap:eval-s:0",
             "image_sha256": review.sha(encoded.tobytes()), "domain": "real", "conditions": ["junction"],
             "now_ns": 1050, "seed_pixels": [[10, 2]], "image_snapshot": snapshot(image),
             "anchor_snapshot": snapshot(anchor)}]}
    (inputs / "manifest.json").write_bytes(review.encoded(doc))
    return model_dir, root, road, region, seal(inputs)


def run(paths):
    model, root, road, region, inputs = paths
    return replay.run(model, store_root=root, road_eval=road, region_eval=region, inputs=inputs, max_age_ns=100)


def revise(folder, change):
    doc = json.loads((folder / "manifest.json").read_bytes())
    change(doc)
    (folder / "manifest.json").write_bytes(review.encoded(doc))
    return seal(folder)


@pytest.mark.parametrize("field,value,error", [
    ("preprocessing_sha256", "0" * 64, "input binding"),
    ("training_refs", [], "training refs"),
    ("frames", [], "non-empty frame"),
])
def test_resealed_inputs_still_require_exact_bindings(tmp_path, monkeypatch, field, value, error):
    paths = list(bundle(tmp_path, monkeypatch))
    paths[-1] = revise(paths[-1], lambda doc: doc.update({field: value}))
    with pytest.raises(ValueError, match=error):
        run(paths)


def test_resealed_truth_requires_exact_pixel_approval(tmp_path, monkeypatch):
    paths = list(bundle(tmp_path, monkeypatch))
    paths[2] = revise(paths[2], lambda doc: doc["frames"][0].update(approval_sha256="0" * 64))
    paths[-1] = revise(paths[-1], lambda doc: doc.update(road_eval_sha256=paths[2].name))
    with pytest.raises(ValueError, match="pixel approval"):
        run(paths)


def test_individually_approved_sets_must_share_the_source_image(tmp_path, monkeypatch):
    paths = list(bundle(tmp_path, monkeypatch))
    region = paths[3]
    _, encoded = cv2.imencode(".jpg", np.full((12, 12, 3), 80, np.uint8))
    (region / "image.jpg").write_bytes(encoded.tobytes())
    digest = review.sha(encoded.tobytes())
    authority = json.loads((region / "authority.json").read_bytes())
    row = authority["frames"][0]
    row["image_sha256"] = row["pixel_approval"]["image_sha256"] = digest
    del authority["decision_sha256"]
    authority["decision_sha256"] = review.sha(review.encoded(authority))
    review.validate_authority(authority)
    (region / "authority.json").write_bytes(review.encoded(authority))
    def update(doc):
        doc["authority_sha256"] = authority["decision_sha256"]
        doc["frames"][0].update(image_sha256=digest,
            approval_sha256=review.sha(review.encoded(row["pixel_approval"])))
    paths[3] = revise(region, update)
    paths[-1] = revise(paths[-1], lambda doc: doc.update(region_eval_sha256=paths[3].name))
    with pytest.raises(ValueError, match="paired road/region source image"):
        run(paths)


def test_exact_training_image_overlap_is_rejected_with_distinct_groups(tmp_path, monkeypatch):
    paths = list(bundle(tmp_path, monkeypatch))
    train = next((paths[1] / "datasets/train").iterdir())
    (train / "image.jpg").write_bytes((paths[2] / "image.jpg").read_bytes())
    train = seal(train)
    model_doc = json.loads((paths[0] / "model_manifest.json").read_bytes())
    model_doc["dataset"]["revision"] = train.name
    (paths[0] / "model_manifest.json").write_bytes(review.encoded(model_doc))
    paths[-1] = revise(paths[-1], lambda doc: doc.update(training_refs=[f"train@{train.name}"]))
    with pytest.raises(ValueError, match="training/evaluation source or image overlap"):
        run(paths)


@pytest.mark.parametrize("semantic", ["current_road_region/1", None])
def test_renamed_training_road_still_requires_whole_surface_semantic(tmp_path, monkeypatch, semantic):
    paths = list(bundle(tmp_path, monkeypatch))
    train = next((paths[1] / "datasets/train").iterdir())
    def change(doc):
        road = next(c for c in doc["classes"] if c["role"] == "drivable")
        road["name"] = "renamed_road"
        if semantic is None:
            road.pop("semantic")
        else:
            road["semantic"] = semantic
    train = revise(train, change)
    model_doc = json.loads((paths[0] / "model_manifest.json").read_bytes())
    model_doc["dataset"]["revision"] = train.name
    (paths[0] / "model_manifest.json").write_bytes(review.encoded(model_doc))
    paths[-1] = revise(paths[-1], lambda doc: doc.update(training_refs=[f"train@{train.name}"]))
    with pytest.raises(ValueError, match="semantic differs or is unverified"):
        run(paths)


@pytest.mark.parametrize("slot", [0, 2, 3, 4])
def test_root_alias_is_refused_before_resolving(tmp_path, monkeypatch, slot):
    paths = list(bundle(tmp_path, monkeypatch))
    alias = tmp_path / "alias"
    alias.symlink_to(paths[slot], target_is_directory=True)
    paths[slot] = alias
    with pytest.raises(ValueError, match="symlink"):
        run(paths)


def test_changed_model_during_inference_is_refused(tmp_path, monkeypatch):
    paths = bundle(tmp_path, monkeypatch)
    model = replay.LaneSegModel.open(paths[0])
    original = model._session.run
    def changed(*args):
        result = original(*args)
        with (paths[0] / "model_manifest.json").open("a") as stream:
            stream.write(" ")
        return result
    monkeypatch.setattr(model._session, "run", changed)
    with pytest.raises(ValueError, match="model manifest changed during replay"):
        run(paths)


def test_changed_dataset_during_inference_produces_no_report(tmp_path, monkeypatch):
    from argparse import Namespace
    paths = bundle(tmp_path, monkeypatch)
    model = replay.LaneSegModel.open(paths[0])
    original = model._session.run
    def changed(*args):
        result = original(*args)
        with (paths[2] / "manifest.json").open("a") as stream:
            stream.write(" ")
        return result
    monkeypatch.setattr(model._session, "run", changed)
    output = tmp_path / "report.json"
    assert replay.execute(Namespace(model=paths[0], store=paths[1], road_eval=paths[2],
                          region_eval=paths[3], inputs=paths[4], max_age_ns=100, out=output)) == 2
    assert not output.exists()


def test_training_capture_group_overlap_is_rejected_with_different_images(tmp_path, monkeypatch):
    paths = list(bundle(tmp_path, monkeypatch))
    train = next((paths[1] / "datasets/train").iterdir())
    train = revise(train, lambda doc: doc["frames"][0].update(capture_group="eval-g"))
    model_doc = json.loads((paths[0] / "model_manifest.json").read_bytes())
    model_doc["dataset"]["revision"] = train.name
    (paths[0] / "model_manifest.json").write_bytes(review.encoded(model_doc))
    paths[-1] = revise(paths[-1], lambda doc: doc.update(training_refs=[f"train@{train.name}"]))
    with pytest.raises(ValueError, match="training/evaluation source or image overlap"):
        run(paths)


def test_empty_declared_training_cannot_prove_disjointness(tmp_path, monkeypatch):
    paths = list(bundle(tmp_path, monkeypatch))
    train = next((paths[1] / "datasets/train").iterdir())
    train = revise(train, lambda doc: doc.update(frames=[]))
    paths[-1] = revise(paths[-1], lambda doc: doc.update(training_refs=[f"train@{train.name}"]))
    with pytest.raises(ValueError, match="non-empty training"):
        run(paths)


def test_fixed_pair_replays_with_separate_truth_and_holds_acceptance(tmp_path, monkeypatch):
    report = run(bundle(tmp_path, monkeypatch))
    assert report["fitness_verdict"] == "HOLD"
    assert report["summary"]["domains"]["real"]["frames"] == 1
    assert report["frames"][0]["road_surface"]["iou"] == 1
    assert report["frames"][0]["current_region"]["iou"] == 1
    assert report["frames"][0]["capture_group"] == 'eval-g'
    sources = report['source_uncertainty']['domains']['real']
    assert sources['source_count'] == 1
    assert sources['intervals']['road_surface']['iou']['reason'] == 'insufficient_sources'
    assert report["bindings"]["declared_training_disjoint"] is True
    assert "live_review_freshness_unverified" in report["hold_reasons"]


def test_changed_immutable_inputs_are_refused_before_model_replay(tmp_path, monkeypatch):
    paths = bundle(tmp_path, monkeypatch)
    (paths[-1] / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="content hash"):
        run(paths)


def test_fixed_manifest_reader_refuses_symlink_files(tmp_path):
    folder = tmp_path / "version"
    folder.mkdir()
    (folder / "manifest.json").write_text("{}")
    (folder / "link").symlink_to(folder / "manifest.json")
    with pytest.raises(ValueError, match="symlink"):
        store.read_fixed_manifest(folder)


def test_cli_fitness_does_not_require_robot_configuration(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools/perception"))
    import rosy_ml
    paths = bundle(tmp_path, monkeypatch)
    output = tmp_path / "report.json"
    monkeypatch.setenv("ROSY_ML_CONFIG", str(tmp_path / "absent.yaml"))
    model, root, road, region, inputs = paths
    args = ["fitness", str(model), "--store", str(root), "--road-eval", str(road),
            "--region-eval", str(region), "--inputs", str(inputs), "--max-age-ns", "100", "--out", str(output)]
    assert rosy_ml.main(args) == 0
    assert json.loads(output.read_text())["fitness_verdict"] == "HOLD"
    assert rosy_ml.main(args) == 2
