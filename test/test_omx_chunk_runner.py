"""Chunks play in order with torque held between them; the judge gets settled state and grasp outcome."""
import importlib.util
from pathlib import Path
import sys

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("chunk_runner", OMX / "chunk_runner.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.remove(str(OMX))

HOME = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]


class Robot:
    """Follows each action at once, except the gripper stops at `object_at` (an object between the jaws)
    and joints listed in `blocked` stay put."""

    def __init__(self, object_at=None, blocked=()):
        self.pos, self.sent, self.object_at, self.blocked = list(HOME), [], object_at, blocked

    def send_action(self, action):
        self.sent.append(action)
        for i, name in enumerate(m.NAMES):
            if i in self.blocked:
                continue
            value = action[name]
            if i == 5 and self.object_at is not None:
                value = max(value, self.object_at)
            self.pos[i] = value

    def get_observation(self):
        return dict(zip(m.NAMES, self.pos))


def library():
    approach = [[k * 2.0, -60.0, 50.0, 45.0, 10.0, 46.6 + k] for k in range(10)]  # pan 0 -> 18, jaws open
    grasp = [[18.0, -60.0, 50.0, 45.0, 10.0, 55.6 - k] for k in range(10)]        # jaws close to 46.6
    return {"schema": m.SCHEMA, "names": m.NAMES, "gripper_closed": 46.6,
            "chunks": {"approach_pinky": approach, "grasp_pinky": grasp}}


def runner(robot, commands):
    status, clock = [], [0.0]
    queue = list(commands)

    def lines():
        return [queue.pop(0)] if queue and not r.chunk else []

    def sleep(seconds):
        clock[0] += 1 / 30

    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0], sleep=sleep)
    r.run(lines)
    return status


def by_command(status, command):
    return [s for s in status if s["command"] == command]


def test_a_chunk_plays_then_holds_and_reports_the_settled_state():
    robot = Robot()
    status = runner(robot, ["run approach_pinky", "state", "state", "state", "stop"])
    done = by_command(status, "run approach_pinky")[0]
    assert done["ok"] and done["settled"] and done["state"][0] == 18.0
    assert by_command(status, "state")[0]["state"][0] == 18.0  # held after the chunk, not dropped
    assert all(a["shoulder_pan.pos"] == 18.0 for a in robot.sent[-3:])


@pytest.mark.parametrize("object_at, holding", [(None, False), (51.0, True)])
def test_a_grasp_reports_whether_anything_is_between_the_jaws(object_at, holding):
    status = runner(Robot(object_at=object_at), ["run approach_pinky", "run grasp_pinky", "stop"])
    assert by_command(status, "run grasp_pinky")[0]["holding"] is holding


def test_a_chunk_out_of_order_and_a_large_jog_are_refused_without_motion():
    robot = Robot()
    status = runner(robot, ["run grasp_pinky", "jog shoulder_pan.pos 9", "jog nonsense 1", "stop"])
    assert [s["ok"] for s in status[1:4]] == [False, False, False]
    assert "starts" in status[1]["error"] and "limited" in status[2]["error"]
    assert all(a["shoulder_pan.pos"] == 0.0 for a in robot.sent)


def test_a_small_jog_and_grip_move_only_their_joint():
    robot = Robot()
    runner(robot, ["jog wrist_flex.pos -4", "grip 55", "stop"])
    assert robot.pos[3] == 41.0 and robot.pos[5] == 55.0 and robot.pos[:3] == HOME[:3]


def test_a_blocked_arm_stops_the_runner():
    far = library()
    far["chunks"]["approach_pinky"] = [[k * 3.0, -60.0, 50.0, 45.0, 10.0, 46.6] for k in range(20)]
    robot = Robot(blocked=(0,))
    status, clock = [], [0.0]
    queue = ["run approach_pinky"]
    r = m.Runner(robot, far, fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    with pytest.raises(RuntimeError, match="following error"):
        r.run(lambda: [queue.pop(0)] if queue else [])


def test_the_library_contract_is_enforced(tmp_path):
    import json
    bad = library()
    bad["chunks"]["grasp_pinky"][0][1] = 130.0
    path = tmp_path / "lib.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(SystemExit, match="within"):
        m.load_library(path)
