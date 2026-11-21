"""Top camera refit by PnP on the pad ends: a moved synthetic camera is recovered, a wrong layout is refused, Layout renders from it."""
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
sys.path.insert(0, str(ROOT / "test"))
import omx_real2sim_comp_helpers as ch  # noqa: E402
import omx_real2sim_refit as refit  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import test_omx_real2sim as base  # noqa: E402


def _layout(tmp_path, **kw):
    path = tmp_path / "lanes.json"
    path.write_text(json.dumps(base.snap()), encoding="utf-8")
    return sites.Layout(cell_snapshot=str(path), temp_lanes="snapshot", **kw)


def _moved(layout):
    nominal = dict(sites.TOP_CAMERA_20261114, f_px=refit.FACTORY_F_PX)
    moved = ch.perturbed_camera_dict(nominal, (.012, -.010, .008), (-.004, .006, 0.), 1.5)
    return nominal, moved


def test_a_moved_camera_is_recovered_from_the_pad_ends(tmp_path):
    layout = _layout(tmp_path)
    nominal, moved = _moved(layout)
    layout.fixture["real_cameras"] = dict(layout.fixture["real_cameras"], top=moved)
    frame = base.frame(layout)
    layout.fixture["real_cameras"] = dict(layout.fixture["real_cameras"], top=nominal)
    got = refit.refit_top_camera(frame, layout, {"nominal": nominal})
    assert got["ok"], got
    assert got["rms_mm"] <= refit.GATE_MM and got["anchors"] >= refit.MIN_ANCHORS
    # the anchors are near-coplanar, so eye x/height trade with tilt: judge the fit by what it is used for, pixels back onto the pad plane
    truth, fitted, z = ch.r2s.Camera(moved, (480, 640)), ch.r2s.Camera(got["camera"], (480, 640)), layout.deck_z + .0006
    uv = np.array([truth.project((x, y, z)) for x in (-.1, 0., .1) for y in (-.2, 0., .2)])
    assert np.abs(fitted.to_plane(uv, z) - truth.to_plane(uv, z)).max() < .004  # the synthetic pads and the anchors are both 90 mm: only the plane/tilt trade is left


def test_too_few_anchors_refuse(tmp_path):
    layout = _layout(tmp_path)
    nominal, _ = _moved(layout)
    blank = np.full((480, 640, 3), (60, 200, 200), np.uint8)
    got = refit.refit_top_camera(blank, layout, {"nominal": nominal})
    assert not got["ok"] and got["camera"] is None


def test_snapshot_top_camera_needs_an_accepted_fit(tmp_path):
    path = tmp_path / "s.json"
    cam = dict(sites.TOP_CAMERA_20261114, f_px=618.5, eye=[0., .09, .69])
    path.write_text(json.dumps(dict(camera=dict(top=cam), camera_fit=dict(ok=False, why="residual"))), encoding="utf-8")
    with pytest.raises(ValueError, match="no accepted top camera fit"):
        sites.Layout(cell_snapshot=str(path), top_camera="snapshot")
    path.write_text(json.dumps(dict(camera=dict(top=cam), camera_fit=dict(ok=True))), encoding="utf-8")
    assert sites.Layout(cell_snapshot=str(path), top_camera="snapshot").fixture["real_cameras"]["top"]["eye"] == [0., .09, .69]


def _anchors(cam_dict, size=(480, 640), off_plane_error_mm=0.):
    """Anchor dicts as _extract_anchors makes them, projected through a known camera: six pad ends on the pad plane, two container tops above it."""
    cam, z0 = ch.r2s.Camera(cam_dict, size), .0746
    pts = [(-.040, -.23, z0), (-.047, -.17, z0), (-.040, -.11, z0), (-.036, .11, z0), (-.044, .17, z0), (-.036, .23, z0)]
    pts += [(-.08, -.20, z0 + .04), (-.07, .20, z0 + .04)]
    return [dict(true_plus=(x + (i >= 6) * off_plane_error_mm / 1000, y), z=z, uv_plus=np.asarray(cam.project((x, y, z)), float), partial=False)
            for i, (x, y, z) in enumerate(pts)]


def test_container_top_anchors_hold_out_off_plane(tmp_path):
    truth = dict(sites.TOP_CAMERA_20261114, f_px=refit.FACTORY_F_PX)
    good = refit.fit_anchors(_anchors(truth), truth, (480, 640))
    assert good["anchors"] == 6 and good["held_mm"] < 1 and good["loo_mm"] < 1
    bad = refit.fit_anchors(_anchors(truth, off_plane_error_mm=15.), truth, (480, 640))
    assert bad["held_mm"] > refit.HOLDOUT_MM  # the plane fit is clean, the container tops it never saw are not: ok=False in refit_top_camera


def test_a_refused_refit_stops_the_measurement_unless_moved_ok(tmp_path):
    layout = _layout(tmp_path)
    nominal, _ = _moved(layout)
    blank = np.full((480, 640, 3), (60, 200, 200), np.uint8)  # no pads: the refit has nothing to fit, the pad check is 99 mm
    tp = dict(camera_check=dict(worst_mm=[99.0]), plates={}, shape=None)
    with pytest.raises(SystemExit, match="refit refused"):
        refit.apply_refit(blank, layout, tp, None, dict(moved=False), False, {"nominal": nominal})
    got_tp, fit = refit.apply_refit(blank, layout, tp, None, dict(moved=True), True, {"nominal": nominal})
    assert got_tp is tp and not fit["ok"] and fit["moved_ok"]  # recorded, and the layout keeps its pose
    assert refit.apply_refit(blank, layout, dict(camera_check=dict(worst_mm=[1.0])), None, dict(moved=False), False, {})[1] is None  # nothing to fix


def test_a_fit_whose_pad_check_still_fails_is_not_kept(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    nominal, _ = _moved(layout)
    before = dict(layout.fixture["real_cameras"]["top"])
    monkeypatch.setattr(refit, "refit_top_camera", lambda *a: dict(ok=True, why="", camera=nominal, rms_mm=1.0))
    monkeypatch.setattr(refit.h, "measure_temp_plates", lambda *a: dict(camera_check=dict(worst_mm=[5.0])))
    tp = dict(camera_check=dict(worst_mm=[9.0]))
    with pytest.raises(SystemExit, match="pad-size check through the fitted pose 5.0"):
        refit.apply_refit(None, layout, tp, None, dict(moved=True), False, {})
    assert layout.fixture["real_cameras"]["top"] == before  # the old pose is back
    monkeypatch.setattr(refit.h, "measure_temp_plates", lambda *a: dict(camera_check=dict(worst_mm=[2.0])))
    got, fit = refit.apply_refit(None, layout, tp, None, dict(moved=True), False, {})
    assert fit["ok"] and fit["pad_check_mm"] == 2.0 and layout.fixture["real_cameras"]["top"] == nominal


def test_an_unmoved_snapshot_pose_stands_without_a_fit(tmp_path):
    path = tmp_path / "s.json"
    cam = dict(sites.TOP_CAMERA_20261114, eye=[0., .09, .69])
    path.write_text(json.dumps(dict(camera=dict(top=cam), camera_fit=None, camera_motion=dict(checked=True, moved=False))), encoding="utf-8")
    assert sites.Layout(cell_snapshot=str(path), top_camera="snapshot").fixture["real_cameras"]["top"]["eye"] == [0., .09, .69]
    path.write_text(json.dumps(dict(camera=dict(top=cam), camera_fit=None, camera_motion=dict(checked=True, moved=True))), encoding="utf-8")
    with pytest.raises(ValueError, match="no accepted top camera fit"):  # moved and never refitted: fail closed
        sites.Layout(cell_snapshot=str(path), top_camera="snapshot")


def test_the_sim_stages_render_through_the_snapshot_camera():
    assert "top_camera=snapshot" in __import__("omx_real2sim").SNAP_CHOICES("x.json")


def test_the_11_14_pose_uses_the_factory_focal_length_the_refit_assumes():
    assert sites.TOP_CAMERA_20261114["f_px"] == refit.FACTORY_F_PX  # one K for the named pose and the refit that starts from it
