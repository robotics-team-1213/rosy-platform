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
    image[180:200, 120:140] = 220  # unlabelled bright stripe between the lanes: stays ignored
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
    assert (out[230, 280:] == 0).all()  # outside band: W 220 -> 110 px, cut by the image edge
    assert (out[180:200, 0:40] == 0).all()
    assert (out[182:198, 122:138] == 255).all()  # stripe is not road


def test_wall_never_below_a_lane_line_in_its_column():
    image, src = _frame()
    image[60:230, 285:] = 220  # bright flat region reaching the floor beyond the line
    src[150:152, 295:305] = 3  # a painted mark in those columns
    out, _ = ldd.derive_mask(src, image)
    assert (out[115:148, 296:304] == 0).all()
    assert (out[155:225, 296:304] == 255).all()  # floor below the mark is never wall
    assert (out[155:225, 310:316] == 0).all()  # columns without a lane mark keep the wall


def test_rows_above_ignore_top_are_unknown_for_every_class():
    image, src = _frame()
    src[100:110, 40:50] = 1
    out, _ = ldd.derive_mask(src, image)
    assert (out[:110] == 255).all()


def test_outside_band_width_and_stops():
    """lane_left 100-109, lane_right 200-209: W 90, k 0.5 -> 45 px bands, then 255."""
    image = np.random.default_rng(0).integers(60, 110, (240, 320, 3)).astype(np.uint8)
    src = np.zeros((240, 320), np.uint8)
    src[110:, 100:110], src[110:, 200:210] = 1, 2
    src[150, 80], src[170, 90] = 3, 255  # a lane-class pixel stops the band; source 255 is skipped
    image[160, 230] = 220  # bright paint stops the band
    out, _ = ldd.derive_mask(src, image)
    assert (out[120, 55:100] == 0).all() and (out[120, :55] == 255).all()
    assert (out[120, 210:255] == 0).all() and (out[120, 255:] == 255).all()
    assert (out[150, 81:100] == 0).all() and (out[150, :80] == 255).all()
    assert (out[160, 210:230] == 0).all() and (out[160, 230:] == 255).all()
    assert out[170, 90] == 255 and (out[170, 55:90] == 0).all()
    out, _ = ldd.derive_mask(src, image, outside_k=0)
    assert not (out == 0).any()


def _perspective(left_until=200, right_until=200, wobble=0):
    """Lines widen toward the bottom: right edge of lane_left 100-(y-110)/2, left edge of lane_right
    220+(y-110)/2, 8 px wide; each drawn only down to its *_until row (then it has left the view)."""
    image = np.random.default_rng(0).integers(60, 110, (240, 320, 3)).astype(np.uint8)
    src = np.zeros((240, 320), np.uint8)
    src[:110] = 255
    for y in range(110, 240):
        xl, xr = 100 - (y - 110) // 2 + (wobble if y % 2 else -wobble), 220 + (y - 110) // 2
        if y <= left_until:
            src[y, max(xl - 7, 0):xl + 1] = 1
        if y <= right_until:
            src[y, xr:xr + 8] = 2
    return image, src


def test_near_rows_extend_the_road_from_the_fitted_lines():
    image, src = _perspective()
    out, both = ldd.derive_mask(src, image)
    assert both == 91
    assert (out[230, 41:280] == ldd.DRIVABLE).all()  # 100-60 .. 220+60, extrapolated
    assert (out[239, 0:320] != 0).all() and (out[230, :40] == 255).all()  # no band beside a missing line
    out, _ = ldd.derive_mask(src, image, near=dict(ldd.NEAR, fit_rows=0))
    assert not (out[201:] == ldd.DRIVABLE).any()


def test_near_rows_use_the_visible_line_and_its_outside_band():
    image, src = _perspective(right_until=239)
    out, _ = ldd.derive_mask(src, image)
    assert (out[230, 41:280] == ldd.DRIVABLE).all() and (out[230, 280:288] == 2).all()
    assert (out[230, 288:] == 0).all()  # right line visible: its outside band holds
    assert (out[230, :40] == 255).all()


def test_near_extension_refused_on_a_bad_fit_or_narrow_road():
    image, src = _perspective(wobble=6)
    out, _ = ldd.derive_mask(src, image)
    assert not (out[201:] == ldd.DRIVABLE).any()
    image, src = _perspective()
    out, _ = ldd.derive_mask(src, image, near=dict(ldd.NEAR, min_width=250))  # row 201 is ~210 wide
    assert (out[200] == ldd.DRIVABLE).any() and not (out[201:] == ldd.DRIVABLE).any()


def _labelled(road_cols=(60, 260)):
    """Rows >= 110 labelled: band 0 at 0-49 and 270-319, lanes 50-59 / 260-269, drivable between."""
    mask = np.full((240, 320), 255, np.uint8)
    mask[110:] = 0
    mask[110:, 50:60], mask[110:, 260:270] = 1, 2
    mask[110:, road_cols[0]:road_cols[1]] = ldd.DRIVABLE
    mask[110:, 60:road_cols[0]] = 0
    mask[110:, road_cols[1]:260] = 0
    return mask


def test_canaries_change_at_least_800px_and_15_percent_of_labelled():
    mask = _labelled()
    removed = ldd._corrupt(mask, "drivable_removed", 110)
    assert (removed[mask == ldd.DRIVABLE] == 0).all()  # cyan, not unknown
    wall = ldd._corrupt(mask, "wall_over_road", 110)
    assert (wall[mask == ldd.DRIVABLE] == 0).sum() >= 0.5 * (mask == ldd.DRIVABLE).sum()
    off = ldd._corrupt(mask, "drivable_over_offroad", 110)
    assert (off[110:, :50] == ldd.DRIVABLE).all() and (off[110:, 270:] == ldd.DRIVABLE).all()
    assert (off[110:, 50:60] == 1).all() and (off[:110] == 255).all()
    narrow = _labelled((150, 160))  # 1300 px of road < 15 % of 41600 labelled
    assert ldd._corrupt(narrow, "drivable_removed", 110) is None
    assert ldd._corrupt(narrow, "wall_over_road", 110) is None
    tiny = np.full((240, 320), 255, np.uint8)
    tiny[200:220, 100:130] = ldd.DRIVABLE  # 600 px: under the 800 px floor
    assert ldd._corrupt(tiny, "drivable_removed", 110) is None


def test_derive_needs_left_before_right():
    image, src = _frame(wall=False)
    src[110:, 40:50], src[110:, 270:280] = 2, 1
    out, both = ldd.derive_mask(src, image)
    assert both == 0 and not (out == ldd.DRIVABLE).any()


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


def test_tool_commit_is_recorded_never_unknown(tmp_path, monkeypatch):
    head = ldd._git_commit()
    assert len(head) == 40
    with pytest.raises(ValueError, match="differs"):
        ldd._git_commit("0" * 40)

    def no_git(*args, **kwargs):
        raise OSError("no git")
    monkeypatch.setattr(ldd.subprocess, "run", no_git)
    with pytest.raises(ValueError, match="tool commit unknown"):
        ldd._git_commit()
    with pytest.raises(ValueError, match="tool commit unknown"):
        ldd._git_commit("unknown")
    assert ldd._git_commit("a" * 40) == "a" * 40


def _derived(tmp_path, n=12, name="out"):
    src = _source(tmp_path, [("train", f"f{i}", _frame()) for i in range(n)])
    out = tmp_path / name
    ldd.derive(src, out)
    return out


@pytest.fixture
def few_canaries(monkeypatch):
    monkeypatch.setattr(ldd, "MIN_CANARIES", 3)


def _write(tmp_path, rows):
    path = tmp_path / "verdicts.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def review(tmp_path, out, verdict=lambda tile: "ok", canaries=0.25, **kwargs):
    """Sheets + a reviewer who catches every canary; returns import_verdicts' result."""
    dest, key = tmp_path / "sheets", tmp_path / "secret" / "key.json"
    ldd.sheets(out, dest, key, per_sheet=6, seed=2, canaries=canaries)
    tiles = json.loads((dest / "index.json").read_text())["tiles"]
    hidden = json.loads(key.read_text())
    rows = [{"tile": t, "verdict": "concern" if t in hidden else verdict(t), "reason": "x"} for t in tiles]
    instructions = tmp_path / "instructions.md"
    instructions.write_text("review rules")
    return ldd.import_verdicts(out, dest, key, _write(tmp_path, rows), "reviewer-a", instructions, **kwargs)


def test_derive_review_finalize(tmp_path, few_canaries):
    out = _derived(tmp_path)
    doc = json.loads((out / "manifest.json").read_text())
    assert doc["annotation_origin"] == "derived_from_reviewed_lanes" and doc["adr"] == "D-554"
    assert doc["evaluation_use"] == "training_val_only" and "approved" not in json.dumps(doc)
    assert doc["frames"][0]["session"] == "20261001T000000Z_rosy-pinky-8kcn"
    with pytest.raises(ValueError, match="not finalized"):
        ldd.verify_dataset(out, finalized=True)
    result = review(tmp_path, out, verdict=lambda tile: "concern" if tile == "T0001" else "ok")
    assert result["canaries"]["rate"] == 1.0 and result["unreviewed"] == 0
    _, final = ldd.finalize(out)
    assert final["judge"]["canaries"] == result["canaries"]
    assert final["judge"]["model"] == "reviewer-a"
    assert final["judge"]["prompt_sha256"] == hashlib.sha256(b"review rules").hexdigest()
    assert len(final["frames"]) + len(final["judge"]["dropped"]) == 12
    ldd.verify_dataset(out, finalized=True)
    with pytest.raises(ValueError, match="already finalized"):
        ldd.finalize(out)
    (out / final["frames"][0]["mask"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash differs"):
        ldd.verify_dataset(out)


def test_finalize_refuses_verdicts_without_enough_canaries(tmp_path, few_canaries):
    out = _derived(tmp_path)
    doc = json.loads((out / "manifest.json").read_text())
    (out / "judge.jsonl").write_text("".join(json.dumps(
        {"item": f["image"], "mask_sha256": f["mask_sha256"], "verdict": "ok"}) + "\n" for f in doc["frames"]))
    run = {"model": "vlm", "endpoint": "e", "prompt_sha256": "p", "splits": [], "seconds": 0}
    (out / "judge-run.json").write_text(json.dumps(run))
    with pytest.raises(ValueError, match="invalid canary block"):
        ldd.finalize(out)
    (out / "judge-run.json").write_text(json.dumps(dict(run, canaries={"count": 2, "caught": 2, "rate": 1.0})))
    with pytest.raises(ValueError, match="at least 3 required"):
        ldd.finalize(out)
    (out / "judge-run.json").write_text(json.dumps(dict(run, canaries={"count": 4, "caught": 3, "rate": 0.75})))
    with pytest.raises(ValueError, match="canary concern rate"):
        ldd.finalize(out)


def test_sheets_cover_every_frame_and_keep_the_key_outside(tmp_path, few_canaries):
    out = _derived(tmp_path)
    dest, key = tmp_path / "sheets", tmp_path / "secret" / "key.json"
    with pytest.raises(ValueError, match="outside"):
        ldd.sheets(out, dest, dest / "key.json")
    with pytest.raises(ValueError, match="at least 3"):
        ldd.sheets(out, dest, key, canaries=0.1)
    result = ldd.sheets(out, dest, key, per_sheet=4, seed=1, canaries=0.25)
    index = json.loads((dest / "index.json").read_text())
    hidden = json.loads(key.read_text())
    assert result == {"sheets": 4, "tiles": 15, "canaries": 3}
    assert not (dest / "canaries.json").exists()
    assert {t["image"] for tile, t in index["tiles"].items() if tile not in hidden} == {
        f["image"] for f in json.loads((out / "manifest.json").read_text())["frames"]}
    assert {h["kind"] for h in hidden.values()} <= set(ldd.CANARY_KINDS)
    assert sorted(p.name for p in dest.glob("sheet-*.png")) == index["sheets"]


def test_import_verdicts_needs_canaries_caught_and_every_tile(tmp_path, few_canaries):
    out = _derived(tmp_path)
    dest, key = tmp_path / "sheets", tmp_path / "key.json"
    ldd.sheets(out, dest, key, per_sheet=6, seed=2, canaries=0.25)
    index = json.loads((dest / "index.json").read_text())["tiles"]
    hidden = json.loads(key.read_text())
    instructions = tmp_path / "instructions.md"
    instructions.write_text("review rules")
    real = sorted(t for t in index if t not in hidden)
    lazy = _write(tmp_path, [{"tile": t, "verdict": "ok"} for t in index])
    with pytest.raises(ValueError, match="canary concern rate"):
        ldd.import_verdicts(out, dest, key, lazy, "reviewer-a", instructions)
    partial = _write(tmp_path, [{"tile": t, "verdict": "concern"} for t in hidden] + [{"tile": real[0], "verdict": "ok"}])
    with pytest.raises(ValueError, match="lack a verdict"):
        ldd.import_verdicts(out, dest, key, partial, "reviewer-a", instructions)


def test_reviewed_verdicts_carry_over_only_label_to_unknown_changes(tmp_path, few_canaries):
    old = _derived(tmp_path, name="old")
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    dest, key = review_dir / "sheets", review_dir / "key.json"
    ldd.sheets(old, dest, key, per_sheet=6, seed=2, canaries=0.25)
    tiles = json.loads((dest / "index.json").read_text())["tiles"]
    hidden = json.loads(key.read_text())
    verdicts = _write(review_dir, [{"tile": t, "verdict": "concern" if t in hidden else "ok"} for t in tiles])
    instructions = review_dir / "instructions.md"
    instructions.write_text("rules")
    new = tmp_path / "new"
    ldd.derive(tmp_path / "src", new)
    doc = json.loads((new / "manifest.json").read_text())
    changed = {}
    for frame, value in zip(doc["frames"][:2], (255, 0)):  # one label->255, one label->other label
        mask = cv2.imread(str(new / frame["mask"]), cv2.IMREAD_UNCHANGED)
        mask[150, 60] = value if value == 255 else 1
        raw = cv2.imencode(".png", mask)[1].tobytes()
        (new / frame["mask"]).write_bytes(raw)
        frame["mask_sha256"] = hashlib.sha256(raw).hexdigest()
        changed[frame["image"]] = value
    (new / "manifest.json").write_text(json.dumps(doc))
    args = (new, dest, key, verdicts, "reviewer-a", instructions)
    with pytest.raises(ValueError, match="different dataset manifest"):
        ldd.import_verdicts(*args)
    with pytest.raises(ValueError, match="1 frames have no verdict"):
        ldd.import_verdicts(*args, reviewed_manifest=old / "manifest.json")
    result = ldd.import_verdicts(*args, reviewed_manifest=old / "manifest.json", drop_unreviewed=True)
    assert result["unreviewed"] == 1 and result["counts"]["ok"] == 11
    _, final = ldd.finalize(new)
    assert [d["image"] for d in final["judge"]["dropped"]] == [
        image for image, value in changed.items() if value == 0]
    assert final["judge"]["dropped"][0]["verdict"] == "unreviewed"
    ldd.verify_dataset(new, finalized=True)
