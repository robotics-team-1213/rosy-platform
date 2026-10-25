"""A taught cycle becomes A, reset hold, B; record_session refuses any other trajectory before the arm."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]
OMX = ROOT / "deploy/robot/omx"


def module(name):
    sys.path.insert(0, str(OMX))
    try:
        spec = importlib.util.spec_from_file_location(name, OMX / f"{name}.py")
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    finally:
        sys.path.remove(str(OMX))


t = module("teach_trajectory")
FPS = 10


def demo(seconds=5):
    return [[i * 0.5, -60.0, 50.0, 45.0, 10.0, 46.6] for i in range(seconds * FPS)]  # 5 units/s: guard speed


def test_a_taught_cycle_splits_into_equal_episodes_around_a_held_reset(tmp_path):
    trajectory = t.compose(demo(), FPS, split_s=3, end_s=4, reset_s=1, source={})
    seg = trajectory["segments"]
    assert seg == {"A": [0, 30], "reset": [30, 40], "B": [40, 70]}
    frames = trajectory["frames"]
    assert frames[29] == frames[30] == frames[39]  # torque stays on at A's last pose through the reset
    assert frames[40][0] == 15.0  # B starts where the demonstration continued
    assert frames[49][0] == 19.5 and frames[69] == frames[49]  # B (10 frames) padded with its last pose
    path = tmp_path / "cycle.json"
    path.write_text(json.dumps(trajectory))
    assert t.load(path, fps=FPS)["sha256"]


@pytest.mark.parametrize("change, message", [
    (lambda d: d.update(fps=30), "fps"),
    (lambda d: d["frames"][5].__setitem__(1, 140.0), "within"),
    (lambda d: d["frames"][5].__setitem__(1, float("nan")), "finite"),
    (lambda d: d["frames"][5].__setitem__(1, d["frames"][4][1] + 2), "faster"),
    (lambda d: d["segments"].update(B=[40, 69]), "segments"),
    (lambda d: d.update(names=d["names"][:5]), "names"),
])
def test_a_trajectory_outside_the_contract_is_refused(tmp_path, change, message):
    trajectory = t.compose(demo(), FPS, split_s=3, end_s=4, reset_s=1, source={})
    change(trajectory)
    path = tmp_path / "cycle.json"
    path.write_text(json.dumps(trajectory))
    with pytest.raises(SystemExit, match="schema|six|segments"):
        t.load(path, fps=FPS)


def cycle(stretch, pan_peak, closed=46.6, opened=58.0):
    """Seven phases of a taught cycle; the gripper changes at the six phase boundaries."""
    frames = []
    for phase, (seconds, grip) in enumerate([(1, closed), (2, opened), (3, closed), (2, opened),
                                             (3, closed), (2, opened), (2, closed)]):
        n = round(seconds * stretch * FPS)
        frames += [[pan_peak * phase / 6 + k / n, -60.0, 50.0, 45.0, 10.0, grip] for k in range(n)]
    return frames


def test_the_standard_cycle_is_the_median_of_demonstrations_cut_at_their_gripper_events():
    demos = [cycle(1.0, 30.0), cycle(1.3, 34.0), cycle(0.8, 32.0), [[0.0] * 6] * 50]  # last: no grasps
    assert len(t.gripper_events(demos[0], FPS)) == t.TRANSITIONS
    actions, split, used = t.standard(demos, FPS, dwell_s=1.0)
    assert used == [0, 1, 2]
    assert max(f[0] for f in actions) == pytest.approx(32.0, abs=1.0)  # median peak, not one demo's
    grasp = t.gripper_events(actions, FPS)[1]
    assert actions[grasp - FPS][:5] == actions[grasp - 1][:5]  # one second still, jaws open, before closing
    grip = [f[5] for f in actions]
    assert grip[split] > 52 and t.gripper_events(actions, FPS)[2] < split < t.gripper_events(actions, FPS)[3]


def test_too_few_usable_demonstrations_are_refused():
    with pytest.raises(SystemExit, match="usable"):
        t.standard([cycle(1.0, 30.0), [[0.0] * 6] * 50], FPS)


def test_record_session_swaps_only_the_teleop_and_episode_timing_for_a_replay(tmp_path):
    session = module("record_session")
    trajectory = t.compose(demo(), FPS, split_s=3, end_s=4, reset_s=1, source={})
    path = tmp_path / "cycle.json"
    path.write_text(json.dumps(trajectory))
    replay = {**t.load(path, fps=FPS), "path": str(path)}
    config = tmp_path / "record-config.json"
    config.write_text(json.dumps({"robot": {"type": "omx_follower", "max_relative_target": 5},
                                  "teleop": {"type": "omx_leader", "port": "/dev/serial/by-id/leader"},
                                  "dataset": {"fps": FPS, "num_episodes": 5, "episode_time_s": 40, "reset_time_s": 10}}))
    command = session.Session.command(config, teleop_only=False, replay=replay)
    assert command[2:4] == ["record", "--teacher"]  # the guard's teacher mode streams the replay
    written = json.loads(Path(command[-1].split("=", 1)[1]).read_text())
    assert written["teleop"] == {"type": "rosy_replay", "id": "rosy_replay", "trajectory": str(path)}
    assert written["dataset"] == {"fps": FPS, "num_episodes": 2, "episode_time_s": 3.0, "reset_time_s": 1.0}
    assert written["robot"] == {"type": "omx_follower", "max_relative_target": 5}  # the same clip as a hand
    assert json.loads(config.read_text())["teleop"]["type"] == "omx_leader"  # the validated config is untouched


def test_the_replay_plugin_is_discoverable_by_its_dist_info_name():
    plugins = OMX / "lerobot_plugins"
    meta = (plugins / "lerobot_teleoperator_rosy_replay-0.1.0.dist-info/METADATA").read_text()
    assert "Name: lerobot_teleoperator_rosy_replay" in meta  # LeRobot imports dists named lerobot_teleoperator_*
    assert (plugins / "lerobot_teleoperator_rosy_replay.py").exists()


def test_a_fast_hand_demonstration_is_slowed_to_the_guard_speed_on_the_same_path():
    fast = [[i * 4.0, -60.0, 50.0, 45.0, 10.0, 46.6] for i in range(11)]  # 40 units/s
    trajectory = t.compose(fast, FPS, split_s=0.5, end_s=1.1, reset_s=1, source={})
    frames = trajectory["frames"]
    assert not t.too_fast(frames, FPS)
    a, b = trajectory["segments"]["A"], trajectory["segments"]["B"]
    assert frames[a[1] - 1][0] == 16.0 and frames[b[0]][0] == 16.5 and max(f[0] for f in frames) == 40.0
