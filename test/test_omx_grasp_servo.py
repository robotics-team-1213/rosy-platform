"""The probe sets each axis's direction, so the same loop converges over Pinky and over the belt (inverted view)."""
import importlib.util
from pathlib import Path
import sys

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("grasp_servo", OMX / "grasp_servo.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.remove(str(OMX))

SITE = {"cx": 347.0, "cy": 204.0, "area": 103500, "tilt": -1.8, "grasp": "grasp_pinky"}


class World:
    """The box in the wrist view moves linearly with pan / reach / roll from where a grasp would succeed."""

    def __init__(self, px_per_pan=-25.0, area_per_reach=0.06, deg_per_roll=-3.0, start=(3.0, -3.0, -4.0),
                 visible=True):
        self.k = (px_per_pan, area_per_reach, deg_per_roll)
        self.offset = list(start)  # pan, reach, roll units away from the grasp pose
        self.visible, self.commands = visible, []

    def observe(self):
        if not self.visible:
            return {"found": False}
        pan, reach, roll = self.offset
        return {"found": True, "cx": SITE["cx"] + self.k[0] * pan, "cy": SITE["cy"],
                "area": SITE["area"] * (1 + self.k[1] * reach), "tilt": SITE["tilt"] + self.k[2] * roll,
                "cut_top": False}

    def act(self, command):
        self.commands.append(command)
        words = command.split()
        if words[0] == "run":
            box = self.observe()
            aligned = abs(box["cx"] - SITE["cx"]) <= 25 and abs(box["area"] / SITE["area"] - 1) <= 0.15 \
                and abs(box["tilt"] - SITE["tilt"]) <= 5  # the servo's own tolerances
            return {"ok": True, "holding": aligned}
        moves = dict(zip(words[1::2], map(float, words[2::2])))
        self.offset[0] += moves.get("shoulder_pan.pos", 0)
        self.offset[1] += moves.get("shoulder_lift.pos", 0)
        self.offset[2] += moves.get("wrist_roll.pos", 0)
        return {"ok": True}


@pytest.mark.parametrize("world", [
    World(),                                                     # over Pinky
    World(px_per_pan=25.0, deg_per_roll=3.0, start=(-4.0, 2.0, 5.0)),  # over the belt: view directions inverted
])
def test_the_probe_sets_directions_and_the_loop_grasps_once_aligned(world):
    log = []
    result = m.Servo(world.act, world.observe, SITE, log=log.append).run()
    assert result["result"] == "holding", log
    assert world.commands[-1] == "run grasp_pinky rel"
    assert sum(c.startswith("jog") for c in world.commands) <= 6 + 12  # 3 probes there and back + a few steps


def test_rotation_is_matched_before_position():
    world = World(start=(3.0, 0.0, -4.0))
    log = []
    m.Servo(world.act, world.observe, SITE, log=log.append).run()
    steps = [e["decision"] for e in log if "decision" in e]
    assert steps[0] == "roll"


def test_no_box_means_no_motion_beyond_the_probe():
    world = World(visible=False)
    result = m.Servo(world.act, world.observe, SITE).run()
    assert result["result"] == "abort" and not any(c.startswith("run") for c in world.commands)


def test_an_axis_that_does_not_move_the_view_is_not_used_blindly():
    world = World(px_per_pan=0.5, start=(3.0, 0.0, 0.0))  # pan barely moves the box: probe shows no usable response
    world.offset[0] = 0.0
    world.k = (0.5, 0.06, -3.0)
    world.offset = [0.0, 0.0, 0.0]
    world.observe_orig = world.observe

    def shifted():
        box = world.observe_orig()
        if box.get("found"):
            box["cx"] += 80  # off to the side, and pan cannot fix it
        return box

    result = m.Servo(world.act, shifted, SITE).run()
    assert result["result"] == "abort" and "no probed axis" in result["reason"]
