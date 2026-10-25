"""Isaac cell frames: the real cell's top-down chunks aimed at the Isaac box and place point, every frame kept."""
import importlib.util
import json
import math
from pathlib import Path
import sys

import pytest

pytest.importorskip("yaml")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("isaac_cell_frames", OMX / "isaac_cell_frames.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    import grasp_planner
finally:
    sys.path.remove(str(OMX))

KIN = grasp_planner.Planner({"fps": 30, "limits": json.loads(
    (OMX / "grasp-plan.example.json").read_text())["limits"]}).kin


def tcp(q):
    return KIN.fk(list(q[:5]))


@pytest.mark.parametrize("scenario", ["nominal", "overhang", "wrong-yaw"])
def test_frames_reach_the_isaac_box_and_place_point_at_30_fps(scenario):
    value = m.frames_for(scenario)
    f = m.fixture()
    assert [p["phase_id"] for p in value["phases"]] == ["approach", "grasp", "transfer", "release"]
    frames = [q for p in value["phases"] for q in p["frames"]]
    assert all(len(q) == 6 and all(math.isfinite(v) for v in q) for q in frames)
    steps = [max(abs(a - b) for a, b in zip(p[:5], q[:5])) for p, q in zip(frames, frames[1:])]
    assert max(steps) < 0.02  # 30 fps under the guard's speed: no thinning, no jumps
    grasp = tcp(value["phases"][0]["frames"][-1])
    (bx, by, _), _ = f.box_start(scenario)
    assert math.dist((grasp.x, grasp.y), (bx, by)) < 0.002 and grasp.z == pytest.approx(f.TRAY["top"] + f.BOX - 0.015, abs=0.002)
    place = tcp(value["phases"][2]["frames"][-1])
    px, py, _ = f.place_point(scenario)
    assert math.dist((place.x, place.y), (px, py)) < 0.002
    assert value["phases"][1]["frames"][-1][5] == pytest.approx(-0.12)  # squeezes; the box stops the fingers


def test_the_wrong_yaw_scenario_keeps_the_site_yaw_on_a_turned_box():
    nominal, turned = m.frames_for("nominal"), m.frames_for("wrong-yaw")
    assert turned["box_yaw_deg"] - nominal["box_yaw_deg"] == pytest.approx(20.0)
    assert turned["phases"][0]["frames"][-1] == pytest.approx(nominal["phases"][0]["frames"][-1])  # same jaw yaw


def test_a_case_turns_the_jaws_by_its_grasp_turn_and_travels_with_the_frames():
    case = {"box": [0.0, 0.0, 25.0], "place": "belt", "grasp_turn": 10.0, "expect": None}
    value, nominal = m.frames_for(case), m.frames_for("nominal")
    assert value["scenario"] == "case" and value["case"] == case and value["box_yaw_deg"] == pytest.approx(
        nominal["box_yaw_deg"] + 25.0)
    wrist = value["phases"][0]["frames"][-1][4] - nominal["phases"][0]["frames"][-1][4]
    # joint5 rolls the jaws by the turn; the jaws are symmetric, so the IK may take the roll half a turn away
    assert abs((wrist + math.pi / 2) % math.pi - math.pi / 2) == pytest.approx(math.radians(10.0), abs=0.01)
