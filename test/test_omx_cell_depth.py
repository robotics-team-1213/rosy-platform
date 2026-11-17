"""cell_depth: heights from a tilted depth view, put onto the colour view by the objects themselves."""
import sys
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_depth as cd  # noqa: E402

SCALE, SHIFT = 0.62, (106.0, 100.0)  # colour -> depth, as measured on the cell 2026-11-01


def scene(tilt_deg=10.0, floor_below_x=None):
    """A table 620 mm away tilted about x, two 76 mm boxes and a plate 20 mm high; depth and colour views.
    `floor_below_x`: depth columns left of it are a surface 60 mm under the table."""
    h, w = 480, 640
    ys, xs = np.mgrid[0:h, 0:w]
    rays = np.dstack([(xs - w / 2) / cd.FOCAL_PX, (ys - h / 2) / cd.FOCAL_PX, np.ones((h, w))])
    t = np.radians(tilt_deg)
    normal = np.array([0.0, -np.sin(t), -np.cos(t)])  # toward the camera
    colour = np.zeros((h, w, 3), np.uint8)
    boxes = [(300, 160, 330, 260), (350, 160, 380, 260)]  # colour pixels (x0, y0, x1, y1)
    lift = np.zeros((h, w))
    to_colour = lambda x, y: ((x - SHIFT[0]) / SCALE, (y - SHIFT[1]) / SCALE)  # noqa: E731
    cxs, cys = to_colour(xs, ys)
    for x0, y0, x1, y1 in boxes:
        colour[y0:y1, x0:x1] = (0, 128, 255)  # orange (BGR)
        lift[(cxs >= x0) & (cxs < x1) & (cys >= y0) & (cys < y1)] = 76.0
    plate = (np.hypot(cxs - 150, cys - 380) < 60) & (np.hypot(cxs - 150, cys - 380) > 25)
    lift[plate] = 20.0
    if floor_below_x is not None:
        lift[:, :floor_below_x] = -60.0
    cv2.circle(colour, (150, 380), 60, (150, 150, 150), -1)  # the plate is seen in colour too (grey: not in the mask)
    cv2.circle(colour, (150, 380), 25, (0, 0, 0), -1)
    # depth along each ray to the plane n.p + 620 = lift (heights measured along the normal)
    depth = (lift - 620.0) / (rays @ normal)
    return depth.astype(np.uint16), colour


def test_the_table_is_found_through_the_tilt_and_heights_are_measured_from_it():
    depth, _ = scene()
    heights = cd.height_map(depth, cd.table_plane(depth))
    assert np.nanmedian(heights[400:470, 400:600]) == pytest.approx(0.0, abs=1.5)
    normal, _ = cd.table_plane(depth)
    assert np.degrees(np.arccos(abs(normal[2]))) == pytest.approx(10.0, abs=0.5)


def test_the_colour_view_is_put_onto_the_depth_view_by_the_objects():
    depth, colour = scene()
    heights = cd.height_map(depth, cd.table_plane(depth))
    mask = cv2.inRange(cv2.cvtColor(colour, cv2.COLOR_BGR2HSV), (5, 120, 120), (22, 255, 255))
    m, overlap = cd.align(mask, heights)
    assert overlap > 0.9
    assert cd.height_at(heights, m, (315, 210)) == pytest.approx(76.0, abs=3.0)
    assert cd.height_at(heights, m, (450, 300)) == pytest.approx(0.0, abs=3.0)
    assert cd.plate_top(heights, m, (150, 380)) == pytest.approx(20.0, abs=3.0)


def test_a_ring_with_no_plate_reads_none():
    depth, _ = scene()
    heights = cd.height_map(depth, cd.table_plane(depth))
    assert cd.plate_top(heights, np.float32([[SCALE, 0, SHIFT[0]], [0, SCALE, SHIFT[1]]]), (500, 120)) is None


def test_the_edges_put_the_colour_view_onto_the_depth_view_even_with_objects_in_one_row():
    depth, colour = scene()
    heights = cd.height_map(depth, cd.table_plane(depth))
    m, edge_px = cd.align_edges(colour, heights)
    assert edge_px < 2.0
    assert m[0, 0] == pytest.approx(SCALE, abs=0.02)
    assert (m[0, 2], m[1, 2]) == pytest.approx(SHIFT, abs=4.0)
    assert cd.height_at(heights, m, (315, 210)) == pytest.approx(76.0, abs=3.0)


def test_a_larger_surface_under_the_table_does_not_become_the_table():
    depth, _ = scene(floor_below_x=330)  # the lower surface holds more points than the table
    heights = cd.height_map(depth, cd.table_plane(depth))
    assert np.nanmedian(heights[400:470, 400:600]) == pytest.approx(0.0, abs=1.5)
    assert np.nanmedian(heights[400:470, 50:300]) == pytest.approx(-60.0, abs=2.0)


def test_verify_profile_depth_checks_depth_touch_and_keeps_legacy_cli(tmp_path, capsys):
    import json

    depth, colour = scene()
    raw_path, img_path = tmp_path / "top.raw", tmp_path / "top.jpg"
    depth.tofile(raw_path)
    cv2.imwrite(str(img_path), colour)
    # Legacy CLI (--depth --colour --px) remains intact
    assert cd.main(["--depth", str(raw_path), "--colour", str(img_path), "--px", "315,210", "--base", "150,380"]) == 0
    legacy = json.loads(capsys.readouterr().out)
    assert legacy["heights_mm"]["315,210"] == pytest.approx(76.0, abs=4.0) and legacy["plates_mm"]["150,380"] == pytest.approx(20.0, abs=4.0)

    # plate at (150, 380) is 20 mm above table; empty table pixel (450, 300) is -0.020 m rel plate, box (315, 210) is +0.056 m rel plate
    work = tmp_path / "work"
    work.mkdir()
    (work / "surface-table_bay.json").write_text(json.dumps({"result": "touched", "surface_z": -0.020, "measured": "2026-11-16 00:00"}))
    (work / "surface-no_contact_bay.json").write_text(json.dumps({"result": "no contact", "site": "no_contact_bay"}))
    # Identity homography on colour px: pixel = [450 + x*1000, 300 + y*1000]
    cal = {"schema": "rosy.omx-cell-calibration.v1", "sites": {"table_bay": {
        "z_view": 0.0, "loo_error_mm": {"max": 2.4, "mean": 1.2},
        "homography": [[0.001, 0.0, -0.45], [0.0, 0.001, -0.30], [0.0, 0.0, 1.0]],
    }}}
    cfg = {
        "arm_id": "arm_test", "work_dir": str(work), "calibration_path": str(tmp_path / "cal.json"),
        "cameras": {"top": {"height_m": 0.62, "plate_px": [150, 380]}},
        "calibrate": {"map_sites": ["table_bay"]},
        "sites": {
            "table_bay": {"surface_z": -0.020, "start": [0.0, 0.0], "place": [0.02, 0.0]},
            "occupied_box": {"map_from": "table_bay", "surface_z": -0.020, "start": [0.0, 0.0], "place": [-0.135, -0.09]},
            "no_contact_bay": {"map_from": "table_bay", "surface_z": -0.020, "start": [0.0, 0.0], "place": [0.02, 0.0]},
        },
    }
    (tmp_path / "cal.json").write_text(json.dumps(cal))
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg))

    assert cd.main(["verify", "--config", str(cfg_path), "--depth", str(raw_path), "--colour", str(img_path), "--write"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["schema"] == "rosy.omx-cell-depth-verify.v1" and (work / "depth-verify.json").is_file()
    assert rep["camera_top"]["plate_mm"] == pytest.approx(20.0, abs=3.0)
    assert rep["sites"]["table_bay"]["flags"] == [] and abs(rep["sites"]["table_bay"]["depth_diff_mm"]) <= 6.0
    assert rep["sites"]["no_contact_bay"]["touch_surface_z_m"] is None
    assert "depth_diff_gt_6mm" in rep["sites"]["occupied_box"]["flags"]
    assert "place_vs_start_step_gt_8mm" in rep["sites"]["occupied_box"]["flags"]
    assert rep["verdict"] == "fail"


def test_verify_profile_depth_handles_polygon_surface_px_and_fetch_errors():
    depth, colour = scene()
    # Box in scene() sits around colour px (315, 210) at +76 mm above table (+56 mm above 20 mm plate)
    cfg = {
        "arm_id": "arm_poly",
        "cameras": {"top": {"height_m": 0.62, "plate_px": [150, 380]}},
        "sites": {
            "belt_poly": {
                "surface_z": 0.056,
                "surface_px": [[302, 198], [328, 198], [328, 222], [302, 222]],
            },
        },
    }
    rep = cd.verify_profile_depth(cfg, None, depth=depth, colour=colour)
    site = rep["sites"]["belt_poly"]
    assert site["surface_px_mm"] == pytest.approx(76.0, abs=4.0)
    assert site["place_mm"] == pytest.approx(76.0, abs=4.0)
    assert site["depth_surface_z_m"] == pytest.approx(0.056, abs=0.005)
    assert site["flags"] == []
    assert cd._fetch_colour_frame("file:///etc/passwd") is None
    assert cd._fetch_colour_frame("http://127.0.0.1:9/no-such.jpg") is None


def test_a_short_capture_timeout_is_raised_to_the_frames_it_must_wait_for(tmp_path, monkeypatch):
    """The cell's 11-13 copy gave v4l2-ctl 1.8 s for 13 frames at 6 fps (2.4-2.6 s measured): always None."""
    import subprocess

    dev, raw = tmp_path / "depth", tmp_path / "depth.raw"
    dev.touch()
    seen = []

    def run(cmd, timeout, **kwargs):
        seen.append(timeout)
        np.full((480, 640), 610, np.uint16).tofile(raw)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(cd.subprocess, "run", run)
    assert cd.capture_top_depth_z16(str(dev), raw, timeout_s=1.8) is not None
    assert seen == [cd.MIN_CAPTURE_S] and cd.MIN_CAPTURE_S > 13 / 6
    assert cd.capture_top_depth_z16(str(dev), raw, timeout_s=12.0) is not None and seen[-1] == 12.0
