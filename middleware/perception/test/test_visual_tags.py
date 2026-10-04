import cv2
import numpy as np
import pytest

import dock_scene
from control.sensing.perception.visual_tags import detect_visual_tags


def test_blank_frame_has_no_tag_and_does_not_invent_an_object_class():
    if not hasattr(cv2, 'aruco'):
        pytest.skip('OpenCV ArUco backend unavailable')
    assert detect_visual_tags(np.full((240, 320, 3), 255, np.uint8)) == []


def test_known_tag_identity_and_image_box_are_from_pixels():
    if not hasattr(cv2, 'aruco'):
        pytest.skip('OpenCV ArUco backend unavailable')
    marker = dock_scene.marker_image(7, 100)
    image = np.full((240, 320, 3), 255, np.uint8)
    image[70:170, 100:200] = marker[:, :, None]
    tags = detect_visual_tags(image)
    assert len(tags) == 1 and tags[0]['tag_id'] == 7
    assert np.min(tags[0]['corners_px'], axis=0) == pytest.approx([100, 70], abs=2)
    assert 'robot_id' not in tags[0] and 'distance_m' not in tags[0]


def test_invalid_image_is_unavailable():
    assert detect_visual_tags(None) is None
    assert detect_visual_tags(np.empty((0, 320, 3), np.uint8)) is None
    assert detect_visual_tags(np.zeros((240, 320, 1), np.uint8)) is None
