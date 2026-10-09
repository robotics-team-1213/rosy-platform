"""D-554 derived drivable labels: synthetic masks only, no torch and no network."""
import hashlib
import json

import cv2
import numpy as np
import pytest

import lane_derived_drivable as ldd


def _frame(wall=True):
    """240x320: rows <110 ignored, lane_left col 40-49, lane_right col 270-279, wall right of it."""
    image = np.random.default_rng(0).integers(60, 110, (240, 320, 3)).astype(np.uint8)  # textured carpet
    mask = np.zeros((240, 320), np.uint8)
    mask[:110] = 255
    mask[110:, 40:50] = 1
    mask[110:, 270:280] = 2
    mask[200:210, 100:120] = 3
    if wall:
        image[60:160, 285:] = 220  # flat white wall continuing above row 110
    image[180:200, 120:140] = 220  # bright flat patch not connected to row 110: stays ignored
    return image, mask


def _source(tmp_path, frames):
    src = tmp_path / "src"
    items = []
    for split, name, (image, mask) in frames:
        for kind, data in (("images", cv2.imencode(".jpg", image)[1]), ("masks", cv2.imencode(".png", mask)[1])):
            folder = src / split / kind
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (name + (".jpg" if kind == "images" else ".png"))).write_bytes(data.tobytes())
        items.append({"split": split,
                      "image_sha256": hashlib.sha256((src / split / "images" / (name + ".jpg")).read_bytes()).hexdigest(),
                      "mask_sha256": hashlib.sha256((src / split / "masks" / (name + ".png")).read_bytes()).hexdigest(),
                      "source_group": "rosy:20261001T000000Z_rosy-pinky-8kcn"})
    (src / "manifest.json").write_text(json.dumps({
        "schema_version": "pinky-lane-dataset-v1", "dataset_revision": "test",
        "classes": ["background", "lane_left", "lane_right", "crosswalk", "speed_bump"], "items": items}))
    return src


def test_derive_mask_band_lanes_walls_and_ignore():
    image, src = _frame()
    out, both = ldd.derive_mask(src, image)
    assert both == 130
    assert (out[:110] == 255).all()
    assert (out[110:, 40:50] == 1).all() and (out[110:, 270:280] == 2).all()
    assert (out[200:210, 100:120] == 3).all()  # crosswalk kept, not drivable
    assert (out[150, 50:270] == ldd.DRIVABLE).all()
    assert (out[115:155, 290:] == 0).sum() > 0.9 * 40 * 30  # wall negatives
    assert (out[230, 285:] == 255).all()  # carpet outside lanes stays unknown
    assert (out[180:200, 0:40] == 255).all()


def test_derive_needs_left_before_right():
    image, src = _frame(wall=False)
    src[110:, 40:50], src[110:, 270:280] = 2, 1
    out, both = ldd.derive_mask(src, image)
    assert both == 0 and not (out == ldd.DRIVABLE).any()


def test_derive_verify_judge_finalize(tmp_path):
    blank = _frame()
    no_right = _frame()
    no_right[1][no_right[1] == 2] = 0
    src = _source(tmp_path, [("train", "a", blank), ("val", "b", _frame(wall=False)),
                             ("train", "c", no_right)])
    out = tmp_path / "out"
    digest, doc = ldd.derive(src, out)
    assert digest == hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest()
    assert doc["skipped_frames"] == 1 and len(doc["frames"]) == 2
    assert doc["annotation_origin"] == "derived_from_reviewed_lanes" and doc["adr"] == "D-554"
    assert doc["evaluation_use"] == "training_val_only"
    assert doc["source"]["manifest_sha256"] == hashlib.sha256((src / "manifest.json").read_bytes()).hexdigest()
    assert doc["classes"][-1] == {"index": 5, "name": "drivable", "role": "drivable"}
    assert doc["frames"][0]["session"] == "20261001T000000Z_rosy-pinky-8kcn"
    assert doc["frames"][0]["wall_px"] > 0 and doc["frames"][1]["wall_px"] == 0
    assert "approved" not in json.dumps(doc)
    ldd.verify_dataset(out)

    answers = iter([{"verdict": "concern", "reason": "green on wall"}, {"verdict": "ok", "reason": "fine"}])
    rows = ldd.judge(out, lambda original, view: next(answers))
    assert [r["verdict"] for r in rows] == ["concern", "ok"]
    _, final = ldd.finalize(out)
    assert len(final["frames"]) == 1 and len(final["judge"]["dropped"]) == 1
    assert not (out / doc["frames"][0]["image"]).exists()
    ldd.verify_dataset(out)

    (out / final["frames"][0]["mask"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash differs"):
        ldd.verify_dataset(out)


def test_derive_refuses_unlisted_frame(tmp_path):
    src = _source(tmp_path, [("train", "a", _frame())])
    (src / "train" / "masks" / "a.png").write_bytes(cv2.imencode(".png", np.zeros((240, 320), np.uint8))[1].tobytes())
    with pytest.raises(ValueError, match="not a reviewed source"):
        ldd.derive(src, tmp_path / "out")


def test_verify_refuses_approval_fields_and_wrong_origin(tmp_path):
    src = _source(tmp_path, [("train", "a", _frame())])
    out = tmp_path / "out"
    _, doc = ldd.derive(src, out)
    doc["frames"][0]["approved"] = True
    (out / "manifest.json").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="approval"):
        ldd.verify_dataset(out)
    doc["frames"][0].pop("approved")
    doc["annotation_origin"] = "human_reviewed_pinky_indexed"
    (out / "manifest.json").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="D-554"):
        ldd.verify_dataset(out)
