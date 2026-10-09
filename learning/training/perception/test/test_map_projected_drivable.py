"""D-563 3 map-projected drivable labels on a synthetic straight road; review + train admission."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
import lane_derived_drivable as ldd  # noqa: E402
import map_projected_drivable as mpd  # noqa: E402
from geometry import Camera, PoseSeries  # noqa: E402

R = 0.002
CAMERA = Camera.from_profile()
FUSE_EXACT = {"sigma_aruco_m": 0.005, "sigma_aruco_yaw": 0.0, "drift_per_m": 0.0}


def _raster():
    """4 x 2 m map, one road along map x: |y| <= 0.0925 road, lines 25 mm wide on its edges."""
    ys = 1.0 - np.arange(1001) * R
    cls = np.full((1001, 2001), mpd.OFF, np.uint8)
    cls[np.abs(ys) <= mpd.HALF_WIDTH_M] = mpd.ROAD
    cls[np.abs(np.abs(ys) - mpd.HALF_WIDTH_M) <= 0.0125] = mpd.LINE
    return {"x0": -2.0, "y1": 1.0, "raster_m": R, "cls": cls, "boundary_m": mpd.boundary_distance(cls, R),
            "lane_graph_sha256": "g" * 64, "stl_sha256": "s" * 64}


def _render(raster, pose, camera=CAMERA):
    """Grey carpet with the map's white lines where the floor is seen."""
    forward, left = mpd.ground_grid(camera)
    c, s = math.cos(pose[2]), math.sin(pose[2])
    with np.errstate(invalid="ignore"):
        row = np.rint((raster["y1"] - (pose[1] + forward * s + left * c)) / R)
        col = np.rint((pose[0] + forward * c - left * s - raster["x0"]) / R)
    ok = np.isfinite(row) & (row >= 0) & (row < 1001) & (col >= 0) & (col < 2001)
    gray = np.full(forward.shape, 80, np.uint8)
    gray[ok] = np.where(raster["cls"][row[ok].astype(int), col[ok].astype(int)] == mpd.LINE, 230, 80)
    return np.repeat(gray[:, :, None], 3, axis=2)


def _pose(x=0.0, y=0.0, yaw=0.0, sigma=0.005):
    return {"x": x, "y": y, "yaw": yaw, "sigma_m": sigma, "sigma_yaw": 0.0}


def test_ground_grid_inverts_camera_project():
    forward, left = mpd.ground_grid(CAMERA)
    for v, u in ((200, 160), (150, 40), (230, 300)):
        pu, pv, _ = CAMERA.project([[forward[v, u], left[v, u], 0.0]])
        assert (pu[0], pv[0]) == pytest.approx((u, v), abs=1e-6)
    assert np.isnan(forward[:70]).all()


def test_label_frame_road_offroad_margin_and_pose_check():
    raster, grid = _raster(), mpd.ground_grid(CAMERA)
    mask, stats = mpd.label_frame(_render(raster, (0, 0, 0)), _pose(), CAMERA, grid, raster)
    assert stats["line_iou"] > 0.9
    forward, left = grid
    road, off = mask == ldd.DRIVABLE, mask == 0
    assert road.sum() > 2000 and off.sum() > 200
    assert (np.abs(left[road]) < mpd.HALF_WIDTH_M - 0.005).all()
    assert (np.abs(left[off]) > mpd.HALF_WIDTH_M + 0.0125 + 0.005).all()
    assert ((forward[mask != 255] >= 0.15) & (forward[mask != 255] <= 0.40)).all()
    assert (mask[:110] == 255).all()
    wide, _ = mpd.label_frame(_render(raster, (0, 0, 0)), _pose(sigma=0.03), CAMERA, grid, raster)
    assert (wide == ldd.DRIVABLE).sum() < road.sum()  # pose margin widens the ignored band
    bad, why = mpd.label_frame(_render(raster, (0, 0.06, 0)), _pose(), CAMERA, grid, raster)
    assert bad is None and why["reason"] == "line_iou"
    none, why = mpd.label_frame(_render(raster, (0, 0, 0)), _pose(y=0.6), CAMERA, grid, raster)
    assert none is None and why["reason"] == "no_line_in_view"


def _derived(tmp_path, n=8, name="out"):
    """Robot drives map +x along the road at 0.1 m/s; robot clock = site clock + 2 s."""
    raster = _raster()
    t = np.arange(10.0, 10.0 + n + 1, 0.1)
    odom = PoseSeries(t, 0.1 * (t - 10.0) - 1.0, np.zeros_like(t), np.zeros_like(t))
    ceiling = tmp_path / "ceiling"
    ceiling.mkdir(exist_ok=True)
    rows = [{"t": rt - 2.0, "x": 0.1 * (rt - 10.0) - 0.5, "y": 0.0, "yaw": 0.0, "src": "aruco",
             "reproj_err": 0.001} for rt in np.arange(10.0, 10.0 + n + 1, 0.5)]
    (ceiling / "poses.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (ceiling / "calibration.json").write_text(json.dumps({"record": {"calibration_revision": "paint-test",
                                                                     "map_id": "test"}}))
    frames = [(10.0 + i, _render(raster, (0.1 * i - 0.5, 0.0, 0.0))) for i in range(n)]
    frames.append((10.0 + n + 30.0, frames[0][1]))  # no detection near: rejected
    out = tmp_path / name
    mpd.derive(out, frames=frames, odom=odom, robot_inputs={"bag": "b" * 64}, ceiling=ceiling, camera=CAMERA,
               camera_values={"pitch_rad": CAMERA.pitch_rad}, camera_source="test", raster=raster,
               session="synthetic", clock_offset_s=2.0, fuse_params=FUSE_EXACT)
    return out


def test_derive_writes_admissible_manifest(tmp_path):
    out = _derived(tmp_path)
    doc = ldd.verify_dataset(out)
    assert (doc["schema"], doc["annotation_origin"], doc["adr"]) == (mpd.SCHEMA, "map_projected", "D-563")
    assert len(doc["frames"]) == 8 and doc["rejected"] == {"no_detection": 1}
    assert doc["params"]["ignore_top"] == 110 and doc["source"]["ceiling_calibration_revision"] == "paint-test"
    assert doc["pose_stats"]["clock_offset_estimate_s"] is None or abs(doc["pose_stats"]["clock_offset_estimate_s"] - 2.0) < 1.0
    assert all(f["line_iou"] > 0.9 and f["drivable_px"] > 0 for f in doc["frames"])
    with pytest.raises(ValueError, match="new output"):
        _derived(tmp_path)


def test_map_projected_dataset_reviews_and_admits_drivable_head(tmp_path, monkeypatch):
    import train_job
    from store import Store
    from test_lane_derived_drivable import review
    from test_lane_derived_training import Boundary, _setup
    monkeypatch.setattr(ldd, "MIN_CANARIES", 1)
    config, _, _ = _setup(tmp_path / "base")
    out = _derived(tmp_path, n=6)
    path, digest = Store(config["store"]).put_dataset(out, "map-projected")
    config["dataset"] = "map-projected@" + digest
    monkeypatch.setattr(train_job, "gpu_lease", lambda: pytest.fail("no real GPU"))
    with pytest.raises(train_job.JobError, match="not finalized"):
        train_job.run(config, tmp_path / "job")
    review(tmp_path, out, canaries=0.5)
    ldd.finalize(out)
    path, digest = Store(config["store"]).put_dataset(out, "map-projected")
    config["dataset"] = "map-projected@" + digest
    seen = {}

    def candidate(cfg, job, ds, profile, training, parent, inputs, check):
        seen.update(inputs)
        check()
        raise Boundary

    monkeypatch.setattr(train_job, "_run_drivable_candidate", candidate)
    with pytest.raises(Boundary):
        train_job.run(config, tmp_path / "job")
    assert (seen["lane_derived"]["annotation_origin"], seen["lane_derived"]["adr"]) == ("map_projected", "D-563")
    assert seen["lane_derived"]["judge"]["canaries"]["rate"] == 1.0
