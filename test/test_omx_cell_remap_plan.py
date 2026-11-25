"""cell_remap_plan: the remap view rises only to clear the obstacle, never below the configured height."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_remap_plan as rp  # noqa: E402

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


def test_obstacle_mm_override_must_be_a_positive_finite_number(capsys):
    """The override stands in for the D435 measurement (cell_calibrate --obstacle-mm): 0, a negative sign or nan would
    otherwise skip the measurement and run at the configured height."""
    import cell_calibrate as cc

    for bad in ("-66", "0", "nan", "inf"):
        with pytest.raises(SystemExit):
            cc.main(["--config", "unused.json", "auto", "--only", "remap", "--obstacle-mm", bad])
        assert "positive finite" in capsys.readouterr().err
