"""cell_replay: a saved frame gives the same dry-run decision as the live cell, with no arm command sent."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_omx_cell_auto_pick import CATALOG, CONFIG, CONT2, ROI, Cell, biased_map, cal  # noqa: E402

import cell_replay  # noqa: E402


def test_a_saved_frame_replays_the_dry_run_and_draws_the_plan(tmp_path):
    path = biased_map(tmp_path)
    frame = Cell([CONT2]).frame("top")  # what the live top camera would show
    out = cell_replay.replay(CONFIG, cal.load(path), CATALOG, frame, "pinky", "0.060,0.090", ROI, path)
    assert out["result"] == "planned"
    row = out["attempts"][0]
    assert row["chosen"]["object"] == "container-2" and "long_axis_deg" in row
    vis = cell_replay.picture(CONFIG, cal.load(path), CATALOG, frame, out, "pinky")
    assert vis.shape == frame.shape and (vis != frame).any()


def test_a_replay_sends_no_arm_command():
    cell = cell_replay.FrameCell(None)
    assert cell.act("goto above_pick")["ok"] is False and cell.commands == ["goto above_pick"]
