"""image_msg_to_frame: sensor_msgs/Image to numpy without ROS."""

from types import SimpleNamespace

import numpy as np
import pytest

from control.sensing.perception.image_frame import image_msg_to_frame


def _msg(encoding, arr):
    h, w = arr.shape[:2]
    return SimpleNamespace(encoding=encoding, height=h, width=w, data=arr.tobytes())


def test_bgr8_passthrough():
    a = np.arange(2 * 2 * 3, dtype=np.uint8).reshape(2, 2, 3)
    assert (image_msg_to_frame(_msg("bgr8", a)) == a).all()


def test_rgb8_becomes_bgr():
    a = np.zeros((1, 1, 3), np.uint8)
    a[0, 0] = (10, 20, 30)
    assert tuple(image_msg_to_frame(_msg("rgb8", a))[0, 0]) == (30, 20, 10)


def test_mono8_is_2d():
    a = np.arange(6, dtype=np.uint8).reshape(2, 3)
    f = image_msg_to_frame(_msg("mono8", a))
    assert f.shape == (2, 3) and (f == a).all()


def test_size_mismatch_and_bad_encoding():
    m = _msg("bgr8", np.zeros((2, 2, 3), np.uint8))
    m.width = 3
    with pytest.raises(ValueError, match="size"):
        image_msg_to_frame(m)
    with pytest.raises(ValueError, match="encoding"):
        image_msg_to_frame(_msg("16UC1", np.zeros((2, 2), np.uint8)))
