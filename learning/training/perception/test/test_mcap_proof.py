"""A reviewed PNG must match one message in the frozen bag bytes."""
import hashlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcap_ros2")
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
from mcap_proof import prove_frames  # noqa: E402
from test_dataset_extract import IMAGE_DEF  # noqa: E402
from mcap_ros2.writer import Writer  # noqa: E402


def _fixture(tmp_path, *, duplicate=False):
    session = tmp_path / "session"
    bag = session / "bag"
    bag.mkdir(parents=True)
    pixels = np.full((4, 6, 3), 47, np.uint8)
    png = tmp_path / "image.png"
    assert cv2.imwrite(str(png), pixels)
    for n in (10, 2):
        with (bag / f"bag_{n}.mcap").open("wb") as stream:
            writer = Writer(stream)
            definition = writer.register_msgdef("sensor_msgs/msg/Image", IMAGE_DEF)
            if n == 2:
                for _ in range(2 if duplicate else 1):
                    writer.write_message("/robot/camera/front", definition, {
                        "header": {"stamp": {"sec": 1, "nanosec": 123}, "frame_id": "camera"},
                        "height": 4, "width": 6, "encoding": "bgr8", "is_bigendian": 0,
                        "step": 18, "data": list(pixels.tobytes())}, 1_000_000_500, 1_000_000_500)
            writer.finish()
    (bag / "metadata.yaml").write_text(
        "rosbag2_bagfile_information:\n  relative_file_paths:\n"
        "    - bag_2.mcap\n    - bag_10.mcap\n")
    row = {"topic": "/robot/camera/front", "log_ns": 1_000_000_500, "image": png}
    return session, row


def test_proof_uses_numeric_bag_order_and_exact_decoded_pixels(tmp_path):
    session, row = _fixture(tmp_path)
    proof = prove_frames(session, [row], tmp_path)
    assert [bag["name"] for bag in proof["bags"]] == ["bag_2.mcap", "bag_10.mcap"]
    assert proof["frames"][0]["header_stamp_ns"] == 1_000_000_123
    assert proof["frames"][0]["image_sha256"] == hashlib.sha256(row["image"].read_bytes()).hexdigest()
    assert prove_frames(session, [row], tmp_path, expected=proof)["frames"] == proof["frames"]


def test_proof_refuses_ambiguous_missing_or_changed_image(tmp_path):
    session, row = _fixture(tmp_path, duplicate=True)
    with pytest.raises(ValueError, match="ambiguous"):
        prove_frames(session, [row], tmp_path)
    single = prove_frames(session, [{**row, "message_ordinal": 0}], tmp_path)
    assert len(single["frames"]) == 1
    with pytest.raises(ValueError, match="missing"):
        prove_frames(session, [{**row, "log_ns": 9}], tmp_path)
    changed = tmp_path / "changed.png"
    assert cv2.imwrite(str(changed), np.zeros((4, 6, 3), np.uint8))
    with pytest.raises(ValueError, match="pixels"):
        prove_frames(session, [{**row, "image": changed, "message_ordinal": 0}], tmp_path)


def test_proof_refuses_metadata_order_hash_drift_and_compact(tmp_path):
    session, row = _fixture(tmp_path)
    proof = prove_frames(session, [row], tmp_path)
    with pytest.raises(ValueError, match="bag hash"):
        prove_frames(session, [row], tmp_path,
                     expected={**proof, "bags": [{**proof["bags"][0], "sha256": "0" * 64},
                                               proof["bags"][1]]})
    metadata = session / "bag" / "metadata.yaml"
    metadata.write_text("rosbag2_bagfile_information:\n  relative_file_paths:\n"
                        "    - bag_10.mcap\n    - bag_2.mcap\n")
    with pytest.raises(ValueError, match="metadata order"):
        prove_frames(session, [row], tmp_path)
    compact = session.with_name("session.compact")
    session.rename(compact)
    with pytest.raises(ValueError, match="equivalence proof"):
        prove_frames(compact, [row], tmp_path)
