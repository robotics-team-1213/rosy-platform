"""The real LeRobot 0.4.4 half of test_two_arm_export, run by the pinned learner venv (test_two_arm_export_lerobot.py): export a fake recording, read it
back, mix it with a collect-format stand-in by weight through `aggregate_datasets` (the call `omx_two_arm_policy round` makes) and count the frames.
Usage: python -I -B two_arm_lerobot_check.py <new-scratch-dir>. Prints OK on success."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
from two_arm_fixture import FPS, export, helpers, inputs, make_source, sim_features, sim_stand_in, window  # noqa: E402
import omx_two_arm_mix as mix  # noqa: E402
from lerobot.datasets.aggregate import aggregate_datasets  # noqa: E402
from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402


def info(root):
    return json.loads((Path(root) / "meta/info.json").read_text(encoding="utf-8"))


tmp = Path(sys.argv[1])
real, part = tmp / "real", tmp / "part0"
meta = export.export(make_source(tmp / "src"), [window("a1"), window("a2", outcome="held"), window("a3", 5, 34)], real)
assert meta["episodes"] == 2 and [r["episode_id"] for r in meta["real"]["rejected"]] == ["a2"], meta["real"]["rejected"]
got = info(real)
# LeRobot adds timestamp/frame_index/... and each video's codec info on its own; every feature collect declares is there, equal
for key, want in sim_features().items():
    assert {k: got["features"][key][k] for k in want} == want, (key, got["features"][key])
assert set(got["features"]) - set(sim_features()) == {"timestamp", "frame_index", "episode_index", "index", "task_index"}, set(got["features"])
assert got["fps"] == FPS and got["robot_type"] == "omx_follower_pair" and got["total_episodes"] == 2 and got["total_frames"] == 60

reader = LeRobotDataset("rosy/omx-two-arm", root=real, video_backend="pyav", download_videos=False)
item = reader[3]
assert len(reader) == 60 and tuple(item["observation.state"].shape) == (12,) and tuple(item["action"].shape) == (12,)
assert all(tuple(item[f"observation.images.{v}"].shape) == (3, 240, 320) for v in inputs.VIEWS)
red = item["observation.images.a_wrist"][:, 120, 160].numpy() * 255  # BGR (0, 0, 30) frame -> RGB (30, 0, 0) after the video round trip
assert abs(red - np.array([30, 0, 0])).max() < 12, red

sim_stand_in(part, 10)
assert info(part)["features"] == got["features"], "a collect-format dataset and the export must carry identical features (video info included)"
roots, shares = mix.weighted_roots([part], [real], [3])
assert len(roots) == 4 and shares[str(real)]["share"] == round(180 / 190, 4), shares
aggregate_datasets([f"rosy/part{i}" for i in range(len(roots))], "rosy/omx-two-arm", roots=roots, aggr_root=tmp / "mixed")
assert info(tmp / "mixed")["total_frames"] == 10 + 3 * 60 and info(tmp / "mixed")["total_episodes"] == 1 + 3 * 2
assert len(LeRobotDataset("rosy/omx-two-arm", root=tmp / "mixed", video_backend="pyav", download_videos=False)) == 190

sim_stand_in(tmp / "goal0", 3, goal=22)  # collect with a goal: the mix refuses it before aggregating
try:
    mix.weighted_roots([tmp / "goal0"], [real])
except ValueError as error:
    assert "observation.environment_state" in str(error), error
else:
    raise AssertionError("a dataset without the goal feature was mixed with one that has it")
print("OK")
