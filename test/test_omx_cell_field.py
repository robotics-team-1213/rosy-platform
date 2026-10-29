"""cell_field: the field tool ranks clear pushes away from the neighbour, summarises a carry's attempt rows, and
shows a dark scene brightened side by side."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_field as cf  # noqa: E402


def test_clear_pushes_rank_away_from_the_neighbour_then_shorter():
    cands = [{"px": (1, 1), "dir": (-1, 0), "half_mm": 15, "mm": 15, "blocked": []},
             {"px": (1, 1), "dir": (1, 1), "half_mm": 15, "mm": 25, "blocked": []},
             {"px": (1, 1), "dir": (1, 1), "half_mm": 15, "mm": 15, "blocked": []},
             {"px": (1, 1), "dir": (1, 0), "half_mm": 15, "mm": 15, "blocked": [["behind", "off the surface"]]}]
    ranked = cf.rank_pushes(cands, (1, 1))
    assert [(c["dir"], c["mm"]) for c in ranked] == [((1, 1), 15), ((1, 1), 25), ((-1, 0), 15)]


def test_a_carry_summary_keeps_what_decided_it():
    row = {"attempt_id": "a1", "from": "floor", "to": "pinky", "outcome": "failed", "fail_class": "contact at run descend_place",
           "plan": {"pick": {"x": 0.1}}, "wrist": {"looks": [{"box_minus_tcp_mm": [9.4, 3.4]}, {"box_minus_tcp_mm": [2.5, 2.2]}]},
           "transfer": {"result": "contact", "at": "run descend_place", "steps": [
               {"command": "goto above_pick"}, {"command": "wrist", "verdict": "pass"},
               {"command": "run grasp_pick", "holding": True}, {"command": "run descend_place", "contact": True}]}}
    (s,) = cf.summarize([row])
    assert s["looks"] == [[9.4, 3.4], [2.5, 2.2]] and s["at"] == "run descend_place"
    assert [st["command"] for st in s["steps"]] == ["wrist", "run grasp_pick", "run descend_place"]


def test_a_dark_scene_is_brightened_side_by_side():
    dark = np.full((48, 64, 3), 30, np.uint8)
    pic = cf.side_by_side(dark, dark)
    assert pic.shape == (48, 128, 3) and pic[40, 30].mean() > 80  # 30 -> about 90 for a person to see
