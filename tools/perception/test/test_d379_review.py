"""D-379 review fixes: session identity, pitch-fit fallback, determinism, clock rule."""
import dataclasses
import json
import math

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

import autolabel  # noqa: E402
import build  # noqa: E402
import labels as L  # noqa: E402
from test_autolabel_geometry import CAM  # noqa: E402
from test_d379_catalog_and_store import _labels_dir  # noqa: E402


# --- 1. a session never spans splits or overwrites another -------------------

def test_video_session_comes_from_the_video_metadata(tmp_path):
    video = tmp_path / "teleop_rosy-pinky-8kcn_20260930T133221Z.mp4"
    video.write_bytes(b"")
    assert autolabel.video_session(video) == (None, None)
    video.with_suffix(".json").write_text(json.dumps({
        "source": {"session": "20260930T133221Z_rosy-pinky-8kcn"},
        "session": {"device": "rosy-pinky-8kcn"}}), encoding="utf-8")
    assert autolabel.video_session(video) == ("20260930T133221Z_rosy-pinky-8kcn",
                                              {"device": "rosy-pinky-8kcn"})


def test_video_without_a_session_name_is_refused(tmp_path):
    video = tmp_path / "x.mp4"
    video.write_bytes(b"")
    (tmp_path / "x.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        autolabel.main(["--video", str(video), "--out", str(tmp_path / "out")])


def test_existing_labels_are_never_silently_replaced(tmp_path):
    d = _labels_dir(tmp_path, "s1", [(L.FLOOR, False)])
    assert autolabel.check_out(tmp_path / "empty", "s1", False) is None
    assert "use --force" in autolabel.check_out(d, "s1", False)
    assert autolabel.check_out(d, "s1", True) is None
    assert "not 's2'" in autolabel.check_out(d, "s2", True)


# --- 2. a failed or weak pitch fit keeps the profile ---------------------------

def _wall_samples(true_cam, ranges=(0.6, 0.9, 1.3)):
    samples = []
    for r in ranges:
        ys = np.linspace(-0.8, 0.8, 161)
        xy = np.column_stack([np.full_like(ys, r), ys])
        img = np.full((240, 320, 3), 40, np.uint8)
        _, vt, _ = true_cam.project([[r, 0.0, L.WALL_HEIGHT_M]])
        base = int(round(true_cam.ground_row(r)))
        img[int(round(vt[0])):base] = 230
        img[base:] = 110
        samples.append((xy, L.edge_image(img)))
    return samples


def test_pitch_fit_without_returns_in_view_keeps_the_profile():
    behind = [(np.array([[-1.0, 0.0], [-1.0, 0.1]]), np.zeros((240, 320), np.float32))]
    pitch, curve = L.fit_pitch(CAM, behind)
    assert pitch is None and set(curve.values()) == {None}
    pitch, info = L.choose_pitch(CAM, behind)
    assert pitch == CAM.pitch_rad
    assert info["pitch_source"] == "profile" and info["why"] == "no LiDAR wall in view"
    assert L.choose_pitch(CAM, [])[1]["pitch_source"] == "profile"


def test_pitch_fit_must_beat_the_profile_by_the_margin():
    true = dataclasses.replace(CAM, pitch_rad=math.radians(11.0))
    pitch, info = L.choose_pitch(CAM, _wall_samples(true))
    assert info["pitch_source"] == "lidar-fit"
    assert math.degrees(pitch) == pytest.approx(11.0, abs=0.3)
    # the camera already sits at the profile pitch: nothing beats it by the margin
    pitch, info = L.choose_pitch(CAM, _wall_samples(CAM))
    assert pitch == CAM.pitch_rad and info["pitch_source"] == "profile"


# --- 3. the content sha does not depend on input order -------------------------

def test_shuffled_inputs_give_the_same_dataset_version(tmp_path):
    a = _labels_dir(tmp_path, "s1", [(L.FLOOR, False), (L.DRIVABLE, False), (L.FLOOR, False)])
    b = _labels_dir(tmp_path, "s2", [(L.DRIVABLE, False), (L.FLOOR, False)])
    _, first = build.build_auto_dataset([a, b], tmp_path / "st1", "n")
    # same folders, other argument order, labels.jsonl rows reversed
    for d in (a, b):
        jl = d / "labels.jsonl"
        rows = jl.read_text(encoding="utf-8").splitlines()
        jl.write_text("\n".join(reversed(rows)) + "\n", encoding="utf-8")
    manifest, second = build.build_auto_dataset([b, a], tmp_path / "st2", "n")
    assert second.name == first.name
    assert [f["image"].rsplit("/", 1)[1] for f in manifest["frames"]] == [
        "s1__000000.jpg", "s1__000001.jpg", "s1__000002.jpg", "s2__000000.jpg", "s2__000001.jpg"]


# --- 4. unlabelled = ignore_index 255, not a class -----------------------------

def test_auto_build_keeps_255_as_ignore_and_rejects_stray_values(tmp_path):
    a = _labels_dir(tmp_path, "s1", [(L.DRIVABLE, False)])
    b = _labels_dir(tmp_path, "s2", [(L.FLOOR, False)])
    mask = cv2.imread(str(a / "masks" / "000000.png"), cv2.IMREAD_UNCHANGED)
    mask[10:] = 255
    cv2.imwrite(str(a / "masks" / "000000.png"), mask)
    manifest, final = build.build_auto_dataset([a, b], tmp_path / "st", "n")
    assert manifest["ignore_index"] == 255
    assert all(c["index"] < len(manifest["classes"]) for c in manifest["classes"])
    got = cv2.imread(str(final / manifest["frames"][0]["mask"]), cv2.IMREAD_UNCHANGED)
    assert set(np.unique(got).tolist()) == {L.WALL, L.DRIVABLE, 255}
    mask[0, 0] = 6  # not a class, not ignore
    cv2.imwrite(str(a / "masks" / "000000.png"), mask)
    with pytest.raises(build.BuildError, match=r"values \[6\]"):
        build.build_auto_dataset([a, b], tmp_path / "st2", "n")


def test_auto_build_refuses_one_session_in_two_label_folders(tmp_path):
    a = _labels_dir(tmp_path / "a", "s1", [(L.FLOOR, False)])
    b = _labels_dir(tmp_path / "b", "s1", [(L.FLOOR, False)])
    c = _labels_dir(tmp_path / "c", "s2", [(L.FLOOR, False)])
    with pytest.raises(build.BuildError, match="one label folder per session"):
        build.build_auto_dataset([a, b, c], tmp_path / "store", "n")
    assert not (tmp_path / "store").exists()
