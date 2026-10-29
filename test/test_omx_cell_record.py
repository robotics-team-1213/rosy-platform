"""A recorded A/B cycle: planned from the located box, recorded in a run folder of its own, each episode
labelled held/empty from the recorded jaws, and the reset checked with the top camera."""
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("yaml")
pd = pytest.importorskip("pandas")
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("cell_record", OMX / "cell_record.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    import cell_calibration as cal
    import cell_perception
finally:
    sys.path.remove(str(OMX))

START = (0.072, 0.106)
PROFILE = cell_perception.load_profile(OMX / "cell-profile.example.json")


def tray_pixel(x, y):
    return 134.5 - 900 * (y - 0.106), 239.5 - 900 * (x - 0.072)


def write_dataset(root, episodes):
    """episodes: list of (state gripper, action gripper) pairs per frame."""
    rows = []
    for e, frames in enumerate(episodes):
        for s, a in frames:
            rows.append({"episode_index": e, "observation.state": [0, 0, 0, 0, 0, s], "action": [0, 0, 0, 0, 0, a]})
    (root / "data" / "chunk-000").mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(root / "data" / "chunk-000" / "file-000.parquet")


@pytest.mark.parametrize("jaws, outcome", [(52.0, "held"), (46.8, "empty")])
def test_an_episode_is_held_when_the_jaws_stopped_short_of_their_closed_command(tmp_path, jaws, outcome):
    write_dataset(tmp_path, [[(56.0, 56.0)] * 5 + [(jaws, 46.6)] * 10])
    assert m.episode_outcomes(tmp_path, 46.6)[0]["outcome"] == outcome


def test_an_episode_that_never_closed_is_unknown(tmp_path):
    write_dataset(tmp_path, [[(56.0, 56.0)] * 5])
    assert m.episode_outcomes(tmp_path, 46.6)[0]["outcome"] == "unknown"


class Cell:
    def __init__(self, box):
        self.box = list(box)

    def act(self, command):
        return {"ok": False}

    def frame(self, camera):
        img = np.full((480, 640, 3), (240, 230, 200), np.uint8)
        u, v = tray_pixel(*self.box)
        cv2.rectangle(img, (round(u) - 16, round(v) - 16), (round(u) + 16, round(v) + 16), (110, 95, 115), -1)
        return img


def test_one_cycle_is_planned_from_the_located_box_recorded_labelled_and_checked_for_its_reset(tmp_path):
    config = json.loads((OMX / "cell-pipeline.example.json").read_text())
    config["profiles"] = {name: PROFILE for name in config["cameras"]}
    config["plan"] = json.loads((OMX / "grasp-plan.example.json").read_text())
    from cell_robot_profile import SCHEMA, digest

    robot = {"type": "omx_follower", "id": "fixture-arm", "port": "/dev/serial/by-id/fixture-arm"}
    (tmp_path / "record-config.json").write_text(json.dumps({"robot": robot,
        "dataset": {"root": str(tmp_path / "ds"), "fps": 30}}))
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"schema": SCHEMA, "device_id": "fixture-device", "instance_id": robot["id"],
        "robot_config_sha256": digest(robot), "work_dir": "work", "operating_envelope_path": "work/review.json"}))
    config["operating_profile_path"] = str(profile)
    config["record"] = {"config": str(tmp_path / "record-config.json"), "caps": str(tmp_path / "caps.json")}
    points = [(tray_pixel(*q), q) for q in cal.grid(START, 0.015)]
    calibration = {"sites": {"pinky": {"homography": cal.fit(points).tolist(), "loo_error_mm": {"mean": 1.0}}}}
    box = (0.075, 0.104)
    seen = {}

    def run(command, cwd):
        seen.update(command=command, cwd=cwd)
        trajectory = json.loads(Path(command[command.index("--replay") + 1]).read_text())
        dataset = Path(json.loads(Path(command[command.index("--config") + 1]).read_text())["dataset"]["root"])
        write_dataset(dataset, [[(56.0, 56.0)] * 5 + [(52.0, 46.6)] * 20] * 2)  # held in A and in B
        (Path(cwd) / "session.json").write_text(json.dumps({"safe_end": True, "source_mode": "scripted_teacher",
                                                             "episode_outcomes": []}))
        seen["segments"] = trajectory["segments"]
        return subprocess.CompletedProcess(command, 0)

    result = m.record_cycle(Cell(box), config, calibration, tmp_path / "work", run=run)
    assert result["result"] == "recorded", result
    assert [o["outcome"] for o in result["outcomes"]] == ["held", "held"]
    assert result["dataset"] != str(tmp_path / "ds") and result["reset_mm"] < 3  # a new root; the box came back
    session = json.loads((Path(result["folder"]) / "session.json").read_text())
    assert [o["segment"] for o in session["episode_outcomes"]] == ["A", "B"] and "cell_record" in session["outcome_source"]
    assert seen["segments"]["A"][1] - seen["segments"]["A"][0] == seen["segments"]["B"][1] - seen["segments"]["B"][0]
    assert seen["command"][seen["command"].index("--operating-profile") + 1] == str(profile)
    profile_data = json.loads(profile.read_text())
    profile.write_text(json.dumps({**profile_data, "instance_id": "other-arm"}))
    calls = []
    held = m.record_cycle(Cell(box), config, calibration, tmp_path / "must-not-start", run=lambda *a, **kw: calls.append(a))
    assert held["result"] == "held: recorder profile mismatch" and calls == []
    assert not (tmp_path / "must-not-start").exists()
