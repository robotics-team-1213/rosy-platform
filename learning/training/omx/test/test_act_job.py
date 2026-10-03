"""ACT chunk boundaries and research evaluation refusal for constant demonstrations."""
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from act_job import chunk_indices, offline_report, compatible_sources


def test_chunk_padding_never_crosses_episode_boundary():
    assert chunk_indices(3, 1, 4) == [1, 2, None, None]
    with pytest.raises(ValueError):
        chunk_indices(3, 3, 4)


def test_constant_goal_is_rejected_even_with_perfect_predictions():
    actions = np.full((10, 2), .02)
    report = offline_report(actions, actions.copy(), actions[0], actions, [[-1, 1]]*2)
    assert report["mae_rad"] == 0
    assert report["verdict"] == "reject"
    assert "insufficient_target_diversity" in report["reasons"]


def test_unsafe_or_nonfinite_prediction_is_not_clamped_to_pass():
    actions = np.array([[.01, .02], [-.1, -.2], [.2, .3]])
    predictions = actions.copy()
    predictions[0, 0] = 10
    report = offline_report(actions, predictions, np.zeros(2), actions, [[-1, 1]]*2)
    assert report["limit_violations"] == 1 and report["verdict"] == "reject"
    predictions[0, 0] = np.nan
    assert offline_report(actions, predictions, np.zeros(2), actions, [[-1, 1]]*2)["verdict"] == "reject"


def test_rig_joint_order_and_limits_mismatch_refused():
    source = {"joint_names": ["j1", "j2"], "position_limits_rad": {"j1": [-1, 1], "j2": [-1, 1]},
              "camera": {"identity": "sim-camera"}, "fps": 10,
              "calibration_revision": "sim-calib", "world_sha256": "a"*64}
    compatible_sources([source, source.copy()])
    with pytest.raises(ValueError):
        compatible_sources([source, {**source, "joint_names": ["j2", "j1"]}])
