"""Raw road visibility keeps clipped white separate from coloured saturation."""
import numpy as np
import pytest

from control.sensing.perception.camera_visibility import visibility_reason


@pytest.mark.parametrize('colour', [(0, 0, 255), (0, 255, 0), (255, 0, 0)])
def test_one_saturated_channel_is_not_white_clipping(colour):
    assert visibility_reason(np.full((100, 100, 3), colour, np.uint8)) != 'overexposed'


def test_clipping_threshold_and_raw_road_region():
    frame = np.full((100, 100, 3), 80, np.uint8)
    road = frame[35:95, 10:90]
    road[:57] = 255  # exactly 95%, remaining road structure is preserved
    assert visibility_reason(frame) == 'usable'
    road[57, 0] = 255
    assert visibility_reason(frame) == 'overexposed'


def test_small_glare_does_not_reject_visible_road():
    frame = np.full((100, 100, 3), 100, np.uint8)
    frame[40:50, 40:50] = 255
    assert visibility_reason(frame) == 'usable'
