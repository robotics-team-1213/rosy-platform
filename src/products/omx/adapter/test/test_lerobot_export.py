import numpy as np
import pytest

from test_demonstration import complete_episode
from omx_adapter.lerobot_export import dataset_features, export_episode, iter_dataset_frames
from omx_adapter.demonstration import validate_episode


def test_export_schema_keeps_radians_and_source_clocks(tmp_path):
    manifest = complete_episode(tmp_path)
    episode = tmp_path / manifest["episode_id"]
    validated = validate_episode(episode)
    features = dataset_features(manifest)
    assert features["action"]["names"] == ["joint1", "gripper_joint_1"]
    assert features["observation.images.front"]["dtype"] == "video"
    frames = list(iter_dataset_frames(episode, validated))
    assert frames[0]["timestamp"] == 0
    assert frames[1]["timestamp"] == 0.1
    np.testing.assert_array_equal(frames[0]["source.capture_time_ns"], [1_000_000_000])
    assert frames[0]["source.capture_time_ns"].dtype == np.int64
    np.testing.assert_allclose(frames[0]["action"], [0.02, -0.1])
    assert frames[0]["observation.images.front"].shape == (6, 8, 3)


def test_export_rejects_missing_source_before_creating_dataset(tmp_path):
    output = tmp_path / "export"
    with pytest.raises(FileNotFoundError):
        export_episode(tmp_path / "missing", output, "rosy-local/omx-sim")
    assert not output.exists()


def test_real_lerobot_v3_export_reopens_state_action_and_video(tmp_path):
    pytest.importorskip("lerobot")
    manifest = complete_episode(tmp_path / "raw")
    output = tmp_path / "export"
    result = export_episode(tmp_path / "raw" / manifest["episode_id"], output, "rosy-local/omx-sim-test")
    assert result["verified_frames"] == 2
    assert result["lerobot_version"] == "0.4.4"
    assert list(output.glob("videos/**/*.mp4"))
    assert (output / "rosy_provenance" / manifest["episode_id"] / "manifest.json").is_file()
