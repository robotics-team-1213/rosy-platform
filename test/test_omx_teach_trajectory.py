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
    return [[float(i), -60.0, 50.0, 45.0, 10.0, 46.6] for i in range(seconds * FPS)]


def test_a_taught_cycle_splits_into_equal_episodes_around_a_held_reset(tmp_path):
    trajectory = t.compose(demo(), FPS, split_s=3, end_s=4, reset_s=1, source={})
    seg = trajectory["segments"]
    assert seg == {"A": [0, 30], "reset": [30, 40], "B": [40, 70]}
    frames = trajectory["frames"]
    assert frames[29] == frames[30] == frames[39]  # torque stays on at A's last pose through the reset
    assert frames[40][0] == 30.0  # B starts where the demonstration continued
    assert frames[49][0] == 39.0 and frames[69] == frames[49]  # B (10 frames) padded with its last pose
    path = tmp_path / "cycle.json"
    path.write_text(json.dumps(trajectory))
    assert t.load(path, fps=FPS)["sha256"]


@pytest.mark.parametrize("change, message", [
    (lambda d: d.update(fps=30), "fps"),
    (lambda d: d["frames"][5].__setitem__(1, 140.0), "within"),
    (lambda d: d["frames"][5].__setitem__(1, float("nan")), "finite"),
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
    written = json.loads(Path(command[1].split("=", 1)[1]).read_text())
    assert written["teleop"] == {"type": "rosy_replay", "id": "rosy_replay", "trajectory": str(path)}
    assert written["dataset"] == {"fps": FPS, "num_episodes": 2, "episode_time_s": 3.0, "reset_time_s": 1.0}
    assert written["robot"] == {"type": "omx_follower", "max_relative_target": 5}  # the same clip as a hand
    assert json.loads(config.read_text())["teleop"]["type"] == "omx_leader"  # the validated config is untouched


def test_the_replay_plugin_is_discoverable_by_its_dist_info_name():
    plugins = OMX / "lerobot_plugins"
    meta = (plugins / "lerobot_teleoperator_rosy_replay-0.1.0.dist-info/METADATA").read_text()
    assert "Name: lerobot_teleoperator_rosy_replay" in meta  # LeRobot imports dists named lerobot_teleoperator_*
    assert (plugins / "lerobot_teleoperator_rosy_replay/__init__.py").exists()
