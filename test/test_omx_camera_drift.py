import json
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "sim"))
import omx_real2sim as r2s


def test_small_camera_shifts_accumulate_against_the_calibrated_frame(tmp_path, monkeypatch):
    import omx_real2sim_refit as refit

    monkeypatch.setenv("ROSY_REAL2SIM_FRAMES", str(tmp_path / "store"))
    scene = np.random.default_rng(0).integers(0, 256, (480, 650), dtype=np.uint8)
    scene = cv2.GaussianBlur(scene, (0, 0), 2)
    surveyed = r2s.sites.Layout()
    offset = 0

    def measure_plates(*_):
        plates = {
            tag: {"seen": [1, 2, 3], "lanes": [
                {"lane": lane, "xy": [xy[0] - offset / 1000, xy[1]], "yaw_deg": np.degrees(yaw)}
                for lane, (xy, yaw) in enumerate(plate["lanes"], 1)
            ]}
            for tag, plate in surveyed.plates.items()
        }
        return {"plates": plates, "shape": {}, "camera_check": {"worst_mm": [0]}}

    monkeypatch.setattr(r2s, "measure_temp_plates", measure_plates)
    monkeypatch.setattr(refit.h, "measure_temp_plates", measure_plates)
    for name in ("measure_ship", "measure_belt", "measure_ship_fixation"):
        monkeypatch.setattr(r2s, name, lambda *_: {})
    monkeypatch.setattr(r2s, "overlay", lambda frame, *_: frame)
    fitted = dict(surveyed.fixture["real_cameras"]["top"], f_px=618.5)

    def fit_top_camera(_, layout, __):
        assert layout.sites["tmp-a-1"]["xy"] == surveyed.sites["tmp-a-1"]["xy"]
        return {"ok": True, "camera": fitted}

    monkeypatch.setattr(refit, "refit_top_camera", fit_top_camera)
    reference = prev = None
    for offset in (0, 2, 4, 5, 9):
        if offset == 9:
            monkeypatch.setattr(refit, "refit_top_camera", lambda *_: {"ok": False, "why": "holdout mismatch"})
        run = tmp_path / str(offset)
        (run / "frames").mkdir(parents=True)
        assert cv2.imwrite(str(run / "frames" / "top.jpg"), scene[:, offset:offset + 640])
        snap = r2s.measure(run, prev, camera_moved_ok=offset == 9)
        prev = run / "snapshot.json"
        assert json.loads(prev.read_text())["camera_reference_top"] == snap["camera_reference_top"]
        if offset in (0, 4):
            reference = snap["frames"]["top"]
        assert snap["camera_reference_top"] == reference
        assert bool((snap["camera_fit"] or {}).get("ok")) == (offset == 4)
        if offset == 2:
            assert snap["camera_motion"]["dx_px"] == pytest.approx(-2, abs=.5)
            assert snap["items"]["temp_plates"]["plates"]["a"][0]["xy"][0] != snap["camera_reference_lanes"]["tmp-a-1"][0]
        if offset in (4, 5, 9):
            assert snap["camera"]["top"] == fitted
    assert snap["camera_fit"]["moved_ok"]
    assert cv2.imwrite(str(run / "frames" / "top.jpg"), scene[:, :600])
    with pytest.raises(SystemExit, match="resolution changed"):
        r2s.measure(run, prev)


@pytest.mark.parametrize("dx", [1, -3, 5])
def test_policy_translation_is_validated_on_held_out_points(dx):
    from omx_policy_camera_drift import translation_report

    ref = [[40, 40], [180, 120], [70, 300], [500, 410]]
    live = [[x + dx, y - 1] for x, y in ref]
    got = translation_report(ref, live, max_shift_px=6, max_residual_px=.5)
    assert got["candidate_matrix"] == [[1, 0, -dx], [0, 1, 1]]
    assert got["holdout_max_after_px"] == 0
    live[-1][0] += 2
    bad = translation_report(ref, live, max_shift_px=6, max_residual_px=.5)
    assert bad["candidate_matrix"] is None
    assert bad["holdout_max_after_px"] == 2


def test_policy_camera_report_binds_frames_and_rejects_a_different_profile(tmp_path, capsys):
    from omx_cell_anchor import digest
    from omx_policy_camera_drift import main

    ref, live = tmp_path / "ref.png", tmp_path / "live.png"
    image = np.zeros((20, 20), np.uint8)
    for x, y in ((2, 3), (4, 5), (7, 10), (11, 17)):
        image[y, x] = 255
    assert cv2.imwrite(str(ref), image)
    assert cv2.imwrite(str(live), np.roll(image, 1, axis=1))
    anchors = tmp_path / "anchors.json"
    data = dict(camera="top", training_profile="native", live_profile="native", reference_sha256=digest(ref), live_sha256=digest(live),
                reference_xy=[[2, 3], [4, 5], [7, 10], [11, 17]], live_xy=[[3, 3], [5, 5], [8, 10], [12, 17]])
    anchors.write_text(json.dumps(data))
    args = [str(ref), str(live), str(anchors), "--max-shift-px", "2", "--max-residual-px", "0.5"]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert (result["reference"], result["live"], result["anchors"]) == (digest(ref), digest(live), digest(anchors))
    data["live_profile"] = "cropped"
    anchors.write_text(json.dumps(data))
    with pytest.raises(SystemExit, match="2"):
        main(args)
    assert "matching capture profiles" in capsys.readouterr().err
    data["live_profile"] = "native"
    anchors.write_text(json.dumps(data))
    assert cv2.imwrite(str(live), image)
    with pytest.raises(SystemExit, match="2"):
        main(args)
    assert "original frame hashes" in capsys.readouterr().err


def test_simulated_camera_angles_move_local_orientation_without_accumulation():
    from types import SimpleNamespace

    mujoco = pytest.importorskip("mujoco")
    from omx_camera_pose import camera_angle_sampler

    model = mujoco.MjModel.from_xml_string("""
        <mujoco><worldbody>
          <camera name="top" pos="0 0 1"/><camera name="side" pos="0 -1 0"/>
          <body><joint/><geom size=".02"/><camera name="a_wrist" pos="0 .03 0"/></body>
        </worldbody></mujoco>
    """)
    base, pos, fov = model.cam_quat.copy(), model.cam_pos.copy(), model.cam_fovy.copy()
    world = SimpleNamespace(model=model)
    collect = camera_angle_sampler(world, "a_wrist", .3, 0)
    evaluate = camera_angle_sampler(world, "a_wrist", .3, 1)
    angles = collect(25)
    rotated = model.cam_quat.copy()
    assert np.all(np.any(rotated != base, axis=1))
    assert all(abs(d) <= .3 for role in angles.values() for d in role.values())
    assert collect(26) != angles and evaluate(25) != angles
    assert collect(25) == angles
    np.testing.assert_array_equal(model.cam_quat, rotated)
    np.testing.assert_array_equal(model.cam_pos, pos)
    np.testing.assert_array_equal(model.cam_fovy, fov)
    collect(None)
    np.testing.assert_array_equal(model.cam_quat, base)
