"""D-373 decision 3: the capture JPEG is encoded from the frame the camera node already holds."""

import cv2
import numpy as np
import pytest

from control.sensing.perception.jpeg_frame import DEFAULT_QUALITY, encode_jpeg


def _frame():
    bgr = np.zeros((24, 32, 3), np.uint8)
    bgr[:, 10:20] = (0, 128, 255)
    return bgr


def test_encode_returns_jpeg_bytes_and_ros_format():
    data, fmt = encode_jpeg(_frame())
    assert fmt == "jpeg"  # sensor_msgs/CompressedImage.format
    assert isinstance(data, bytes) and data[:2] == b"\xff\xd8"
    back = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert back.shape == (24, 32, 3)
    assert np.abs(back.astype(int) - _frame().astype(int)).mean() < 8


def test_quality_changes_size():
    rng = np.random.default_rng(0)
    noisy = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
    small, _ = encode_jpeg(noisy, quality=20)
    big, _ = encode_jpeg(noisy, quality=95)
    assert len(small) < len(big)
    assert DEFAULT_QUALITY == 85


@pytest.mark.parametrize("q", [0, 101, -5])
def test_quality_out_of_range_rejected(q):
    with pytest.raises(ValueError):
        encode_jpeg(_frame(), quality=q)


def test_grey_frame_accepted():
    data, fmt = encode_jpeg(np.full((8, 8), 127, np.uint8))
    assert fmt == "jpeg" and data[:2] == b"\xff\xd8"
