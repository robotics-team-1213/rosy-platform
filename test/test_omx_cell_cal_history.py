"""Calibration writes keep the values they replace (2026-11-26)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_cal_history  # noqa: E402
import cell_pivot_bias  # noqa: E402


def test_keep_copies_the_existing_files_and_never_deletes(tmp_path):
    cal, bias = tmp_path / "cal.json", tmp_path / "cal.bias.json"
    cal.write_text('{"sites": {"a": 1}}')
    assert cell_cal_history.keep([cal, bias], "map", clock=lambda: 0.5) == tmp_path / "calibration-history" / "19700101T000000.500000-map"
    kept = tmp_path / "calibration-history" / "19700101T000000.500000-map"
    assert sorted(p.name for p in kept.iterdir()) == ["cal.json"] and cal.read_text() == '{"sites": {"a": 1}}'
    assert cell_cal_history.keep([bias], "bias") is None  # nothing there yet: nothing to keep
    cell_cal_history.keep([cal], "map", clock=lambda: 1.0)
    assert len(list((tmp_path / "calibration-history").iterdir())) == 2


def test_a_history_that_cannot_be_written_does_not_stop_the_save(tmp_path, monkeypatch, capsys):
    cal = tmp_path / "cal.json"
    cal.write_text("{}")
    monkeypatch.setattr(cell_cal_history.shutil, "copy2", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    assert cell_cal_history.keep([cal], "map") is None and "disk full" in capsys.readouterr().err
    assert cell_cal_history.keep([cal], "map", clock=lambda: 1 / 0) is None  # nothing keep() meets may raise


def test_a_saved_map_keeps_the_map_reference_and_bias_it_replaced(tmp_path):
    import numpy as np
    import cell_calibrate_bound as bound

    cal, ref = tmp_path / "cal.json", tmp_path / "ref.jpg"
    config = {"sites": {"pinky": {"auto_roi": [0, 0, 8, 8]}}}
    bound.save_bound_map_reference(cal, ref, {"sites": {"pinky": {"n": 1}}}, config, np.full((8, 8, 3), 80, np.uint8))
    (tmp_path / "cal.bias.json").write_text('{"regions": [1]}')
    bound.save_bound_map_reference(cal, ref, {"sites": {"pinky": {"n": 2}}}, config, np.full((8, 8, 3), 150, np.uint8))
    (kept,) = (tmp_path / "calibration-history").iterdir()
    assert sorted(p.name for p in kept.iterdir()) == ["cal.bias.json", "cal.json", "ref.jpg"]
    assert json.loads((kept / "cal.json").read_text())["sites"]["pinky"]["n"] == 1
    assert json.loads(cal.read_text())["sites"]["pinky"]["n"] == 2


def test_every_saved_bias_keeps_the_regions_it_replaced(tmp_path):
    path = tmp_path / "cal.bias.json"
    region = {"site": "belt", "point_m": [0.1, 0.2], "bias_mm": [1.0, 2.0], "kind": "pivot", "radius_mm": 20.0}
    cell_pivot_bias.save_bias(path, region)
    cell_pivot_bias.save_bias(path, {**region, "bias_mm": [3.0, 4.0]})
    (kept,) = (tmp_path / "calibration-history").iterdir()
    assert json.loads((kept / "cal.bias.json").read_text())["regions"][0]["bias_mm"] == [1.0, 2.0]
    assert json.loads(path.read_text())["regions"][0]["bias_mm"] == [3.0, 4.0]
