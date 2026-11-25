"""cell_remap_plan: the remap view rises only to clear the obstacle, never below the configured height."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_calibrate as cc  # noqa: E402
import cell_remap_plan as rp  # noqa: E402
from test_omx_cell_calibrate import FIX, arm_a, arm_b  # noqa: E402

PLAIN = {"coarse": {"z_view": 0.12}, "sites": {}}  # no surface_z anywhere: the table counts as 0.0
CELL = {
    "coarse": {"z_view": 0.11},
    "calibrate": {"map_sites": ["pallet", "beltend", "stack"]},
    "sites": {"pallet": {"surface_z": -0.01}, "beltend": {"surface_z": -0.0721}, "stack": {"surface_z": 0.031}},
}


def test_resolve_z_view_keeps_base_when_clear_and_raises_for_tall_obstacle():
    same, info0 = rp.resolve_z_view(PLAIN, obstacle_mm=None)
    assert same is PLAIN and info0["raised"] is False and info0["z_view"] == pytest.approx(0.12)

    low, info_low = rp.resolve_z_view(PLAIN, obstacle_mm=66.0)  # 0.0 + (66 + 35) / 1000 = 0.101 < 0.12
    assert low is PLAIN and info_low["raised"] is False and info_low["z_view"] == pytest.approx(0.12)

    raised, info_hi = rp.resolve_z_view(PLAIN, obstacle_mm=100.0)  # 0.0 + (100 + 35) / 1000 = 0.135
    assert info_hi["raised"] is True and info_hi["z_view"] == pytest.approx(0.135)
    assert raised["coarse"]["z_view"] == pytest.approx(0.135)
    assert PLAIN["coarse"]["z_view"] == pytest.approx(0.12)  # the cell config itself is not written


def test_resolve_z_view_ignores_the_recessed_chute_and_the_raised_layer():
    # Sunken chutes (beltend=-0.0721) and raised container layers (stack=+0.031) do not shift the tabletop (-0.01).
    _, cell_low = rp.resolve_z_view(CELL, obstacle_mm=66.0)
    assert cell_low["raised"] is False and cell_low["z_view"] == pytest.approx(0.11)
    assert cell_low["table_z_m"] == pytest.approx(-0.01)
    raised_cell, cell_hi = rp.resolve_z_view(CELL, obstacle_mm=100.0)
    assert cell_hi["table_z_m"] == pytest.approx(-0.01) and cell_hi["raised"] is True
    assert raised_cell["coarse"]["z_view"] == pytest.approx(0.125)  # -0.01 + (100 + 35) / 1000


@pytest.mark.parametrize("obstacle_mm", [True, float("nan"), float("inf"), -5.0, 0.0])
def test_resolve_z_view_ignores_a_nonsensical_obstacle_and_keeps_the_base(obstacle_mm):
    same, info = rp.resolve_z_view(PLAIN, obstacle_mm=obstacle_mm)
    assert same is PLAIN and info["raised"] is False and info["z_view"] == pytest.approx(0.12)


def test_remap_view_records_a_failed_depth_capture_and_keeps_the_base_view(monkeypatch):
    pytest.importorskip("cv2")
    import cell_cal_eval

    monkeypatch.setattr(cell_cal_eval, "top_has_depth", lambda config: True)

    def busy():
        raise OSError("depth device busy")

    view, info = rp.remap_view(PLAIN, None, None, busy)
    assert view is PLAIN and info["raised"] is False and info["depth_error"] == "depth device busy"
    assert "sites_mm" not in info and "edge_px" not in info


def test_site_obstacle_mm_reads_the_tallest_block_under_a_site(monkeypatch):
    """A synthetic D435 frame: a flat table 650 mm away with a 60 mm block under the pallet site; the alignment is the identity."""
    import cell_depth

    colour = np.zeros((48, 64, 3), np.uint8)
    depth = np.full((48, 64), 650, np.uint16)
    depth[20:28, 30:40] = 590  # 60 mm tall; 80 of 3072 pixels, far below the quarter that would make the block the "table"
    config = {"calibrate": {"map_sites": ["pallet"]}, "sites": {"pallet": {"auto_roi": [24, 12, 50, 40]}}}
    monkeypatch.setattr(cell_depth, "align_edges", lambda colour, heights: (np.eye(3, dtype=np.float32), 1.25))
    meta = rp.site_obstacle_mm(config, depth, colour)
    assert meta["obstacle_mm"] == pytest.approx(60.0, abs=0.5) and meta["sites_mm"] == {"pallet": pytest.approx(60.0, abs=0.5)}
    assert meta["edge_px"] == 1.25 and meta["plane_nz"] == pytest.approx(1.0, abs=1e-6)
    # a block under a site that is not remapped is no obstacle, and a flat table has none
    other = {"calibrate": {"map_sites": ["belt"]}, "sites": {"belt": {"auto_roi": [0, 0, 10, 10]}}}
    assert rp.site_obstacle_mm(other, depth, colour)["obstacle_mm"] == 0.0
    assert rp.site_obstacle_mm(config, np.full((48, 64), 650, np.uint16), colour)["obstacle_mm"] == 0.0


def test_site_obstacle_mm_refuses_without_a_frame_or_with_a_loose_alignment(monkeypatch):
    import cell_depth

    colour = np.zeros((48, 64, 3), np.uint8)
    with pytest.raises(ValueError, match="no frame"):
        rp.site_obstacle_mm({"sites": {}}, None, colour)
    with pytest.raises(ValueError, match="no frame"):
        rp.site_obstacle_mm({"sites": {}}, np.full((48, 64), 650, np.uint16), None)
    for edge_px in (float("inf"), float("nan"), 9.0):
        monkeypatch.setattr(cell_depth, "align_edges", lambda colour, heights, edge_px=edge_px: (np.eye(3, dtype=np.float32), edge_px))
        with pytest.raises(ValueError, match="loose"):
            rp.site_obstacle_mm({"sites": {}}, np.full((48, 64), 650, np.uint16), colour)


def test_remap_obstacle_height_includes_a_small_taller_return(monkeypatch):
    import cell_cal_eval
    import cell_depth

    depth = np.full((180, 180), 650, np.uint16)
    depth[20:100, 20:100] = 626
    depth[50:52, 50:55] = 538  # 112 mm above table, less than one percent of the already raised ROI
    colour = np.zeros(depth.shape + (3,), np.uint8)
    config = {"coarse": {"z_view": 0.06}, "calibrate": {"map_sites": ["target"]},
              "sites": {"target": {"auto_roi": [20, 20, 100, 100]}}}
    monkeypatch.setattr(cell_depth, "align_edges", lambda *a: (np.eye(3), 2.0))
    monkeypatch.setattr(cell_cal_eval, "top_has_depth", lambda c: True)

    view, measured = rp.remap_view(config, colour, depth_capture=lambda: depth)
    assert "depth_error" not in measured
    assert measured["obstacle_mm"] == pytest.approx(112.0, abs=0.2)
    assert view["coarse"]["z_view"] == pytest.approx(0.147, abs=0.0002)


@pytest.mark.parametrize(("defect", "message"), [
    ("missing_roi", "target: missing remap depth ROI"),
    ("undefined_site", "target: missing remap depth ROI"),
    ("clipped_roi", "target: remap ROI is outside the depth frame"),
    ("invalid_depth", "target: insufficient depth coverage"),
    ("sparse_depth", "target: insufficient depth coverage"),
    ("empty_frame", "the D435 frame has no usable table plane"),
    ("sparse_raised", "target: inconclusive raised obstacle"),
    ("out_of_range", "target: obstacle return exceeds the measured height range"),
])
def test_remap_depth_requires_coverage_at_every_site(monkeypatch, defect, message):
    import cell_cal_eval
    import cell_depth

    depth = np.full((48, 64), 650, np.uint16)
    colour = np.zeros((48, 64, 3), np.uint8)
    transform = np.eye(3, dtype=np.float32)
    config = {"coarse": {"z_view": 0.11}, "calibrate": {"map_sites": ["valid", "target"]},
              "sites": {"valid": {"auto_roi": [5, 5, 20, 20]}, "target": {"auto_roi": [40, 10, 60, 32]}}}
    if defect == "missing_roi":
        config["sites"]["target"].clear()
    elif defect == "undefined_site":
        del config["sites"]["target"]
    elif defect == "clipped_roi":
        transform[0, 2] = 5
    elif defect in ("invalid_depth", "sparse_depth"):
        depth[10:32, 40:60] = 0
        if defect == "sparse_depth":
            depth[10:17, 40:60] = 650
    elif defect == "empty_frame":
        depth.fill(0)
    elif defect == "sparse_raised":
        depth[10:12, 40:45] = 590
    else:
        depth[10:16, 40:46] = 400
    monkeypatch.setattr(cell_depth, "align_edges", lambda *a: (transform, 2.0))
    monkeypatch.setattr(cell_cal_eval, "top_has_depth", lambda c: True)

    view, result = rp.remap_view(config, colour, depth_capture=lambda: depth)
    assert view is config and result["obstacle_mm"] is None
    assert result["depth_error"].startswith(message)
    view, override = rp.remap_view(config, colour, obstacle_mm=100,
                                   depth_capture=lambda: pytest.fail("override must not read depth"))
    assert view["coarse"]["z_view"] == pytest.approx(0.135)
    assert "depth_error" not in override


def test_obstacle_mm_override_must_be_a_positive_finite_number(capsys):
    """The override stands in for the D435 measurement (cell_calibrate --obstacle-mm): 0, a negative sign or nan would
    otherwise skip the measurement and run at the configured height."""
    import cell_calibrate as cc

    for bad in ("-66", "0", "nan", "inf"):
        with pytest.raises(SystemExit):
            cc.main(["--config", "unused.json", "auto", "--only", "remap", "--obstacle-mm", bad])
        assert "positive finite" in capsys.readouterr().err


def test_plan_only_with_obstacle_mm_refuses_when_raised_z_view_exceeds_arm_b_window(tmp_path, monkeypatch, capsys):
    import socket

    import cell_pipeline

    def no_open(*a, **k):
        raise AssertionError("plan-only opened a camera, FIFO or port")

    monkeypatch.setattr(cell_pipeline, "FifoCell", no_open)
    monkeypatch.setattr(socket.socket, "connect", no_open)
    config = {k: v for k, v in arm_b().items() if k != "plan"}
    config["plan_path"] = str(FIX / "plan.json")
    path = tmp_path / "arm_b_obs.json"
    path.write_text(json.dumps(config))

    assert cc.main(["--config", str(path), "auto", "--plan-only", "--obstacle-mm", "66"]) == 0
    ok_out = json.loads(capsys.readouterr().out)
    assert ok_out["refused"] is None and ok_out["z_view"]["raised"] is False

    assert cc.main(["--config", str(path), "auto", "--plan-only", "--obstacle-mm", "100"]) == 2
    bad_out = json.loads(capsys.readouterr().out)
    assert bad_out["z_view"]["raised"] is True and bad_out["z_view"]["z_view"] == pytest.approx(0.135)
    assert bad_out["refused"] and "wrist_flex.pos" in bad_out["refused"]


def test_live_route_check_returns_before_remap_admission(tmp_path, monkeypatch, capsys):
    import cell_pipeline
    import cell_route_check

    cfg = arm_a()
    cfg.update(plan_path=str(FIX / "plan.json"), calibration_path=str(tmp_path / "cal.json"),
               work_dir=str(tmp_path / "work"), io=str(tmp_path / "io"), cameras={})
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg))

    def forbidden(*args, **kwargs):
        pytest.fail("read-only route check attempted remap admission or motion")

    class ReadOnlyCell:
        def frame(self, role):
            assert role == "top"
            return np.zeros((32, 32, 3), np.uint8)

        act = forbidden

    route = {"source": "temp-a", "destination": "ship-h1"}
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a, **k: ReadOnlyCell())
    monkeypatch.setattr(cell_route_check, "route_check", lambda c, s, d: {"source": s, "destination": d})
    monkeypatch.setattr(cc, "check", lambda *a, **k: {})
    monkeypatch.setattr(cc, "stale", lambda found: ["remap"])
    monkeypatch.setattr(cc.rp, "remap_view", forbidden)
    monkeypatch.setattr(cc, "remap", forbidden)

    assert cc.main(["--config", str(config_path), "check", "--route", *route.values()]) == 0
    assert json.loads(capsys.readouterr().out) == {"check": {"route": route}, "todo": ["remap"]}


def test_remap_auto_raises_z_view_from_depth_and_records_effective_z_view(tmp_path, monkeypatch, capsys):
    pytest.importorskip("cv2")
    import cell_cal_eval
    import cell_hooks
    import cell_pipeline as cp

    cfg = arm_a()  # joint_max wrist_flex=60 via config-planb
    cfg["coarse"]["z_view"] = 0.11
    cfg["sites"]["pallet"]["surface_z"] = -0.01
    cfg["sites"]["pallet"]["auto_roi"] = [0, 0, 32, 32]
    cfg["plan_path"] = str(FIX / "plan.json")
    cfg.pop("plan", None)
    cal_path = tmp_path / "cal.json"
    ref_path = tmp_path / "ref.jpg"
    cfg["calibration_path"] = str(cal_path)
    cfg["preflight"] = {"reference_top": str(ref_path)}
    cfg["work_dir"] = str(tmp_path / "work")
    cfg["io"] = str(tmp_path / "io")
    cfg["cameras"] = {"top": {"url": "http://unused/top.jpg", "depth_device": "/dev/unused"}}
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg))

    class FakeCell:
        def __init__(self, *a, **k):
            pass

        def frame(self, name):
            return np.zeros((32, 32, 3), np.uint8)

    checked_frame = None

    def fake_check(config, calibration, targets, frame, params):
        nonlocal checked_frame
        checked_frame = frame
        return {"camera_moved": False, "missing_map": ["pallet"], "targets": [], "missing_bias": [], "missing_surface": []}

    def fake_site_obstacle(config, depth, frame):
        assert frame is checked_frame
        return {"obstacle_mm": 100.0, "sites_mm": {"pallet": 100.0}, "edge_px": 4.2}

    monkeypatch.setattr(cp, "FifoCell", FakeCell)
    monkeypatch.setattr(cc, "check", fake_check)
    monkeypatch.setattr(cell_cal_eval, "top_has_depth", lambda c: True)
    monkeypatch.setattr(cc, "depth_capture", lambda: np.full((16, 16), 700, np.uint16))
    monkeypatch.setattr(cc.rp, "site_obstacle_mm", fake_site_obstacle)
    monkeypatch.setattr(cell_hooks, "stills", lambda *a, **k: type("S", (), {"close": lambda self: None})())

    seen_z = []

    def fake_remap(cell, r_cfg, points, work, at_stop=None):
        seen_z.append(r_cfg["coarse"]["z_view"])
        return {"z_view": r_cfg["coarse"]["z_view"], "loo_error_mm": {"max": 1.0}, "homography": np.eye(3).tolist(), "points": []}

    monkeypatch.setattr(cc, "remap", fake_remap)

    assert cc.main(["--config", str(cfg_path), "auto", "--only", "remap", "--commissioning", "--person-at-switch"]) == 0
    assert seen_z == [pytest.approx(0.125)]
    saved_cal = json.loads(cal_path.read_text())
    assert saved_cal["sites"]["pallet"]["z_view"] == pytest.approx(0.125)
    # Fail-closed refusal BEFORE motion when elevated obstacle pushes wrist_flex past window
    cfg["joint_max"] = {"wrist_flex.pos": 51.5}
    cfg_path.write_text(json.dumps(cfg))
    seen_z.clear()
    capsys.readouterr()
    assert cc.main(["--config", str(cfg_path), "auto", "--only", "remap", "--commissioning", "--person-at-switch"]) == 2
    assert seen_z == []
    assert "wrist_flex.pos" in json.loads(capsys.readouterr().out.splitlines()[-1])["refused"]
    # A D435 frame that could not be taken is refused before any move; --obstacle-mm is the explicit way past it
    cfg["joint_max"] = arm_a()["joint_max"]
    cfg_path.write_text(json.dumps(cfg))
    monkeypatch.setattr(cc, "depth_capture", lambda: None)
    monkeypatch.setattr(cc.rp, "site_obstacle_mm", lambda c, d, f: (_ for _ in ()).throw(ValueError("the D435 depth capture returned no frame")))
    seen_z.clear()
    capsys.readouterr()
    assert cc.main(["--config", str(cfg_path), "auto", "--only", "remap", "--commissioning", "--person-at-switch"]) == 2
    out = capsys.readouterr().out
    assert seen_z == [] and "obstacle not measured" in out and out.splitlines()[-1].startswith('{"refused"')
    # fresh calibration and reference files: a second remap here would carry regions from the blank frame saved above
    cfg["calibration_path"], cfg["preflight"] = str(tmp_path / "cal-override.json"), {"reference_top": str(tmp_path / "ref-override.jpg")}
    cfg_path.write_text(json.dumps(cfg))
    # the override stands in for the measurement: the same 100 mm obstacle raises the view exactly as before
    assert cc.main(["--config", str(cfg_path), "auto", "--only", "remap", "--commissioning", "--person-at-switch", "--obstacle-mm", "100"]) == 0
    assert seen_z == [pytest.approx(0.125)]
