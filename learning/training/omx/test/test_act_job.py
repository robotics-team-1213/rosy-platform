"""ACT chunk boundaries and research evaluation refusal for constant demonstrations."""
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from act_job import chunk_indices, offline_report, compatible_sources, run


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


@pytest.mark.parametrize('steps',[True,0,5,1.5])
def test_invalid_action_queue_length_fails_before_source_or_model_access(tmp_path,steps):
    with pytest.raises(ValueError,match='n_action_steps'):
        run([],tmp_path/'absent',tmp_path/'output',n_action_steps=steps)
    assert not (tmp_path/'output').exists()


def test_consumed_reader_frame_is_bound_to_original_png(tmp_path):
    from hashlib import sha256
    from PIL import Image
    from act_job import verify_reader_image
    original = tmp_path / "original.png"
    rgb = np.full((32, 32, 3), [255, 0, 0], dtype=np.uint8)
    Image.fromarray(rgb).save(original)
    matching = rgb.transpose(2, 0, 1).astype(np.float32) / 255
    assert verify_reader_image(matching, original, sha256(original.read_bytes()).hexdigest()) == 0
    # Preserve the existing exporter's lossy encoding allowance.
    assert verify_reader_image(matching * .99, original, sha256(original.read_bytes()).hexdigest()) < 8
    substituted = np.full((3, 32, 32), 0., dtype=np.float32)
    substituted[2] = 1
    with pytest.raises(ValueError, match="source image differs"):
        verify_reader_image(substituted, original, sha256(original.read_bytes()).hexdigest())


@pytest.mark.parametrize('pixels', [
    np.full((3, 32, 32), np.nan), np.zeros((3, 31, 32)),
    np.full((3, 32, 32), 1.1), np.zeros((3, 32, 32), dtype=np.uint8),
])
def test_consumed_reader_frame_shape_range_and_finiteness_are_checked(tmp_path, pixels):
    from hashlib import sha256
    from PIL import Image
    from act_job import verify_reader_image
    original = tmp_path / "original.png"
    Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8)).save(original)
    with pytest.raises(ValueError, match="source image dimensions/range"):
        verify_reader_image(pixels, original, sha256(original.read_bytes()).hexdigest())


def test_source_png_changed_after_validation_is_refused_even_if_reader_matches(tmp_path):
    from hashlib import sha256
    from PIL import Image
    from act_job import verify_reader_image
    original = tmp_path / "original.png"
    Image.fromarray(np.full((32, 32, 3), [255, 0, 0], dtype=np.uint8)).save(original)
    validated_hash = sha256(original.read_bytes()).hexdigest()
    changed = np.full((32, 32, 3), [0, 0, 255], dtype=np.uint8)
    Image.fromarray(changed).save(original)
    with pytest.raises(ValueError, match="PNG hash differs"):
        verify_reader_image(changed.transpose(2, 0, 1).astype(np.float32) / 255,
                            original, validated_hash)
