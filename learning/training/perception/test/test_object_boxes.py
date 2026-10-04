"""D-423 §2.5: LiDAR clusters -> candidate object boxes; human labels always win."""
import json
import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
for _p in (ROOT / "learning" / "training" / "perception" / "dataset", ROOT / "middleware" / "perception"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import object_boxes as OB  # noqa: E402
from geometry import Camera, Lidar  # noqa: E402
from control.sensing.perception.learned.manifest import OBJECT_CLASSES  # noqa: E402

CAM = Camera.from_profile(width=320, height=240)


def bind_image(tmp_path, labels, human):
    import cv2
    image = cv2.imencode(".png", np.zeros((240, 320, 3), dtype=np.uint8))[1].tobytes()
    (tmp_path / "frame.png").write_bytes(image)
    digest = hashlib.sha256(image).hexdigest()
    rows = [json.loads(x) for x in labels.read_text().splitlines()]
    rows[0].update(image="frame.png", image_sha256=digest)
    labels.write_text("".join(json.dumps(x) + "\n" for x in rows))
    reviews = [json.loads(x) for x in human.read_text().splitlines()]
    reviews[0]["image_sha256"] = digest
    human.write_text("".join(json.dumps(x) + "\n" for x in reviews))
    return digest


def box_points(cx, cy, half=0.04, n=9):
    """A small object's face seen by the scan: points along y at forward distance cx."""
    return np.stack([np.full(n, cx), np.linspace(cy - half, cy + half, n)], axis=1)


def test_a_small_cluster_ahead_becomes_one_unlabelled_box_at_its_floor_contact():
    boxes = OB.lidar_object_boxes(CAM, box_points(0.40, 0.0), lidar_height_m=Lidar().height_m)
    assert len(boxes) == 1
    box = boxes[0]
    assert box["label"] is None and box["source"] == "lidar_cluster"
    x0, y0, x1, y1 = box["bbox_xyxy"]
    assert x0 < 160 < x1 and y0 < y1
    assert y1 == pytest.approx(float(CAM.project([[0.40, 0.0, 0.0]])[1][0]), abs=1.0)  # floor contact
    assert box["distance_m"] == pytest.approx(0.40 - CAM.x_offset_m, abs=1e-4)
    assert box["top"] == "scan_plane_lower_bound"


def test_long_runs_are_walls_and_behind_the_camera_is_dropped():
    wall = np.stack([np.full(40, 0.5), np.linspace(-0.4, 0.4, 40)], axis=1)
    behind = box_points(-0.3, 0.0)
    assert OB.lidar_object_boxes(CAM, np.concatenate([wall, behind]), lidar_height_m=0.125) == []


def test_two_separate_objects_give_two_boxes():
    xy = np.concatenate([box_points(0.35, 0.10), box_points(0.50, -0.12)])
    assert len(OB.lidar_object_boxes(CAM, xy, lidar_height_m=0.125)) == 2


def test_human_labels_win_and_unreviewed_auto_boxes_stay_in_the_queue():
    auto = [{"bbox_xyxy": [100, 100, 140, 160], "label": None, "source": "lidar_cluster"},
            {"bbox_xyxy": [200, 100, 240, 160], "label": None, "source": "lidar_cluster"},
            {"bbox_xyxy": [10, 10, 30, 30], "label": None, "source": "lidar_cluster"}]
    human = [{"bbox_xyxy": [102, 98, 142, 162], "label": "cone"},      # confirms auto 0
             {"bbox_xyxy": [198, 101, 241, 159], "label": "none"},     # rejects auto 1
             {"bbox_xyxy": [260, 50, 300, 120], "label": "robot"}]     # one the LiDAR missed
    merged = OB.merge_review(auto, human)
    assert [(b["label"], b["source"]) for b in merged] == [
        ("cone", "human"), ("robot", "human"), (None, "lidar_cluster")]
    assert OB.needs_review(merged) == [merged[2]]


def test_unknown_human_class_is_refused():
    with pytest.raises(ValueError, match="class"):
        OB.merge_review([], [{"bbox_xyxy": [0, 0, 5, 5], "label": "dog"}])


def test_yolo_lines_use_the_contract_class_order_and_skip_unlabelled():
    boxes = [{"bbox_xyxy": [0, 0, 32, 24], "label": "cone"}, {"bbox_xyxy": [1, 1, 5, 5], "label": None}]
    assert OB.to_yolo_lines(boxes, (320, 240)) == [f"{OBJECT_CLASSES.index('cone')} 0.050000 0.050000 0.100000 0.100000"]


def test_cli_merges_a_labels_jsonl_with_human_rows(tmp_path):
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"index": 0, "objects": [
        {"bbox_xyxy": [100, 100, 140, 160], "label": None, "source": "lidar_cluster"}]}) + "\n" +
        json.dumps({"index": 1}) + "\n", encoding="utf-8")
    human = tmp_path / "human.jsonl"
    human.write_text(json.dumps({"index": 0, "review_status": "approved", "complete_frame_review": True,
                                "boxes": [{"bbox_xyxy": [100, 100, 140, 160], "label": "robot"}]})
                     + "\n", encoding="utf-8")
    out = tmp_path / "yolo"
    bind_image(tmp_path, labels, human)
    assert OB.main([str(labels), "--human", str(human), "--out", str(out), "--size", "320", "240"]) == 0
    assert (out / "000000.txt").read_text(encoding="utf-8").startswith(f"{OBJECT_CLASSES.index('robot')} ")
    # Not reviewed by a person: no label file (an empty one would claim "nothing there",
    # and the LiDAR cannot see anything lower than its scan plane), so it waits in the queue.
    assert not (out / "000001.txt").exists()
    queue = [json.loads(line) for line in (out / "review_queue.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [q["index"] for q in queue] == [1]


@pytest.mark.parametrize("review", [
    {}, {"review_status": "pending_human", "complete_frame_review": False},
    {"review_status": "approved", "complete_frame_review": False},
    {"review_status": "pending_human", "complete_frame_review": True},
    {"review_status": "approved", "complete_frame_review": 1},
])
@pytest.mark.parametrize("boxes", [[], [{"bbox_xyxy": [0, 0, 5, 5], "label": "robot"}]])
def test_partial_or_pending_review_never_exports_training_label(tmp_path, review, boxes):
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"index": 0}) + "\n")
    human = tmp_path / "human.jsonl"
    human.write_text(json.dumps({"index": 0, "boxes": boxes, **review}) + "\n")
    out = tmp_path / "out"
    assert OB.main([str(labels), "--human", str(human), "--out", str(out), "--size", "320", "240"]) == 0
    assert not (out / "000000.txt").exists()
    queue = [json.loads(x) for x in (out / "review_queue.jsonl").read_text().splitlines()]
    assert [q["index"] for q in queue] == [0]


def test_only_explicit_complete_approved_empty_boxes_can_claim_negative(tmp_path):
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"index": 0}) + "\n")
    human = tmp_path / "human.jsonl"
    human.write_text(json.dumps({"index": 0, "boxes": [], "review_status": "approved",
                                 "complete_frame_review": True}) + "\n")
    out = tmp_path / "out"
    digest = bind_image(tmp_path, labels, human)
    OB.main([str(labels), "--human", str(human), "--out", str(out), "--size", "320", "240"])
    assert (out / "000000.txt").read_text() == ""
    assert (out / "source.jsonl").read_bytes() == labels.read_bytes()
    assert (out / "human.jsonl").read_bytes() == human.read_bytes()
    (tmp_path / "frame.png").write_bytes(b"source changed after export")
    assert hashlib.sha256((out / "images/000000.png").read_bytes()).hexdigest() == digest
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["exported_indices"] == [0] and manifest["queued_indices"] == []
    assert manifest["classes"] == list(OBJECT_CLASSES)
    assert {x["path"] for x in manifest["files"]} == {
        p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file() and p.name != "manifest.json"}
    for ref in manifest["files"]:
        data = (out / ref["path"]).read_bytes()
        assert len(data) == ref["bytes"] and hashlib.sha256(data).hexdigest() == ref["sha256"]


@pytest.mark.parametrize("mutation", ["image", "review_hash", "source_hash", "path_escape", "size"])
def test_approved_label_must_match_exact_source_image(tmp_path, mutation):
    labels, human = tmp_path / "labels.jsonl", tmp_path / "human.jsonl"
    labels.write_text(json.dumps({"index": 0}) + "\n")
    human.write_text(json.dumps({"index": 0, "review_status": "approved", "complete_frame_review": True,
                                 "boxes": []}) + "\n")
    bind_image(tmp_path, labels, human)
    size = ["320", "240"]
    if mutation == "image":
        (tmp_path / "frame.png").write_bytes(b"different image")
    elif mutation == "size":
        size = ["640", "480"]
    else:
        path = human if mutation == "review_hash" else labels
        row = json.loads(path.read_text())
        if mutation == "path_escape":
            outside = tmp_path.parent / "outside.png"
            outside.write_bytes((tmp_path / "frame.png").read_bytes())
            row["image"] = "../outside.png"
        else:
            row["image_sha256"] = "a" * 64
        path.write_text(json.dumps(row) + "\n")
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        OB.main([str(labels), "--human", str(human), "--out", str(out), "--size", *size])
    assert not out.exists()


def test_approved_review_without_image_binding_is_refused(tmp_path):
    labels, human = tmp_path / "labels.jsonl", tmp_path / "human.jsonl"
    labels.write_text(json.dumps({"index": 0}) + "\n")
    human.write_text(json.dumps({"index": 0, "review_status": "approved", "complete_frame_review": True,
                                 "boxes": []}) + "\n")
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="image"):
        OB.main([str(labels), "--human", str(human), "--out", str(out), "--size", "320", "240"])
    assert not out.exists()


def test_existing_output_cannot_retain_stale_training_labels(tmp_path):
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"index": 0}) + "\n")
    out = tmp_path / "out"
    out.mkdir()
    (out / "000000.txt").write_text("old approved label")
    with pytest.raises(ValueError, match="new output"):
        OB.main([str(labels), "--out", str(out), "--size", "320", "240"])
    assert (out / "000000.txt").read_text() == "old approved label"


@pytest.mark.parametrize("reviews", [
    [{"index": 0, "review_status": "approved", "complete_frame_review": True}],
    [{"index": 0}, {"index": 0}],
    [{"index": True}], [{"index": -1}], [{"index": 1}],
    [{"index": 0, "review_status": "approved", "complete_frame_review": True,
      "boxes": [{"bbox_xyxy": [-1, 0, 5, 5], "label": "robot"}]}],
])
def test_ambiguous_or_invalid_review_cannot_create_partial_export(tmp_path, reviews):
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"index": 0}) + "\n")
    human = tmp_path / "human.jsonl"
    human.write_text("".join(json.dumps(row) + "\n" for row in reviews))
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        OB.main([str(labels), "--human", str(human), "--out", str(out), "--size", "320", "240"])
    assert not out.exists()


def test_out_of_bounds_rejection_cannot_turn_candidate_into_negative(tmp_path):
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"index": 0, "objects": [
        {"bbox_xyxy": [0, 0, 5, 5], "label": None}]}) + "\n")
    human = tmp_path / "human.jsonl"
    human.write_text(json.dumps({"index": 0, "review_status": "approved", "complete_frame_review": True,
        "boxes": [{"bbox_xyxy": [-1, -1, 5, 5], "label": "none"}]}) + "\n")
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="bounds"):
        OB.main([str(labels), "--human", str(human), "--out", str(out), "--size", "320", "240"])
    assert not out.exists()


def test_autolabel_writes_candidate_boxes_only_on_request():
    source = (ROOT / "learning" / "training" / "perception" / "dataset" / "autolabel.py").read_text(encoding="utf-8")
    assert '"--object-boxes"' in source
    assert 'rec["objects"] = lidar_object_boxes(cam, xy, lidar_height_m=lidar.height_m' in source
    assert "object_boxes=args.object_boxes" in source



@pytest.mark.parametrize("row", [
    {"label": "cone"},                                          # no box
    {"bbox_xyxy": [0, 0, 5], "label": "cone"},                  # three numbers
    {"bbox_xyxy": [10, 0, 5, 5], "label": "cone"},              # x1 < x0
    {"bbox_xyxy": [0, 0, 5, float("nan")], "label": "cone"},
    {"bbox_xyxy": ["0", 0, 5, 5], "label": "cone"},
    "not a row",
])
def test_malformed_human_rows_are_refused(row):
    """Review L9: a bad review row must fail loudly, not silently drop or keep auto boxes."""
    with pytest.raises(ValueError):
        OB.merge_review([], [row])
